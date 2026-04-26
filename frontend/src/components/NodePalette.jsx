import { NODE_TYPES, TYPE_BG } from "../nodeTypes.js";
import { useTranslation } from "../i18n.js";

export default function NodePalette() {
  const { t } = useTranslation();

  const onDragStart = (event, nodeType) => {
    event.dataTransfer.setData("application/reactflow", nodeType);
    event.dataTransfer.effectAllowed = "move";
  };

  return (
    <aside className="flex w-56 flex-col border-r border-nexus-border bg-nexus-panel p-3 text-sm">
      <div className="font-semibold">{t("palette.heading")}</div>
      <div className="mt-1 text-xs text-nexus-muted">{t("palette.hint")}</div>

      <div className="mt-3 flex flex-col gap-2">
        {NODE_TYPES.map((type) => (
          <div
            key={type}
            draggable
            onDragStart={(e) => onDragStart(e, type)}
            className={
              "cursor-grab select-none rounded-md px-3 py-2 text-xs font-semibold text-white shadow active:cursor-grabbing " +
              TYPE_BG[type]
            }
            title={t(`palette.${type}`)}
          >
            {t(`palette.${type}`)}
          </div>
        ))}
      </div>
    </aside>
  );
}
