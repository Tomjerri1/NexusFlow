import { useEffect, useRef, useState } from "react";
import { useTranslation } from "../i18n.js";
import { openLogsSocket } from "../api.js";

const LEVEL_COLORS = {
  info: "text-nexus-text",
  warning: "text-amber-400",
  error: "text-rose-400",
  done: "text-emerald-400 font-semibold",
};

export default function LogConsole({ jobId, onJobFinished }) {
  const { t } = useTranslation();
  const [entries, setEntries] = useState([]);
  const scrollRef = useRef(null);

  useEffect(() => {
    if (!jobId) {
      setEntries([]);
      return;
    }

    setEntries([]);
    const ws = openLogsSocket(jobId);
    ws.onmessage = (event) => {
      try {
        const entry = JSON.parse(event.data);
        setEntries((prev) => prev.concat(entry));
        if (entry.level === "done") {
          onJobFinished?.(jobId);
        }
      } catch {
        /* ignore malformed payloads */
      }
    };
    return () => ws.close();
  }, [jobId, onJobFinished]);

  // автоскрол униз при новому повідомленні
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [entries.length]);

  return (
    <div className="flex h-48 min-h-0 flex-col border-t border-nexus-border bg-nexus-bg p-3 text-sm">
      <div className="mb-2 font-semibold text-nexus-text">{t("logs.heading")}</div>

      {entries.length === 0 ? (
        <div className="text-xs text-nexus-muted">{t("logs.empty")}</div>
      ) : (
        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto rounded border border-nexus-border bg-black/30 p-2 font-mono text-[11px] leading-relaxed"
        >
          {entries.map((e, i) => (
            <div key={i} className={LEVEL_COLORS[e.level] || "text-nexus-text"}>
              <span className="opacity-50">
                [{(e.timestamp || "").slice(11, 19)}]
              </span>{" "}
              <span className="opacity-70">{e.node_id || "—"}</span>{" "}
              <span>{e.message}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
