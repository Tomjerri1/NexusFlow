import {
  createContext,
  createElement,
  useContext,
  useEffect,
  useState,
} from "react";
import { fetchNodesSchema } from "./api.js";

// React-контекст із JSON-маніфестом усіх вузлів (`/api/nodes/schema`).
// Динамічний UI рендерить порти зі schema, замість того щоб мати їх hardcoded.

const NodeSchemaContext = createContext({
  schemas: {},
  loading: true,
  error: null,
});

export function NodeSchemaProvider({ children }) {
  const [state, setState] = useState({ schemas: {}, loading: true, error: null });

  useEffect(() => {
    let cancelled = false;
    fetchNodesSchema()
      .then((body) => {
        if (cancelled) return;
        const map = {};
        for (const node of body.nodes || []) {
          map[node.type_name] = node;
        }
        setState({ schemas: map, loading: false, error: null });
      })
      .catch((err) => {
        if (cancelled) return;
        setState({ schemas: {}, loading: false, error: String(err.message || err) });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return createElement(NodeSchemaContext.Provider, { value: state }, children);
}

export function useNodeSchemas() {
  return useContext(NodeSchemaContext);
}

// Чи має воркфлоу хоча б один static-зв'язок — тоді редагування ліній блокується.
export function hasReadonlyConnections(schemaMap, nodeTypes) {
  for (const type of nodeTypes) {
    const schema = schemaMap[type];
    if (schema?.static_connections?.some((c) => c.is_readonly)) return true;
  }
  return false;
}
