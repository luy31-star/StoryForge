import type { NodeTypes } from "reactflow";
import { WorkflowNode } from "@/components/agents/WorkflowNode";
import type { WorkflowNodeType } from "@/types/workflow";

const types: WorkflowNodeType[] = [
  "audio-input",
  "text-input",
  "url-input",
  "voice-synthesis",
  "voice-clone",
  "voice-blend",
  "character-setup",
  "seedance-video",
  "scene-config",
  "gemini-chat",
  "user-input",
  "decision-gate",
  "output",
];

export const workflowNodeTypes: NodeTypes = types.reduce((acc, t) => {
  acc[t] = WorkflowNode;
  return acc;
}, {} as NodeTypes);
