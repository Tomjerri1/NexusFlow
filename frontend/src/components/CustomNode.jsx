import { Handle, Position } from "@xyflow/react";
import { useTranslation } from "../i18n.js";
import { TYPE_BG, summarize } from "../nodeTypes.js";

export default function CustomNode({ id, data, selected }) {
  const { t } = useTranslation();
  const type = data.type;
  const isCondition = type === "condition";
  const isTrigger = type === "manual_trigger";

  return (
    <div
      className={
        "min-w-[170px] rounded-md border bg-nexus-panel shadow text-nexus-text " +
        (selected ? "border-nexus-accent" : "border-nexus-border")
      }
    >
      {!isTrigger && (
        <Handle
          type="target"
          position={Position.Left}
          className="!bg-nexus-accent"
        />
      )}

      <div
        className={
          "rounded-t-md px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-white " +
          TYPE_BG[type]
        }
      >
        {t(`palette.${type}`)}
      </div>

      <div className="px-2 py-1.5 text-[11px]">
        <div className="text-nexus-muted">
          <span className="opacity-70">id:</span> {id}
        </div>
        <div className="mt-0.5 truncate text-nexus-text" title={summarize(type, data.config)}>
          {summarize(type, data.config)}
        </div>
      </div>

      {isCondition ? (
        <>
          <Handle
            type="source"
            position={Position.Right}
            id="true"
            style={{ top: "62%" }}
            className="!bg-emerald-500"
          />
          <span
            className="absolute right-3 text-[10px] text-emerald-400"
            style={{ top: "calc(62% - 14px)" }}
          >
            {t("canvas.handleTrue")}
          </span>

          <Handle
            type="source"
            position={Position.Right}
            id="false"
            style={{ top: "85%" }}
            className="!bg-rose-500"
          />
          <span
            className="absolute right-3 text-[10px] text-rose-400"
            style={{ top: "calc(85% - 14px)" }}
          >
            {t("canvas.handleFalse")}
          </span>
          <div className="h-6" />
        </>
      ) : (
        <Handle
          type="source"
          position={Position.Right}
          className="!bg-nexus-accent"
        />
      )}
    </div>
  );
}
