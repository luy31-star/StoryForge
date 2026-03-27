import { memo, useCallback } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import type { WorkflowNodeType } from "@/types/workflow";

const nodeCategories: {
  name: string;
  nodes: { type: WorkflowNodeType; icon: string; name: string }[];
}[] = [
  {
    name: "输入",
    nodes: [
      { type: "audio-input", icon: "🎵", name: "音频输入" },
      { type: "text-input", icon: "📝", name: "文本输入" },
      { type: "url-input", icon: "🔗", name: "URL输入" },
    ],
  },
  {
    name: "声音处理",
    nodes: [
      { type: "voice-synthesis", icon: "🗣️", name: "语音合成" },
      { type: "voice-clone", icon: "👥", name: "声音克隆" },
      { type: "voice-blend", icon: "🎭", name: "声音融合" },
    ],
  },
  {
    name: "视频生成",
    nodes: [
      { type: "character-setup", icon: "👤", name: "角色设定" },
      { type: "seedance-video", icon: "🎬", name: "视频生成" },
      { type: "scene-config", icon: "🎪", name: "场景配置" },
    ],
  },
  {
    name: "AI对话",
    nodes: [
      { type: "gemini-chat", icon: "🤖", name: "Gemini对话" },
      { type: "user-input", icon: "👨‍💼", name: "用户输入" },
      { type: "decision-gate", icon: "🚦", name: "决策节点" },
    ],
  },
  {
    name: "输出",
    nodes: [{ type: "output", icon: "📤", name: "最终输出" }],
  },
];

function onDragStart(
  event: React.DragEvent,
  nodeType: WorkflowNodeType,
  label: string
) {
  event.dataTransfer.setData(
    "application/reactflow",
    JSON.stringify({ type: nodeType, label })
  );
  event.dataTransfer.effectAllowed = "move";
}

const NodePaletteItem = memo(function NodePaletteItem({
  type,
  icon,
  label,
}: {
  type: WorkflowNodeType;
  icon: string;
  label: string;
}) {
  const drag = useCallback(
    (e: React.DragEvent) => onDragStart(e, type, label),
    [type, label]
  );
  return (
    <div
      draggable
      onDragStart={drag}
      className={cn(
        "flex cursor-grab items-center gap-2 rounded-md border border-border bg-secondary/40 px-2 py-2 text-sm",
        "hover:bg-secondary/80 active:cursor-grabbing"
      )}
    >
      <span className="text-lg" aria-hidden>
        {icon}
      </span>
      <span className="font-medium">{label}</span>
    </div>
  );
});

export function NodePanel() {
  return (
    <aside className="flex w-72 shrink-0 flex-col border-r border-border bg-card/50">
      <div className="border-b border-border p-4">
        <h2 className="text-sm font-semibold tracking-tight">节点库</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          拖拽节点到画布以添加
        </p>
      </div>
      <ScrollArea className="flex-1 px-3 py-3">
        {nodeCategories.map((category, idx) => (
          <div key={category.name} className="mb-2">
            <div className="mb-2 text-xs font-medium uppercase text-muted-foreground">
              {category.name}
            </div>
            <div className="space-y-1.5">
              {category.nodes.map((n) => (
                <NodePaletteItem
                  key={n.type}
                  type={n.type}
                  icon={n.icon}
                  label={n.name}
                />
              ))}
            </div>
            {idx < nodeCategories.length - 1 ? (
              <Separator className="mt-4 bg-border" />
            ) : null}
          </div>
        ))}
      </ScrollArea>
    </aside>
  );
}
