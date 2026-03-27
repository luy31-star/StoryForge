import { create } from "zustand";
import type { Message } from "@/types/workflow";

interface AgentState {
  /** 按节点 ID 存储多轮对话 */
  messagesByNode: Record<string, Message[]>;
  appendMessage: (nodeId: string, message: Message) => void;
  setMessages: (nodeId: string, messages: Message[]) => void;
  clearNode: (nodeId: string) => void;
}

export const useAgentStore = create<AgentState>((set) => ({
  messagesByNode: {},
  appendMessage: (nodeId, message) =>
    set((s) => ({
      messagesByNode: {
        ...s.messagesByNode,
        [nodeId]: [...(s.messagesByNode[nodeId] ?? []), message],
      },
    })),
  setMessages: (nodeId, messages) =>
    set((s) => ({
      messagesByNode: { ...s.messagesByNode, [nodeId]: messages },
    })),
  clearNode: (nodeId) =>
    set((s) => {
      const next = { ...s.messagesByNode };
      delete next[nodeId];
      return { messagesByNode: next };
    }),
}));
