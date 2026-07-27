export const NODE_TYPES = [
  "manual_trigger",
  "read_file",
  "write_file",
  "condition",
  "log",
  "custom_code",
  "expression",
  "note",
  "read_directory",
  "hello",
];

// Default configurations when creating a node from the palette.
export const DEFAULT_CONFIG = {
  manual_trigger: { initial_data: {} },
  read_file: { path: "data/input.txt", encoding: "utf-8" },
  write_file: { path: "output.txt", content: "", content_key: "content", append: false },
  condition: { expression: "input.size > 100" },
  log: { message: "Hello, {input.user}!", level: "info" },
  custom_code: { script_name: "my_script", entry_point: "main", params: {} },
  expression: { expression: "input.a + input.b" },
  hello: {},
  // Note — a purely visual sticker (the engine ignores it).
  read_directory: { path: "data/", recursive: false, extension: "", name_contains: "" },
  note: {
    title: "Примітка",
    html_content: "",
    width: 240,
    height: 160,
    background_color: "#fef3c7",
    text_color: "#1f2937",
    font_family: "system-ui, sans-serif",
    font_size: 14,
  },
};

// Accent color for the node header on the canvas.
export const TYPE_BG = {
  manual_trigger: "bg-emerald-600",
  read_file: "bg-sky-600",
  write_file: "bg-violet-600",
  condition: "bg-amber-600",
  log: "bg-slate-500",
  custom_code: "bg-fuchsia-600",
  expression: "bg-teal-600",
  note: "bg-amber-300 text-slate-900",
  read_directory: "bg-emerald-500",
};

// Abbreviated caption under the node title (rendered in CustomNode).
export function summarize(type, config) {
  switch (type) {
    case "manual_trigger": {
      const keys = Object.keys(config?.initial_data || {});
      return keys.length ? `data: {${keys.join(", ")}}` : "no initial data";
    }
    case "read_file":
      return config?.path || "—";
    case "write_file":
      return `${config?.path || "—"}${config?.append ? " (append)" : ""}`;
    case "condition":
      return config?.expression || "—";
    case "log":
      return config?.message || "—";
    case "custom_code":
      return `${config?.script_name || "—"}.${config?.entry_point || "main"}()`;
    case "expression":
      return config?.expression || "—";
    case "read_directory":
      return `${config?.path || "—"} [фільтр: ${config?.name_contains || "*"}]`;
    case "note":
      return "";
    default:
      return "";
  }
}
