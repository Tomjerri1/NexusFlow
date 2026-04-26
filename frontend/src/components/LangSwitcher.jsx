import { SUPPORTED_LANGS, useTranslation } from "../i18n.js";

export default function LangSwitcher() {
  const { lang, setLang } = useTranslation();
  return (
    <div className="flex items-center gap-1 rounded-md border border-nexus-border bg-nexus-panel p-0.5">
      {SUPPORTED_LANGS.map((code) => (
        <button
          key={code}
          type="button"
          onClick={() => setLang(code)}
          className={
            "px-2.5 py-1 text-xs font-medium uppercase rounded " +
            (lang === code
              ? "bg-nexus-accent text-nexus-bg"
              : "text-nexus-muted hover:text-nexus-text")
          }
        >
          {code}
        </button>
      ))}
    </div>
  );
}
