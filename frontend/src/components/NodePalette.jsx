import { useEffect, useState } from "react";
import { fetchWorkflows } from "../api.js";
import { NODE_TYPES, TYPE_BG } from "../nodeTypes.js";
import { useTranslation } from "../i18n.js";
import { useNodeSchemas } from "../nodeSchema.js";

// Назви вузлів і категорій ходять через i18n.
// Якщо ключа в словнику немає — fallback на schema-метадані з бекенду
// (а якщо й їх нема — на сирий type_name / "general").

function nodeLabel(t, type, schema) {
  const backendName = schema?.info?.display_name;
  return t(`nodes.${type}`, backendName || type);
}

function categoryKey(schema) {
  return schema?.info?.category || "general";
}

function categoryLabel(t, key) {
  return t(`categories.${key}`, key.charAt(0).toUpperCase() + key.slice(1));
}

export default function NodePalette({ onLoadWorkflow, refreshTick = 0, loadError }) {
  const { t } = useTranslation();
  const { schemas } = useNodeSchemas();

  const [savedWorkflows, setSavedWorkflows] = useState([]);
  const [savedError, setSavedError] = useState(null);
  const [loadingNames, setLoadingNames] = useState(true);

  // Перетягуємо тип-вузла з палітри на канвас.
  const onDragStart = (event, nodeType) => {
    event.dataTransfer.setData("application/reactflow", nodeType);
    event.dataTransfer.effectAllowed = "move";
  };

  // Список збережених workflow підтягується при mount + при `refreshTick`
  // (інкрементується після успішного збереження з RunPanel).
  useEffect(() => {
    let cancelled = false;
    setLoadingNames(true);
    fetchWorkflows()
      .then((names) => {
        if (cancelled) return;
        setSavedWorkflows(Array.isArray(names) ? names : []);
        setSavedError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setSavedError(String(err.message || err));
      })
      .finally(() => {
        if (!cancelled) setLoadingNames(false);
      });
    return () => {
      cancelled = true;
    };
  }, [refreshTick]);

  // Групуємо типи по категоріях (ключ = бекендний `category`).
  const groups = new Map();
  for (const type of NODE_TYPES) {
    const schema = schemas[type];
    const key = categoryKey(schema);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(type);
  }

  return (
    <aside className="flex w-56 flex-col overflow-y-auto border-r border-nexus-border bg-nexus-panel p-3 text-sm">
      <div className="font-semibold">{t("palette.heading")}</div>
      <div className="mt-1 text-xs text-nexus-muted">{t("palette.hint")}</div>

      <div className="mt-3 flex flex-col gap-3">
        {[...groups.entries()].map(([catKey, types]) => (
          <div key={catKey} className="flex flex-col gap-2">
            <div className="text-[10px] font-semibold uppercase tracking-wide text-nexus-muted">
              {categoryLabel(t, catKey)}
            </div>
            {types.map((type) => {
              const schema = schemas[type];
              const label = nodeLabel(t, type, schema);
              return (
                <div
                  key={type}
                  draggable
                  onDragStart={(e) => onDragStart(e, type)}
                  className={
                    "cursor-grab select-none rounded-md px-3 py-2 text-xs font-semibold text-white shadow active:cursor-grabbing " +
                    (TYPE_BG[type] || "bg-slate-600")
                  }
                  title={schema?.info?.description || label}
                >
                  {label}
                </div>
              );
            })}
          </div>
        ))}
      </div>

      {/* --- Збережені сценарії ------------------------------------------ */}
      <div className="mt-5 border-t border-nexus-border pt-3">
        <div className="text-[10px] font-semibold uppercase tracking-wide text-nexus-muted">
          {t("palette.savedHeading")}
        </div>

        {loadingNames && (
          <div className="mt-2 text-xs text-nexus-muted">{t("palette.savedLoading")}</div>
        )}

        {!loadingNames && savedWorkflows.length === 0 && !savedError && (
          <div className="mt-2 text-xs text-nexus-muted">
            {t("palette.savedEmpty")}
          </div>
        )}

        {savedError && (
          <div className="mt-2 break-words text-xs text-rose-400">
            {savedError}
          </div>
        )}

        {loadError && (
          <div className="mt-2 break-words text-xs text-rose-400">
            {loadError}
          </div>
        )}

        <div className="mt-2 flex flex-col gap-1">
          {savedWorkflows.map((wfName) => (
            <button
              key={wfName}
              type="button"
              onClick={() => onLoadWorkflow?.(wfName)}
              className="truncate rounded border border-nexus-border bg-nexus-bg px-2 py-1 text-left text-xs text-nexus-text hover:border-nexus-accent hover:text-nexus-accent"
              title={t("palette.savedClickHint", "Click to load")}
            >
              {wfName}
            </button>
          ))}
        </div>
      </div>
    </aside>
  );
}
