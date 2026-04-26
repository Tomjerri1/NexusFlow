from simpleeval import EvalWithCompoundTypes

from app.core.context import ExecutionContext
from app.nodes.base import BaseNode
from app.nodes.condition import _rewrite_dot_access
from app.schemas.node_configs import ExpressionConfig


class ExpressionEvalError(ValueError):
    """Помилка під час обчислення виразу expression-вузла."""


class ExpressionNode(BaseNode):
    """Гнучкий обчислювач: повертає `{"result": <value>}` для будь-якого виразу.

    Доступні імена у виразі:
      - `input` — поточний вхід вузла (dict)
      - `nodes` — `dict[node_id, output_dict]` усіх попередніх вузлів
    Дот-нотація (`input.size`, `nodes.r1.path`) переписується у subscript,
    як і у ConditionNode.
    """

    type_name = "expression"
    config_model = ExpressionConfig

    async def execute(self, context: ExecutionContext) -> dict:
        rewritten = _rewrite_dot_access(self.config.expression)
        evaluator = EvalWithCompoundTypes(
            names={"input": context.current_input, "nodes": context.node_outputs}
        )
        # `simpleeval` піднімає різні винятки (InvalidExpression, KeyError,
        # SyntaxError при парсингу AST тощо). Обгортаємо все у єдиний типовий
        # ExpressionEvalError, щоб engine давав однаковий контракт помилок.
        try:
            value = evaluator.eval(rewritten)
        except Exception as exc:
            raise ExpressionEvalError(
                f"Failed to evaluate {self.config.expression!r}: {exc}"
            ) from exc

        return {"result": value}
