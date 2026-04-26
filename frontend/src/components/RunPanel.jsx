import { useState } from "react";
import { useTranslation } from "../i18n.js";
import { runJob } from "../api.js";

const STATUS_COLORS = {
  pending: "text-amber-400",
  running: "text-sky-400",
  success: "text-emerald-400",
  failed: "text-rose-400",
};

function buildPayload(name, nodes, edges) {
  return {
    name: name || "untitled",
    nodes: nodes.map((n) => ({
      id: n.id,
      type: n.data.type,
      config: n.data.config,
    })),
    edges: edges.map((e) => ({
      from: e.source,
      to: e.target,
      ...(e.sourceHandle ? { source_handle: e.sourceHandle } : {}),
    })),
  };
}

export default function RunPanel({ nodes, edges, jobInfo, onJobStarted }) {
  const { t } = useTranslation();
  const [name, setName] = useState("untitled");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const onRun = async () => {
    setError(null);
    if (nodes.length === 0) {
      setError(t("run.cantRunEmpty"));
      return;
    }
    try {
      setBusy(true);
      const job = await runJob(buildPayload(name, nodes, edges));
      onJobStarted(job);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="border-t border-nexus-border bg-nexus-panel p-3 text-sm">
      <div className="mb-2 font-semibold">{t("run.heading")}</div>

      <div className="flex items-center gap-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="flex-1 rounded border border-nexus-border bg-nexus-bg px-2 py-1 text-xs text-nexus-text focus:border-nexus-accent focus:outline-none"
        />
        <button
          type="button"
          disabled={busy}
          onClick={onRun}
          className="rounded bg-nexus-accent px-3 py-1 text-xs font-semibold text-nexus-bg hover:opacity-90 disabled:opacity-50"
        >
          {busy ? t("run.running") : t("run.button")}
        </button>
      </div>

      {error && (
        <div className="mt-2 break-words text-xs text-rose-400">
          {t("run.error")} {error}
        </div>
      )}

      {jobInfo && (
        <div className="mt-2 text-xs">
          <div className="text-nexus-muted">
            {t("run.jobId")} <span className="font-mono text-nexus-text">{jobInfo.id}</span>
          </div>
          <div className="text-nexus-muted">
            {t("run.status")}{" "}
            <span className={STATUS_COLORS[jobInfo.status] || "text-nexus-text"}>
              {jobInfo.status}
            </span>
          </div>
          {jobInfo.error && (
            <div className="mt-1 text-rose-400">{jobInfo.error}</div>
          )}
        </div>
      )}
    </div>
  );
}
