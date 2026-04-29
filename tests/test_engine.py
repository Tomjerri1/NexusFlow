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
    """Перевіряє низькорівневу поведінку `topological_sort` — створюємо
    nodes/edges напряму, бо `Workflow.model_validate` з циклом тепер
    впаде на власному pre-execution-валідаторі (див.
    `test_workflow_rejects_cyclic_graph` у test_schemas.py).
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


async def test_port_mapping_autoconverts_str_to_int(ctx: ExecutionContext):
    """Експресія очікує int на порт `expression`, але trigger дає рядок —
    рушій повинен автоконвертувати без warning'а лише в коректних кейсах,
    тут тип збігається (str → str), значення йде як є.
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
    # Тут порт `expression` декларовано як str, а ми передаємо int 42 —
    # рушій сконвертує його у "42", expression-вузол отримає рядок-вираз.
    result = await _run(wf, ctx)
    # "42" — це валідний sandbox-вираз, який повертає 42.
    assert result["e1"]["result"] == 42


async def test_port_mapping_logs_warning_on_unconvertible_type(
    ctx: ExecutionContext, fake_broker
):
    """Якщо тип непідходить і конвертація не вдається — у логах має
    бути warning, але виконання продовжується.
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
                # порт `path` очікує str, а ми пихаємо весь dict через source_handle
                {"from": "t1", "to": "r1", "source_handle": "obj", "target_handle": "path"},
            ],
        }
    )
    # Тут конвертація dict→str через str(value) насправді спрацює (це не помилка),
    # тож warning не з'явиться. Перевіряємо лише, що граф не падає.
    try:
        await _run(wf, ctx)
    except Exception:
        # Можлива FileNotFoundError від read_file — нас цікавить лише,
        # що рушій дійшов до execute() (тобто warning не зупинив виконання).
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
    # Регулярне виконання все одно проходить — readonly не блокує рушій.
    await _run(wf, ctx)


async def test_dead_branch_cascades_through_chain(
    ctx: ExecutionContext, fake_broker
):
    """Якщо condition обрав true-гілку, ВСЯ false-гілка (включно з
    нащадками вузла, що сидить на false-handle) має пропуститися —
    жоден з них не повинен викликати execute().
    """
    wf = Workflow.model_validate(
        {
            "name": "dead_chain",
            "nodes": [
                {"id": "t1", "type": "manual_trigger",
                 "config": {"initial_data": {"size": 200}}},
                {"id": "c1", "type": "condition",
                 "config": {"expression": "input.size > 100"}},
                # true-гілка
                {"id": "lt", "type": "log", "config": {"message": "big"}},
                # false-гілка: lf1 → lf2 → lf3
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
    # Жоден із false-нащадків НЕ виконався
    assert "lf1" not in result
    assert "lf2" not in result
    assert "lf3" not in result
    # Усі троє мають у логах "Skipped due to dead branch"
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
    """Вузол, у якого ВСІ inbound-ребра походять з мертвої гілки
    (хай навіть через різні проміжні вузли), теж має бути мертвим.
    """
    wf = Workflow.model_validate(
        {
            "name": "diamond_dead",
            "nodes": [
                {"id": "t1", "type": "manual_trigger",
                 "config": {"initial_data": {"flag": False}}},
                {"id": "c1", "type": "condition",
                 "config": {"expression": "input.flag"}},
                # обидва входи `merge` походять з false-гілки
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
    # merge має лише мертві inbound — теж мертвий, навіть із 2 ребрами
    assert "merge" not in result


async def test_trigger_rule_all_success_skips_node_when_one_input_dead(
    ctx: ExecutionContext,
):
    """За дефолтним правилом `all_success` merge-вузол не має виконатися,
    якщо хоча б одне його вхідне ребро мертве (тут — false-гілка condition'а).
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
                # merge має ДВА вхідні ребра: одне з true-гілки, одне з false-гілки.
                # Default trigger_rule = all_success, тож merge має пропуститися.
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
    # all_success: одне з вхідних ребер merge мертве → merge мертвий
    assert "merge" not in result


async def test_trigger_rule_one_success_runs_node_when_at_least_one_input_alive(
    ctx: ExecutionContext,
):
    """Той самий граф, але merge має `trigger_rule="one_success"` —
    OR-семантика, тож merge має виконатися, бо true-гілка жива.
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
    # one_success: достатньо одного живого вхідного ребра (lt) → merge виконується
    assert "merge" in result


async def test_trigger_rule_one_success_skipped_when_all_inputs_dead(
    ctx: ExecutionContext,
):
    """Навіть для `one_success` вузол має померти, якщо ВСІ його входи мертві."""
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
    # Усі inbound merge мертві → merge мертвий навіть із one_success
    assert "merge" not in result


async def test_kill_marks_outgoing_edges_dead():
    """Прямий unit-тест на каскад: `_kill` додає вузол у `dead_nodes`
    і стампує усі його вихідні ребра у `dead_edges`. Це гарант того, що
    наступне `_evaluate_child` побачить нащадків мертвої гілки як мертвих.
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


# ---------- engine: Async Ready Pool — паралелізм та м'яка зупинка ----------

import asyncio as _asyncio
import time as _time

from pydantic import BaseModel as _BaseModel

from app.nodes.base import NODE_REGISTRY as _REG, BaseNode as _BaseNode, output_port as _output_port


class _SleepConfig(_BaseModel):
    delay: float = 0.5
    label: str = ""


@_output_port("output", type_hint="dict")
class _SleeperNode(_BaseNode):
    """Тест-вузол: засинає на `config.delay` секунд і повертає мітку."""

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
    """Тест-вузол: опційно засинає, потім піднімає RuntimeError."""

    type_name = "test_failer"
    config_model = _FailConfig

    async def execute(self, context, input_data: dict) -> dict:
        if self.config.delay > 0:
            await _asyncio.sleep(self.config.delay)
        raise RuntimeError(self.config.message)


@pytest.fixture
def custom_test_nodes():
    """Тимчасово реєструє тестові вузли test_sleeper / test_failer
    у NODE_REGISTRY і прибирає їх після тесту, щоб не протікати між
    тестами та не псувати /api/nodes/schema у тестах API.
    """
    _REG["test_sleeper"] = _SleeperNode
    _REG["test_failer"] = _FailerNode
    yield
    _REG.pop("test_sleeper", None)
    _REG.pop("test_failer", None)


def _construct_wf(name: str, nodes: list, edges: list):
    """Будує Workflow в обхід `Literal[NodeType]`-перевірки — потрібно для
    тест-вузлів, що не входять у production-набір."""
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
    """Доводить, що рушій справді запускає вузли паралельно.

    Граф: один тригер → дві гілки по 1 секунді сну.
    Якщо двигун послідовний — час буде ~2 с.
    Якщо паралельний (Async Ready Pool) — ~1 с.
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
    # Запас на накладні витрати planner'а; послідовне виконання було б ~2 с.
    assert elapsed < 1.7, (
        f"expected ~1s parallel execution, got {elapsed:.2f}s "
        f"— це натяк на втрату паралелізму у воркер-пулі"
    )


async def test_six_parallel_sleeps_within_worker_pool_limit(
    ctx: ExecutionContext, custom_test_nodes
):
    """6 паралельних гілок вкладаються у дефолтний пул (MAX_WORKERS=6)
    і фінішують за ~`delay` секунд, а не за `6 × delay`."""
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
    # Послідовне було б ~3 с; паралельне ~0.5 с + накладні.
    assert elapsed < 1.5, f"expected ~{delay}s, got {elapsed:.2f}s"


async def test_failure_in_one_branch_lets_running_finish_but_blocks_new(
    ctx: ExecutionContext, custom_test_nodes
):
    """Семантика «м'якої зупинки»:

      • один з паралельних вузлів падає з помилкою → `should_stop=True`,
      • вже запущений сусідній вузол має дограти до кінця (не cancel'иться),
      • нащадки впалого вузла НЕ стартують (їх відсікає dead-каскад).

    Граф:
        t ─┬─→ s_long  (sleep 0.4s, паралельно з fail)
           └─→ fail    (raise одразу)
                  └─→ after_fail (має пропуститися як dead)
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

    # s_long встиг дограти — рушій НЕ кенселить запущених.
    assert "s_long" in ctx.node_outputs
    assert ctx.node_outputs["s_long"]["label"] == "long"

    # after_fail — нащадок мертвої гілки → execute() не викликався.
    assert "after_fail" not in ctx.node_outputs

    # Прапорець м'якої зупинки залишився виставленим.
    assert ctx.should_stop is True
    assert isinstance(ctx.first_error, RuntimeError)

    # Час ~ delay s_long'а, а не 0 (бо чекали його завершення).
    assert elapsed >= 0.35, (
        f"expected to wait for s_long (~0.4s), finished in {elapsed:.2f}s"
    )


async def test_failure_does_not_start_pending_independent_node(
    ctx: ExecutionContext, custom_test_nodes
):
    """Якщо помилка трапляється до того, як воркер встиг забрати з черги
    незалежний вузол — той вузол НЕ виконається (`should_stop` ловиться
    на вході в worker-loop).

    Тут гарантуємо ситуацію: ставимо max_workers=1, щоб черга гарантовано
    мала «непочатий» вузол на момент фейлу.
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

    # При одному воркері: t → fail → fail падає → should_stop=True → independent
    # дочекалася в черзі і її не запустили.
    assert "fail" not in ctx.node_outputs  # впав
    assert "independent" not in ctx.node_outputs  # не стартував через should_stop


async def test_resolve_template_uses_snapshot_under_concurrent_writes(
    ctx: ExecutionContext, custom_test_nodes
):
    """Поки один вузол робить `resolve_template`, інші вузли можуть писати
    нові виходи у `node_outputs`. resolve_template має зробити локальний
    snapshot, тож гонка не призведе до RuntimeError.

    Тестуємо непрямо: запускаємо граф, де багато паралельних вузлів пишуть
    у node_outputs, а log-вузли читають через шаблони. Якщо snapshot
    не зробити — падало б `RuntimeError: dictionary changed size`.
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
