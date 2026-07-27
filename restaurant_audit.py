from app.schemas.workflow import Node, Edge, Workflow
from app.storage.file_storage import save_workflow

wf = Workflow(
    name="restaurant_audit_pipeline",
    nodes=[
        Node(
            id="start_audit",
            type="manual_trigger",
            config={"initial_data": {"data": "Борошно"}}
        ),

        Node(
            id="scan_dir",
            type="read_directory",
            config={"path": "data/", "extension": "", "name_contains": ""}
        ),

        Node(
            id="check_files",
            type="condition",
            config={"expression": "input.count > 0"},
        ),

        # НОВИЙ ВУЗОЛ: Пакувальник даних (Адаптер)
        # Він бере список файлів і слово, і створює з них красивий словник
        Node(
            id="data_merger",
            type="expression",
            config={
                # Звертаємося до результатів інших вузлів напряму
                "expression": "{'files': nodes.scan_dir.file_list, 'term': nodes.start_audit.data}"
            },
            inputs={
                # Щоб лінійки на UI намалювалися красиво
                "input": [("scan_dir", "file_list"), ("start_audit", "data")]
            }
        ),

        Node(
            id="find_orders",
            type="custom_code",
            config={"script_name": "find_orders"},
            inputs={
                "@on_true": "check_files",
                # Передаємо наш ідеально запакований словник в офіційний порт input!
                "input": ("data_merger", "result")
            }
        ),

        Node(
            id="log_result",
            type="log",
            config={"message": "Результат аудиту: {input.output}"},
            inputs={"input": "find_orders"}
        ),

        Node(
            id="log_empty",
            type="log",
            config={"message": "Увага! Папка зі звітами порожня."},
            inputs={"@on_false": "check_files"}
        )
    ],
    edges=[
        Edge(from_node="scan_dir", to_node="check_files")
    ]
)

if __name__ == "__main__":
    save_workflow(wf)
    print("Воркфлоу створенний.")