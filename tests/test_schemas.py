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
