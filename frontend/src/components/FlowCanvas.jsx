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

let idCounter = 1;
function makeId(type) {
  // Короткий читабельний id типу `mt_3`, `cnd_1` тощо.
  const prefix = type.split("_").map((p) => p[0]).join("");
  return `${prefix}_${idCounter++}`;
}

export default function FlowCanvas({
  nodes,
  edges,
  setNodes,
  setEdges,
  setSelectedId,
}) {
  const { t } = useTranslation();
  const wrapperRef = useRef(null);
  const { screenToFlowPosition } = useReactFlow();
  const { schemas } = useNodeSchemas();

  const nodeTypes = useMemo(() => ({ nexus: CustomNode }), []);

  // Якщо у воркфлоу є вузол з декларативним static-зв'язком — редагування
  // ребер блокується (ребра помічаються as readonly).
  const readonly = useMemo(() => {
    const types = nodes.map((n) => n.data?.type).filter(Boolean);
    return hasReadonlyConnections(schemas, types);
  }, [schemas, nodes]);

  const onNodesChange = useCallback(
    (changes) => setNodes((ns) => applyNodeChanges(changes, ns)),
    [setNodes]
  );
  const onEdgesChange = useCallback(
    (changes) => {
      if (readonly) {
        // Дозволяємо лише selection-зміни, блокуємо delete/replace.
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

  const onDragOver = useCallback((event) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (event) => {
      event.preventDefault();
      const type = event.dataTransfer.getData("application/reactflow");
      if (!type) return;

      const position = screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });
      const id = makeId(type);
      const newNode = {
        id,
        type: "nexus",
        position,
        data: {
          type,
          config: structuredClone(DEFAULT_CONFIG[type]),
        },
      };
      setNodes((ns) => ns.concat(newNode));
    },
    [screenToFlowPosition, setNodes]
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
        edgesReconnectable={!readonly}
        edgesFocusable={!readonly}
        nodesConnectable={!readonly}
        nodesDraggable={true}
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
