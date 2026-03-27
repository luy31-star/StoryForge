import { LayoutTemplate, Play, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { geminiSeedanceTemplate } from "@/data/templates";
import { useWorkflowStore } from "@/stores/workflowStore";

export function Toolbar() {
  const loadGraph = useWorkflowStore((s) => s.loadGraph);
  const clear = useWorkflowStore((s) => s.clear);
  const workflowId = useWorkflowStore((s) => s.workflowId);

  const loadTemplate = () => {
    loadGraph(
      geminiSeedanceTemplate.nodes as Parameters<typeof loadGraph>[0],
      geminiSeedanceTemplate.edges
    );
    useWorkflowStore.getState().setWorkflowId(geminiSeedanceTemplate.id);
  };

  return (
    <div className="flex items-center gap-2 rounded-lg border border-border bg-card/95 px-2 py-1.5 shadow-lg backdrop-blur">
      <span className="px-2 text-xs font-medium text-muted-foreground">
        VocalFlow Studio
      </span>
      {workflowId ? (
        <span className="max-w-[140px] truncate text-xs text-muted-foreground">
          {workflowId}
        </span>
      ) : null}
      <Button type="button" variant="secondary" size="sm" onClick={loadTemplate}>
        <LayoutTemplate className="size-4" />
        加载 Gemini + SeeDance 模板
      </Button>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => {
          void fetch("/api/workflow/execute-demo", { method: "POST" }).catch(
            () => undefined
          );
        }}
      >
        <Play className="size-4" />
        试运行（需后端）
      </Button>
      <Button type="button" variant="ghost" size="sm" onClick={clear}>
        <Trash2 className="size-4" />
        清空
      </Button>
    </div>
  );
}
