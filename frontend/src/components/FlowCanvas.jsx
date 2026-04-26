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

  const nodeTypes = useMemo(() => ({ nexus: CustomNode }), []);

  const onNodesChange = useCallback(
    (changes) => setNodes((ns) => applyNodeChanges(changes, ns)),
    [setNodes]
  );
  const onEdgesChange = useCallback(
    (changes) => setEdges((es) => applyEdgeChanges(changes, es)),
    [setEdges]
  );
  const onConnect = useCallback(
    (connection) => setEdges((es) => addEdge(connection, es)),
    [setEdges]
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
    </section>
  );
}
