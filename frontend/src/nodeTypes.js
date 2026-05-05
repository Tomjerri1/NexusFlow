// Єдине джерело правди про типи вузлів — синхронізовано з NODE_REGISTRY бекенду.

export const NODE_TYPES = [
  "manual_trigger",
  "read_file",
  "write_file",
  "condition",
  "log",
  "custom_code",
  "expression",
  "note",
];

// Дефолтні config'и при створенні вузла з палітри.
export const DEFAULT_CONFIG = {
  manual_trigger: { initial_data: {} },
  read_file: { path: "data/input.txt", encoding: "utf-8" },
  write_file: { path: "output.txt", content: "", content_key: "content", append: false },
  condition: { expression: "input.size > 100" },
  log: { message: "Hello, {input.user}!", level: "info" },
  custom_code: { script_name: "my_script", entry_point: "main", params: {} },
  expression: { expression: "input.a + input.b" },
  // Note — суто візуальний стікер (рушій його ігнорує).
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

// Колір-акцент для заголовка вузла на канвасі.
export const TYPE_BG = {
  manual_trigger: "bg-emerald-600",
  read_file: "bg-sky-600",
  write_file: "bg-violet-600",
  condition: "bg-amber-600",
  log: "bg-slate-500",
  custom_code: "bg-fuchsia-600",
  expression: "bg-teal-600",
  note: "bg-amber-300 text-slate-900",
};

// Скорочений підпис під заголовком вузла (рендериться у CustomNode).
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
      return (config?.message || "").slice(0, 40);
    case "custom_code":
      return `${config?.script_name || "—"}.${config?.entry_point || "main"}()`;
    case "expression":
      return config?.expression || "—";
    case "note":
      return "";
    default:
      return "";
  }
}
