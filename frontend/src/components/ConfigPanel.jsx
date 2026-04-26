import { useEffect, useState } from "react";
import { useTranslation } from "../i18n.js";

function Field({ label, children }) {
  return (
    <label className="mb-3 block text-xs">
      <div className="mb-1 text-nexus-muted">{label}</div>
      {children}
    </label>
  );
}

const inputClass =
  "w-full rounded border border-nexus-border bg-nexus-bg px-2 py-1 text-xs text-nexus-text focus:border-nexus-accent focus:outline-none";

export default function ConfigPanel({ node, onUpdate, onDelete }) {
  const { t } = useTranslation();

  if (!node) {
    return (
      <aside className="w-80 border-l border-nexus-border bg-nexus-panel p-3 text-sm">
        <div className="font-semibold">{t("config.heading")}</div>
        <div className="mt-1 text-xs text-nexus-muted">{t("config.empty")}</div>
      </aside>
    );
  }

  const type = node.data.type;
  const config = node.data.config;

  const updateConfig = (patch) =>
    onUpdate(node.id, { data: { ...node.data, config: { ...config, ...patch } } });

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
          <div className="text-nexus-text">{t(`palette.${type}`)}</div>
        </div>
      </div>

      <div className="mt-4">
        {type === "manual_trigger" && (
          <InitialDataField config={config} updateConfig={updateConfig} />
        )}

        {type === "read_file" && (
          <>
            <Field label={t("config.path")}>
              <input
                className={inputClass}
                value={config.path}
                onChange={(e) => updateConfig({ path: e.target.value })}
              />
            </Field>
            <Field label={t("config.encoding")}>
              <input
                className={inputClass}
                value={config.encoding}
                onChange={(e) => updateConfig({ encoding: e.target.value })}
              />
            </Field>
          </>
        )}

        {type === "write_file" && (
          <>
            <Field label={t("config.path")}>
              <input
                className={inputClass}
                value={config.path}
                onChange={(e) => updateConfig({ path: e.target.value })}
              />
            </Field>
            <Field label={t("config.content")}>
              <textarea
                rows={4}
                className={inputClass + " font-mono"}
                value={config.content ?? ""}
                onChange={(e) => updateConfig({ content: e.target.value })}
              />
              <div className="mt-1 text-[11px] text-nexus-muted">
                {t("config.contentHint")}
              </div>
            </Field>
            <Field label={t("config.content_key")}>
              <input
                className={inputClass}
                value={config.content_key}
                onChange={(e) => updateConfig({ content_key: e.target.value })}
              />
            </Field>
            <label className="mb-3 flex items-center gap-2 text-xs">
              <input
                type="checkbox"
                checked={!!config.append}
                onChange={(e) => updateConfig({ append: e.target.checked })}
              />
              <span className="text-nexus-muted">{t("config.append")}</span>
            </label>
          </>
        )}

        {type === "condition" && (
          <Field label={t("config.expression")}>
            <input
              className={inputClass + " font-mono"}
              value={config.expression}
              onChange={(e) => updateConfig({ expression: e.target.value })}
            />
          </Field>
        )}

        {type === "log" && (
          <>
            <Field label={t("config.message")}>
              <input
                className={inputClass}
                value={config.message}
                onChange={(e) => updateConfig({ message: e.target.value })}
              />
            </Field>
            <Field label={t("config.level")}>
              <select
                className={inputClass}
                value={config.level}
                onChange={(e) => updateConfig({ level: e.target.value })}
              >
                <option value="info">info</option>
                <option value="warning">warning</option>
                <option value="error">error</option>
              </select>
            </Field>
          </>
        )}

        {type === "custom_code" && (
          <>
            <Field label={t("config.script_name")}>
              <input
                className={inputClass + " font-mono"}
                value={config.script_name}
                onChange={(e) => updateConfig({ script_name: e.target.value })}
              />
            </Field>
            <Field label={t("config.entry_point")}>
              <input
                className={inputClass + " font-mono"}
                value={config.entry_point}
                onChange={(e) => updateConfig({ entry_point: e.target.value })}
              />
            </Field>
            <ParamsField config={config} updateConfig={updateConfig} />
          </>
        )}

        {type === "expression" && (
          <Field label={t("config.expression")}>
            <input
              className={inputClass + " font-mono"}
              value={config.expression}
              onChange={(e) => updateConfig({ expression: e.target.value })}
            />
          </Field>
        )}
      </div>

      <button
        type="button"
        onClick={() => onDelete(node.id)}
        className="mt-4 rounded border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-xs font-semibold text-rose-300 hover:bg-rose-500/20"
      >
        {t("config.delete")}
      </button>
    </aside>
  );
}

function InitialDataField({ config, updateConfig }) {
  const { t } = useTranslation();
  const [text, setText] = useState(() =>
    JSON.stringify(config.initial_data ?? {}, null, 2)
  );
  const [error, setError] = useState(null);

  // Якщо вибраний інший вузол manual_trigger — синхронізуємо textarea.
  useEffect(() => {
    setText(JSON.stringify(config.initial_data ?? {}, null, 2));
    setError(null);
  }, [config.initial_data]);

  const onChange = (e) => {
    const v = e.target.value;
    setText(v);
    try {
      const parsed = JSON.parse(v);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        setError(null);
        updateConfig({ initial_data: parsed });
      } else {
        setError(t("config.invalidJson"));
      }
    } catch {
      setError(t("config.invalidJson"));
    }
  };

  return (
    <Field label={t("config.initial_data")}>
      <textarea
        rows={5}
        value={text}
        onChange={onChange}
        className={inputClass + " font-mono"}
      />
      {error && <div className="mt-1 text-rose-400">{error}</div>}
    </Field>
  );
}

function ParamsField({ config, updateConfig }) {
  const { t } = useTranslation();
  const [text, setText] = useState(() =>
    JSON.stringify(config.params ?? {}, null, 2)
  );
  const [error, setError] = useState(null);

  useEffect(() => {
    setText(JSON.stringify(config.params ?? {}, null, 2));
    setError(null);
  }, [config.params]);

  const onChange = (e) => {
    const v = e.target.value;
    setText(v);
    try {
      const parsed = JSON.parse(v);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        setError(null);
        updateConfig({ params: parsed });
      } else {
        setError(t("config.invalidJson"));
      }
    } catch {
      setError(t("config.invalidJson"));
    }
  };

  return (
    <Field label={t("config.params")}>
      <textarea
        rows={4}
        value={text}
        onChange={onChange}
        className={inputClass + " font-mono"}
      />
      {error && <div className="mt-1 text-rose-400">{error}</div>}
    </Field>
  );
}
