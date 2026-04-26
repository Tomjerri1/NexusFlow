from pathlib import Path

import pytest

from app.core.context import ExecutionContext
from app.core.engine import UnknownNodeTypeError, WorkflowEngine
from app.core.scheduler import CycleDetectedError, topological_sort
from app.schemas.workflow import Workflow

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


def _load(name: str) -> Workflow:
    return Workflow.model_validate_json((EXAMPLES_DIR / name).read_text(encoding="utf-8"))


async def _run(workflow: Workflow, ctx: ExecutionContext) -> dict:
    return await WorkflowEngine().run(workflow, ctx.job_id, ctx)


# ---------- scheduler ----------

def test_topological_sort_linear():
    wf = Workflow.model_validate(
        {
            "name": "lin",
            "nodes": [
                {"id": "a", "type": "manual_trigger", "config": {}},
                {"id": "b", "type": "log", "config": {"message": "x"}},
                {"id": "c", "type": "log", "config": {"message": "y"}},
            ],
            "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}],
        }
    )
    order = [n.id for n in topological_sort(wf.nodes, wf.edges)]
    assert order == ["a", "b", "c"]


def test_topological_sort_diamond_keeps_partial_order():
    wf = Workflow.model_validate(
        {
            "name": "diamond",
            "nodes": [
                {"id": "a", "type": "manual_trigger", "config": {}},
                {"id": "b", "type": "log", "config": {"message": "x"}},
                {"id": "c", "type": "log", "config": {"message": "y"}},
                {"id": "d", "type": "log", "config": {"message": "z"}},
            ],
            "edges": [
                {"from": "a", "to": "b"},
                {"from": "a", "to": "c"},
                {"from": "b", "to": "d"},
                {"from": "c", "to": "d"},
            ],
        }
    )
    order = [n.id for n in topological_sort(wf.nodes, wf.edges)]
    assert order.index("a") < order.index("b")
    assert order.index("a") < order.index("c")
    assert order.index("b") < order.index("d")
    assert order.index("c") < order.index("d")


def test_topological_sort_detects_cycle():
    wf = Workflow.model_validate(
        {
            "name": "cyc",
            "nodes": [
                {"id": "a", "type": "log", "config": {"message": "x"}},
                {"id": "b", "type": "log", "config": {"message": "y"}},
            ],
            "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}],
        }
    )
    with pytest.raises(CycleDetectedError) as exc_info:
        topological_sort(wf.nodes, wf.edges)
    assert exc_info.value.cycle_node_ids == ["a", "b"]


# ---------- engine: 3 example workflows ----------

async def test_example_hello_world(ctx: ExecutionContext, fake_broker):
    result = await _run(_load("01_hello_world.json"), ctx)
    assert set(result) == {"t1", "l1"}
    messages = [e.message for _, e in fake_broker.entries]
    assert "Hello, Student!" in messages


async def test_example_read_write_copy(ctx: ExecutionContext):
    result = await _run(_load("02_read_write_copy.json"), ctx)
    assert "w1" in result
    written_path = Path(result["w1"]["path"])
    try:
        assert written_path.exists()
        assert result["w1"]["bytes_written"] == result["r1"]["size"]
        assert written_path.read_text(encoding="utf-8") == result["r1"]["content"]
    finally:
        written_path.unlink(missing_ok=True)


async def test_example_condition_branching_takes_true(
    ctx: ExecutionContext, fake_broker
):
    """`data/input.txt` свідомо > 100 байт, тож true-гілка має виконатися,
    а false-гілка — пропуститися."""
    result = await _run(_load("03_condition_branching.json"), ctx)
    assert result["c1"]["result"] is True
    assert "l_big" in result
    assert "l_small" not in result
    skipped = [
        e.message for _, e in fake_broker.entries
        if e.node_id == "l_small" and "Skipped" in e.message
    ]
    assert skipped, "expected a 'Skipped' log entry for l_small"


# ---------- engine: behaviour ----------

async def test_engine_propagates_node_error_as_failure(ctx: ExecutionContext, fake_broker):
    wf = Workflow.model_validate(
        {
            "name": "missing_file",
            "nodes": [
                {"id": "t1", "type": "manual_trigger", "config": {}},
                {"id": "r1", "type": "read_file", "config": {"path": "/__nope__/x"}},
            ],
            "edges": [{"from": "t1", "to": "r1"}],
        }
    )
    with pytest.raises(FileNotFoundError):
        await _run(wf, ctx)
    error_logs = [e for _, e in fake_broker.entries if e.level == "error"]
    assert error_logs, "expected an error-level log entry"


async def test_engine_unknown_node_type_raises(ctx: ExecutionContext):
    # Створюємо граф через model_construct, щоб обійти Pydantic Literal-перевірку.
    from app.schemas.workflow import Edge, Node
    bad_node = Node.model_construct(id="x", type="unknown", config={})  # type: ignore[arg-type]
    wf = Workflow.model_construct(name="bad", nodes=[bad_node], edges=[])
    with pytest.raises(UnknownNodeTypeError):
        await _run(wf, ctx)


async def test_port_mapped_value_visible_via_input_in_template(
    ctx: ExecutionContext, fake_broker
):
    """Значення, яке прийшло на порт log-вузла, має бути видно у шаблоні
    `{input.<port>}` без додаткових налаштувань — це універсальний міст
    із node_inputs у current_input.
    """
    from app.schemas.workflow import Workflow as _Wf  # local alias avoids shadowing
    wf = _Wf.model_validate(
        {
            "name": "bridge",
            "nodes": [
                {
                    "id": "t1",
                    "type": "manual_trigger",
                    "config": {"initial_data": {"label": "hi"}},
                },
                {
                    "id": "l1",
                    "type": "log",
                    "config": {"message": "got {input.headline}"},
                },
            ],
            "edges": [
                {
                    "from": "t1",
                    "to": "l1",
                    "source_handle": "label",
                    "target_handle": "headline",
                },
            ],
        }
    )
    await _run(wf, ctx)
    messages = [e.message for _, e in fake_broker.entries]
    assert "got hi" in messages


async def test_log_node_with_empty_message_dumps_input_as_json(
    ctx: ExecutionContext, fake_broker
):
    wf = Workflow.model_validate(
        {
            "name": "log_dump",
            "nodes": [
                {
                    "id": "t1",
                    "type": "manual_trigger",
                    "config": {"initial_data": {"a": 1, "b": "x"}},
                },
                {"id": "l1", "type": "log", "config": {"message": ""}},
            ],
            "edges": [{"from": "t1", "to": "l1"}],
        }
    )
    await _run(wf, ctx)
    json_dumps = [
        e.message for _, e in fake_broker.entries
        if e.node_id == "l1" and e.message.startswith("{")
    ]
    assert json_dumps, "expected a JSON-dump log entry from log node"
    assert '"a": 1' in json_dumps[0]
    assert '"b": "x"' in json_dumps[0]


async def test_port_mapping_routes_value_into_target_handle(ctx: ExecutionContext):
    """expression-вузол отримує значення `expression` через port-mapping
    (без дублювання в config) і повертає обчислений результат.
    """
    wf = Workflow.model_validate(
        {
            "name": "port_map",
            "nodes": [
                {
                    "id": "t1",
                    "type": "manual_trigger",
                    "config": {"initial_data": {"expr_text": "1 + 2"}},
                },
                {
                    "id": "e1",
                    "type": "expression",
                    # дефолт — буде перекритий port-mapping'ом
                    "config": {"expression": "0"},
                },
            ],
            "edges": [
                {
                    "from": "t1",
                    "to": "e1",
                    "source_handle": "expr_text",
                    "target_handle": "expression",
                },
            ],
        }
    )
    result = await _run(wf, ctx)
    assert result["e1"]["result"] == 3


async def test_condition_false_branch_executes_when_expression_false(
    ctx: ExecutionContext, fake_broker
):
    wf = Workflow.model_validate(
        {
            "name": "false_branch",
            "nodes": [
                {"id": "t1", "type": "manual_trigger", "config": {"initial_data": {"size": 5}}},
                {"id": "c1", "type": "condition", "config": {"expression": "input.size > 100"}},
                {"id": "lt", "type": "log", "config": {"message": "big"}},
                {"id": "lf", "type": "log", "config": {"message": "small"}},
            ],
            "edges": [
                {"from": "t1", "to": "c1"},
                {"from": "c1", "to": "lt", "source_handle": "true"},
                {"from": "c1", "to": "lf", "source_handle": "false"},
            ],
        }
    )
    result = await _run(wf, ctx)
    assert result["c1"]["result"] is False
    assert "lf" in result
    assert "lt" not in result
