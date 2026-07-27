from pathlib import Path

import pytest

from app.core.context import ExecutionContext
from app.nodes.base import NODE_REGISTRY
from app.nodes.condition import ConditionNode, _rewrite_dot_access
from app.nodes.custom_code import SCRIPTS_DIR, CustomCodeError, CustomCodeNode
from app.nodes.expression import ExpressionEvalError, ExpressionNode
from app.nodes.log_node import LogNode
from app.nodes.manual_trigger import ManualTriggerNode
from app.nodes.read_file import ReadFileNode
from app.nodes.write_file import (
    SANDBOX_DIR,
    PathTraversalError,
    WriteFileNode,
    _resolve_safe_path,
)

#registry

def test_registry_contains_all_node_types():
    expected = {
        "manual_trigger",
        "read_file",
        "write_file",
        "condition",
        "log",
        "custom_code",
        "expression",
    }
    assert expected.issubset(NODE_REGISTRY.keys())

def test_registry_classes_match_concrete_types():
    """Auto-discovery should associate `type_name` with the class itself, not with the abstract class."""
    assert NODE_REGISTRY["manual_trigger"] is ManualTriggerNode
    assert NODE_REGISTRY["expression"] is ExpressionNode
    assert NODE_REGISTRY["custom_code"] is CustomCodeNode

#manual_trigger

async def test_manual_trigger_emits_initial_data(ctx: ExecutionContext):
    node = ManualTriggerNode("t1", {"initial_data": {"k": "v", "n": 42}})
    out = await node.execute(ctx, {})
    assert out == {"k": "v", "n": 42}

async def test_manual_trigger_returns_independent_dict(ctx: ExecutionContext):
    node = ManualTriggerNode("t1", {"initial_data": {"k": "v"}})
    out = await node.execute(ctx, {})
    out["k"] = "mutated"
    assert node.config.initial_data == {"k": "v"}

#read_file

async def test_read_file_reads_existing(tmp_path: Path, ctx: ExecutionContext):
    file = tmp_path / "in.txt"
    file.write_text("hello world", encoding="utf-8")
    node = ReadFileNode("r1", {"path": str(file)})
    out = await node.execute(ctx, {})
    assert out == {"content": "hello world", "size": 11, "path": str(file)}

async def test_read_file_uses_resolve_template(tmp_path: Path, ctx: ExecutionContext):
    file = tmp_path / "templated.txt"
    file.write_text("x", encoding="utf-8")
    node = ReadFileNode("r1", {"path": str(tmp_path) + "/{input.file_name}"})
    out = await node.execute(ctx, {"file_name": "templated.txt"})
    assert out["content"] == "x"

async def test_read_file_missing_raises(ctx: ExecutionContext):
    node = ReadFileNode("r1", {"path": "/__definitely_missing__/x.txt"})
    with pytest.raises(FileNotFoundError):
        await node.execute(ctx, {})

#write_file

async def test_write_file_writes_to_sandbox(ctx: ExecutionContext):
    node = WriteFileNode("w1", {"path": "test_node_out.txt"})
    out = await node.execute(ctx, {"content": "payload"})
    written = Path(out["path"])
    try:
        assert written.read_text(encoding="utf-8") == "payload"
        assert out["bytes_written"] == 7
        assert out["append"] is False
    finally:
        written.unlink(missing_ok=True)

async def test_write_file_append_mode(ctx: ExecutionContext):
    file_name = "test_node_append.txt"
    await WriteFileNode("w1", {"path": file_name}).execute(ctx, {"content": "first"})
    out = await WriteFileNode("w2", {"path": file_name, "append": True}).execute(
        ctx, {"content": "second"}
    )
    written = Path(out["path"])
    try:
        assert written.read_text(encoding="utf-8") == "firstsecond"
    finally:
        written.unlink(missing_ok=True)

async def test_write_file_uses_inline_content(ctx: ExecutionContext):
    node = WriteFileNode(
        "w1",
        {"path": "test_node_inline.txt", "content": "literal text"},
    )
    out = await node.execute(ctx, {"content": "from-input"})
    written = Path(out["path"])
    try:
        assert written.read_text(encoding="utf-8") == "literal text"
    finally:
        written.unlink(missing_ok=True)

async def test_write_file_inline_content_resolves_templates(ctx: ExecutionContext):
    node = WriteFileNode(
        "w1",
        {"path": "test_node_tpl.txt", "content": "hello, {input.user}!"},
    )
    out = await node.execute(ctx, {"user": "Alice"})
    written = Path(out["path"])
    try:
        assert written.read_text(encoding="utf-8") == "hello, Alice!"
    finally:
        written.unlink(missing_ok=True)

async def test_write_file_blocks_path_traversal(ctx: ExecutionContext):
    node = WriteFileNode("w1", {"path": "../../etc/passwd"})
    with pytest.raises(PathTraversalError, match="outside sandbox"):
        await node.execute(ctx, {"content": "evil"})

def test_resolve_safe_path_inside_sandbox():
    p = _resolve_safe_path("inside.txt")
    assert p.is_relative_to(SANDBOX_DIR)

def test_resolve_safe_path_blocks_absolute_outside():
    with pytest.raises(PathTraversalError):
        _resolve_safe_path(str(Path(__file__).parent / "x.txt"))

#condition

@pytest.mark.parametrize(
    "expr, expected",
    [
        ("input.size > 100", "input['size'] > 100"),
        ("nodes.r1.path", "nodes['r1']['path']"),
        ("input.a == nodes.b.c and 1 < 2", "input['a'] == nodes['b']['c'] and 1 < 2"),
        ("42 + 1", "42 + 1"),
    ],
)
def test_rewrite_dot_access(expr, expected):
    assert _rewrite_dot_access(expr) == expected

async def test_condition_true(ctx: ExecutionContext):
    node = ConditionNode("c1", {"expression": "input.size > 100"})
    out = await node.execute(ctx, {"size": 200})
    assert out == {"result": True, "input": {"size": 200}}

async def test_condition_false(ctx: ExecutionContext):
    node = ConditionNode("c1", {"expression": "input.size > 100"})
    out = await node.execute(ctx, {"size": 50})
    assert out["result"] is False

async def test_condition_uses_nodes_namespace(ctx: ExecutionContext):
    ctx.node_outputs = {"r1": {"size": 7}}
    node = ConditionNode("c1", {"expression": "nodes.r1.size == 7"})
    out = await node.execute(ctx, {})
    assert out["result"] is True

#log

async def test_log_renders_template_and_publishes(ctx: ExecutionContext, fake_broker):
    node = LogNode("l1", {"message": "Hi {input.name}", "level": "warning"})
    out = await node.execute(ctx, {"name": "Olena"})
    assert out == {"name": "Olena"}  # passthrough
    assert len(fake_broker.entries) == 1
    _, entry = fake_broker.entries[0]
    assert entry.message == "Hi Olena"
    assert entry.level == "warning"
    assert entry.node_id == "l1"

#custom_code

@pytest.fixture
def script_factory():
    """Creates temporary .py scripts in `scripts/` and deletes them after the test."""
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []

    def _make(name: str, body: str) -> Path:
        path = SCRIPTS_DIR / f"{name}.py"
        path.write_text(body, encoding="utf-8")
        created.append(path)
        return path

    yield _make

    for p in created:
        p.unlink(missing_ok=True)

async def test_custom_code_calls_async_entry_point(script_factory, ctx: ExecutionContext):
    script_factory(
        "tn_double",
        "async def main(input, nodes, **params):\n"
        "    return {'doubled': input['x'] * 2}\n",
    )
    node = CustomCodeNode("c1", {"script_name": "tn_double"})
    out = await node.execute(ctx, {"x": 21})
    assert out == {"doubled": 42}

async def test_custom_code_passes_params_and_nodes(script_factory, ctx: ExecutionContext):
    script_factory(
        "tn_params",
        "async def run(input, nodes, factor, label):\n"
        "    return {'value': nodes['src']['v'] * factor, 'label': label}\n",
    )
    ctx.node_outputs = {"src": {"v": 5}}
    node = CustomCodeNode(
        "c1",
        {
            "script_name": "tn_params",
            "entry_point": "run",
            "params": {"factor": 3, "label": "x"},
        },
    )
    out = await node.execute(ctx, {})
    assert out == {"value": 15, "label": "x"}

async def test_custom_code_returns_empty_dict_when_none(
    script_factory, ctx: ExecutionContext
):
    script_factory(
        "tn_none",
        "async def main(input, nodes, **params):\n    return None\n",
    )
    node = CustomCodeNode("c1", {"script_name": "tn_none"})
    out = await node.execute(ctx, {})
    assert out == {}

async def test_custom_code_returns_empty_dict_when_no_return(
    script_factory, ctx: ExecutionContext
):
    script_factory(
        "tn_void",
        "async def main(input, nodes, **params):\n    pass\n",
    )
    node = CustomCodeNode("c1", {"script_name": "tn_void"})
    out = await node.execute(ctx, {})
    assert out == {}

async def test_custom_code_missing_script_raises(ctx: ExecutionContext):
    node = CustomCodeNode("c1", {"script_name": "tn_does_not_exist_xyz"})
    with pytest.raises(CustomCodeError, match="not found"):
        await node.execute(ctx, {})

async def test_custom_code_missing_entry_point_raises(
    script_factory, ctx: ExecutionContext
):
    script_factory(
        "tn_no_entry",
        "async def other(input, nodes, **params):\n    return {}\n",
    )
    node = CustomCodeNode("c1", {"script_name": "tn_no_entry"})
    with pytest.raises(CustomCodeError, match="entry_point"):
        await node.execute(ctx, {})

async def test_custom_code_non_dict_return_raises(
    script_factory, ctx: ExecutionContext
):
    script_factory(
        "tn_wrong_type",
        "async def main(input, nodes, **params):\n    return [1, 2, 3]\n",
    )
    node = CustomCodeNode("c1", {"script_name": "tn_wrong_type"})
    with pytest.raises(CustomCodeError, match="expected dict"):
        await node.execute(ctx, {})

async def test_custom_code_blocks_path_traversal(ctx: ExecutionContext):
    node = CustomCodeNode("c1", {"script_name": "../evil"})
    with pytest.raises(CustomCodeError, match="invalid script_name"):
        await node.execute(ctx, {})

#expression

async def test_expression_arithmetic(ctx: ExecutionContext):
    node = ExpressionNode("e1", {"expression": "input.a + input.b"})
    out = await node.execute(ctx, {"a": 10, "b": 32})
    assert out == {"result": 42}

async def test_expression_uses_nodes_namespace(ctx: ExecutionContext):
    ctx.node_outputs = {"r1": {"size": 7}}
    node = ExpressionNode("e1", {"expression": "nodes.r1.size * 6"})
    out = await node.execute(ctx, {})
    assert out == {"result": 42}

async def test_expression_returns_string_value(ctx: ExecutionContext):
    node = ExpressionNode("e1", {"expression": "'Hi, ' + input.name"})
    out = await node.execute(ctx, {"name": "Olena"})
    assert out == {"result": "Hi, Olena"}

async def test_expression_returns_list(ctx: ExecutionContext):
    node = ExpressionNode("e1", {"expression": "[1, 2, 3]"})
    out = await node.execute(ctx, {})
    assert out == {"result": [1, 2, 3]}

async def test_expression_invalid_syntax_raises(ctx: ExecutionContext):
    node = ExpressionNode("e1", {"expression": "1 + +"})
    with pytest.raises(ExpressionEvalError, match="Failed to evaluate"):
        await node.execute(ctx, {})