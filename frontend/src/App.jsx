import { ReactFlowProvider } from "@xyflow/react";
import { useCallback, useEffect, useState } from "react";
import LangSwitcher from "./components/LangSwitcher.jsx";
import NodePalette from "./components/NodePalette.jsx";
import FlowCanvas from "./components/FlowCanvas.jsx";
import ConfigPanel from "./components/ConfigPanel.jsx";
import RunPanel from "./components/RunPanel.jsx";
import LogConsole from "./components/LogConsole.jsx";
import { getJob } from "./api.js";
import { useTranslation } from "./i18n.js";

export default function App() {
  const { t } = useTranslation();

  const [nodes, setNodes] = useState([]);
  const [edges, setEdges] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [jobInfo, setJobInfo] = useState(null);

  const selectedNode = nodes.find((n) => n.id === selectedId) || null;

  const updateNode = useCallback(
    (id, patch) =>
      setNodes((ns) => ns.map((n) => (n.id === id ? { ...n, ...patch } : n))),
    []
  );

  const deleteNode = useCallback((id) => {
    setNodes((ns) => ns.filter((n) => n.id !== id));
    setEdges((es) => es.filter((e) => e.source !== id && e.target !== id));
    setSelectedId((cur) => (cur === id ? null : cur));
  }, []);

  // Після завершення WS-стріму витягуємо фінальний Job для відображення статусу.
  const onJobFinished = useCallback(async (jobId) => {
    try {
      const job = await getJob(jobId);
      setJobInfo(job);
    } catch {
      /* ігноруємо — можливо, сервер уже забув про job */
    }
  }, []);

  // Поллимо статус, поки не пішов done з WS — це покриває кейси, коли WS падає.
  useEffect(() => {
    if (!jobInfo || ["success", "failed"].includes(jobInfo.status)) return;
    const t = setInterval(async () => {
      try {
        const updated = await getJob(jobInfo.id);
        setJobInfo(updated);
      } catch {
        /* noop */
      }
    }, 1000);
    return () => clearInterval(t);
  }, [jobInfo]);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-nexus-border bg-nexus-panel px-4 py-2">
        <div>
          <h1 className="text-base font-semibold tracking-tight">{t("app.title")}</h1>
          <p className="text-xs text-nexus-muted">{t("app.subtitle")}</p>
        </div>
        <LangSwitcher />
      </header>

      <ReactFlowProvider>
        <main className="flex flex-1 overflow-hidden">
          <NodePalette />

          <div className="flex flex-1 flex-col">
            <FlowCanvas
              nodes={nodes}
              edges={edges}
              setNodes={setNodes}
              setEdges={setEdges}
              setSelectedId={setSelectedId}
            />
            <RunPanel
              nodes={nodes}
              edges={edges}
              jobInfo={jobInfo}
              onJobStarted={setJobInfo}
            />
            <LogConsole jobId={jobInfo?.id || null} onJobFinished={onJobFinished} />
          </div>

          <ConfigPanel
            node={selectedNode}
            onUpdate={updateNode}
            onDelete={deleteNode}
          />
        </main>
      </ReactFlowProvider>
    </div>
  );
}
