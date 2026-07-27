import { Handle, Position } from "@xyflow/react";
import { useTranslation } from "../i18n.js";
import { useNodeSchemas } from "../nodeSchema.js";
import { TYPE_BG, summarize } from "../nodeTypes.js";

// Source-handle colors for condition ports (true/false).
const HANDLE_COLOR = {
  true: "!bg-emerald-500",
  false: "!bg-rose-500",
};

// We set the handles to `relative`, overriding the default `absolute`
// from React Flow—otherwise, flex won't be able to arrange the port rows vertically.
// React Flow continues to correctly calculate the coordinates of the handle points from the DOM,
// because the bounding box is calculated based on the element's actual position.
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
      title={t(`nodes.${type}_hint`, schema?.info?.description)}
      className={
        "min-w-[210px] max-w-[260px] rounded-md border bg-nexus-panel shadow text-nexus-text " +
        (selected ? "border-nexus-accent" : "border-nexus-border")
      }
    >
      <div
        className={
          "rounded-t-md px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-white " +
          (TYPE_BG[type] || "bg-slate-600")
        }
      >
        {/* First, we look for a localization based on the `type_name`, then fall back to the backend
           `display_name`, and finally to the raw `type_name`. */}
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

      {/* Two flex columns of ports. Each column automatically distributes its
         rows vertically—the `handle` position is calculated by React Flow from the DOM. */}
      <div className="flex justify-between gap-2 px-1 pb-1.5">
        <div className="flex min-w-[80px] flex-col gap-1">
          {!isTrigger &&
            inputs.map((port) => (
              <div
                key={`in-${port.name}`}
                className="flex items-center gap-1.5 text-[10px] text-nexus-muted"
                title={t(`ports.${port.name}_hint`, port.description || port.name)}
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
              title={t(`ports.${port.name}_hint`, port.description || port.name)}
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

      {/* Fallback handles, in case the schema hasn't arrived yet—so that edges that already exist
         in the graph don't end up “hanging” without a render. */}
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