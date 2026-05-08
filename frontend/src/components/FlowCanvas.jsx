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
  workflowReadonly = false,
}) {
  const { t } = useTranslation();
  const wrapperRef = useRef(null);
  const reactFlow = useReactFlow();
  const { screenToFlowPosition } = reactFlow;
  const { schemas } = useNodeSchemas();

  // Викликається після того, як React Flow виміряв реальні розміри ВСІХ
  // вузлів у DOM. Тільки на цьому етапі fitView знає справжні bbox і може
  // коректно центрувати/масштабувати граф. Проп `fitView` сам по собі
  // спрацьовує до dagre-розкладки → в результаті масштаб брався з нульових
  // розмірів. Хук гарантує: dagre розставив координати → DOM відрендерив
  // вузли з реальними size'ами → fitView рахує bbox правильно.
  const onNodesInitialized = useCallback(() => {
    reactFlow.fitView({ duration: 500, padding: 0.2 });
  }, [reactFlow]);

  // `nexus` — універсальний логічний вузол, `note` — суто візуальний стікер.
  // Бекенд відрізняє їх через прапорець `is_visual_only` у схемі.
  const nodeTypes = useMemo(
    () => ({ nexus: CustomNode, note: NoteNode }),
    []
  );

  // Воркфлоу повністю readonly: або встановлено явний прапорець на самому
  // воркфлоу, або є хоча б один вузол з декларативним static-зв'язком.
  const readonly = useMemo(() => {
    if (workflowReadonly) return true;
    const types = nodes.map((n) => n.data?.type).filter(Boolean);
    return hasReadonlyConnections(schemas, types);
  }, [schemas, nodes, workflowReadonly]);

  const onNodesChange = useCallback(
    (changes) => {
      if (readonly) {
        // Лише selection — позиція/видалення/розмір блокуються.
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
      // Візуальний стікер `note` рендериться окремим React Flow type'ом
      // (без хедера/портів). Усі решта — універсальний `nexus` вузол.
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
          // Для note одразу засіваємо UI Metadata Pocket (width/height) —
          // щоб NoteNode читав розмір із того ж джерела, куди потім писатиме
          // resize-handler. position/координати ми не дублюємо в ui_metadata
          // тут — flowToWorkflow зчитає їх із n.position на момент save'у.
          ui_metadata: isNote ? { width: 240, height: 160 } : {},
        },
        // Стартовий розмір на рівні React Flow node — щоб NodeResizer мав
        // bbox, навіть поки в data.ui_metadata ще нічого нема.
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
