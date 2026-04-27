import { Handle, Position } from "@xyflow/react";
import { useTranslation } from "../i18n.js";
import { useNodeSchemas } from "../nodeSchema.js";
import { TYPE_BG, summarize } from "../nodeTypes.js";

// Кольори source-handle для condition-портів (true/false).
const HANDLE_COLOR = {
  true: "!bg-emerald-500",
  false: "!bg-rose-500",
};

// Хендли позиціонуємо `relative`, перевизначаючи дефолтний `absolute`
// з React Flow — інакше flex не зможе розкласти рядки портів вертикально.
// React Flow і далі коректно рахує координати handle-точок із DOM,
// бо bounding box обчислюється від реального положення елемента.
const HANDLE_RESET = "!relative !left-auto !right-auto !top-auto !transform-none";

export default function CustomNode({ id, data, selected }) {
  const { t } = useTranslation();
  const { schemas } = useNodeSchemas();
  const type = data.type;
  const schema = schemas[type];

  const inputs = schema?.inputs ?? [];
  const outputs = schema?.outputs ?? [];

  const isTrigger = type === "manual_trigger" || inputs.length === 0;

  return (
    <div
      className={
        "min-w-[210px] rounded-md border bg-nexus-panel shadow text-nexus-text " +
        (selected ? "border-nexus-accent" : "border-nexus-border")
      }
    >
      <div
        className={
          "rounded-t-md px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-white " +
          (TYPE_BG[type] || "bg-slate-600")
        }
      >
        {/* Спершу шукаємо локалізацію за type_name, потім fallback на бекендний
           display_name, і нарешті — на сирий type_name. */}
        {t(`nodes.${type}`, schema?.info?.display_name || type)}
      </div>

      <div className="px-2 py-1.5 text-[11px]">
        <div className="text-nexus-muted">
          <span className="opacity-70">id:</span> {id}
        </div>
        <div
          className="mt-0.5 truncate text-nexus-text"
          title={summarize(type, data.config)}
        >
          {summarize(type, data.config)}
        </div>
      </div>

      {/* Дві flex-колонки портів. Кожна колонка автоматично розподіляє свої
         рядки по вертикалі — позиція Handle обчислюється React Flow з DOM. */}
      <div className="flex justify-between gap-2 px-1 pb-1.5">
        <div className="flex min-w-[80px] flex-col gap-1">
          {!isTrigger &&
            inputs.map((port) => (
              <div
                key={`in-${port.name}`}
                className="flex items-center gap-1.5 text-[10px] text-nexus-muted"
                title={port.description || port.name}
              >
                <Handle
                  id={port.name}
                  type="target"
                  position={Position.Left}
                  className={`${HANDLE_RESET} !h-2 !w-2 !bg-nexus-accent`}
                />
                <span className="truncate">
                  {t(`ports.${port.name}`, port.name)}
                  {port.required ? "*" : ""}
                </span>
              </div>
            ))}
        </div>

        <div className="flex min-w-[80px] flex-col items-end gap-1">
          {outputs.map((port) => (
            <div
              key={`out-${port.name}`}
              className="flex flex-row-reverse items-center gap-1.5 text-[10px] text-nexus-muted"
              title={port.description || port.name}
            >
              <Handle
                id={port.name}
                type="source"
                position={Position.Right}
                className={`${HANDLE_RESET} !h-2 !w-2 ${
                  HANDLE_COLOR[port.name] || "!bg-nexus-accent"
                }`}
              />
              <span className="truncate">
                {t(`ports.${port.name}`, port.name)}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Fallback handles, якщо schema ще не прийшла — щоб ребра, що вже існують
         у графі, не залишилися «висіти» без рендера. */}
      {!schema && !isTrigger && (
        <Handle
          type="target"
          position={Position.Left}
          className="!bg-nexus-accent"
        />
      )}
      {!schema && (
        <Handle
          type="source"
          position={Position.Right}
          className="!bg-nexus-accent"
        />
      )}
    </div>
  );
}
