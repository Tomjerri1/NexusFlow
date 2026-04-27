import os
import sys

# Додаємо шлях до проєкту
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.schemas.workflow import Workflow, Node, Edge
from app.storage.file_storage import save_workflow


def create_complex_demo():
    # --- Вузли ---

    # 1. Тригер з лімітом
    trigger = Node(
        id="trigger_1",
        type="manual_trigger",
        config={"initial_data": {"threshold": 3}}
    )

    # 2. Читання вхідного файлу
    reader = Node(
        id="reader_1",
        type="read_file",
        config={"path": "logs.txt"}
    )

    # 3. Кастомний обробник (рахує ERROR)
    processor = Node(
        id="processor_1",
        type="custom_code",
        config={
            "script_name": "log_processor",
            "entry_point": "count_errors"
        }
    )

    # 4. Перевірка умови (count > threshold)
    check_limit = Node(
        id="condition_1",
        type="condition",
        config={"expression": "input.count > input.threshold"}
    )

    # 5. Форматування звіту (якщо помилок багато)
    formatter = Node(
        id="formatter_1",
        type="expression",
        config={"expression": "'УВАГА! Знайдено ' + str(input.count) + ' помилок.'"}
    )

    # 6. Запис звіту у файл
    writer = Node(
        id="writer_1",
        type="write_file",
        config={"path": "critical_report.txt"}
    )

    # 7. Лог успіху/стабільності
    logger = Node(
        id="logger_1",
        type="log",
        config={"message": "Аналіз завершено. {input.result}"}
    )

    # --- Зв'язки (Edges) ---
    edges = [
        # Дані від тригера до умови (threshold)
        Edge(from_node="trigger_1", to_node="condition_1", target_handle="input", is_readonly=True),

        # Контент файлу до процесора
        Edge(from_node="reader_1", to_node="processor_1", source_handle="content", target_handle="input",
             is_readonly=True),

        # Результат процесора до умови та форматера
        Edge(from_node="processor_1", to_node="condition_1", source_handle="output", target_handle="input", is_readonly=True),
        Edge(from_node="processor_1", to_node="formatter_1", source_handle="output", target_handle="input", is_readonly=True),

        # Умовне розгалуження (Condition branches)
        # Гілка True: виконуємо запис
        Edge(from_node="condition_1", to_node="formatter_1", source_handle="true", is_readonly=True),
        Edge(from_node="formatter_1", to_node="writer_1", source_handle="result", target_handle="content",
             is_readonly=True),
        Edge(from_node="writer_1", to_node="logger_1", source_handle="result", target_handle="input", is_readonly=True),

        # Гілка False: просто логуємо
        Edge(from_node="condition_1", to_node="logger_1", source_handle="false", is_readonly=True),
    ]

    # --- Створення Workflow ---
    workflow = Workflow(
        name="Complex_Log_Analyzer",
        nodes=[trigger, reader, processor, check_limit, formatter, writer, logger],
        edges=edges,
        is_readonly=True  # Захищаємо складну логіку від змін в UI
    )

    path = save_workflow(workflow)
    print(f"Сценарій 'Complex_Log_Analyzer' збережено: {path}")


if __name__ == "__main__":
    create_complex_demo()