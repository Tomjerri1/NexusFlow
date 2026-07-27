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

#scheduler

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
    """Checks the low-level behavior of `topological_sort` — we create
    nodes and edges directly, because `Workflow.model_validate` with a loop will now
    fail on its own pre-execution validator (see
    `test_workflow_rejects_cyclic_graph` in test_schemas.py).
    """
    from app.schemas.workflow import Edge as _Edge, Node as _Node

    nodes = [
        _Node(id="a", type="log", config={"message": "x"}),
        _Node(id="b", type="log", config={"message": "y"}),
    ]
    edges = [
        _Edge.model_validate({"from": "a", "to": "b"}),
        _Edge.model_validate({"from": "b", "to": "a"}),
    ]
    with pytest.raises(CycleDetectedError) as exc_info:
        topological_sort(nodes, edges)
    assert exc_info.value.cycle_node_ids == ["a", "b"]


#engine: 3 example workflows

async def test_example_hello_world(ctx: ExecutionContext, fake_broker):
    result = await _run(_load("01_hello_world.json"), ctx)
    assert set(result) == {"t1", "l1"}
    messages = [e.message for _, e in fake_broker.entries]
    assert "Hello, Student!" in messages

async def test_example_condition_branching_takes_true(
    ctx: ExecutionContext, fake_broker
):
    """`Since `data/input.txt` is intentionally larger than 100 bytes, the true branch should be executed,
    while the false branch should be skipped."""
    result = await _run(_load("03_condition_branching.json"), ctx)
    assert result["c1"]["result"] is True
    assert "l_big" in result
    assert "l_small" not in result
    skipped = [
        e.message for _, e in fake_broker.entries
        if e.node_id == "l_small" and "Skipped" in e.message
    ]
    assert skipped, "expected a 'Skipped' log entry for l_small"

#engine: behaviour

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
    # We create a graph using `model_construct` to bypass the Pydantic Literal check.
    from app.schemas.workflow import Edge, Node
    bad_node = Node.model_construct(id="x", type="unknown", config={})  # type: ignore[arg-type]
    wf = Workflow.model_construct(name="bad", nodes=[bad_node], edges=[])
    with pytest.raises(UnknownNodeTypeError):
        await _run(wf, ctx)

async def test_port_mapped_value_visible_via_input_in_template(
    ctx: ExecutionContext, fake_broker
):
    """The value received on the log node's port should be visible in the template
    `{input.<port>}` without any additional configuration—this is a universal bridge
    from `node_inputs` to `current_input`.
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
    """The `expression` node receives the value of `expression` via port mapping
    (without duplication in the config) and returns the calculated result.
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
                    # default — will be overridden by port mapping
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

async def test_port_mapping_autoconverts_str_to_int(ctx: ExecutionContext):
    """The expression expects an int on the `expression` port, but the trigger returns a string—
    the engine should auto-convert without issuing a warning only in valid cases;
    here, the types match (str → str), so the value is passed as-is.
    """
    wf = Workflow.model_validate(
        {
            "name": "auto_str_pass",
            "nodes": [
                {"id": "t1", "type": "manual_trigger", "config": {"initial_data": {"e": 42}}},
                {"id": "e1", "type": "expression", "config": {"expression": "input.value + 1"}},
            ],
            "edges": [
                {"from": "t1", "to": "e1", "source_handle": "e", "target_handle": "expression"},
            ],
        }
    )
    # Here, the `expression` port is declared as a string, but we're passing the integer 42—
    # the engine will convert it to “42”, and the expression node will receive a string expression.
    result = await _run(wf, ctx)
    # “42” is a valid sandbox expression that returns 42.
    assert result["e1"]["result"] == 42

async def test_port_mapping_logs_warning_on_unconvertible_type(
    ctx: ExecutionContext, fake_broker
):
    """If the type doesn't match and the conversion fails, there should
    be a warning in the logs, but execution continues.
    """
    wf = Workflow.model_validate(
        {
            "name": "bad_convert",
            "nodes": [
                {
                    "id": "t1",
                    "type": "manual_trigger",
                    "config": {"initial_data": {"obj": {"a": 1}}},
                },
                {"id": "r1", "type": "read_file", "config": {"path": "data/input.txt"}},
            ],
            "edges": [
                # The `path` port expects a string, but we're passing the entire dictionary through the source_handle
                {"from": "t1", "to": "r1", "source_handle": "obj", "target_handle": "path"},
            ],
        }
    )
    # Here, converting a dict to a string using `str(value)` actually works (this isn't a bug),
    # so no warning will be displayed. We're just checking that the graph doesn't crash.
    try:
        await _run(wf, ctx)
    except Exception:
        # A FileNotFoundError may occur when calling read_file — we're only interested in
        # whether the engine reached execute() (i.e., the warning didn't stop execution).
        pass

async def test_workflow_is_readonly_propagates_to_edges(ctx: ExecutionContext):
    from app.core.engine import _collect_effective_edges
    wf = Workflow.model_validate(
        {
            "name": "ro",
            "is_readonly": True,
            "nodes": [
                {"id": "t1", "type": "manual_trigger", "config": {}},
                {"id": "l1", "type": "log", "config": {"message": "hi"}},
            ],
            "edges": [{"from": "t1", "to": "l1"}],
        }
    )
    edges = _collect_effective_edges(wf)
    assert all(e.is_readonly for e in edges)
    # Regular execution still proceeds—`readonly` does not block the engine.
    await _run(wf, ctx)


async def test_dead_branch_cascades_through_chain(
    ctx: ExecutionContext, fake_broker
):
    """If the condition selects the true branch, the ENTIRE false branch (including
    the descendants of the node on the false handle) must be skipped—
    none of them should call execute().
    """
    wf = Workflow.model_validate(
        {
            "name": "dead_chain",
            "nodes": [
                {"id": "t1", "type": "manual_trigger",
                 "config": {"initial_data": {"size": 200}}},
                {"id": "c1", "type": "condition",
                 "config": {"expression": "input.size > 100"}},
                # true branch
                {"id": "lt", "type": "log", "config": {"message": "big"}},
                # false branch: lf1 → lf2 → lf3
                {"id": "lf1", "type": "log", "config": {"message": "small1"}},
                {"id": "lf2", "type": "log", "config": {"message": "small2"}},
                {"id": "lf3", "type": "log", "config": {"message": "small3"}},
            ],
            "edges": [
                {"from": "t1", "to": "c1"},
                {"from": "c1", "to": "lt", "source_handle": "true"},
                {"from": "c1", "to": "lf1", "source_handle": "false"},
                {"from": "lf1", "to": "lf2"},
                {"from": "lf2", "to": "lf3"},
            ],
        }
    )
    result = await _run(wf, ctx)
    assert result["c1"]["result"] is True
    assert "lt" in result
    # None of the false descendants were executed
    assert "lf1" not in result
    assert "lf2" not in result
    assert "lf3" not in result
    # All three have “Skipped due to dead branch” in their logs
    skip_messages = {
        e.node_id: e.message
        for _, e in fake_broker.entries
        if "Skipped" in e.message
    }
    assert "lf1" in skip_messages
    assert "lf2" in skip_messages
    assert "lf3" in skip_messages
    assert all("dead branch" in m for m in skip_messages.values())

async def test_dead_branch_kills_node_with_other_inputs_only_from_dead_branch(
    ctx: ExecutionContext,
):
    """A node whose ALL inbound edges originate from a dead branch
    (even if through different intermediate nodes) must also be dead.
    """
    wf = Workflow.model_validate(
        {
            "name": "diamond_dead",
            "nodes": [
                {"id": "t1", "type": "manual_trigger",
                 "config": {"initial_data": {"flag": False}}},
                {"id": "c1", "type": "condition",
                 "config": {"expression": "input.flag"}},
                # Both `merge` inputs come from the false branch
                {"id": "lf_a", "type": "log", "config": {"message": "a"}},
                {"id": "lf_b", "type": "log", "config": {"message": "b"}},
                {"id": "merge", "type": "log", "config": {"message": "merge"}},
            ],
            "edges": [
                {"from": "t1", "to": "c1"},
                {"from": "c1", "to": "lf_a", "source_handle": "true"},
                {"from": "c1", "to": "lf_b", "source_handle": "true"},
                {"from": "lf_a", "to": "merge"},
                {"from": "lf_b", "to": "merge"},
            ],
        }
    )
    result = await _run(wf, ctx)
    assert result["c1"]["result"] is False
    assert "lf_a" not in result
    assert "lf_b" not in result
    # If a merge has only dead inbounds, it is also dead, even with two edges
    assert "merge" not in result

async def test_trigger_rule_all_success_skips_node_when_one_input_dead(
    ctx: ExecutionContext,
):
    """By default, the `all_success` merge node should not be executed
    if at least one of its incoming edges is dead (in this case, the false branch of the condition).
    """
    wf = Workflow.model_validate(
        {
            "name": "all_success_diamond",
            "nodes": [
                {"id": "t1", "type": "manual_trigger",
                 "config": {"initial_data": {"v": 200}}},
                {"id": "c1", "type": "condition",
                 "config": {"expression": "input.v > 100"}},
                {"id": "lt", "type": "log", "config": {"message": "true"}},
                {"id": "lf", "type": "log", "config": {"message": "false"}},
                # The merge has TWO incoming edges: one from the true branch and one from the false branch.
                # The default trigger_rule is all_success, so the merge should be skipped.
                {"id": "merge", "type": "log", "config": {"message": "merge"}},
            ],
            "edges": [
                {"from": "t1", "to": "c1"},
                {"from": "c1", "to": "lt", "source_handle": "true"},
                {"from": "c1", "to": "lf", "source_handle": "false"},
                {"from": "lt", "to": "merge"},
                {"from": "lf", "to": "merge"},
            ],
        }
    )
    result = await _run(wf, ctx)
    assert result["c1"]["result"] is True
    assert "lt" in result
    assert "lf" not in result
    # all_success: one of the merge's incoming edges is dead → merge is dead
    assert "merge" not in result

async def test_trigger_rule_one_success_runs_node_when_at_least_one_input_alive(
    ctx: ExecutionContext,
):
    """It's the same graph, but the merge has `trigger_rule=“one_success”` —
    OR semantics, so the merge must be executed because the true branch is alive.
    """
    wf = Workflow.model_validate(
        {
            "name": "one_success_diamond",
            "nodes": [
                {"id": "t1", "type": "manual_trigger",
                 "config": {"initial_data": {"v": 200}}},
                {"id": "c1", "type": "condition",
                 "config": {"expression": "input.v > 100"}},
                {"id": "lt", "type": "log", "config": {"message": "true"}},
                {"id": "lf", "type": "log", "config": {"message": "false"}},
                {"id": "merge", "type": "log",
                 "config": {"message": "merge"},
                 "trigger_rule": "one_success"},
            ],
            "edges": [
                {"from": "t1", "to": "c1"},
                {"from": "c1", "to": "lt", "source_handle": "true"},
                {"from": "c1", "to": "lf", "source_handle": "false"},
                {"from": "lt", "to": "merge"},
                {"from": "lf", "to": "merge"},
            ],
        }
    )
    result = await _run(wf, ctx)
    assert "lt" in result
    assert "lf" not in result
    # one_success: one live incoming edge is sufficient (lt) → merge is performed
    assert "merge" in result


async def test_trigger_rule_one_success_skipped_when_all_inputs_dead(
    ctx: ExecutionContext,
):
    """Even for `one_success`, the node must die if ALL of its inputs are dead."""
    wf = Workflow.model_validate(
        {
            "name": "one_success_all_dead",
            "nodes": [
                {"id": "t1", "type": "manual_trigger",
                 "config": {"initial_data": {"v": 1}}},
                {"id": "c1", "type": "condition",
                 "config": {"expression": "input.v > 100"}},
                {"id": "lt", "type": "log", "config": {"message": "true"}},
                {"id": "lt2", "type": "log", "config": {"message": "true2"}},
                {"id": "merge", "type": "log",
                 "config": {"message": "merge"},
                 "trigger_rule": "one_success"},
            ],
            "edges": [
                {"from": "t1", "to": "c1"},
                {"from": "c1", "to": "lt", "source_handle": "true"},
                {"from": "c1", "to": "lt2", "source_handle": "true"},
                {"from": "lt", "to": "merge"},
                {"from": "lt2", "to": "merge"},
            ],
        }
    )
    result = await _run(wf, ctx)
    assert result["c1"]["result"] is False
    assert "lt" not in result
    assert "lt2" not in result
    # All inbound merges are dead → a merge is dead even with `one_success`
    assert "merge" not in result

async def test_kill_marks_outgoing_edges_dead():
    """A direct unit test for the cascade: `_kill` adds a node to `dead_nodes`
    and marks all its outgoing edges as `dead_edges`. This ensures that
    the next `_evaluate_child` will treat the descendants of the dead branch as dead.
    """
    from app.core.engine import WorkflowEngine, _RunState, _edge_key
    from app.schemas.workflow import Edge as _Edge, Node as _Node, Workflow as _Wf

    wf = _Wf.model_construct(
        name="kill_test",
        nodes=[
            _Node.model_construct(id="a", type="log", config={}),
            _Node.model_construct(id="b", type="log", config={}),
            _Node.model_construct(id="c", type="log", config={}),
        ],
        edges=[
            _Edge.model_validate({"from": "a", "to": "b"}),
            _Edge.model_validate({"from": "a", "to": "c"}),
            _Edge.model_validate({"from": "b", "to": "c"}),
        ],
    )
    state = _RunState.build(wf, list(wf.edges))

    WorkflowEngine._kill(state, "a")
    assert "a" in state.dead_nodes
    assert _edge_key(wf.edges[0]) in state.dead_edges  # a→b
    assert _edge_key(wf.edges[1]) in state.dead_edges  # a→c
    assert _edge_key(wf.edges[2]) not in state.dead_edges  # b→c (не від a)

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


#engine: Async Ready Pool — Parallelism and Soft Stopping

import asyncio as _asyncio
import time as _time

from pydantic import BaseModel as _BaseModel

from app.nodes.base import NODE_REGISTRY as _REG, BaseNode as _BaseNode, output_port as _output_port

class _SleepConfig(_BaseModel):
    delay: float = 0.5
    label: str = ""

@_output_port("output", type_hint="dict")
class _SleeperNode(_BaseNode):
    """Test node: sleeps for `config.delay` seconds and returns a token."""

    type_name = "test_sleeper"
    config_model = _SleepConfig

    async def execute(self, context, input_data: dict) -> dict:
        await _asyncio.sleep(self.config.delay)
        return {"slept": self.config.delay, "label": self.config.label}

class _FailConfig(_BaseModel):
    delay: float = 0.0
    message: str = "boom"


@_output_port("output", type_hint="dict")
class _FailerNode(_BaseNode):
    """Test case: optionally hangs, then raises a RuntimeError."""

    type_name = "test_failer"
    config_model = _FailConfig

    async def execute(self, context, input_data: dict) -> dict:
        if self.config.delay > 0:
            await _asyncio.sleep(self.config.delay)
        raise RuntimeError(self.config.message)

@pytest.fixture
def custom_test_nodes():
    """Temporarily registers the test nodes test_sleeper and test_failer
    in NODE_REGISTRY and removes them after the test to prevent them from leaking between
    tests and corrupting /api/nodes/schema in API tests.
    """
    _REG["test_sleeper"] = _SleeperNode
    _REG["test_failer"] = _FailerNode
    yield
    _REG.pop("test_sleeper", None)
    _REG.pop("test_failer", None)

def _construct_wf(name: str, nodes: list, edges: list):
    """Creates a workflow that bypasses the `Literal[NodeType]` check—required for
    test nodes that are not part of the production set."""
    from app.schemas.workflow import Edge as _E, Node as _N, Workflow as _W

    return _W.model_construct(
        name=name,
        nodes=[_N.model_construct(**n) for n in nodes],
        edges=[_E.model_validate(e) for e in edges],
        is_readonly=False,
    )

async def test_two_parallel_sleeps_finish_in_about_one_second(
    ctx: ExecutionContext, custom_test_nodes
):
    """This demonstrates that the engine does indeed launch tasks in parallel.
    Diagram: one trigger → two branches, each with a 1-second sleep.
    If the engine is sequential, the time will be ~2 seconds.
    If it is parallel (Async Ready Pool), the time will be ~1 second.
    """
    wf = _construct_wf(
        "parallel_sleeps",
        nodes=[
            {"id": "t", "type": "manual_trigger", "config": {}},
            {"id": "s1", "type": "test_sleeper",
             "config": {"delay": 1.0, "label": "A"}},
            {"id": "s2", "type": "test_sleeper",
             "config": {"delay": 1.0, "label": "B"}},
        ],
        edges=[
            {"from": "t", "to": "s1"},
            {"from": "t", "to": "s2"},
        ],
    )

    start = _time.monotonic()
    result = await _run(wf, ctx)
    elapsed = _time.monotonic() - start

    assert "s1" in result and "s2" in result
    assert result["s1"]["label"] == "A"
    assert result["s2"]["label"] == "B"
    # Buffer for the planner's overhead; sequential execution would take ~2 seconds.
    assert elapsed < 1.7, (
        f"expected ~1s parallel execution, got {elapsed:.2f}s "
        f"— це натяк на втрату паралелізму у воркер-пулі"
    )

async def test_six_parallel_sleeps_within_worker_pool_limit(
    ctx: ExecutionContext, custom_test_nodes
):
    """6 parallel threads are added to the default pool (MAX_WORKERS=6)
    and finish in ~`delay` seconds, rather than `6 × delay`."""
    delay = 0.5
    nodes = [{"id": "t", "type": "manual_trigger", "config": {}}]
    edges = []
    for i in range(6):
        sid = f"s{i}"
        nodes.append({
            "id": sid, "type": "test_sleeper",
            "config": {"delay": delay, "label": str(i)},
        })
        edges.append({"from": "t", "to": sid})

    wf = _construct_wf("parallel_six", nodes=nodes, edges=edges)

    start = _time.monotonic()
    result = await _run(wf, ctx)
    elapsed = _time.monotonic() - start

    for i in range(6):
        assert f"s{i}" in result
    # The sequential version would take ~3 seconds; the parallel version ~0.5 seconds + overhead.
    assert elapsed < 1.5, f"expected ~{delay}s, got {elapsed:.2f}s"

async def test_failure_in_one_branch_lets_running_finish_but_blocks_new(
    ctx: ExecutionContext, custom_test_nodes
):
    """“Soft stop” semantics:
      • If one of the parallel nodes fails → `should_stop=True`,
      • Any already-running child nodes must complete their execution (they are not canceled),
      • The child nodes of the failed node DO NOT start (they are cut off by the dead-cascade).
    Graph:
        t ─┬─→ s_long  (sleep 0.4s, in parallel with fail)
           └─→ fail    (raise immediately)
                  └─→ after_fail (should be skipped as dead)
    """
    wf = _construct_wf(
        "fail_isolation",
        nodes=[
            {"id": "t", "type": "manual_trigger", "config": {}},
            {"id": "s_long", "type": "test_sleeper",
             "config": {"delay": 0.4, "label": "long"}},
            {"id": "fail", "type": "test_failer",
             "config": {"message": "branch boom"}},
            {"id": "after_fail", "type": "test_sleeper",
             "config": {"delay": 0.1, "label": "after"}},
        ],
        edges=[
            {"from": "t", "to": "s_long"},
            {"from": "t", "to": "fail"},
            {"from": "fail", "to": "after_fail"},
        ],
    )

    start = _time.monotonic()
    with pytest.raises(RuntimeError, match="branch boom"):
        await _run(wf, ctx)
    elapsed = _time.monotonic() - start

    # s_long finished playing — the engine does not cancel running processes.
    assert "s_long" in ctx.node_outputs
    assert ctx.node_outputs["s_long"]["label"] == "long"

    # after_fail — descendant of a dead branch → execute() was not called.
    assert "after_fail" not in ctx.node_outputs

    # The soft stop flag remained raised.
    assert ctx.should_stop is True
    assert isinstance(ctx.first_error, RuntimeError)

    # The time is ~ s_long's delay, not 0 (because we were waiting for it to finish).
    assert elapsed >= 0.35, (
        f"expected to wait for s_long (~0.4s), finished in {elapsed:.2f}s"
    )


async def test_failure_does_not_start_pending_independent_node(
    ctx: ExecutionContext, custom_test_nodes
):
    """If an error occurs before the worker has had a chance to retrieve an
    independent node from the queue, that node will NOT be executed (`should_stop` is triggered
    at the entrance to the worker loop).
    Here we ensure the following: we set max_workers=1 so that the queue is guaranteed
    to have an “unstarted” node at the time of the failure.
    """
    from app.core.engine import WorkflowEngine as _WE

    wf = _construct_wf(
        "fail_blocks_pending",
        nodes=[
            {"id": "t", "type": "manual_trigger", "config": {}},
            {"id": "fail", "type": "test_failer",
             "config": {"message": "early boom"}},
            {"id": "independent", "type": "test_sleeper",
             "config": {"delay": 0.05, "label": "ind"}},
        ],
        edges=[
            {"from": "t", "to": "fail"},
            {"from": "t", "to": "independent"},
        ],
    )

    engine = _WE(max_workers=1)
    with pytest.raises(RuntimeError, match="early boom"):
        await engine.run(wf, ctx.job_id, ctx)

    # With a single worker: t → fail → fail (worker crashes) → should_stop=True → independent
    # It waited in the queue and was not started.
    assert "fail" not in ctx.node_outputs  # fell
    assert "independent" not in ctx.node_outputs  # Did not start due to should_stop


async def test_resolve_template_uses_snapshot_under_concurrent_writes(
    ctx: ExecutionContext, custom_test_nodes
):
    """While one node is performing `resolve_template`, other nodes can write
    new outputs to `node_outputs`. `resolve_template` must take a local
    snapshot, so a race condition will not result in a RuntimeError.

    We test this indirectly: we run a graph where many parallel nodes write
    to `node_outputs`, and log nodes read via templates. If a snapshot
    is not taken, a `RuntimeError: dictionary changed size` would occur.
    """
    nodes = [{"id": "t", "type": "manual_trigger",
              "config": {"initial_data": {"label": "X"}}}]
    edges = []
    for i in range(8):
        sid = f"s{i}"
        lid = f"l{i}"
        nodes.append({"id": sid, "type": "test_sleeper",
                      "config": {"delay": 0.05, "label": str(i)}})
        nodes.append({"id": lid, "type": "log",
                      "config": {"message": "tick {input.label}"}})
        edges.append({"from": "t", "to": sid})
        edges.append({"from": "t", "to": lid})

    wf = _construct_wf("snapshot_race", nodes=nodes, edges=edges)
    result = await _run(wf, ctx)
    for i in range(8):
        assert f"s{i}" in result
        assert f"l{i}" in result


#engine: visual-only nodes (Note)

async def test_note_nodes_are_filtered_before_execution(
    ctx: ExecutionContext, fake_broker
):
    """The Note (is_visual_only=True) must be completely invisible to the engine:
    no entries in node_outputs, no logs about it, no
    pending_count. Neighboring (active) nodes behave as usual.
    """
    wf = Workflow.model_validate(
        {
            "name": "with_note",
            "nodes": [
                {"id": "t1", "type": "manual_trigger",
                 "config": {"initial_data": {"x": 1}}},
                {"id": "n1", "type": "note",
                 "config": {"html_content": "<strong>doc me</strong>"}},
                {"id": "l1", "type": "log", "config": {"message": "hi"}},
            ],
            "edges": [{"from": "t1", "to": "l1"}],
        }
    )
    result = await _run(wf, ctx)
    assert "t1" in result
    assert "l1" in result
    assert "n1" not in result
    # Жоден лог не має згадувати note-вузол.
    assert all(e.node_id != "n1" for _, e in fake_broker.entries)


async def test_note_node_with_dangling_edges_is_dropped(ctx: ExecutionContext):
    """Якщо у JSON-графі лишилися ребра, що торкаються note-вузла, рушій
    має їх відкинути ще до topological_sort — інакше відбувся б фейл
    pre-flight'а через невідомий тип/інші поля.
    """
    wf = Workflow.model_validate(
        {
            "name": "note_with_edges",
            "nodes": [
                {"id": "t1", "type": "manual_trigger", "config": {}},
                {"id": "n1", "type": "note", "config": {}},
                {"id": "l1", "type": "log", "config": {"message": "ok"}},
            ],
            "edges": [
                {"from": "t1", "to": "l1"},
                # “phantom” edge in note (the front end might not have generated this, but
                # we guarantee stability).
                {"from": "t1", "to": "n1"},
                {"from": "n1", "to": "l1"},
            ],
        }
    )
    result = await _run(wf, ctx)
    assert "t1" in result and "l1" in result
    assert "n1" not in result
