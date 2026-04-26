"""Авто-реєстрація вузлів workflow.

При імпорті пакета викликається `discover_nodes`, що сканує всі модулі
в `app/nodes/` і реєструє у `NODE_REGISTRY` усі підкласи `BaseNode`
з валідним `type_name`. Щоб додати новий вузол — просто створи файл
`app/nodes/<name>.py` із класом `class FooNode(BaseNode): type_name = "foo" ...`.
"""

from app.nodes.base import NODE_REGISTRY, BaseNode, discover_nodes

discover_nodes(__name__)

__all__ = ["BaseNode", "NODE_REGISTRY", "discover_nodes"]
