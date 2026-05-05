import { Extension } from "@tiptap/core";

// Власне TipTap-розширення розміру шрифту. У базовому пакеті його немає
// (TipTap зумисно не включає всі дрібні format-марки у starter-kit).
//
// Технічно це не окремий Mark, а розширення `textStyle` додатковим
// атрибутом `fontSize`. Завдяки `addGlobalAttributes` ми навісом'мо
// `style="font-size: …"` саме на span'и `<span data-text-style>`,
// які створює `@tiptap/extension-text-style`. Це означає:
//  • розмір зберігається у тому самому span'і, що й `font-family`/`color`,
//    а не плодить вкладені <font>-теги (як це робив старий execCommand);
//  • `editor.getAttributes('textStyle').fontSize` одразу повертає поточне
//    значення для синхронізації <select> у тулбарі.
const FontSize = Extension.create({
  name: "fontSize",

  addOptions() {
    return {
      // Для яких типів марок чіпляти атрибут. textStyle — стандартна обгортка
      // зі @tiptap/extension-text-style, її ми завантажуємо у NoteNode.
      types: ["textStyle"],
    };
  },

  addGlobalAttributes() {
    return [
      {
        types: this.options.types,
        attributes: {
          fontSize: {
            default: null,
            parseHTML: (element) =>
              element.style.fontSize?.replace(/['"]+/g, "") || null,
            renderHTML: (attributes) => {
              if (!attributes.fontSize) return {};
              return { style: `font-size: ${attributes.fontSize}` };
            },
          },
        },
      },
    ];
  },

  addCommands() {
    return {
      // Приймаємо вже зібраний CSS-розмір ("14px", "1.2em", …) — щоб дати
      // користувачу гнучкість і не плодити форматерів у різних місцях коду.
      setFontSize:
        (fontSize) =>
        ({ chain }) =>
          chain().setMark("textStyle", { fontSize }).run(),
      unsetFontSize:
        () =>
        ({ chain }) =>
          chain()
            .setMark("textStyle", { fontSize: null })
            // Прибере порожній <span>, якщо це був останній атрибут textStyle.
            .removeEmptyTextStyle()
            .run(),
    };
  },
});

export default FontSize;
