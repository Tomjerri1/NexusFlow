import { Handle, Position } from "@xyflow/react";
import { useTranslation } from "../i18n.js";
import { useNodeSchemas } from "../nodeSchema.js";
import { TYPE_BG, summarize } from "../nodeTypes.js";

// Висота рядка-порту в пікселях (для розрахунку top:%).
const PORT_ROW_PX = 22;
const HEADER_PX = 26;

// Кольори source-handle для condition-портів (true/false).
const HANDLE_COLOR = {
  true: "!bg-emerald-500",
  false: "!bg-rose-500",
};

function portTop(index, count) {
  // Розподіляємо порти рівномірно по висоті блоку.
  const offset = HEADER_PX + (index + 1) * PORT_ROW_PX;
  return offset;
}

export default function CustomNode({ id, data, selected }) {
  const { t } = useTranslation();
  const { schemas } = useNodeSchemas();
  const type = data.type;
  const schema = schemas[type];

  // Fallback на legacy-розкладку, якщо schema ще не завантажено.
  const inputs = schema?.inputs ?? [];
  const outputs = schema?.outputs ?? [];

  const isTrigger = type === "manual_trigger" || inputs.length === 0;
  const minHeight = Math.max(inputs.length, outputs.length, 1) * PORT_ROW_PX + HEADER_PX + 24;

  return (
    <div
      className={
        "relative min-w-[190px] rounded-md border bg-nexus-panel shadow text-nexus-text " +
        (selected ? "border-nexus-accent" : "border-nexus-border")
      }
      style={{ minHeight }}
    >
      <div
        className={
          "rounded-t-md px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-white " +
          TYPE_BG[type]
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

      {/* Вхідні порти (зліва) */}
      {!isTrigger &&
        inputs.map((port, idx) => (
          <span key={`in-${port.name}`}>
            <Handle
              id={port.name}
              type="target"
              position={Position.Left}
              style={{ top: portTop(idx, inputs.length) }}
              className="!bg-nexus-accent"
            />
            <span
              className="absolute left-3 text-[10px] text-nexus-muted"
              style={{ top: portTop(idx, inputs.length) - 8 }}
              title={port.description || port.name}
            >
              {t(`ports.${port.name}`, port.name)}
              {port.required ? "*" : ""}
            </span>
          </span>
        ))}

      {/* Вихідні порти (справа) */}
      {outputs.map((port, idx) => (
        <span key={`out-${port.name}`}>
          <Handle
            id={port.name}
            type="source"
            position={Position.Right}
            style={{ top: portTop(idx, outputs.length) }}
            className={HANDLE_COLOR[port.name] || "!bg-nexus-accent"}
          />
          <span
            className="absolute right-3 text-[10px] text-nexus-muted"
            style={{ top: portTop(idx, outputs.length) - 8 }}
            title={port.description || port.name}
          >
            {t(`ports.${port.name}`, port.name)}
          </span>
        </span>
      ))}

      {/* Fallback handles, якщо schema ще не прийшла */}
      {!schema && !isTrigger && (
        <Handle type="target" position={Position.Left} className="!bg-nexus-accent" />
      )}
      {!schema && (
        <Handle type="source" position={Position.Right} className="!bg-nexus-accent" />
      )}
    </div>
  );
}
