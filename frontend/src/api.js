async function throwCleanError(res) {
  const text = await res.text();
  let cleanMessage = text;

  try {
    const errJson = JSON.parse(text);

    if (errJson.detail && Array.isArray(errJson.detail)) {
      cleanMessage = errJson.detail.map(e => e.msg).join("; ");
    } else if (errJson.detail && typeof errJson.detail === "string") {
      cleanMessage = errJson.detail;
    }
  } catch (e) {
  }

  throw new Error(`HTTP ${res.status}: ${cleanMessage}`);
}

export async function runJob(workflow) {
  const res = await fetch("/jobs/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ workflow }),
  });
  if (!res.ok) {
    await throwCleanError(res);
  }
  return res.json();
}

export async function getJob(jobId) {
  const res = await fetch(`/jobs/${jobId}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export function openLogsSocket(jobId) {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return new WebSocket(`${proto}://${window.location.host}/ws/jobs/${jobId}`);
}

export async function fetchNodesSchema() {
  const res = await fetch("/api/nodes/schema");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function fetchWorkflows() {
  const res = await fetch("/workflows");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json(); // -> string[]
}

export async function fetchWorkflow(name) {
  const res = await fetch(`/workflows/${encodeURIComponent(name)}`);
  if (!res.ok) {
    await throwCleanError(res);
  }
  return res.json(); // -> Workflow JSON
}

export async function saveWorkflow(data) {
  const res = await fetch("/workflows", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    await throwCleanError(res);
  }
  return res.json();
}