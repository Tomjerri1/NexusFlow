from app.schemas.workflow import Node, Workflow
from app.storage.file_storage import save_workflow

MSG_SAFE = "Код безпечний! Секретів не знайдено.Можна деплоїти"
MSG_DANGER = "КРИТИЧНО! Витік секретів у коді."

wf = Workflow(
    name="cybersecurity_audit",
    nodes=[
        Node(
            id="read_env",
            type="read_directory",
            config={"path": "data/", "recursive": True, "extension": ".env, .json", "name_contains": ""}
        ),
        Node(
            id="read_code",
            type="read_directory",
            config={"path": "data/", "recursive": True, "extension": ".py, .js", "name_contains": ""}
        ),

        Node(
            id="scan_env",
            type="custom_code",
            config={"script_name": "scan_env"},
            inputs={"input": ("read_env", "file_list")}
        ),
        Node(
            id="scan_code",
            type="custom_code",
            config={"script_name": "scan_code"},
            inputs={"input": ("read_code", "file_list")}
        ),

        Node(
            id="check_safety",
            type="condition",
            config={
                "expression": "nodes.scan_env.output['is_safe'] == True and nodes.scan_code.output['is_safe'] == True"},
            inputs={"input": [("scan_env", "output"), ("scan_code", "output")]}
        ),

        Node(
            id="log_safe",
            type="log",
            config={"message": MSG_SAFE},
            inputs={"input": ("check_safety", "true")}
        ),
        Node(
            id="log_danger",
            type="log",
            config={"message": MSG_DANGER},
            inputs={"input": ("check_safety", "false")}
        ),

        Node(
            id="notify_telegram",
            type="custom_code",
            trigger_rule="one_success",
            config={
                "script_name": "telegram_notifier",
                "params": {"msg_safe": MSG_SAFE, "msg_danger": MSG_DANGER}
            },
            inputs={"input": [("log_safe", "output"), ("log_danger", "output")]}
        )
    ]
)

if __name__ == "__main__":
    save_workflow(wf)