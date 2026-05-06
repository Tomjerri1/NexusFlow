import dagre from "dagre";

// Конвертація між backend-форматом Workflow і React Flow nodes/edges.
//
// === UI Metadata Pocket ===
// Бекенд тримає у `Node.ui_metadata` непрозорий словник для фронтенду:
// координати (`position: {x, y}`), розміри стікерів і т.д. Двигун у це
// поле НЕ заглядає; це простий round-trip контракт між UI та JSON.
//
// === Авто-вирівнювання (Dagre) ===
// Раніше координати губилися при збереженні, а UI робив примітивний
// layered-layout `x = layer*280, y = slot*130`, який накладав вузли при
// бодай трохи нетривіальних графах (особливо для сценаріїв, що
// генеруються з Python-коду через `Workflow(...)` без позицій). Тепер:
//   • при load'і, якщо ХОЧА Б ОДИН вузол не має `ui_metadata.position`,
//     ми проганяємо весь граф через dagre (rankdir LR) — і отримуємо
//     гарантовано не-перекритий layout без ручної настройки;
//   • при save'і пишемо `ui_metadata.position = {x, y}` із актуального
//     `node.position` React Flow — позиції живуть між сесіями.

const FALLBACK_NODE_WIDTH = 220;
const FALLBACK_NODE_HEIGHT = 90;
const NOTE_DEFAULT_WIDTH = 240;
const NOTE_DEFAULT_HEIGHT = 160;

// Dagre layout. Викликається тільки коли позиції відсутні (або частково
// відсутні) — а не на кожен load. `rankdir: LR` — зліва направо, що
// узгоджується з нашою mental-model «trigger → ... → output». Щедрі
// `nodesep`/`ranksep` дають достатньо простору під handle'и портів.
function computeLayout(nodes, edges) {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 30, ranksep: 80 });
  g.setDefaultEdgeLabel(() => ({}));

  for (const n of nodes) {
    // Для note-стікерів беремо їхній реальний розмір (із ui_metadata
    // або з config-fallback'у) — інакше великий стікер зіткнеться з сусідами.
    const isNote = n.type === "note";
    const ui = n.ui_metadata || {};
    const cfg = n.config || {};
    const width = isNote
      ? (ui.width ?? cfg.width ?? NOTE_DEFAULT_WIDTH)
      : FALLBACK_NODE_WIDTH;
    const height = isNote
      ? (ui.height ?? cfg.height ?? NOTE_DEFAULT_HEIGHT)
      : FALLBACK_NODE_HEIGHT;
    g.setNode(n.id, { width, height });
  }

  for (const e of edges) {
    const src = e.from ?? e.from_node;
    const tgt = e.to ?? e.to_node;
    if (!src || !tgt) continue;
    if (!g.hasNode(src) || !g.hasNode(tgt)) continue;
    g.setEdge(src, tgt);
  }

  dagre.layout(g);

  // Dagre повертає координати ЦЕНТРУ вузла; React Flow ставить вузол
  // за лівим-верхнім кутом — конвертуємо.
  const positions = {};
  for (const n of nodes) {
    const node = g.node(n.id);
    if (!node) {
      positions[n.id] = { x: 40, y: 40 };
      continue;
    }
    positions[n.id] = {
      x: Math.round(node.x - node.width / 2),
      y: Math.round(node.y - node.height / 2),
    };
  }
  return positions;
}

// Backend Workflow → React Flow state.
export function workflowToFlow(workflow) {
  const nodes = workflow.nodes || [];
  const edges = workflow.edges || [];

  // Якщо хоча б одного вузла бракує `ui_metadata.position` — заганяємо
  // весь граф у dagre. Це покриває обидва кейси:
  //  (а) сценарій згенеровано Python-кодом без візуальних координат;
  //  (б) старі збережені сценарії, що ще не пройшли save-with-positions.
  const needsLayout = nodes.some((n) => {
    const pos = n.ui_metadata?.position;
    return !pos || typeof pos.x !== "number" || typeof pos.y !== "number";
  });
  const dagrePositions = needsLayout ? computeLayout(nodes, edges) : {};

  const flowNodes = nodes.map((n) => {
    const cfg = structuredClone(n.config ?? {});
    const uiMeta = structuredClone(n.ui_metadata ?? {});
    const reactFlowType = n.type === "note" ? "note" : "nexus";

    const explicitPos = uiMeta.position;
    const position =
      explicitPos && typeof explicitPos.x === "number" && typeof explicitPos.y === "number"
        ? { x: explicitPos.x, y: explicitPos.y }
        : (dagrePositions[n.id] || { x: 40, y: 40 });

    const node = {
      id: n.id,
      type: reactFlowType,
      position,
      data: {
        type: n.type,
        config: cfg,
        ui_metadata: uiMeta,
        // Системний атрибут — як двигун трактує вхідні ребра (AND/OR).
        trigger_rule: n.trigger_rule || "all_success",
      },
    };

    if (n.type === "note") {
      // Міграція: спочатку ui_metadata (новий канон), потім config (старі
      // workflows, які ще не пройшли save-cycle після фічі ui_metadata).
      const w = uiMeta.width ?? cfg.width ?? NOTE_DEFAULT_WIDTH;
      const h = uiMeta.height ?? cfg.height ?? NOTE_DEFAULT_HEIGHT;
      // React Flow читає `style.width/height` для resize-bbox — щоб
      // NodeResizer стартував з правильним розміром одразу після завантаження.
      node.style = { width: w, height: h };
      // Дзеркало у data.ui_metadata, щоб NoteNode/handler'и завжди читали
      // з єдиного джерела (нова конвенція — width/height живуть тут).
      node.data.ui_metadata = { ...node.data.ui_metadata, width: w, height: h };
    }
    return node;
  });

  const flowEdges = edges.map((e, i) => {
    const src = e.from ?? e.from_node;
    const tgt = e.to ?? e.to_node;
    const sh = e.source_handle ?? null;
    const th = e.target_handle ?? null;
    return {
      id: `e_${src}_${tgt}_${i}`,
      source: src,
      target: tgt,
      ...(sh ? { sourceHandle: sh } : {}),
      ...(th ? { targetHandle: th } : {}),
      data: { is_readonly: !!e.is_readonly },
    };
  });

  return {
    name: workflow.name || "",
    nodes: flowNodes,
    edges: flowEdges,
    isReadonly: !!workflow.is_readonly,
  };
}

// React Flow state → backend Workflow JSON.
export function flowToWorkflow(name, flowNodes, flowEdges, options = {}) {
  return {
    name: name || "untitled",
    is_readonly: !!options.isReadonly,
    nodes: flowNodes.map((n) => {
      // Збираємо ui_metadata «з нуля» з актуального стану React Flow,
      // зберігаючи тільки те, що нам реально потрібно для round-trip:
      //  • position — завжди з `n.position` (live-стан React Flow);
      //  • width/height — лише для note-стікерів (із n.style або data).
      const uiMeta = {
        ...(n.data?.ui_metadata || {}),
        position: {
          x: Math.round(n.position?.x ?? 0),
          y: Math.round(n.position?.y ?? 0),
        },
      };

      if (n.data?.type === "note") {
        // Резолвимо розмір у пріоритеті: style React Flow → data.ui_metadata
        // → дефолт. Style має пріоритет, бо саме його оновлює NodeResizer
        // на льоту, навіть якщо в data.ui_metadata ще не дійшов patch.
        const w =
          n.style?.width ?? n.data?.ui_metadata?.width ?? NOTE_DEFAULT_WIDTH;
        const h =
          n.style?.height ?? n.data?.ui_metadata?.height ?? NOTE_DEFAULT_HEIGHT;
        uiMeta.width = Math.round(Number(w));
        uiMeta.height = Math.round(Number(h));
      }

      return {
        id: n.id,
        type: n.data.type,
        config: n.data.config,
        // Передаємо тригер-правило лише якщо воно не дефолтне — щоб JSON
        // залишався мінімальним для звичайних воркфлоу.
        ...(n.data.trigger_rule && n.data.trigger_rule !== "all_success"
          ? { trigger_rule: n.data.trigger_rule }
          : {}),
        ui_metadata: uiMeta,
      };
    }),
    edges: flowEdges.map((e) => ({
      from: e.source,
      to: e.target,
      ...(e.sourceHandle ? { source_handle: e.sourceHandle } : {}),
      ...(e.targetHandle ? { target_handle: e.targetHandle } : {}),
      ...(e.data?.is_readonly ? { is_readonly: true } : {}),
    })),
  };
}
