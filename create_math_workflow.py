import os
import sys

# Додаємо шлях до проєкту, щоб імпорти працювали
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.schemas.workflow import Workflow, Node, Edge
from app.storage.file_storage import save_workflow


def create_my_code_first_workflow():
    # 1. Визначаємо вузли (Nodes)
    trigger = Node(
        id="mt_code_1",
        type="manual_trigger",
        config={"initial_data": {"a": "15", "b": 25}} # Тепер можна передавати "15" як рядок, двигун сам конвертує в int
    )

    expression = Node(
        id="e_code_2",
        type="expression",
        config={"expression": "input.a + input.b"}
    )

    log_node = Node(
        id="l_code_3",
        type="log",
        config={"message": "Результат обчислення в коді: {input.result}"}
    )

    # 2. Визначаємо зв'язки (Edges)
    # Тепер ми можемо позначати конкретні ребра як readonly
    edge1 = Edge(
        **{"from": "mt_code_1", "to": "e_code_2", "target_handle": "input", "is_readonly": True}
    )

    edge2 = Edge(
        **{"from": "e_code_2", "to": "l_code_3", "source_handle": "result", "target_handle": "input", "is_readonly": True}
    )

    # 3. Створюємо об'єкт Workflow
    # Головна зміна: додано is_readonly=True.
    # Це заблокує видалення блоків та зміну ліній у веб-інтерфейсі.
    new_workflow = Workflow(
        name="Code_First_Math",
        nodes=[trigger, expression, log_node],
        edges=[edge1, edge2],
        is_readonly=True  # Весь сценарій стає захищеним у UI
    )

    # 4. Зберігаємо у папку workflows/
    path = save_workflow(new_workflow)
    print(f"Сценарій успішно створено за шляхом: {path}")


if __name__ == "__main__":
    create_my_code_first_workflow()