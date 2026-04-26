// Тонкий REST/WS-клієнт. Усі шляхи відносні — Vite-proxy у dev переадресує на :8000.

export async function runJob(workflow) {
  const res = await fetch("/jobs/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ workflow }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
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
