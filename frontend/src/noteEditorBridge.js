import { useCallback, useEffect, useState } from "react";

// Bridge between NoteNode (where TipTap instance lives) and ConfigPanel.NoteToolbar
// (where user presses B/I/U/S, chooses font, etc.).
// Implementation — simple module-level Map<nodeId, Editor> + Set<listener>.
// Instead of Zustand or own React-context (it would have to be stretched
// throughout App.jsx) — minimal dependency on nothing but React.
// Contract:
// NoteNode REGISTERS its editor in `useEffect` after creation (and
// UNREGISTERS in cleanup — so that after unmounting there are no
// “ghost” editors for missing stickers);
// ConfigPanel reads the editor via `useNoteEditor(nodeId)` — hook, which
// additionally subscribes to TipTap-events `transaction|selectionUpdate
// |focus|blur` and forces the component to rerender. Without this isActive(),
// getAttributes() would return stale data.

const editors = new Map();
const subscribers = new Set();

function notify() {
  for (const fn of subscribers) {
    fn();
  }
}

export function registerNoteEditor(nodeId, editor) {
  if (!nodeId || !editor) return;
  editors.set(nodeId, editor);
  notify();
}

export function unregisterNoteEditor(nodeId) {
  if (!nodeId) return;
  if (!editors.has(nodeId)) return;
  editors.delete(nodeId);
  notify();
}

export function getNoteEditor(nodeId) {
  if (!nodeId) return null;
  return editors.get(nodeId) ?? null;
}


export function useNoteEditor(nodeId) {
  const [, setVersion] = useState(0);
  const bump = useCallback(() => {

    setVersion((v) => (v + 1) % 1_000_000);
  }, []);


  useEffect(() => {
    subscribers.add(bump);
    return () => {
      subscribers.delete(bump);
    };
  }, [bump]);

  const editor = nodeId ? editors.get(nodeId) ?? null : null;


  useEffect(() => {
    if (!editor) return undefined;
    editor.on("transaction", bump);
    editor.on("selectionUpdate", bump);
    editor.on("focus", bump);
    editor.on("blur", bump);
    return () => {
      editor.off("transaction", bump);
      editor.off("selectionUpdate", bump);
      editor.off("focus", bump);
      editor.off("blur", bump);
    };
  }, [editor, bump]);

  return editor;
}
