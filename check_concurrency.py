import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.schemas.workflow import Node, Workflow
from app.storage.file_storage import save_workflow

def create_concurrency_test():
    # Вузол А та B стартують паралельно
    node_a = Node(id="node_a", type="expression", config={"expression": "'Alpha'"})
    node_b = Node(id="node_b", type="expression", config={"expression": "'Omega'"})

    # Вузол C агрегує дані
    node_c = Node(
        id="node_c",
        type="log",
        config={
            # Звертаємося до порту 'input', а потім до індексу 0 та 1
            "message": "Конкурентна перевірка: {input.input.0} та {input.input.1}"
        },
        inputs={
            "input": [("node_a", "result"), ("node_b", "result")]
        },
        trigger_rule="all_success"
    )

    workflow = Workflow(
        name="Concurrency_Verification",
        nodes=[node_a, node_b, node_c],
        is_readonly=True
    )

    save_workflow(workflow)
    print(f"✅ Тест збережено.")

if __name__ == "__main__":
    create_concurrency_test()