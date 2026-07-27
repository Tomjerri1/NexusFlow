import { NodeResizer, useReactFlow, useStore } from "@xyflow/react";
import { Color } from "@tiptap/extension-color";
import { FontFamily } from "@tiptap/extension-font-family";
import { TextAlign } from "@tiptap/extension-text-align";
import { TextStyle } from "@tiptap/extension-text-style";
import { Underline } from "@tiptap/extension-underline";
import { EditorContent, useEditor } from "@tiptap/react";
import { StarterKit } from "@tiptap/starter-kit";
import { useEffect, useRef } from "react";

import {
  registerNoteEditor,
  unregisterNoteEditor,
} from "../noteEditorBridge.js";
import FontSize from "./FontSize.js";

const MAX_CHARS = 10_000;

// Custom React Flow visual node: post-it style sticker.No handles - does not participate in graph execution.

// Architecture (TipTap edition):Editor - full TipTap (`@tiptap/react`) with a set of extensions,covering formatting of selected text: 
// Bold/Italic/Strike(from StarterKit), Underline, TextAlign, TextStyle, FontFamily, Color,plus our FontSize. 
// All formatting - at the level of ProseMirror marks,so the selection/cursor does not "jump" with each click on the toolbar(the old execCommand implementation had problems with this).
// Data: initial content → from `config.html_content`. 
// Back in React Flowstate we write only to blur - so as not to spam ReactFlow.setNodes()on each character. 
// External update of `html_content` (for example,loading another workflow) overwrites the editor only if itis NOT currently in focus - otherwise we will destroy the input.
// Security: TipTap parses incoming HTML through its schema and automatically discards tags/attributes that are not in the loaded extensions. 
// This is native sanitization - DOMPurify is no longer needed. 
// Bridge: editor registers with `noteEditorBridge` under nodeId so that the ConfigPanel toolbar can reach it and call editor.chain().
export default function NoteNode({ id, data, selected }) {
  const reactFlow = useReactFlow();

  const isDraggable = useStore((state) => state.nodesDraggable);
  const isReadonly = !isDraggable;

  const config = data?.config || {};
  const uiMeta = data?.ui_metadata || {};
  const {
    title = "Примітка",
    html_content = "",
    background_color = "#fef3c7",
    text_color = "#1f2937",
    font_family = "system-ui, sans-serif",
    font_size = 14,
  } = config;
  // width/height are now stored in `ui_metadata` (UI Metadata Pocket).
  // Fallback to the old config — for workflows saved before the ui_metadata feature was introduced.
  const width = uiMeta.width ?? config.width ?? 240;
  const height = uiMeta.height ?? config.height ?? 160;

  // Updating data.config via reactFlow.updateNodeData — a point update
  // of a single node without applying a map to the entire array. Previously, this used setNodes(nodes =>
  // nodes.map(...)) — on large graphs, this caused all nodes to re-render
  // on every keystroke. updateNodeData performs a shallow merge with
  // the existing data, so we manually merge only the nested config object.
  const patchConfig = (patch) => {
    reactFlow.updateNodeData(id, {
      config: { ...(data?.config || {}), ...patch },
    });
  };

  // Same as `patchConfig`, but mutates `data.ui_metadata`—a container for
  // visual/UI-only attributes (sticker size, and in the future: whether
  // groups are collapsed, etc.). The logical `config` remains unchanged, and the engine
  // does not access this field at all.
  const patchUiMetadata = (patch) => {
    reactFlow.updateNodeData(id, {
      ui_metadata: { ...(data?.ui_metadata || {}), ...patch },
    });
  };

  const editor = useEditor({
    editable: !isReadonly,
    extensions: [
      StarterKit,
      Underline,
      TextAlign.configure({ types: ["heading", "paragraph"] }),
      TextStyle,
      FontFamily,
      Color,
      FontSize,
    ],
    content: html_content || "<p></p>",
    editorProps: {
      attributes: {
        // nodrag/nopan REQUIRED - otherwise React Flow catches mouse draginstead of highlighting text. h-full + overflow-auto → editorstretches to the full height given by the flex-1 header below.
        class:
          "nodrag nopan h-full w-full overflow-auto p-3 text-left outline-none",
        spellcheck: "false",
      },
    },
    onBlur: ({ editor: ed }) => {
      const html = ed.getHTML();
      const text = ed.getText();
      if (text.length > MAX_CHARS) return;
      if (html === html_content) return;
      patchConfig({ html_content: html });
    },
    // In TipTap v3, by default the editor tries to render immediately - in the client Vite build it is safe, but we are removing the potential SSR warning.
    immediatelyRender: false,
  });
  useEffect(() => {
    if (editor) {
      editor.setEditable(!isReadonly);
    }
  }, [editor, isReadonly]);

  // We register the editor in the bridge so that ConfigPanel.NoteToolbar can find it.
  useEffect(() => {
    if (!editor) return undefined;
    registerNoteEditor(id, editor);
    return () => {
      unregisterNoteEditor(id);
    };
  }, [editor, id]);

  // External change html_content (load workflow) → overwrite content,but NOT if the editor is in focus (otherwise we will crash the input).
  useEffect(() => {
    if (!editor) return;
    if (editor.isFocused) return;
    const current = editor.getHTML();
    if (current === html_content) return;
    if (current === "<p></p>" && !html_content) return;
    editor.commands.setContent(html_content || "<p></p>", { emitUpdate: false });
  }, [editor, html_content]);

  // Resize: we set width/height in `data.ui_metadata` only on onResizeEnd
  // (during a drag, NodeResizer updates React Flow's `node.style.width/height`
  // live, and our wrapper with w-full/h-full simply follows suit).
  // Previously, this was written in `data.config` — now UI Metadata Pocket keeps
  // the logical config clean of visual attributes.
  const handleResizeEnd = (_evt, params) => {
    if (!params) return;
    const w = Math.round(params.width);
    const h = Math.round(params.height);
    if (w === width && h === height) return;
    patchUiMetadata({ width: w, height: h });
  };

  return (
    <div
      className={
        "relative flex h-full w-full flex-col overflow-hidden rounded-md shadow-md transition-shadow " +
        (selected ? "ring-2 ring-amber-400" : "")
      }
      style={{
        backgroundColor: background_color,
        color: text_color,
        fontFamily: font_family,
        fontSize: `${font_size}px`,
      }}
    >
      <NodeResizer
        isVisible={selected}
        minWidth={120}
        minHeight={80}
        onResizeEnd={handleResizeEnd}
        lineClassName="!z-50 !border-2 !border-amber-400"
        handleClassName="!z-50 !h-5 !w-5 !rounded !border-2 !border-amber-500 !bg-amber-300"
      />

      {/*
        Header strip - drag zone for React Flow (WITHOUT `nodrag` class). Inline style with HARSH system font and fixed size: changing `font_family`/`font_size` of the sticker should NOT creep into the header (otherwise strangely large/italic smiley-caps would appear in the graph).
      */}
      <div
        className="flex shrink-0 cursor-grab select-none items-center px-2 py-1 font-semibold active:cursor-grabbing"
        style={{
          backgroundColor: "rgba(0, 0, 0, 0.08)",
          fontFamily: "system-ui, sans-serif",
          fontSize: "12px",
        }}
        title={title}
      >
        <span className="truncate">{title}</span>
      </div>

      {/*
        EditorContent - TipTap wrapper over ProseMirror. flex-1 + min-h-0REQUIRED: without `min-h-0` flex-child prevents the innerscrollable-block from shrinking and overflow-auto stops working.
      */}
      <EditorContent
        editor={editor}
        className="flex min-h-0 flex-1 flex-col"
      />
    </div>
  );
}
