import {
  Background,
  Controls,
  ReactFlow,
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  useReactFlow,
} from "@xyflow/react";
import { useCallback, useMemo, useRef } from "react";
import { useTranslation } from "../i18n.js";
import { useNodeSchemas, hasReadonlyConnections } from "../nodeSchema.js";
import { DEFAULT_CONFIG } from "../nodeTypes.js";
import CustomNode from "./CustomNode.jsx";
import NoteNode from "./NoteNode.jsx";

let idCounter = 1;
function makeId(type) {
  // A short, human-readable ID such as `mt_3`, `cnd_1`, etc.
  const prefix = type.split("_").map((p) => p[0]).join("");
  return `${prefix}_${idCounter++}`;
}

export default function FlowCanvas({
  nodes,
  edges,
  setNodes,
  setEdges,
  setSelectedId,
  workflowReadonly = false,
}) {
  const { t } = useTranslation();
  const wrapperRef = useRef(null);
  const reactFlow = useReactFlow();
  const { screenToFlowPosition } = reactFlow;
  const { schemas } = useNodeSchemas();

  // Called after React Flow has measured the actual dimensions of ALL
  // nodes in the DOM. Only at this stage does `fitView` know the true bbox and can
  // correctly center/scale the graph. The `fitView` prop itself
  // triggers before the dagre layout → as a result, the scale was taken from zero
  // dimensions. The hook guarantees: dagre has set the coordinates → the DOM has rendered
  // nodes with actual sizes → fitView calculates the bbox correctly.
  const onNodesInitialized = useCallback(() => {
    reactFlow.fitView({ duration: 500, padding: 0.2 });
  }, [reactFlow]);

  // `nexus` is a universal logical node, while `note` is a purely visual sticker.
  // The backend distinguishes between them using the `is_visual_only` flag in the schema.
  const nodeTypes = useMemo(
    () => ({ nexus: CustomNode, note: NoteNode }),
    []
  );

  // The workflow is completely read-only: either an explicit flag is set on the
  // workflow itself, or there is at least one node with a declarative static link.
  const readonly = useMemo(() => {
    if (workflowReadonly) return true;
    const types = nodes.map((n) => n.data?.type).filter(Boolean);
    return hasReadonlyConnections(schemas, types);
  }, [schemas, nodes, workflowReadonly]);

  const onNodesChange = useCallback(
    (changes) => {
      if (readonly) {
        // Only selection—position, deletion, and size are locked.
        const safe = changes.filter((c) => c.type === "select");
        setNodes((ns) => applyNodeChanges(safe, ns));
        return;
      }
      setNodes((ns) => applyNodeChanges(changes, ns));
    },
    [setNodes, readonly]
  );
  const onEdgesChange = useCallback(
    (changes) => {
      if (readonly) {
        const safe = changes.filter((c) => c.type === "select");
        setEdges((es) => applyEdgeChanges(safe, es));
        return;
      }
      setEdges((es) => applyEdgeChanges(changes, es));
    },
    [setEdges, readonly]
  );
  const onConnect = useCallback(
    (connection) => {
      if (readonly) return;
      setEdges((es) => addEdge(connection, es));
    },
    [setEdges, readonly]
  );

  const onDragOver = useCallback(
    (event) => {
      event.preventDefault();
      event.dataTransfer.dropEffect = readonly ? "none" : "move";
    },
    [readonly]
  );

  const onDrop = useCallback(
    (event) => {
      event.preventDefault();
      if (readonly) return;
      const type = event.dataTransfer.getData("application/reactflow");
      if (!type) return;

      const position = screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });
      const id = makeId(type);
      // The `note` visual sticker is rendered as a separate React Flow type
      // (without a header or ports). Everything else is a universal `nexus` node.
      const reactFlowType = type === "note" ? "note" : "nexus";
      const isNote = type === "note";
      const newNode = {
        id,
        type: reactFlowType,
        position,
        data: {
          type,
          config: structuredClone(DEFAULT_CONFIG[type]),
          trigger_rule: "all_success",
          // For the note, we immediately populate the UI Metadata Pocket (width/height) —
          // so that NoteNode reads the dimensions from the same source where the
          // resize-handler will later write them. We do not duplicate the position/coordinates in ui_metadata
          // here — flowToWorkflow will read them from n.position at the time of saving.
          ui_metadata: isNote ? { width: 240, height: 160 } : {},
        },
        // Initial size at the React Flow node level — so that NodeResizer has
        // a bbox, even if there is nothing in data.ui_metadata yet.
        ...(isNote ? { style: { width: 240, height: 160 } } : {}),
      };
      setNodes((ns) => ns.concat(newNode));
    },
    [screenToFlowPosition, setNodes, readonly]
  );

  const onSelectionChange = useCallback(
    ({ nodes: selectedNodes }) => {
      setSelectedId(selectedNodes?.[0]?.id ?? null);
    },
    [setSelectedId]
  );

  return (
    <section
      ref={wrapperRef}
      className="relative flex-1 bg-nexus-bg"
      onDrop={onDrop}
      onDragOver={onDragOver}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onSelectionChange={onSelectionChange}
        onInit={(instance) => {
          setTimeout(() => instance.fitView({ duration: 500, padding: 0.2 }), 50);
        }}
        edgesReconnectable={!readonly}
        edgesFocusable={!readonly}
        nodesConnectable={!readonly}
        nodesDraggable={!readonly}
        elementsSelectable={true}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={16} color="#334155" />
        <Controls />
      </ReactFlow>

      {nodes.length === 0 && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-nexus-muted">
          {t("canvas.empty")}
        </div>
      )}

      {readonly && (
        <div className="pointer-events-none absolute right-3 top-3 rounded bg-amber-600/80 px-2 py-1 text-[11px] font-semibold text-white shadow">
          {t("canvas.readonlyEdges") || "Edges are read-only"}
        </div>
      )}
    </section>
  );
}
