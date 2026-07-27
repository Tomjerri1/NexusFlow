"""Async Ready Pool: a parallel DAG executor with a limited number of workers.

Architectural outline:
• Instead of sequentially traversing a topologically sorted list, a pool of
`MAX_WORKERS` worker tasks that take ready nodes from
`asyncio.Queue` in a race.
• Node readiness (`in_degree == 0` for `all_success`, or `at least
one live parent has arrived` for `one_success`) is calculated at the moment
the parent node finishes. State transfer and push to queue are atomic
under a shared `state.lock`, so even if two parents finish
at the same time, the child will be queued exactly once.
• `should_stop` - soft stop: on the first error, it is set to
`True`, new nodes are not started, but already running ones finish. This
gives clean completions instead of cancels in the middle of I/O.
• Data isolation: `current_input` is gone. The engine generates `input_data`
locally before each call and passes it to `execute()` as
a parameter - a race to shared-state on the input is impossible in principle.

The contract of "dead" branches is inherited from the previous version: dead_edges
holds the keys of edges that do not carry data (false-branch of the condition that issued
true; outbound-edges from a node that has fallen), and dead_nodes - ids of nodes that are
skipped completely. "Death" is propagated via `_propagate_finish`:
as soon as a parent completes (success/fail/dead), all its descendants
are reevaluated; those that can no longer be helped by any living parent (according to the
activation rule) are also marked as dead, which restarts
propagation.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from pydantic import ConfigDict, TypeAdapter, ValidationError

from app.core.context import ExecutionContext
from app.core.scheduler import topological_sort
from app.nodes.base import NODE_REGISTRY
from app.schemas.workflow import Edge, Node, Workflow

logger = logging.getLogger(__name__)

class UnknownNodeTypeError(ValueError):
    """There is no type declared in `NODE_REGISTRY` in the workflow."""


# The “dead” rib key is a deterministic identifier that takes the source_handle into account.
DeadEdgeKey = tuple[str, str, str | None]


def _edge_key(edge: Edge) -> DeadEdgeKey:
    return (edge.from_node, edge.to_node, edge.source_handle)


def _is_branching_handle(handle: str | None) -> bool:
    return handle in ("true", "false")

TYPE_MAPPING: dict[str, Any] = {
    "int": int,
    "integer": int,
    "float": float,
    "number": float,
    "str": str,
    "string": str,
    "bool": bool,
    "boolean": bool,
    "dict": dict,
    "object": dict,
    "list": list,
    "array": list,
    "any": Any,
    "": Any,
}

# Lax-config: enables `int/float → str` conversions (“42” → “42”),
# which are expected by NexusFlow nodes and were previously handled manually with `str(value)`.
# Other Lax conversions (“42” → 42, “true” → True, tuple → list, etc.)
_LAX_CONFIG = ConfigDict(coerce_numbers_to_str=True)


def _try_convert(value: Any, expected: str) -> Any:
    """Attempt to convert `value` to the type corresponding to the string `expected`.

    Logic:
      • take the actual Python type from `TYPE_MAPPING`,
      • for `Any` (or an unknown type) – return the value unchanged,
      • otherwise create `TypeAdapter(target, config=_LAX_CONFIG)` and call
        `validate_python(value)`.

    If Pydantic rejects the value, it raises a `TypeError` so that the
    `except (ValueError, TypeError)` block in `_route_inputs` behaves identically
    to the old behavior: log a warning and pass the original value.
    """
    target = TYPE_MAPPING.get(expected.lower())
    if target is None or target is Any:
        return value
    try:
        return TypeAdapter(target, config=_LAX_CONFIG).validate_python(value)
    except ValidationError as exc:
        msg = exc.errors()[0]["msg"] if exc.errors() else str(exc)
        raise TypeError(
            f"cannot convert {type(value).__name__} to {expected!r}: {msg}"
        ) from exc


def _expected_port_type(node_type: str, port_name: str) -> str | None:
    cls = NODE_REGISTRY.get(node_type)
    if cls is None:
        return None
    inputs = cls.__dict__.get("__inputs__") or getattr(cls, "__inputs__", []) or []
    for spec in inputs:
        if spec.name == port_name:
            return spec.type_hint
    return None


def _collect_effective_edges(workflow: Workflow) -> list[Edge]:
    """Combines explicit edges with declarative static_connections of nodes."""
    workflow_readonly = bool(getattr(workflow, "is_readonly", False))

    edges: list[Edge] = []
    for edge in workflow.edges:
        if workflow_readonly and not edge.is_readonly:
            edges.append(edge.model_copy(update={"is_readonly": True}))
        else:
            edges.append(edge)

    node_ids = {n.id for n in workflow.nodes}

    for node_def in workflow.nodes:
        node_cls = NODE_REGISTRY.get(node_def.type)
        if node_cls is None:
            continue
        statics = getattr(node_cls, "__static_connections__", []) or []
        for sc in statics:
            if sc.target_node not in node_ids:
                continue
            edges.append(
                Edge(
                    from_node=node_def.id,
                    to_node=sc.target_node,
                    source_handle=sc.source_port,
                    target_handle=sc.target_port,
                    is_readonly=True,
                )
            )
    return edges

# Internal startup status

@dataclass
class _RunState:
    """Encapsulates the entire state of a single workflow run.

    All mutations of dictionary/set fields (`dead_edges`, `dead_nodes`,
    `scheduled`, `finished`, `pending_count`) occur only under
    `lock`. This guarantees the atomicity of the triad “decrement the counter →
    re-evaluate readiness → add to the queue,” which is a requirement of the task.
    """

    nodes_by_id: dict[str, Node]
    edges: list[Edge]
    inbound: dict[str, list[Edge]]
    outbound: dict[str, list[Edge]]

    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    done_event: asyncio.Event = field(default_factory=asyncio.Event)

    scheduled: set[str] = field(default_factory=set)
    finished: set[str] = field(default_factory=set)
    dead_nodes: set[str] = field(default_factory=set)
    dead_edges: set[DeadEdgeKey] = field(default_factory=set)
    pending_count: int = 0
    # The number of workers currently inside `_process_node` (between the increment
    # and the `finally` decrement). This is needed for a soft stop: when
    # `should_stop=True`, we do not accept new nodes, but those already running will finish.
    # As soon as `running_count` drops to 0 under `should_stop`, the engine can
    # terminate, even if there are still “unstarted” nodes left in the queue.
    running_count: int = 0

    @classmethod
    def build(cls, workflow: Workflow, edges: list[Edge]) -> "_RunState":
        inbound: dict[str, list[Edge]] = defaultdict(list)
        outbound: dict[str, list[Edge]] = defaultdict(list)
        for e in edges:
            inbound[e.to_node].append(e)
            outbound[e.from_node].append(e)
        return cls(
            nodes_by_id={n.id: n for n in workflow.nodes},
            edges=edges,
            inbound=inbound,
            outbound=outbound,
            pending_count=len(workflow.nodes),
        )

# WorkflowEngine

class WorkflowEngine:
    """Async Ready Pool executor.

    Parameters:
      • `max_workers` - a fixed number of concurrent workers. Default
        6: a compromise between parallelism for I/O-heavy graphs and protection
        against OOM on massive graphs. Pass a different value to
        the constructor to tune it for your workload.

    Contracts:
      • Supported `trigger_rule`: `all_success` (AND), `one_success` (OR).
      • Guarantees that a descendant will enter the `ready_queue` exactly once —
        protected by `state.lock`.
      • On the first critical error, sets `context.should_stop=True`
        and re-raises the error after active workers have finished.
    """

    DEFAULT_MAX_WORKERS = 6

    def __init__(self, max_workers: int | None = None):
        self.max_workers = max_workers or self.DEFAULT_MAX_WORKERS

    # Public entrance

    async def run(
        self,
        workflow: Workflow,
        job_id: str,
        context: ExecutionContext,
    ) -> dict:
        # Pre-flight: All types must be registered.
        for n in workflow.nodes:
            if n.type not in NODE_REGISTRY:
                raise UnknownNodeTypeError(f"Unknown node type: {n.type!r}")

        # CRITICAL: filter out purely visual nodes (is_visual_only=True,
        # e.g. Note) BEFORE topological sorting and building _RunState.
        # They should not leave any trace - neither in the logs, nor in the queue,
        # nor in pending_count. At the same time, we discard all edges touching
        # such nodes (incoming and outgoing).
        visual_ids = {
            n.id for n in workflow.nodes
            if getattr(NODE_REGISTRY[n.type], "is_visual_only", False)
        }
        if visual_ids:
            executable_nodes = [n for n in workflow.nodes if n.id not in visual_ids]
            executable_workflow = workflow.model_copy(update={"nodes": executable_nodes})
        else:
            executable_workflow = workflow

        edges = [
            e for e in _collect_effective_edges(executable_workflow)
            if e.from_node not in visual_ids and e.to_node not in visual_ids
        ]

        topological_sort(executable_workflow.nodes, edges)

        await context.log(None, f"Starting workflow {workflow.name!r}")

        if not executable_workflow.nodes:
            await context.log(None, "Workflow completed successfully")
            return context.node_outputs

        state = _RunState.build(executable_workflow, edges)

        # Initial queue filling: all nodes without incoming edges.
        async with state.lock:
            for n in executable_workflow.nodes:
                if not state.inbound[n.id]:
                    state.scheduled.add(n.id)
                    state.queue.put_nowait(n.id)
            if state.pending_count == 0:
                state.done_event.set()

        worker_count = max(1, min(self.max_workers, len(executable_workflow.nodes)))
        workers = [
            asyncio.create_task(self._worker(state, context, worker_id=i))
            for i in range(worker_count)
        ]

        try:
            await state.done_event.wait()
        finally:
            for _ in workers:
                state.queue.put_nowait(None)
            await asyncio.gather(*workers, return_exceptions=True)

        # If there was a critical error, we will throw it out (job → FAILED).
        if context.first_error is not None:
            raise context.first_error

        await context.log(None, "Workflow completed successfully")
        return context.node_outputs

    async def _worker(
        self,
        state: _RunState,
        context: ExecutionContext,
        worker_id: int,
    ) -> None:
        while True:
            # Before each new node - check the soft stop flag.
            # We do this BEFORE `queue.get()` so that busy workers don't pull
            # new nodes while others are still running after an error.
            if context.should_stop:
                return

            item = await state.queue.get()
            if item is None:
                return
            if context.should_stop:
                continue

            async with state.lock:
                state.running_count += 1
            try:
                await self._process_node(state, context, item)
            finally:
                async with state.lock:
                    state.running_count -= 1
                    if (
                        context.should_stop
                        and state.running_count == 0
                        and not state.done_event.is_set()
                    ):
                        state.done_event.set()

    # Assembly of a single unit

    async def _process_node(
        self,
        state: _RunState,
        context: ExecutionContext,
        node_id: str,
    ) -> None:
        node_def = state.nodes_by_id[node_id]
        node_cls = NODE_REGISTRY[node_def.type]
        node = node_cls(node_def.id, node_def.config)

        success = False
        output: dict = {}
        try:
            # 1) Collect local `input_data` and ports at the time of startup.
            #    This is a snapshot: parent processes that haven't finished yet (for `one_success`)
            #    simply won't be included in the input—and that's the correct behavior.
            input_data, mapped = await self._route_inputs(state, context, node_def)

            async with state.lock:
                # Write the ports to a shared context—atomically with the rest of the state—
                # so that other concurrent readers do not see a half-write.
                for port_name, value in mapped.items():
                    context.set_input(node_def.id, port_name, value)

            # 2) Universal port-mapping bridge → `input` template.
            #    We duplicate the port values in `input_data` so that templates
            #    `{input.<port>}` work without overwriting nodes.
            for port_name, value in mapped.items():
                if isinstance(value, dict):
                    for k, v in value.items():
                        input_data.setdefault(k, v)
                input_data[port_name] = value

            await context.log(node.id, f"Executing ({node.type_name})")
            output = await node.execute(context, input_data)
            if not isinstance(output, dict):
                raise TypeError(
                    f"node {node.id!r} returned {type(output).__name__}, expected dict"
                )
            success = True
        except Exception as exc:  # noqa: BLE001 - we intentionally capture everything
            await context.log(node.id, f"Error: {exc}", level="error")
            # Soft stop: We record the first error and set a flag.
            context.request_stop(exc)
        finally:
            # Atomic state update + propagation of the “finish” to descendants.
            await self._finalize_node(state, context, node_def, success, output)

    
    # Data Routing
    

    async def _route_inputs(
        self,
        state: _RunState,
        context: ExecutionContext,
        node: Node,
    ) -> tuple[dict, dict]:
        """Collects `(legacy_merged_input, mapped_ports)` for a specific run.

        Snapshot under `state.lock`:
          • dead_edges/dead_nodes - to avoid seeing a partially updated state,
          • node_outputs - a consistent snapshot of the outputs of all parents that
            have completed by this point.

        Type checking / auto-conversion of port mappings remain unchanged.
        """
        async with state.lock:
            dead_edges_snap = set(state.dead_edges)
            dead_nodes_snap = set(state.dead_nodes)
            outputs_snap = {
                k: dict(v) if isinstance(v, dict) else v
                for k, v in context.node_outputs.items()
            }

        merged: dict = {}
        mapped: dict = {}

        for edge in state.inbound[node.id]:
            if _edge_key(edge) in dead_edges_snap:
                continue
            if edge.from_node in dead_nodes_snap:
                continue
            source_output = outputs_snap.get(edge.from_node)
            if source_output is None:
                continue
            if isinstance(source_output, dict):
                merged.update(source_output)

            if edge.target_handle is None:
                continue

            if edge.source_handle is None or _is_branching_handle(edge.source_handle):
                value = source_output
            else:
                value = (
                    source_output.get(edge.source_handle)
                    if isinstance(source_output, dict)
                    else None
                )

            expected = _expected_port_type(node.type, edge.target_handle)
            if expected and value is not None:
                # `_try_convert` is now a no-op for type matching, because
                # `TypeAdapter.validate_python` returns
                # a valid value without any modifications. Therefore, a separate `_matches` check is unnecessary.
                try:
                    value = _try_convert(value, expected)
                except (ValueError, TypeError) as exc:
                    await context.log(
                        node.id,
                        (
                            f"Type mismatch on port '{edge.target_handle}': "
                            f"expected {expected}, got {type(value).__name__} "
                            f"(auto-convert failed: {exc}) - passing original value"
                        ),
                        level="warning",
                    )

            if edge.target_handle in mapped:
                if not isinstance(mapped[edge.target_handle], list):
                    mapped[edge.target_handle] = [mapped[edge.target_handle]]
                mapped[edge.target_handle].append(value)
            else:
                mapped[edge.target_handle] = value

        return merged, mapped

    
    # Atomic node termination + propagation
    

    async def _finalize_node(
        self,
        state: _RunState,
        context: ExecutionContext,
        node: Node,
        success: bool,
        output: dict,
    ) -> None:
        """Save the result and update the status of the descendants.

        This method is called in the `finally` block of `_process_node`, so
        its contract is NOT to throw exceptions (otherwise, the worker will crash due to
        an unhandled exception, while the others will continue executing). All errors
        here are converted to warning logs.
        """
        try:
            ready_now: list[str] = []

            async with state.lock:
                if success:
                    context.node_outputs[node.id] = output
                    state.finished.add(node.id)
                    await context.log(
                        node.id,
                        f"Done. output keys: {list(output)}",
                    )
                    # Condition node: remove the edge with the opposite handle.
                    if node.type == "condition":
                        chosen = "true" if output.get("result") else "false"
                        for e in state.outbound[node.id]:
                            if (
                                e.source_handle is not None
                                and _is_branching_handle(e.source_handle)
                                and e.source_handle != chosen
                            ):
                                state.dead_edges.add(_edge_key(e))
                else:
                    # Error/exception: The node is down; all outbound edges are down.
                    state.finished.add(node.id)
                    state.dead_nodes.add(node.id)
                    for e in state.outbound[node.id]:
                        state.dead_edges.add(_edge_key(e))

                state.pending_count -= 1
                if state.pending_count == 0:
                    state.done_event.set()

                # We propagate the “finish” state to descendants. This can cascade
                # down several levels (via _propagate_dead).
                ready_now = await self._propagate_finish(state, context, node.id)

            for child_id in ready_now:
                state.queue.put_nowait(child_id)
        except Exception as exc:  # noqa: BLE001 - Worker Protection
            logger.exception(
                "Internal error while finalizing node %s: %s", node.id, exc
            )

    async def _propagate_finish(
        self,
        state: _RunState,
        context: ExecutionContext,
        finished_id: str,
    ) -> list[str]:
        """Check each descendant of `finished_id` and return a list of those
        who should be added to the queue. Called under `state.lock`.

        May cascade the marking of others as dead (via _kill).
        """
        to_enqueue: list[str] = []
        # “Death” cascade stack: when a node is marked as dead,
        # its descendants are also re-evaluated in subsequent iterations.
        pending_finished: list[str] = [finished_id]

        while pending_finished:
            parent_id = pending_finished.pop()
            for edge in state.outbound[parent_id]:
                child_id = edge.to_node
                if child_id in state.scheduled or child_id in state.finished:
                    continue

                verdict = self._evaluate_child(state, child_id)
                if verdict == "ready":
                    state.scheduled.add(child_id)
                    to_enqueue.append(child_id)
                elif verdict == "dead":
                    # Cascading death: mark and add to the stack to
                    # re-evaluate the descendants of this specific node.
                    self._kill(state, child_id)
                    await context.log(
                        child_id,
                        "Skipped due to dead branch",
                        level="info",
                    )
                    state.pending_count -= 1
                    if state.pending_count == 0:
                        state.done_event.set()
                    pending_finished.append(child_id)
                # verdict == “wait”: we're just waiting for the parents

        return to_enqueue

    @staticmethod
    def _evaluate_child(state: _RunState, child_id: str) -> str:
        """Returns ‘ready’ / ‘dead’ / ‘wait’ for the child.

        Semantics:
          • all_success: all parents must finish alive; the first
            dead parent → the child is dead (early termination).
          • one_success: at least one alive, finished parent is sufficient;
            as long as alive parents remain active, we wait; if all
            parents have finished and none are alive, the child is dead.
        """
        node = state.nodes_by_id[child_id]
        rule = getattr(node, "trigger_rule", "all_success")
        inbound = state.inbound[child_id]
        if not inbound:
            return "ready"

        alive_finished = 0
        dead_finished = 0
        unfinished = 0
        for e in inbound:
            edge_dead = (
                _edge_key(e) in state.dead_edges
                or e.from_node in state.dead_nodes
            )
            parent_done = e.from_node in state.finished
            if edge_dead and parent_done:
                dead_finished += 1
            elif parent_done:
                alive_finished += 1
            else:
                unfinished += 1

        if rule == "one_success":
            if alive_finished >= 1:
                return "ready"
            if unfinished == 0:
                return "dead"
            return "wait"
        # all_success
        if dead_finished >= 1:
            return "dead"
        if unfinished == 0 and alive_finished == len(inbound):
            return "ready"
        return "wait"

    @staticmethod
    def _kill(state: _RunState, node_id: str) -> None:
        """Mark the node as dead and stamp its outbound edges.
        Called under `state.lock`."""
        if node_id in state.dead_nodes:
            return
        state.dead_nodes.add(node_id)
        state.finished.add(node_id)
        state.scheduled.add(node_id)
        for e in state.outbound[node_id]:
            state.dead_edges.add(_edge_key(e))
