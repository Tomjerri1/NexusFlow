from simpleeval import EvalWithCompoundTypes

from app.core.context import ExecutionContext
from app.nodes.base import BaseNode, input_port, node_info, output_port
from app.nodes.condition import _rewrite_dot_access
from app.schemas.node_configs import ExpressionConfig


class ExpressionEvalError(ValueError):
    """Помилка під час обчислення виразу expression-вузла."""


@node_info(
    display_name="Expression",
    category="logic",
    color="#0d9488",
    icon="function-square",
    description="Evaluates a sandboxed Python expression over input/nodes.",
)
@input_port("expression", type_hint="str", required=False, description="Override of config.expression.")
@input_port("input", type_hint="dict", required=False, description="Generic data input.")
@output_port("result", type_hint="any", description="Computed value.")
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
        port_expr = context.get_input(self.id, "expression")
        expression = port_expr if isinstance(port_expr, str) and port_expr else self.config.expression

        rewritten = _rewrite_dot_access(expression)
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
                f"Failed to evaluate {expression!r}: {exc}"
            ) from exc

        return {"result": value}
