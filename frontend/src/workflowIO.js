// Конвертація між backend-форматом Workflow і React Flow nodes/edges.
// Backend не зберігає координати, тому при load'і ми робимо простий
// топологічний layered-layout: x = layer * 280, y = slot * 130.

const COL_PX = 280;
const ROW_PX = 130;

function computeLayout(nodes, edges) {
  const inDegree = {};
  const adj = {};
  for (const n of nodes) {
    inDegree[n.id] = 0;
    adj[n.id] = [];
  }
  for (const e of edges) {
    if (!(e.to in inDegree) || !(e.from in adj)) continue;
    inDegree[e.to] = (inDegree[e.to] || 0) + 1;
    adj[e.from].push(e.to);
  }

  // Kahn з відстеженням шару.
  const layer = {};
  const queue = [];
  for (const n of nodes) {
    if (inDegree[n.id] === 0) {
      layer[n.id] = 0;
      queue.push(n.id);
    }
  }
  while (queue.length) {
    const id = queue.shift();
    for (const next of adj[id] || []) {
      const candidate = layer[id] + 1;
      if (layer[next] === undefined || candidate > layer[next]) {
        layer[next] = candidate;
      }
      if ((--inDegree[next]) === 0) queue.push(next);
    }
  }

  // Слоти всередині кожного шару — стабільний порядок за вхідним списком вузлів.
  const slot = {};
  const positions = {};
  for (const n of nodes) {
    const l = layer[n.id] ?? 0;
    slot[l] = (slot[l] || 0);
    positions[n.id] = { x: l * COL_PX + 40, y: slot[l] * ROW_PX + 40 };
    slot[l] += 1;
  }
  return positions;
}

// Backend Workflow → React Flow state.
export function workflowToFlow(workflow) {
  const positions = computeLayout(workflow.nodes || [], workflow.edges || []);

  const flowNodes = (workflow.nodes || []).map((n) => {
    const cfg = structuredClone(n.config ?? {});
    // Візуальні стікери `note` мають окремий React Flow type'у і
    // тримають width/height у `data.config` (рушій ігнорує цей вузол).
    const reactFlowType = n.type === "note" ? "note" : "nexus";
    const node = {
      id: n.id,
      type: reactFlowType,
      position: positions[n.id] || { x: 40, y: 40 },
      data: {
        type: n.type,
        config: cfg,
        // Системний атрибут — як двигун трактує вхідні ребра (AND/OR).
        // Дефолт `all_success` синхронізовано з Pydantic-моделлю Node.
        trigger_rule: n.trigger_rule || "all_success",
      },
    };
    if (n.type === "note") {
      // React Flow читає `style.width/height` для resize-bbox; ми
      // дублюємо їх із config, щоб NodeResizer стартував з правильним
      // розміром одразу після завантаження сценарію.
      if (typeof cfg.width === "number") node.style = { ...(node.style || {}), width: cfg.width };
      if (typeof cfg.height === "number") node.style = { ...(node.style || {}), height: cfg.height };
    }
    return node;
  });

  const flowEdges = (workflow.edges || []).map((e, i) => {
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
    nodes: flowNodes.map((n) => ({
      id: n.id,
      type: n.data.type,
      config: n.data.config,
      // Передаємо тригер-правило лише якщо воно не дефолтне — щоб JSON
      // залишався мінімальним для звичайних воркфлоу.
      ...(n.data.trigger_rule && n.data.trigger_rule !== "all_success"
        ? { trigger_rule: n.data.trigger_rule }
        : {}),
    })),
    edges: flowEdges.map((e) => ({
      from: e.source,
      to: e.target,
      ...(e.sourceHandle ? { source_handle: e.sourceHandle } : {}),
      ...(e.targetHandle ? { target_handle: e.targetHandle } : {}),
      ...(e.data?.is_readonly ? { is_readonly: true } : {}),
    })),
  };
}
