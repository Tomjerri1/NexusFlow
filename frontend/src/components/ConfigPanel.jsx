import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "../i18n.js";
import { useNodeSchemas } from "../nodeSchema.js";

// Поля з імен у цьому списку рендеримо як textarea — корисно для текстових
// та шаблонних значень, де користувач часто вводить багаторядковий контент.
const LONG_TEXT_FIELDS = new Set([
  "message",
  "content",
  "description",
  "body",
  "sql",
  "code",
  "prompt",
]);

// JSON-textarea використовуємо для object/array-полів та для всього, що має
// тип `object` без явного підтипу.
const JSON_TYPES = new Set(["object", "array"]);

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

// JSON Schema допускає `anyOf: [{type:"string"},{type:"null"}]` для optional
// полів (Pydantic `str | None`). Витягуємо ефективний (не-null) тип.
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
  // Pydantic не виставляє maxLength, але користувач може вручну.
  if (schema?.maxLength && schema.maxLength > 200) return true;
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
  // Прапорець «текст щойно змінив користувач»: запобігає перезатиранню
  // textarea при кожному батьківському апдейті (інакше курсор стрибає
  // і форматування ламається на льоту).
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

  const safeValue = value !== undefined ? value : defaultForType(type, schema);

  if (type === "boolean") {
    return (
      <label className="mb-3 flex items-center gap-2 text-xs">
        <BoolInput value={safeValue} onChange={onChange} disabled={disabled} />
        <span className="text-nexus-muted">{label}</span>
      </label>
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
  } else if (JSON_TYPES.has(type)) {
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

  return <Field label={label}>{control}</Field>;
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
  const schema = schemas[type];
  const configSchema = schema?.config_schema;

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
