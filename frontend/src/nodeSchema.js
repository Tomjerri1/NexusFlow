import {
  createContext,
  createElement,
  useContext,
  useEffect,
  useState,
} from "react";
import { fetchNodesSchema } from "./api.js";

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

// Does the workflow have at least one static link? If so, editing the lines is blocked.
export function hasReadonlyConnections(schemaMap, nodeTypes) {
  for (const type of nodeTypes) {
    const schema = schemaMap[type];
    if (schema?.static_connections?.some((c) => c.is_readonly)) return true;
  }
  return false;
}
