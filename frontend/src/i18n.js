import {
  createContext,
  createElement,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

const STORAGE_KEY = "nexusflow.lang";

export const SUPPORTED_LANGS = ["en", "uk"];

// --- Перекладні словники --------------------------------------------------

export const translations = {
  en: {
    app: {
      title: "NexusFlow",
      subtitle: "Visual workflow editor",
    },
    palette: {
      heading: "Node palette",
      hint: "Drag a node onto the canvas",
      manual_trigger: "Manual trigger",
      read_file: "Read file",
      write_file: "Write file",
      condition: "Condition",
      log: "Log",
      custom_code: "Custom code",
      expression: "Expression",
    },
    // Локалізовані назви вузлів (перекривають schema.info.display_name з бекенду).
    // Якщо ключа нема — UI падає на бекендний display_name, а потім на сирий type_name.
    nodes: {
      manual_trigger: "Manual trigger",
      read_file: "Read file",
      write_file: "Write file",
      condition: "Condition",
      log: "Log",
      custom_code: "Custom code",
      expression: "Expression",
    },
    // Локалізовані категорії (для палітри/підпису). Fallback — сира категорія.
    categories: {
      core: "Core",
      trigger: "Core",
      files: "Files",
      io: "Files",
      logic: "Logic",
      util: "Logic",
      net: "Network",
      general: "General",
    },
    // Локалізовані назви портів. Fallback — оригінальне ім'я порту з бекенду.
    ports: {
      input: "input",
      output: "output",
      data: "data",
      path: "path",
      content: "content",
      size: "size",
      bytes_written: "bytes",
      append: "append",
      expression: "expression",
      result: "result",
      message: "message",
      true: "true",
      false: "false",
      url: "url",
      status: "status",
      body: "body",
    },
    canvas: {
      empty: "Drop nodes here to start building your workflow",
      handleTrue: "true",
      handleFalse: "false",
      readonlyEdges: "Edges are read-only (static connections)",
    },
    config: {
      heading: "Node settings",
      empty: "Select a node to edit its settings",
      id: "ID",
      type: "Type",
      delete: "Delete node",
      initial_data: "Initial data (JSON)",
      path: "Path",
      encoding: "Encoding",
      content: "What to write",
      contentHint: "Plain text. Leave empty to use the input key below.",
      content_key: "Content key",
      append: "Append mode",
      expression: "Expression",
      message: "Message",
      level: "Level",
      invalidJson: "Invalid JSON",
      script_name: "Script (file in scripts/)",
      entry_point: "Entry point (function name)",
      params: "Params (JSON)",
    },
    run: {
      heading: "Run",
      button: "Run workflow",
      running: "Running…",
      jobId: "Job:",
      status: "Status:",
      error: "Error:",
      cantRunEmpty: "Add at least one node before running",
    },
    logs: {
      heading: "Live logs",
      empty: "Logs will stream here after a run",
      done: "Stream finished",
    },
  },
  uk: {
    app: {
      title: "NexusFlow",
      subtitle: "Візуальний редактор сценаріїв",
    },
    palette: {
      heading: "Палітра вузлів",
      hint: "Перетягни вузол на канвас",
      manual_trigger: "Ручний тригер",
      read_file: "Читання файлу",
      write_file: "Запис у файл",
      condition: "Умова",
      log: "Лог",
      custom_code: "Кастомний код",
      expression: "Вираз",
    },
    nodes: {
      manual_trigger: "Ручний тригер",
      read_file: "Читання файлу",
      write_file: "Запис у файл",
      condition: "Умова",
      log: "Лог",
      custom_code: "Кастомний код",
      expression: "Вираз",
    },
    categories: {
      core: "Базові",
      trigger: "Базові",
      files: "Файли",
      io: "Файли",
      logic: "Логіка",
      util: "Логіка",
      net: "Мережа",
      general: "Інше",
    },
    ports: {
      input: "вхід",
      output: "вихід",
      data: "дані",
      path: "шлях",
      content: "вміст",
      size: "розмір",
      bytes_written: "байтів",
      append: "дописати",
      expression: "вираз",
      result: "результат",
      message: "повідомлення",
      true: "так",
      false: "ні",
      url: "URL",
      status: "статус",
      body: "тіло",
    },
    canvas: {
      empty: "Перетягни вузли сюди, щоб почати збирати сценарій",
      handleTrue: "так",
      handleFalse: "ні",
      readonlyEdges: "Зв'язки лише для читання (static connections)",
    },
    config: {
      heading: "Налаштування вузла",
      empty: "Обери вузол, щоб редагувати його параметри",
      id: "ID",
      type: "Тип",
      delete: "Видалити вузол",
      initial_data: "Початкові дані (JSON)",
      path: "Шлях",
      encoding: "Кодування",
      content: "Що записати",
      contentHint: "Звичайний текст. Залиш порожнім, щоб брати з ключа нижче.",
      content_key: "Ключ із вмістом",
      append: "Дописування",
      expression: "Вираз",
      message: "Повідомлення",
      level: "Рівень",
      invalidJson: "Некоректний JSON",
      script_name: "Скрипт (файл у scripts/)",
      entry_point: "Точка входу (назва функції)",
      params: "Параметри (JSON)",
    },
    run: {
      heading: "Запуск",
      button: "Запустити сценарій",
      running: "Виконується…",
      jobId: "Завдання:",
      status: "Статус:",
      error: "Помилка:",
      cantRunEmpty: "Додай хоча б один вузол перед запуском",
    },
    logs: {
      heading: "Логи в реальному часі",
      empty: "Логи з'являться тут після запуску",
      done: "Стрім завершено",
    },
  },
};

// --- Context + Provider (без JSX, щоб .js не вимагав spec-loader) --------

const LangContext = createContext(null);

export function LangProvider(props) {
  const [lang, setLang] = useState(() => {
    if (typeof window === "undefined") return "en";
    const saved = window.localStorage.getItem(STORAGE_KEY);
    return SUPPORTED_LANGS.includes(saved) ? saved : "en";
  });

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY, lang);
    if (typeof document !== "undefined") {
      document.documentElement.lang = lang;
    }
  }, [lang]);

  const value = useMemo(() => ({ lang, setLang }), [lang]);
  return createElement(LangContext.Provider, { value }, props.children);
}

// --- Hook ---------------------------------------------------------------

export function useTranslation() {
  const ctx = useContext(LangContext);
  if (!ctx) {
    throw new Error("useTranslation must be used inside <LangProvider>");
  }
  const { lang, setLang } = ctx;

  const t = (path, fallback) => {
    const parts = path.split(".");
    let cur = translations[lang];
    for (const p of parts) {
      if (cur && typeof cur === "object" && p in cur) {
        cur = cur[p];
      } else {
        return fallback ?? path;
      }
    }
    return typeof cur === "string" ? cur : fallback ?? path;
  };

  return { t, lang, setLang };
}
