import re

from simpleeval import EvalWithCompoundTypes, InvalidExpression

from app.core.context import ExecutionContext
from app.nodes.base import BaseNode
from app.schemas.node_configs import ConditionConfig

# `simpleeval` не дає атрибутного доступу за замовчуванням.
# Переписуємо `input.size` -> `input["size"]`, `nodes.r1.path` -> `nodes["r1"]["path"]`.
# Це дозволяє писати у виразах звичну dot-нотацію, а під капотом
# simpleeval працює через підписку (subscript), що йому дозволено.
_DOT_ACCESS = re.compile(r"\b(input|nodes)((?:\.[a-zA-Z_][a-zA-Z0-9_]*)+)")


def _rewrite_dot_access(expr: str) -> str:
    def repl(m: re.Match[str]) -> str:
        scope = m.group(1)
        keys = m.group(2).lstrip(".").split(".")
        return scope + "".join(f"[{k!r}]" for k in keys)

    return _DOT_ACCESS.sub(repl, expr)


class ConditionEvalError(ValueError):
    """Помилка під час обчислення виразу condition-вузла."""


class ConditionNode(BaseNode):
    """Безпечне обчислення булевого виразу.

    Доступні імена у виразі:
      - `input` — поточний вхід вузла (dict)
      - `nodes` — `dict[node_id, output_dict]` усіх попередніх вузлів
    """

    type_name = "condition"
    config_model = ConditionConfig

    async def execute(self, context: ExecutionContext) -> dict:
        rewritten = _rewrite_dot_access(self.config.expression)
        evaluator = EvalWithCompoundTypes(
            names={"input": context.current_input, "nodes": context.node_outputs}
        )
        try:
            value = evaluator.eval(rewritten)
        except InvalidExpression as exc:
            raise ConditionEvalError(
                f"Failed to evaluate {self.config.expression!r}: {exc}"
            ) from exc

        return {"result": bool(value), "input": context.current_input}
