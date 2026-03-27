import { useMemo } from "react";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { useAgentStore } from "@/stores/agentStore";
import { useWorkflowStore } from "@/stores/workflowStore";
import type { WorkflowNodeData } from "@/types/workflow";

export function PropertiesPanel() {
  const selectedNodeId = useWorkflowStore((s) => s.selectedNodeId);
  const nodes = useWorkflowStore((s) => s.nodes);
  const updateNodeData = useWorkflowStore((s) => s.updateNodeData);
  const messagesByNode = useAgentStore((s) => s.messagesByNode);

  const node = useMemo(
    () => nodes.find((n) => n.id === selectedNodeId) ?? null,
    [nodes, selectedNodeId]
  );

  const title =
    node && typeof node.data.title === "string"
      ? node.data.title
      : "";

  if (!node) {
    return (
      <aside className="flex w-80 shrink-0 flex-col border-l border-border bg-card/50 p-4">
        <h2 className="text-sm font-semibold">属性</h2>
        <p className="mt-2 text-xs text-muted-foreground">
          在画布上选择一个节点以编辑属性或与 Agent 对话。
        </p>
      </aside>
    );
  }

  const messages = messagesByNode[node.id] ?? [];

  return (
    <aside className="flex w-80 shrink-0 flex-col border-l border-border bg-card/50">
      <div className="border-b border-border p-4">
        <h2 className="text-sm font-semibold">属性</h2>
        <p className="mt-0.5 truncate text-xs text-muted-foreground">
          {node.type} · {node.id}
        </p>
      </div>
      <Tabs defaultValue="props" className="flex flex-1 flex-col px-4 pt-3">
        <TabsList className="w-full">
          <TabsTrigger className="flex-1" value="props">
            配置
          </TabsTrigger>
          <TabsTrigger className="flex-1" value="chat">
            对话
          </TabsTrigger>
        </TabsList>
        <TabsContent value="props" className="mt-3 flex-1 overflow-hidden">
          <div className="space-y-3">
            <div>
              <Label htmlFor="node-title">标题</Label>
              <Input
                id="node-title"
                className="mt-1"
                value={title}
                onChange={(e) =>
                  updateNodeData(node.id, {
                    title: e.target.value,
                  } as Partial<WorkflowNodeData>)
                }
              />
            </div>
            <Separator />
            <p className="text-xs text-muted-foreground">
              更多字段（语音参数、场景、Gemini 提示词等）将在后续阶段与后端 API
              联动。
            </p>
          </div>
        </TabsContent>
        <TabsContent value="chat" className="mt-3 flex flex-1 flex-col overflow-hidden">
          <ScrollArea className="h-[min(420px,50vh)] rounded-md border border-border p-2">
            {messages.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                暂无对话。执行工作流或接入 WebSocket 后将在此显示多轮对话。
              </p>
            ) : (
              <ul className="space-y-2 text-xs">
                {messages.map((m, i) => (
                  <li
                    key={`${m.timestamp}-${i}`}
                    className="rounded-md bg-muted/50 p-2"
                  >
                    <span className="font-medium text-muted-foreground">
                      {m.role}
                    </span>
                    <div className="mt-1 whitespace-pre-wrap">{m.content}</div>
                  </li>
                ))}
              </ul>
            )}
          </ScrollArea>
        </TabsContent>
      </Tabs>
    </aside>
  );
}
