import { Extension } from "@tiptap/core";
// This is a TipTap font size extension. It is not included in the base package
// (TipTap intentionally does not include all minor format tags in the starter kit).
// Technically, this isn’t a separate Mark, but an extension of `textStyle` with an additional
// `fontSize` attribute. Thanks to `addGlobalAttributes`, we can apply
// `style=“font-size: …”` specifically to the `<span data-text-style>` spans
// created by `@tiptap/extension-text-style`. This means:
//  • the size is stored in the same span as `font-family`/`color`,
//    rather than generating nested `font` tags (as the old `execCommand` did);
//  • `editor.getAttributes(‘textStyle’).fontSize` immediately returns the current
//    value for synchronizing the <select> in the toolbar.
const FontSize = Extension.create({
  name: "fontSize",

  addOptions() {
    return {
      // For which tag types to apply the attribute. textStyle — a standard wrapper
      // from @tiptap/extension-text-style, which we load into NoteNode.
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
      // We accept pre-defined CSS units (“14px”, “1.2em”, …) — to give
      // the user flexibility and avoid having to create multiple formatters in different parts of the code.
      setFontSize:
        (fontSize) =>
        ({ chain }) =>
          chain().setMark("textStyle", { fontSize }).run(),
      unsetFontSize:
        () =>
        ({ chain }) =>
          chain()
            .setMark("textStyle", { fontSize: null })
            // Removes the empty <span> if it was the last textStyle attribute.
            .removeEmptyTextStyle()
            .run(),
    };
  },
});

export default FontSize;
