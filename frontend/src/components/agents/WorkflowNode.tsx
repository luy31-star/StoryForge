import { memo } from "react";
import { Handle, Position, type NodeProps } from "reactflow";
import { cn } from "@/lib/utils";
import type { WorkflowNodeData, WorkflowNodeType } from "@/types/workflow";

const categoryStyles: Record<string, string> = {
  input: "border-emerald-500/50 bg-emerald-950/40",
  voice: "border-violet-500/50 bg-violet-950/40",
  video: "border-sky-500/50 bg-sky-950/40",
  chat: "border-amber-500/50 bg-amber-950/40",
  output: "border-rose-500/50 bg-rose-950/40",
};

function categoryForType(type: WorkflowNodeType): keyof typeof categoryStyles {
  if (
    type === "audio-input" ||
    type === "text-input" ||
    type === "url-input"
  ) {
    return "input";
  }
  if (
    type === "voice-synthesis" ||
    type === "voice-clone" ||
    type === "voice-blend"
  ) {
    return "voice";
  }
  if (
    type === "seedance-video" ||
    type === "character-setup" ||
    type === "scene-config"
  ) {
    return "video";
  }
  if (
    type === "gemini-chat" ||
    type === "user-input" ||
    type === "decision-gate"
  ) {
    return "chat";
  }
  return "output";
}

function WorkflowNodeInner({
  data,
  type,
  selected,
}: NodeProps<WorkflowNodeData>) {
  const cat = categoryForType(type as WorkflowNodeType);
  const title =
    typeof data.title === "string" ? data.title : (type as string);

  return (
    <div
      className={cn(
        "min-w-[180px] max-w-[240px] rounded-lg border-2 px-3 py-2 shadow-md transition-shadow",
        categoryStyles[cat],
        selected && "ring-2 ring-ring ring-offset-2 ring-offset-background"
      )}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!h-2.5 !w-2.5 !border-2 !bg-background"
      />
      <div className="text-xs font-medium text-muted-foreground">
        {String(type)}
      </div>
      <div className="truncate text-sm font-semibold text-foreground">
        {title}
      </div>
      <Handle
        type="source"
        position={Position.Right}
        className="!h-2.5 !w-2.5 !border-2 !bg-background"
      />
    </div>
  );
}

export const WorkflowNode = memo(WorkflowNodeInner);
