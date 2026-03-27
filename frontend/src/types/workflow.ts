import type { Edge, Node } from "reactflow";

export type InputNodeType = "audio-input" | "text-input" | "url-input";

export type VoiceNodeType =
  | "voice-synthesis"
  | "voice-clone"
  | "voice-blend";

export type VideoNodeType =
  | "seedance-video"
  | "character-setup"
  | "scene-config";

export type ConversationNodeType =
  | "gemini-chat"
  | "user-input"
  | "decision-gate";

export type OutputNodeType = "output";

export type WorkflowNodeType =
  | InputNodeType
  | VoiceNodeType
  | VideoNodeType
  | ConversationNodeType
  | OutputNodeType;

export interface InputNodeData {
  title: string;
  content?: string;
  metadata?: {
    duration?: number;
    format?: string;
    quality?: string;
  };
  [key: string]: unknown;
}

export interface VoiceNodeData {
  title: string;
  voiceModel?: string;
  text?: string;
  referenceVoices?: string[];
  settings?: {
    pitch: number;
    speed: number;
    emotion: string;
    style: string;
  };
  [key: string]: unknown;
}

export interface VideoNodeData {
  title: string;
  characterImage?: string;
  sceneSettings?: {
    background: string;
    lighting: string;
    cameraAngle: string;
  };
  lipSyncSettings?: {
    precision: number;
    emotionIntensity: number;
  };
  quality?: string;
  resolution?: string;
  [key: string]: unknown;
}

export interface ConversationNodeData {
  title: string;
  systemPrompt?: string;
  model?: string;
  autoNext?: boolean;
  conversation?: Message[];
  [key: string]: unknown;
}

export interface OutputNodeData {
  title: string;
  format?: string;
  [key: string]: unknown;
}

export type WorkflowNodeData =
  | InputNodeData
  | VoiceNodeData
  | VideoNodeData
  | ConversationNodeData
  | OutputNodeData;

export interface Message {
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: string;
  metadata?: Record<string, unknown>;
}

export type WorkflowNode = Node<WorkflowNodeData, WorkflowNodeType>;
export type WorkflowEdge = Edge;

export interface WorkflowTemplate {
  id: string;
  name: string;
  description: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
}
