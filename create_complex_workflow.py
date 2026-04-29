import os
import sys

# Додаємо шлях до проєкту
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.schemas.workflow import Node, Workflow
from app.storage.file_storage import save_workflow


def create_complex_demo():
    """Code-first приклад: жодного `edges=[...]` вручну.

    Усі підключення оголошено у параметрі `inputs` кожного вузла.
    Назви портів у `inputs` СУВОРО збігаються з декораторами
    `@input_port` / `@output_port` у `app/nodes/*` — інакше двигун
    не зможе передати дані, а UI не намалює лінію в потрібну точку.

    Формати значень `inputs[<target_port>]`:
      • "src_id"            — джерело з default-портом "output";
      • ("src_id", "port")  — порт-у-порт (явний source_handle);
      • [...]               — ФАН-ІН: список джерел в один target_port,
                              кожен елемент розгортається в окремий Edge;
      • "@on_true"/"@on_false" → керуючий зв'язок від condition'а
        (source_handle="true"/"false", без target_handle).
    """

    # 1. Тригер: output-порт називається "data" (див. manual_trigger.py).
    trigger = Node(
        id="trigger_1",
        type="manual_trigger",
        config={"initial_data": {"threshold": 3}},
    )

    # 2. Читач файлу: output-порт "content" (read_file.py).
    reader = Node(
        id="reader_1",
        type="read_file",
        config={"path": "logs.txt"},
    )

    # 3. Кастомний код: input-порт "input", output-порт "output".
    processor = Node(
        id="processor_1",
        type="custom_code",
        config={"script_name": "log_processor", "entry_point": "count_errors"},
        inputs={
            "input": ("reader_1", "content"),  # reader.content → processor.input
        },
    )

    # 4. Умова: input-порт "input". ВАЖЛИВО: ми хочемо, щоб у
    #    `current_input` потрапили і `threshold` (із trigger'а),
    #    і `count` (із processor'а). Використовуємо НОВИЙ list-формат —
    #    fan-in двох джерел в один target-порт "input":
    check_limit = Node(
        id="condition_1",
        type="condition",
        config={"expression": "input.count > input.threshold"},
        inputs={
            "input": [
                ("trigger_1", "data"),       # threshold ← trigger.data
                ("processor_1", "output"),   # count     ← processor.output
            ],
        },
    )

    # 5. Форматер: вираз із input-портом "input" та output "result".
    #    Тригериться і даними з processor'а, і керуванням @on_true.
    #    Дефолтний trigger_rule="all_success" — обидва входи мають бути живі.
    formatter = Node(
        id="formatter_1",
        type="expression",
        config={
            "expression": "'УВАГА! Знайдено ' + str(input.count) + ' помилок.'"
        },
        inputs={
            "input": ("processor_1", "output"),
            "@on_true": "condition_1",
        },
    )

    # 6. Writer: input-порти "path" та "content". Беремо результат
    #    форматера у "content"; "path" візьметься з config'а.
    writer = Node(
        id="writer_1",
        type="write_file",
        config={"path": "critical_report.txt"},
        inputs={
            "content": ("formatter_1", "result"),
        },
    )

    # 7. Лог: input-порт "input" + керуюче ребро від condition.false.
    #    Спрацьовує АБО після writer'а (success-гілка),
    #    АБО від condition.false (stable-гілка) → trigger_rule="one_success".
    logger = Node(
        id="logger_1",
        type="log",
        config={"message": "Аналіз завершено."},
        inputs={
            "input": ("writer_1", "path"),
            "@on_false": "condition_1",
        },
        trigger_rule="one_success",
    )

    # --- Workflow: edges автоматично згенеруються з node.inputs -----------
    workflow = Workflow(
        name="Complex_Log_Analyzer",
        nodes=[trigger, reader, processor, check_limit, formatter, writer, logger],
        # edges= навмисно пропущено — Pydantic-валідатор збере все з node.inputs
        is_readonly=True,  # захищаємо складну логіку від змін у UI
    )

    path = save_workflow(workflow)
    print(f"Сценарій 'Complex_Log_Analyzer' збережено: {path}")
    print(f"Згенеровано ребер: {len(workflow.edges)}")
    for e in workflow.edges:
        print(
            f"  {e.from_node} --[{e.source_handle or '*'}/{e.target_handle or '*'}]--> {e.to_node}"
        )


if __name__ == "__main__":
    create_complex_demo()
