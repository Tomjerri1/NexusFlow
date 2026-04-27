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

  const flowNodes = (workflow.nodes || []).map((n) => ({
    id: n.id,
    type: "nexus",
    position: positions[n.id] || { x: 40, y: 40 },
    data: {
      type: n.type,
      config: structuredClone(n.config ?? {}),
    },
  }));

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
    };
  });

  return { name: workflow.name || "", nodes: flowNodes, edges: flowEdges };
}

// React Flow state → backend Workflow JSON.
export function flowToWorkflow(name, flowNodes, flowEdges) {
  return {
    name: name || "untitled",
    nodes: flowNodes.map((n) => ({
      id: n.id,
      type: n.data.type,
      config: n.data.config,
    })),
    edges: flowEdges.map((e) => ({
      from: e.source,
      to: e.target,
      ...(e.sourceHandle ? { source_handle: e.sourceHandle } : {}),
      ...(e.targetHandle ? { target_handle: e.targetHandle } : {}),
    })),
  };
}
