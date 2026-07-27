import re

from simpleeval import EvalWithCompoundTypes, InvalidExpression

from app.core.context import ExecutionContext
from app.nodes.base import BaseNode, input_port, node_info, output_port
from app.schemas.node_configs import ConditionConfig

# `simpleeval` does not provide attribute access by default.
# Rewrite `input.size` as `input[“size”]` and `nodes.r1.path` as `nodes[‘r1’][“path”]`.
_DOT_ACCESS = re.compile(r"\b(input|nodes)((?:\.[a-zA-Z_][a-zA-Z0-9_]*)+)")


def _rewrite_dot_access(expr: str) -> str:
    def repl(m: re.Match[str]) -> str:
        scope = m.group(1)
        keys = m.group(2).lstrip(".").split(".")
        return scope + "".join(f"[{k!r}]" for k in keys)

    return _DOT_ACCESS.sub(repl, expr)


class ConditionEvalError(ValueError):
    """An error occurred while evaluating the condition node expression."""


@node_info(
    display_name="Condition",
    category="logic",
    color="#d97706",
    icon="git-branch",
    description="Boolean branch: routes execution via 'true'/'false' source handles.",
)
@input_port("input", type_hint="any", required=False)
@output_port("true", type_hint="dict", description="Branch when expression is truthy.")
@output_port("false", type_hint="dict", description="Branch when expression is falsy.")
@output_port("result", type_hint="bool")
class ConditionNode(BaseNode):
    """Safe evaluation of a Boolean expression.
    Available names in the expression:
      - `input` — the local `input_data` passed by the engine
      - `nodes` — a snapshot of `node_outputs` from all preceding nodes
    """

    type_name = "condition"
    config_model = ConditionConfig

    async def execute(self, context: ExecutionContext, input_data: dict) -> dict:
        rewritten = _rewrite_dot_access(self.config.expression)
        # Take a snapshot of `node_outputs` to avoid a race condition with parallel workers.
        evaluator = EvalWithCompoundTypes(
            names={"input": dict(input_data), "nodes": dict(context.node_outputs)}
        )
        try:
            value = evaluator.eval(rewritten)
        except InvalidExpression as exc:
            raise ConditionEvalError(
                f"Failed to evaluate {self.config.expression!r}: {exc}"
            ) from exc

        return {"result": bool(value), "input": dict(input_data)}
