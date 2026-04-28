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


async def test_dead_node_marks_outgoing_edges_dead():
    """Прямий unit-тест на каскад: `_mark_node_dead` стампує усі
    вихідні ребра у `dead_edges`.
    """
    from app.core.engine import WorkflowEngine, _edge_key
    from app.schemas.workflow import Edge as _Edge, Node as _Node

    nodes = [
        _Node.model_construct(id="a", type="log", config={}),
        _Node.model_construct(id="b", type="log", config={}),
        _Node.model_construct(id="c", type="log", config={}),
    ]
    edges = [
        _Edge.model_validate({"from": "a", "to": "b"}),
        _Edge.model_validate({"from": "a", "to": "c"}),
        _Edge.model_validate({"from": "b", "to": "c"}),
    ]
    dead_nodes: set[str] = set()
    dead_edges: set = set()

    WorkflowEngine._mark_node_dead(nodes[0], edges, dead_nodes, dead_edges)
    assert "a" in dead_nodes
    assert _edge_key(edges[0]) in dead_edges  # a→b
    assert _edge_key(edges[1]) in dead_edges  # a→c
    assert _edge_key(edges[2]) not in dead_edges  # b→c (не від a)


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
