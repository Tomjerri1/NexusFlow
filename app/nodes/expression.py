from simpleeval import EvalWithCompoundTypes

from app.core.context import ExecutionContext
from app.nodes.base import BaseNode, input_port, node_info, output_port
from app.nodes.condition import _rewrite_dot_access
from app.schemas.node_configs import ExpressionConfig


class ExpressionEvalError(ValueError):
    """An error occurred while evaluating the expression in the expression node."""


@node_info(
    display_name="Expression",
    category="logic",
    color="#0d9488",
    icon="function-square",
    description="Evaluates a sandboxed Python expression over input/nodes.",
)
@input_port("expression", type_hint="str", required=False, description="Override of config.expression.")
@input_port("input", type_hint="any", required=False, description="Generic data input.")
@output_port("result", type_hint="any", description="Computed value.")
class ExpressionNode(BaseNode):
    """Flexible evaluator: returns `{“result”: <value>}` for any expression.
    Available names in the expression:
      - `input` — the local `input_data` passed by the engine
      - `nodes` — a snapshot of `node_outputs` from all preceding nodes
    """

    type_name = "expression"
    config_model = ExpressionConfig

    async def execute(self, context: ExecutionContext, input_data: dict) -> dict:
        port_expr = context.get_input(self.id, "expression")
        expression = port_expr if isinstance(port_expr, str) and port_expr else self.config.expression

        rewritten = _rewrite_dot_access(expression)
        evaluator = EvalWithCompoundTypes(
            names={"input": dict(input_data), "nodes": dict(context.node_outputs)}
        )
        try:
            value = evaluator.eval(rewritten)
        except Exception as exc:
            raise ExpressionEvalError(
                f"Failed to evaluate {expression!r}: {exc}"
            ) from exc

        return {"result": value}
