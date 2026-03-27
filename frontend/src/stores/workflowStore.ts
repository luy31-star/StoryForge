import {
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
} from "reactflow";
import { create } from "zustand";
import type { WorkflowNodeData, WorkflowNodeType } from "@/types/workflow";

export interface WorkflowState {
  nodes: Node<WorkflowNodeData, WorkflowNodeType>[];
  edges: Edge[];
  selectedNodeId: string | null;
  workflowId: string | null;
  setWorkflowId: (id: string | null) => void;
  setSelectedNodeId: (id: string | null) => void;
  onNodesChange: (changes: NodeChange[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  onConnect: (connection: Connection) => void;
  addNode: (node: Node<WorkflowNodeData, WorkflowNodeType>) => void;
  updateNodeData: (
    id: string,
    data: Partial<WorkflowNodeData>
  ) => void;
  loadGraph: (nodes: Node<WorkflowNodeData, WorkflowNodeType>[], edges: Edge[]) => void;
  clear: () => void;
}

const initialNodes: Node<WorkflowNodeData, WorkflowNodeType>[] = [];
const initialEdges: Edge[] = [];

export const useWorkflowStore = create<WorkflowState>((set, get) => ({
  nodes: initialNodes,
  edges: initialEdges,
  selectedNodeId: null,
  workflowId: null,
  setWorkflowId: (workflowId) => set({ workflowId }),
  setSelectedNodeId: (selectedNodeId) => set({ selectedNodeId }),
  onNodesChange: (changes) => {
    set({
      nodes: applyNodeChanges(changes, get().nodes) as Node<
        WorkflowNodeData,
        WorkflowNodeType
      >[],
    });
    if (changes.some((c) => c.type === "remove")) {
      const removed = changes.filter((c) => c.type === "remove");
      const removedIds = new Set(removed.map((c) => c.id));
      if (get().selectedNodeId && removedIds.has(get().selectedNodeId!)) {
        set({ selectedNodeId: null });
      }
    }
  },
  onEdgesChange: (changes) =>
    set({
      edges: applyEdgeChanges(changes, get().edges),
    }),
  onConnect: (connection) =>
    set({
      edges: addEdge(
        { ...connection, animated: true, style: { strokeWidth: 2 } },
        get().edges
      ),
    }),
  addNode: (node) =>
    set({
      nodes: [...get().nodes, node],
    }),
  updateNodeData: (id, data) =>
    set({
      nodes: get().nodes.map((n) =>
        n.id === id
          ? { ...n, data: { ...n.data, ...data } as WorkflowNodeData }
          : n
      ),
    }),
  loadGraph: (nodes, edges) => set({ nodes, edges, selectedNodeId: null }),
  clear: () =>
    set({
      nodes: [],
      edges: [],
      selectedNodeId: null,
      workflowId: null,
    }),
}));
