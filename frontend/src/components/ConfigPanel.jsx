import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "../i18n.js";
import { useNodeSchemas } from "../nodeSchema.js";
import { useNoteEditor } from "../noteEditorBridge.js";

const LONG_TEXT_FIELDS = new Set([
  "message",
  "content",
  "description",
  "body",
  "sql",
  "code",
  "prompt",
]);

const JSON_TYPES = new Set(["object", "array"]);

const JSON_FIELD_NAMES = new Set(["initial_data", "params"]);

const inputClass =
  "w-full rounded border border-nexus-border bg-nexus-bg px-2 py-1 text-xs text-nexus-text focus:border-nexus-accent focus:outline-none disabled:cursor-not-allowed disabled:opacity-60";

function Field({ label, hint, children }) {
  return (
    <label className="mb-3 block text-xs">
      <div className="mb-1 text-nexus-muted">{label}</div>
      {children}
      {hint && <div className="mt-1 text-[11px] text-nexus-muted">{hint}</div>}
    </label>
  );
}

function effectiveType(schema) {
  if (!schema) return "string";
  if (schema.enum) return "enum";
  if (schema.type && schema.type !== "null") return schema.type;
  if (Array.isArray(schema.anyOf)) {
    const nonNull = schema.anyOf.find((s) => s?.type && s.type !== "null");
    if (nonNull?.type) return nonNull.type;
  }
  if (Array.isArray(schema.oneOf)) {
    const nonNull = schema.oneOf.find((s) => s?.type && s.type !== "null");
    if (nonNull?.type) return nonNull.type;
  }
  return "string";
}

function isLongText(name, schema) {
  if (LONG_TEXT_FIELDS.has(name)) return true;
  if (schema?.maxLength && schema.maxLength > 200) return true;
  return false;
}

function isJsonField(name, schema, type) {
  if (JSON_TYPES.has(type)) return true;
  if (JSON_FIELD_NAMES.has(name)) return true;
  const desc = schema?.description || "";
  if (typeof desc === "string" && /\bjson\b/i.test(desc)) return true;
  return false;
}

function defaultForType(type, schema) {
  if (schema?.default !== undefined) return schema.default;
  switch (type) {
    case "boolean":
      return false;
    case "integer":
    case "number":
      return 0;
    case "object":
      return {};
    case "array":
      return [];
    default:
      return "";
  }
}

// --- Окремі рендерери полів --------------------------------------------------

function StringInput({ value, onChange, schema, name, disabled }) {
  const long = isLongText(name, schema);
  const Tag = long ? "textarea" : "input";
  const props = long
    ? { rows: 4, className: inputClass + " font-mono" }
    : { type: "text", className: inputClass };
  return (
    <Tag
      {...props}
      value={value ?? ""}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

function NumberInput({ value, onChange, schema, disabled }) {
  const isInt = schema?.type === "integer";
  return (
    <input
      type="number"
      step={isInt ? 1 : "any"}
      className={inputClass}
      disabled={disabled}
      value={value ?? ""}
      onChange={(e) => {
        const raw = e.target.value;
        if (raw === "") {
          onChange("");
          return;
        }
        const parsed = isInt ? parseInt(raw, 10) : parseFloat(raw);
        onChange(Number.isNaN(parsed) ? raw : parsed);
      }}
    />
  );
}

function BoolInput({ value, onChange, disabled }) {
  return (
    <input
      type="checkbox"
      checked={!!value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.checked)}
    />
  );
}

function EnumInput({ value, onChange, schema, disabled }) {
  const options = schema.enum || [];
  return (
    <select
      className={inputClass}
      disabled={disabled}
      value={value ?? options[0] ?? ""}
      onChange={(e) => onChange(e.target.value)}
    >
      {options.map((opt) => (
        <option key={String(opt)} value={opt}>
          {String(opt)}
        </option>
      ))}
    </select>
  );
}

function JsonInput({ value, onChange, disabled }) {
  const { t } = useTranslation();
  const [text, setText] = useState(() =>
    JSON.stringify(value ?? {}, null, 2)
  );
  const [error, setError] = useState(null);
  const localChangeRef = useRef(false);

  useEffect(() => {
    if (localChangeRef.current) {
      localChangeRef.current = false;
      return;
    }
    setText(JSON.stringify(value ?? {}, null, 2));
    setError(null);
  }, [value]);

  const onTextChange = (e) => {
    const v = e.target.value;
    setText(v);
    if (disabled) return;
    try {
      const parsed = JSON.parse(v);
      setError(null);
      localChangeRef.current = true;
      onChange(parsed);
    } catch {
      setError(t("config.invalidJson"));
    }
  };

  return (
    <>
      <textarea
        rows={5}
        className={inputClass + " font-mono"}
        disabled={disabled}
        value={text}
        onChange={onTextChange}
      />
      {error && <div className="mt-1 text-rose-400">{error}</div>}
    </>
  );
}

// --- Динамічна панель --------------------------------------------------------

function DynamicField({ name, schema, value, onChange, disabled }) {
  const { t } = useTranslation();
  const type = effectiveType(schema);
  const label = t(`config.${name}`, schema?.title || name);
  const hint = t(`config.${name}.hint`, schema?.description || "");

  const safeValue = value !== undefined ? value : defaultForType(type, schema);

  if (type === "boolean") {
    return (
      <div className="mb-3 text-xs">
        <label className="flex items-center gap-2">
          <BoolInput value={safeValue} onChange={onChange} disabled={disabled} />
          <span className="text-nexus-muted">{label}</span>
        </label>
        {hint && (
          <div className="mt-1 pl-5 text-[11px] text-nexus-muted">{hint}</div>
        )}
      </div>
    );
  }

  let control;
  if (type === "enum") {
    control = (
      <EnumInput
        value={safeValue}
        onChange={onChange}
        schema={schema}
        disabled={disabled}
      />
    );
  } else if (type === "integer" || type === "number") {
    control = (
      <NumberInput
        value={safeValue}
        onChange={onChange}
        schema={schema}
        disabled={disabled}
      />
    );
  } else if (isJsonField(name, schema, type)) {
    control = (
      <JsonInput value={safeValue} onChange={onChange} disabled={disabled} />
    );
  } else {
    // string / null / unknown → текст
    control = (
      <StringInput
        value={safeValue}
        onChange={onChange}
        schema={schema}
        name={name}
        disabled={disabled}
      />
    );
  }

  return (
    <Field label={label} hint={hint}>
      {control}
    </Field>
  );
}

// Список шрифтів і розмірів для тулбара нотатки.
const NOTE_FONT_FAMILIES = [
  { label: "System (За замовчуванням)", value: "system-ui, sans-serif" },
  { label: "Arial", value: "Arial, Helvetica, sans-serif" },
  { label: "Times New Roman", value: "'Times New Roman', Times, serif" },
  { label: "Georgia", value: "Georgia, serif" },
  { label: "Verdana", value: "Verdana, Geneva, sans-serif" },
  { label: "Courier New", value: "'Courier New', Courier, monospace" },
  { label: "Monospace", value: "ui-monospace, Menlo, monospace" },
  { label: "Comic Sans", value: "'Comic Sans MS', cursive, sans-serif" },
  { label: "Impact", value: "Impact, Charcoal, sans-serif" },
  { label: "Trebuchet MS", value: "'Trebuchet MS', Helvetica, sans-serif" },
  { label: "Tahoma", value: "Tahoma, Geneva, sans-serif" },
  { label: "Palatino", value: "'Palatino Linotype', 'Book Antiqua', Palatino, serif" },
];
const NOTE_FONT_SIZES = [ 8, 10, 11, 12, 14, 16, 18, 20, 22, 24, 28, 32, 36, 42, 48, 64, 72 ];

// 5 класичних пар (фон + текст) для швидкого вибору теми стікера.
const NOTE_PRESETS = [
  { id: "yellow", bg: "#fef3c7", text: "#1f2937", labelKey: "notePresetYellow" },
  { id: "green",  bg: "#d1fae5", text: "#064e3b", labelKey: "notePresetGreen"  },
  { id: "blue",   bg: "#dbeafe", text: "#1e3a8a", labelKey: "notePresetBlue"   },
  { id: "pink",   bg: "#fce7f3", text: "#831843", labelKey: "notePresetPink"   },
  { id: "dark",   bg: "#1f2937", text: "#f9fafb", labelKey: "notePresetDark"   },
];

function NoteToolbar({ node, patchConfig, readonly }) {
  const { t } = useTranslation();
  const config = node.data.config || {};
  const editor = useNoteEditor(node.id);
  const editorReady = !!editor && !readonly;

  const noBlur = (e) => e.preventDefault();

  const runChain = (build) => () => {
    if (!editorReady) return;
    build(editor.chain().focus()).run();
  };

  const updateNodeProp = (patch) => {
    if (readonly) return;
    patchConfig(patch);
  };

  const applyPreset = (preset) => () => {
    if (readonly) return;
    patchConfig({ background_color: preset.bg, text_color: preset.text });
  };


  const applyFontSize = (val) => {
    if (!editorReady) return;
    const num = parseFloat(val);
    if (isNaN(num)) return;


    editor.chain().focus().setFontSize(`${num}px`).run();
  };

  const textStyleAttrs = editor ? editor.getAttributes("textStyle") : {};
  const activeFontFamily =
    textStyleAttrs.fontFamily || config.font_family || NOTE_FONT_FAMILIES[0].value;
  const activeFontSize = (() => {
    const raw = textStyleAttrs.fontSize;
    if (typeof raw === "string") {
      const parsed = parseFloat(raw);
      if (!Number.isNaN(parsed)) return parsed;
    }
    const fromConfig = Number(config.font_size);
    return Number.isFinite(fromConfig) ? fromConfig : 14;
  })();
  const activeColor = textStyleAttrs.color || config.text_color || "#1f2937";


  const [localFontSize, setLocalFontSize] = useState("");
  const [isFontSizeFocused, setIsFontSizeFocused] = useState(false);


  useEffect(() => {
    if (!isFontSizeFocused) {
      setLocalFontSize(activeFontSize);
    }
  }, [activeFontSize, isFontSizeFocused]);


  const isActive = (name, attrs) =>
    !!editor && editor.isActive(name, attrs);

  const buttonClass = (active) =>
    "rounded border px-2 py-1 text-xs hover:border-amber-400 disabled:cursor-not-allowed disabled:opacity-50 " +
    (active
      ? "border-amber-400 bg-amber-500/30 text-amber-100"
      : "border-nexus-border bg-nexus-bg text-nexus-text");

  const ALIGNMENTS = [
    { value: "left", label: "L", titleKey: "noteAlignLeft" },
    { value: "center", label: "C", titleKey: "noteAlignCenter" },
    { value: "right", label: "R", titleKey: "noteAlignRight" },
    { value: "justify", label: "J", titleKey: "noteAlignJustify" },
  ];

  return (
    <div className="mt-4 rounded border border-amber-500/40 bg-amber-500/10 p-3">
      <div className="text-xs font-semibold text-amber-200">
        {t("config.noteHeading")}
      </div>
      <div className="mt-1 text-[11px] text-nexus-muted">
        {t("config.noteHint")}
      </div>

      {/* --- Заголовок стікера --- */}
      <label className="mt-3 block text-[11px] text-nexus-muted">
        {t("config.noteTitle")}
      </label>
      <input
        type="text"
        disabled={readonly}
        value={config.title ?? ""}
        onChange={(e) => updateNodeProp({ title: e.target.value })}
        placeholder={t("config.noteTitlePlaceholder")}
        className={inputClass + " mt-1"}
      />

      {/* --- B / I / U / S через TipTap --- */}
      <div className="mt-3 flex gap-1">
        <button
          type="button"
          disabled={!editorReady}
          onMouseDown={noBlur}
          onClick={runChain((c) => c.toggleBold())}
          className={buttonClass(isActive("bold")) + " font-bold"}
          title={t("config.noteBold")}
        >
          B
        </button>
        <button
          type="button"
          disabled={!editorReady}
          onMouseDown={noBlur}
          onClick={runChain((c) => c.toggleItalic())}
          className={buttonClass(isActive("italic")) + " italic"}
          title={t("config.noteItalic")}
        >
          I
        </button>
        <button
          type="button"
          disabled={!editorReady}
          onMouseDown={noBlur}
          onClick={runChain((c) => c.toggleUnderline())}
          className={buttonClass(isActive("underline")) + " underline"}
          title={t("config.noteUnderline")}
        >
          U
        </button>
        <button
          type="button"
          disabled={!editorReady}
          onMouseDown={noBlur}
          onClick={runChain((c) => c.toggleStrike())}
          className={buttonClass(isActive("strike")) + " line-through"}
          title={t("config.noteStrike")}
        >
          S
        </button>
      </div>

      {/* --- Вирівнювання тексту --- */}
      <label className="mt-3 block text-[11px] text-nexus-muted">
        {t("config.noteAlign")}
      </label>
      <div className="mt-1 flex gap-1">
        {ALIGNMENTS.map((a) => (
          <button
            key={a.value}
            type="button"
            disabled={!editorReady}
            onMouseDown={noBlur}
            onClick={runChain((c) => c.setTextAlign(a.value))}
            className={buttonClass(isActive({ textAlign: a.value }))}
            title={t(`config.${a.titleKey}`)}
          >
            {a.label}
          </button>
        ))}
      </div>

      {/* --- Шрифт виділеного тексту --- */}
      <label className="mt-3 block text-[11px] text-nexus-muted">
        {t("config.noteFontFamily")}
      </label>
      <select
        className={inputClass + " mt-1"}
        disabled={!editorReady}
        value={activeFontFamily}
        onChange={(e) => {
          if (!editorReady) return;
          editor.chain().focus().setFontFamily(e.target.value).run();
        }}
      >
        {!NOTE_FONT_FAMILIES.some((f) => f.value === activeFontFamily) && (
          <option value={activeFontFamily}>{activeFontFamily}</option>
        )}
        {NOTE_FONT_FAMILIES.map((f) => (
          <option key={f.value} value={f.value}>
            {f.label}
          </option>
        ))}
      </select>

      {/* --- Розмір шрифту (TipTap Stepper) --- */}
      <label className="mt-3 block text-[11px] text-nexus-muted">
        {t("config.noteFontSize")}
      </label>

      <div className="mt-1 flex flex-col items-start gap-1">
        {/* ПОЛЕ ВВОДУ */}
        <input
          type="number"
          step="0.5"
          disabled={!editorReady}
          // Показуємо те, що ввів юзер, коли поле у фокусі
          value={isFontSizeFocused ? localFontSize : activeFontSize}
          onFocus={() => {
            setIsFontSizeFocused(true);
            setLocalFontSize(activeFontSize);
          }}
          onChange={(e) => {
            // ТІЛЬКИ записуємо цифру в поле. Ніяких змін стилів під час друку!
            setLocalFontSize(e.target.value);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              e.target.blur();
            }
          }}
          onBlur={() => {
            setIsFontSizeFocused(false);
            const finalVal = parseFloat(localFontSize);
            if (!isNaN(finalVal) && localFontSize !== "") {
              applyFontSize(finalVal);
            }
          }}
          className="h-7 w-16 rounded border border-nexus-border bg-nexus-bg px-1 text-center text-xs text-nexus-text focus:border-amber-400 focus:outline-none disabled:cursor-not-allowed"
        />

        {/* КНОПКИ + та - */}
        <div className="flex gap-1">
          <button
            type="button"
            disabled={!editorReady || activeFontSize <= 8}
            onMouseDown={noBlur}
            onClick={() => {
              const current = parseFloat(activeFontSize) || 14;
              const smaller = NOTE_FONT_SIZES.slice().reverse().find(s => s < current) || 8;
              setLocalFontSize(smaller);
              applyFontSize(smaller);
            }}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded border border-nexus-border bg-nexus-bg text-nexus-text hover:border-amber-400 disabled:cursor-not-allowed disabled:opacity-50"
          >
            −
          </button>

          <button
            type="button"
            disabled={!editorReady || activeFontSize >= 72}
            onMouseDown={noBlur}
            onClick={() => {
              const current = parseFloat(activeFontSize) || 14;
              const larger = NOTE_FONT_SIZES.find(s => s > current) || 72;
              setLocalFontSize(larger);
              applyFontSize(larger);
            }}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded border border-nexus-border bg-nexus-bg text-nexus-text hover:border-amber-400 disabled:cursor-not-allowed disabled:opacity-50"
          >
            +
          </button>
        </div>
      </div>

      {/* --- Популярні стилі (теми стікерів) --- */}
      <label className="mt-3 block text-[11px] text-nexus-muted">
        {t("config.notePresets")}
      </label>
      <div className="mt-1 flex flex-wrap gap-1.5">
        {NOTE_PRESETS.map((p) => {
          const active =
            (config.background_color || "#fef3c7").toLowerCase() === p.bg.toLowerCase() &&
            (config.text_color || "#1f2937").toLowerCase() === p.text.toLowerCase();
          return (
            <button
              key={p.id}
              type="button"
              disabled={readonly}
              onMouseDown={noBlur}
              onClick={applyPreset(p)}
              title={t(`config.${p.labelKey}`, p.id)}
              style={{
                backgroundColor: p.bg,
                color: p.text,
                borderColor: active ? "#f59e0b" : p.text,
              }}
              className={
                "flex h-7 w-7 items-center justify-center rounded text-[11px] font-bold transition-transform hover:scale-110 disabled:cursor-not-allowed disabled:opacity-50 " +
                (active ? "border-2" : "border")
              }
            >
              A
            </button>
          );
        })}
      </div>

{/* --- Колір тексту (TipTap: для виділеного або наступних введених символів) --- */}
      <label className="mt-3 block text-[11px] text-nexus-muted">
        {t("config.noteTextColor")}
      </label>
      <input
        type="color"
        disabled={!editorReady}
        value={activeColor}
        onChange={(e) => {
          if (!editorReady) return;
          editor.chain().focus().setColor(e.target.value).run();
        }}
        className="mt-1 h-7 w-12 cursor-pointer rounded border border-nexus-border bg-nexus-bg disabled:cursor-not-allowed"
      />

      {/* --- Колір фону стікера (глобально) --- */}
      <label className="mt-3 block text-[11px] text-nexus-muted">
        {t("config.noteBgColor")}
      </label>
      <input
        type="color"
        disabled={readonly}
        value={config.background_color || "#fef3c7"}
        onMouseDown={noBlur}
        onChange={(e) => updateNodeProp({ background_color: e.target.value })}
        className="mt-1 h-7 w-12 cursor-pointer rounded border border-nexus-border bg-nexus-bg disabled:cursor-not-allowed"
      />
    </div>
  );
}

export default function ConfigPanel({ node, onUpdate, onDelete, readonly }) {
  const { t } = useTranslation();
  const { schemas } = useNodeSchemas();

  if (!node) {
    return (
      <aside className="w-80 border-l border-nexus-border bg-nexus-panel p-3 text-sm">
        <div className="font-semibold">{t("config.heading")}</div>
        <div className="mt-1 text-xs text-nexus-muted">{t("config.empty")}</div>
      </aside>
    );
  }

  const type = node.data.type;
  const config = node.data.config || {};
  const triggerRule = node.data.trigger_rule || "all_success";
  const schema = schemas[type];
  const configSchema = schema?.config_schema;

  if (type === "note") {
    const patchNoteConfig = (patch) => {
      if (readonly) return;
      onUpdate(node.id, {
        data: { ...node.data, config: { ...config, ...patch } },
      });
    };
    return (
      <aside className="flex w-80 flex-col overflow-y-auto border-l border-nexus-border bg-nexus-panel p-3 text-sm">
        <div className="font-semibold">{t("config.heading")}</div>

        <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-nexus-muted">
          <div>
            <div className="opacity-70">{t("config.id")}</div>
            <div className="text-nexus-text">{node.id}</div>
          </div>
          <div>
            <div className="opacity-70">{t("config.type")}</div>
            <div className="text-nexus-text">{t(`nodes.${type}`, type)}</div>
          </div>
        </div>

        {readonly && (
          <div className="mt-3 rounded border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-[11px] text-amber-300">
            {t("config.readonly")}
          </div>
        )}

        <NoteToolbar
          node={node}
          patchConfig={patchNoteConfig}
          readonly={readonly}
        />

        <button
          type="button"
          disabled={readonly}
          onClick={() => onDelete(node.id)}
          className="mt-4 rounded border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-xs font-semibold text-rose-300 hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {t("config.delete")}
        </button>
      </aside>
    );
  }

  const properties = useMemo(() => {
    if (!configSchema?.properties) return [];
    const required = new Set(configSchema.required || []);
    return Object.entries(configSchema.properties).map(([name, propSchema]) => ({
      name,
      schema: propSchema,
      required: required.has(name),
    }));
  }, [configSchema]);

  const updateField = (name, value) => {
    if (readonly) return;
    onUpdate(node.id, {
      data: { ...node.data, config: { ...config, [name]: value } },
    });
  };

  const updateTriggerRule = (value) => {
    if (readonly) return;
    onUpdate(node.id, { data: { ...node.data, trigger_rule: value } });
  };

  return (
    <aside className="flex w-80 flex-col overflow-y-auto border-l border-nexus-border bg-nexus-panel p-3 text-sm">
      <div className="font-semibold">{t("config.heading")}</div>

      <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-nexus-muted">
        <div>
          <div className="opacity-70">{t("config.id")}</div>
          <div className="text-nexus-text">{node.id}</div>
        </div>
        <div>
          <div className="opacity-70">{t("config.type")}</div>
          <div className="text-nexus-text">{t(`palette.${type}`, type)}</div>
        </div>
      </div>

      <div className="mt-3 text-xs">
        <div className="mb-1 text-nexus-muted">{t("config.triggerRule")}</div>
        <select
          className={inputClass}
          disabled={readonly}
          value={triggerRule}
          onChange={(e) => updateTriggerRule(e.target.value)}
        >
          <option value="all_success">{t("config.allSuccess")}</option>
          <option value="one_success">{t("config.oneSuccess")}</option>
        </select>
        <div className="mt-1 text-[11px] text-nexus-muted">
          {triggerRule === "one_success"
            ? t("config.oneSuccessHint")
            : t("config.allSuccessHint")}
        </div>
      </div>

      {readonly && (
        <div className="mt-3 rounded border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-[11px] text-amber-300">
          {t("config.readonly")}
        </div>
      )}

      <div className="mt-4">
        {properties.length === 0 && (
          <div className="text-xs text-nexus-muted">{t("config.noFields")}</div>
        )}
        {properties.map(({ name, schema: propSchema }) => (
          <DynamicField
            key={name}
            name={name}
            schema={propSchema}
            value={config[name]}
            onChange={(v) => updateField(name, v)}
            disabled={readonly}
          />
        ))}
      </div>

      <button
        type="button"
        disabled={readonly}
        onClick={() => onDelete(node.id)}
        className="mt-4 rounded border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-xs font-semibold text-rose-300 hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {t("config.delete")}
      </button>
    </aside>
  );
}