from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas.job import Job, JobStatus, LogEntry
from app.schemas.node_configs import (
    ConditionConfig,
    LogNodeConfig,
    ManualTriggerConfig,
    ReadFileConfig,
    WriteFileConfig,
    validate_node_config,
)
from app.schemas.workflow import Edge, Node, Workflow


# ---------- Edge / Node / Workflow ----------

def test_edge_alias_from_to_maps_to_python_names():
    edge = Edge.model_validate({"from": "a", "to": "b"})
    assert edge.from_node == "a"
    assert edge.to_node == "b"
    assert edge.source_handle is None


def test_edge_handles_accept_arbitrary_port_names():
    """Після переходу на гібридний port-mapping `source_handle`/`target_handle`
    можуть бути будь-яким рядком (назва порту), не лише true/false.
    """
    e1 = Edge.model_validate({"from": "a", "to": "b", "source_handle": "true"})
    assert e1.source_handle == "true"
    e2 = Edge.model_validate(
        {"from": "a", "to": "b", "source_handle": "content", "target_handle": "path"}
    )
    assert e2.source_handle == "content"
    assert e2.target_handle == "path"


def test_workflow_minimal_valid():
    wf = Workflow.model_validate(
        {
            "name": "minimal",
            "nodes": [
                {"id": "t1", "type": "manual_trigger", "config": {}},
                {"id": "l1", "type": "log", "config": {"message": "hi"}},
            ],
            "edges": [{"from": "t1", "to": "l1"}],
        }
    )
    assert wf.name == "minimal"
    assert len(wf.nodes) == 2
    assert len(wf.edges) == 1


def test_workflow_rejects_duplicate_node_ids():
    with pytest.raises(ValidationError, match="Duplicate"):
        Workflow.model_validate(
            {
                "name": "dup",
                "nodes": [
                    {"id": "x", "type": "log", "config": {"message": "a"}},
                    {"id": "x", "type": "log", "config": {"message": "b"}},
                ],
                "edges": [],
            }
        )


def test_workflow_rejects_dangling_edge():
    with pytest.raises(ValidationError, match="unknown"):
        Workflow.model_validate(
            {
                "name": "dangling",
                "nodes": [{"id": "a", "type": "log", "config": {"message": "x"}}],
                "edges": [{"from": "a", "to": "ghost"}],
            }
        )


def test_workflow_rejects_unknown_node_type():
    with pytest.raises(ValidationError):
        Workflow.model_validate(
            {
                "name": "badtype",
                "nodes": [{"id": "x", "type": "telegram", "config": {}}],
                "edges": [],
            }
        )


def test_workflow_rejects_empty_name():
    with pytest.raises(ValidationError):
        Workflow.model_validate({"name": "", "nodes": [], "edges": []})


def test_workflow_is_readonly_defaults_to_false():
    wf = Workflow.model_validate(
        {
            "name": "x",
            "nodes": [{"id": "t1", "type": "manual_trigger", "config": {}}],
            "edges": [],
        }
    )
    assert wf.is_readonly is False


def test_workflow_accepts_is_readonly_true():
    wf = Workflow.model_validate(
        {
            "name": "x",
            "is_readonly": True,
            "nodes": [{"id": "t1", "type": "manual_trigger", "config": {}}],
            "edges": [],
        }
    )
    assert wf.is_readonly is True


def test_edge_is_readonly_defaults_false_and_accepts_true():
    e1 = Edge.model_validate({"from": "a", "to": "b"})
    assert e1.is_readonly is False
    e2 = Edge.model_validate({"from": "a", "to": "b", "is_readonly": True})
    assert e2.is_readonly is True


def test_node_trigger_rule_default_is_all_success():
    n = Node.model_validate({"id": "x", "type": "log", "config": {"message": "hi"}})
    assert n.trigger_rule == "all_success"


def test_node_trigger_rule_accepts_one_success():
    n = Node.model_validate(
        {"id": "x", "type": "log", "config": {"message": "hi"},
         "trigger_rule": "one_success"}
    )
    assert n.trigger_rule == "one_success"


def test_node_trigger_rule_rejects_unknown_value():
    with pytest.raises(ValidationError):
        Node.model_validate(
            {"id": "x", "type": "log", "config": {"message": "hi"},
             "trigger_rule": "always"}
        )


# ---------- inputs shorthand → edges ----------


def test_inputs_shorthand_string_defaults_source_handle_to_output():
    """Bare-string значення → source_handle="output" (DEFAULT_SOURCE_HANDLE).
    Це стандарт для більшості наших вузлів (custom_code, log, …).
    """
    wf = Workflow.model_validate(
        {
            "name": "i_str",
            "nodes": [
                {"id": "t1", "type": "manual_trigger", "config": {}},
                {
                    "id": "l1", "type": "log", "config": {"message": "x"},
                    "inputs": {"input": "t1"},
                },
            ],
            "edges": [],
        }
    )
    assert len(wf.edges) == 1
    e = wf.edges[0]
    assert (e.from_node, e.to_node) == ("t1", "l1")
    assert e.source_handle == "output"
    assert e.target_handle == "input"


def test_inputs_shorthand_tuple_creates_port_to_port_edge():
    wf = Workflow.model_validate(
        {
            "name": "i_tup",
            "nodes": [
                {"id": "t1", "type": "manual_trigger", "config": {}},
                {
                    "id": "l1", "type": "log", "config": {"message": "x"},
                    "inputs": {"input": ("t1", "data")},
                },
            ],
            "edges": [],
        }
    )
    assert len(wf.edges) == 1
    e = wf.edges[0]
    assert e.source_handle == "data"
    assert e.target_handle == "input"


def test_inputs_control_flow_keys_create_branch_edges():
    wf = Workflow.model_validate(
        {
            "name": "i_ctrl",
            "nodes": [
                {"id": "t1", "type": "manual_trigger", "config": {}},
                {"id": "c1", "type": "condition",
                 "config": {"expression": "True"}},
                {"id": "lt", "type": "log", "config": {"message": "yes"},
                 "inputs": {"@on_true": "c1"}},
                {"id": "lf", "type": "log", "config": {"message": "no"},
                 "inputs": {"@on_false": "c1"}},
            ],
            "edges": [{"from": "t1", "to": "c1"}],
        }
    )
    branch_edges = [e for e in wf.edges if e.from_node == "c1"]
    handles = sorted(e.source_handle for e in branch_edges)
    assert handles == ["false", "true"]
    assert all(e.target_handle is None for e in branch_edges)


def test_inputs_does_not_duplicate_already_explicit_edges():
    wf = Workflow.model_validate(
        {
            "name": "i_dedup",
            "nodes": [
                {"id": "t1", "type": "manual_trigger", "config": {}},
                {
                    "id": "l1", "type": "log", "config": {"message": "x"},
                    "inputs": {"input": ("t1", "data")},
                },
            ],
            # Те саме ребро вказано вручну — Workflow-валідатор НЕ дублює.
            "edges": [
                {"from": "t1", "to": "l1",
                 "source_handle": "data", "target_handle": "input"}
            ],
        }
    )
    assert len(wf.edges) == 1


def test_inputs_field_is_excluded_from_json_dump():
    """Поле `inputs` — code-only shortcut: воно не повинне потрапляти у
    канонічний JSON-формат. Фронтенд читає лише `edges`.
    """
    wf = Workflow.model_validate(
        {
            "name": "i_dump",
            "nodes": [
                {"id": "t1", "type": "manual_trigger", "config": {}},
                {
                    "id": "l1", "type": "log", "config": {"message": "x"},
                    "inputs": {"input": "t1"},
                },
            ],
            "edges": [],
        }
    )
    dumped = wf.model_dump_json(by_alias=True)
    assert '"inputs"' not in dumped
    # А ось згенероване ребро має бути присутнє.
    assert '"from":"t1"' in dumped or '"from": "t1"' in dumped


def test_inputs_unknown_source_node_fails_integrity_check():
    with pytest.raises(ValidationError, match="unknown"):
        Workflow.model_validate(
            {
                "name": "i_bad",
                "nodes": [
                    {"id": "l1", "type": "log", "config": {"message": "x"},
                     "inputs": {"input": "ghost_id"}},
                ],
                "edges": [],
            }
        )


def test_inputs_invalid_value_format_raises():
    with pytest.raises(ValidationError):
        Workflow.model_validate(
            {
                "name": "i_invalid",
                "nodes": [
                    {"id": "t1", "type": "manual_trigger", "config": {}},
                    {"id": "l1", "type": "log", "config": {"message": "x"},
                     # 3-element tuple — недопустимий формат
                     "inputs": {"input": ("t1", "a", "b")}},
                ],
                "edges": [],
            }
        )


def test_inputs_list_value_creates_edge_per_source():
    """fan-in: список джерел в один target_handle → окремий Edge на кожне."""
    wf = Workflow.model_validate(
        {
            "name": "i_list",
            "nodes": [
                {"id": "n1", "type": "manual_trigger", "config": {}},
                {"id": "n2", "type": "manual_trigger", "config": {}},
                {
                    "id": "merge", "type": "log", "config": {"message": "x"},
                    "inputs": {"input": ["n1", ("n2", "out")]},
                },
            ],
            "edges": [],
        }
    )
    edges_into_merge = [e for e in wf.edges if e.to_node == "merge"]
    assert len(edges_into_merge) == 2
    # n1 (str shorthand) → source_handle = "output" (DEFAULT_SOURCE_HANDLE)
    # n2 (tuple)         → source_handle = "out"
    by_src = {(e.from_node, e.source_handle): e.target_handle for e in edges_into_merge}
    assert by_src == {
        ("n1", "output"): "input",
        ("n2", "out"): "input",
    }


def test_inputs_list_with_three_sources_creates_three_edges():
    wf = Workflow.model_validate(
        {
            "name": "i_list3",
            "nodes": [
                {"id": "a", "type": "manual_trigger", "config": {}},
                {"id": "b", "type": "manual_trigger", "config": {}},
                {"id": "c", "type": "manual_trigger", "config": {}},
                {
                    "id": "fan", "type": "log", "config": {"message": "x"},
                    "inputs": {
                        "input": [("a", "data"), ("b", "data"), ("c", "data")]
                    },
                },
            ],
            "edges": [],
        }
    )
    assert len([e for e in wf.edges if e.to_node == "fan"]) == 3


def test_inputs_list_dedups_against_existing_edges():
    """Якщо одне з джерел у списку вже є як explicit-edge — дублювання
    НЕ відбувається, але інші джерела зі списку додаються нормально.
    """
    wf = Workflow.model_validate(
        {
            "name": "i_list_dedup",
            "nodes": [
                {"id": "a", "type": "manual_trigger", "config": {}},
                {"id": "b", "type": "manual_trigger", "config": {}},
                {
                    "id": "merge", "type": "log", "config": {"message": "x"},
                    "inputs": {"input": [("a", "data"), ("b", "data")]},
                },
            ],
            "edges": [
                {"from": "a", "to": "merge",
                 "source_handle": "data", "target_handle": "input"}
            ],
        }
    )
    incoming = [e for e in wf.edges if e.to_node == "merge"]
    assert len(incoming) == 2  # one pre-existing, one added from list
    # порядок: спершу explicit, потім додані з inputs (b)
    assert incoming[0].from_node == "a"
    assert incoming[1].from_node == "b"


def test_workflow_edges_default_to_empty_list_when_using_inputs_only():
    """Якщо програміст оголошує всі звʼязки через `inputs`, явний
    `edges=[]` можна не передавати — він тепер опціональний.
    """
    wf = Workflow.model_validate(
        {
            "name": "no_edges_field",
            "nodes": [
                {"id": "t1", "type": "manual_trigger", "config": {}},
                {"id": "l1", "type": "log", "config": {"message": "x"},
                 "inputs": {"input": "t1"}},
            ],
            # `edges` ключа взагалі немає
        }
    )
    assert len(wf.edges) == 1


# ---------- node_configs ----------

@pytest.mark.parametrize(
    "type_name, config, expected_cls",
    [
        ("manual_trigger", {"initial_data": {"a": 1}}, ManualTriggerConfig),
        ("read_file", {"path": "data/input.txt"}, ReadFileConfig),
        ("write_file", {"path": "out.txt"}, WriteFileConfig),
        ("condition", {"expression": "input.x > 0"}, ConditionConfig),
        ("log", {"message": "hi"}, LogNodeConfig),
    ],
)
def test_validate_node_config_for_each_type(type_name, config, expected_cls):
    node = Node(id="n", type=type_name, config=config)
    cfg = validate_node_config(node)
    assert isinstance(cfg, expected_cls)


def test_validate_node_config_unknown_type_raises():
    # Цей шлях обходить Pydantic-Literal: створюємо Node динамічно через construct.
    bad_node = Node.model_construct(id="x", type="unknown", config={})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Unknown node type"):
        validate_node_config(bad_node)


def test_read_file_path_optional_for_port_mapping():
    """Шлях у ReadFileConfig може бути порожнім — реальне значення прийде
    через port-mapping (`target_handle="path"`). Дефолт = "".
    """
    cfg = ReadFileConfig.model_validate({})
    assert cfg.path == ""
    assert cfg.encoding == "utf-8"


def test_condition_requires_expression():
    with pytest.raises(ValidationError):
        ConditionConfig.model_validate({})


def test_log_node_default_level_is_info():
    cfg = LogNodeConfig.model_validate({"message": "x"})
    assert cfg.level == "info"


# ---------- Job / JobStatus / LogEntry ----------

def test_job_default_logs_empty():
    job = Job(
        id="j1",
        workflow_name="w",
        status=JobStatus.PENDING,
        started_at=datetime.utcnow(),
    )
    assert job.logs == []
    assert job.result is None
    assert job.error is None
    assert job.finished_at is None


def test_job_status_enum_values():
    assert JobStatus.PENDING.value == "pending"
    assert JobStatus.RUNNING.value == "running"
    assert JobStatus.SUCCESS.value == "success"
    assert JobStatus.FAILED.value == "failed"


def test_log_entry_done_level_accepted():
    entry = LogEntry(
        timestamp=datetime.utcnow(),
        node_id=None,
        level="done",
        message="finished",
    )
    assert entry.level == "done"


def test_log_entry_rejects_invalid_level():
    with pytest.raises(ValidationError):
        LogEntry.model_validate(
            {"timestamp": datetime.utcnow().isoformat(), "level": "panic", "message": "x"}
        )
