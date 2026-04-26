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
  // Спершу пробуємо точний бекендний ключ (io / logic / trigger / ...).
  // Якщо нема — повертаємо саме сире значення (з великої літери).
  return t(`categories.${key}`, key.charAt(0).toUpperCase() + key.slice(1));
}

export default function NodePalette() {
  const { t } = useTranslation();
  const { schemas } = useNodeSchemas();

  const onDragStart = (event, nodeType) => {
    event.dataTransfer.setData("application/reactflow", nodeType);
    event.dataTransfer.effectAllowed = "move";
  };

  // Групуємо типи по категоріях (ключ = бекендний `category`).
  const groups = new Map();
  for (const type of NODE_TYPES) {
    const schema = schemas[type];
    const key = categoryKey(schema);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(type);
  }

  return (
    <aside className="flex w-56 flex-col border-r border-nexus-border bg-nexus-panel p-3 text-sm">
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
                    TYPE_BG[type]
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
    </aside>
  );
}
