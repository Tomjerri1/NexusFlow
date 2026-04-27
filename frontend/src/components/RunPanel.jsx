import { useState } from "react";
import { useTranslation } from "../i18n.js";
import { runJob, saveWorkflow } from "../api.js";
import { flowToWorkflow } from "../workflowIO.js";

const STATUS_COLORS = {
  pending: "text-amber-400",
  running: "text-sky-400",
  success: "text-emerald-400",
  failed: "text-rose-400",
};

export default function RunPanel({
  name,
  setName,
  nodes,
  edges,
  isReadonly = false,
  setIsReadonly,
  jobInfo,
  onJobStarted,
  onSaved,
}) {
  const { t } = useTranslation();
  const [busyRun, setBusyRun] = useState(false);
  const [busySave, setBusySave] = useState(false);
  const [error, setError] = useState(null);
  const [savedNotice, setSavedNotice] = useState(null);

  const onRun = async () => {
    setError(null);
    setSavedNotice(null);
    if (nodes.length === 0) {
      setError(t("run.cantRunEmpty"));
      return;
    }
    try {
      setBusyRun(true);
      const job = await runJob(
        flowToWorkflow(name, nodes, edges, { isReadonly })
      );
      onJobStarted(job);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusyRun(false);
    }
  };

  const onSave = async () => {
    setError(null);
    setSavedNotice(null);
    if (nodes.length === 0) {
      setError(t("run.cantRunEmpty"));
      return;
    }
    if (!name || !name.trim()) {
      setError(t("run.nameRequired"));
      return;
    }
    try {
      setBusySave(true);
      const result = await saveWorkflow(
        flowToWorkflow(name.trim(), nodes, edges, { isReadonly })
      );
      setSavedNotice(t("run.savedAs", `Saved as ${result.name}`));
      onSaved?.(result);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusySave(false);
    }
  };

  return (
    <div className="border-t border-nexus-border bg-nexus-panel p-3 text-sm">
      <div className="mb-2 font-semibold">{t("run.heading")}</div>

      <div className="flex items-center gap-2">
        <input
          value={name ?? ""}
          onChange={(e) => setName(e.target.value)}
          className="flex-1 rounded border border-nexus-border bg-nexus-bg px-2 py-1 text-xs text-nexus-text focus:border-nexus-accent focus:outline-none"
          placeholder={t("run.namePlaceholder")}
        />
        <button
          type="button"
          disabled={busySave}
          onClick={onSave}
          title={t("run.saveTitle")}
          className="rounded border border-nexus-border bg-nexus-bg px-3 py-1 text-xs font-semibold text-nexus-text hover:border-nexus-accent hover:text-nexus-accent disabled:opacity-50"
        >
          {busySave ? t("run.saving") : t("run.save")}
        </button>
        <button
          type="button"
          disabled={busyRun}
          onClick={onRun}
          className="rounded bg-nexus-accent px-3 py-1 text-xs font-semibold text-nexus-bg hover:opacity-90 disabled:opacity-50"
        >
          {busyRun ? t("run.running") : t("run.button")}
        </button>
      </div>

      {setIsReadonly && (
        <label className="mt-2 flex items-center gap-2 text-[11px] text-nexus-muted">
          <input
            type="checkbox"
            checked={!!isReadonly}
            onChange={(e) => setIsReadonly(e.target.checked)}
          />
          <span>{t("run.readonly")}</span>
        </label>
      )}

      {savedNotice && (
        <div className="mt-2 text-xs text-emerald-400">{savedNotice}</div>
      )}

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
