import { useState } from "react";
import { Sparkles, AlertTriangle, MonitorPlay, ServerCog } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

export type ContinueWriteDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  safeGenerateCount: number;
  useColdRecall: boolean;
  coldRecallItems: number;
  busy: boolean;
  onConfirm: (mode: "async" | "stream") => void | Promise<void>;
};

export function ContinueWriteDialog({
  open,
  onOpenChange,
  safeGenerateCount,
  useColdRecall,
  coldRecallItems,
  busy,
  onConfirm,
}: ContinueWriteDialogProps) {
  const [mode, setMode] = useState<"async" | "stream">("async");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <div className="mb-2 flex items-center gap-2 text-amber-500">
            <div className="flex h-9 w-9 items-center justify-center rounded-2xl border border-amber-500/30 bg-amber-500/10">
              <Sparkles className="h-4 w-4" />
            </div>
            <span className="text-xs font-medium uppercase tracking-[0.18em]">
              AI 续写确认
            </span>
          </div>
          <DialogTitle>确认续写 {safeGenerateCount} 章？</DialogTitle>
          <DialogDescription className="leading-6">
            选择你想要的创作模式。在线生成可以实时看到进度并在每章完成后调整，异步任务则会在后台静默完成。
          </DialogDescription>
        </DialogHeader>

        <div className="grid grid-cols-2 gap-4 my-2">
          <div
            className={`cursor-pointer rounded-xl border p-4 transition-all ${
              mode === "stream"
                ? "border-emerald-500 bg-emerald-500/10"
                : "border-border hover:bg-muted"
            }`}
            onClick={() => setMode("stream")}
          >
            <div className="flex items-center gap-2 font-bold mb-1">
              <MonitorPlay className={`h-4 w-4 ${mode === "stream" ? "text-emerald-500" : "text-muted-foreground"}`} />
              <span className={mode === "stream" ? "text-emerald-500" : ""}>在线流式生成</span>
            </div>
            <p className="text-xs text-muted-foreground leading-relaxed">
              沉浸式体验：章节卡和正文一章章实时生成，每章完成时可随时确认或修改，适合精细打磨。
            </p>
          </div>
          <div
            className={`cursor-pointer rounded-xl border p-4 transition-all ${
              mode === "async"
                ? "border-amber-500 bg-amber-500/10"
                : "border-border hover:bg-muted"
            }`}
            onClick={() => setMode("async")}
          >
            <div className="flex items-center gap-2 font-bold mb-1">
              <ServerCog className={`h-4 w-4 ${mode === "async" ? "text-amber-500" : "text-muted-foreground"}`} />
              <span className={mode === "async" ? "text-amber-500" : ""}>后台异步任务</span>
            </div>
            <p className="text-xs text-muted-foreground leading-relaxed">
              全自动体验：所有章节放入后台排队生成，无需人工干预。关闭页面也不会中断。
            </p>
          </div>
        </div>

        <div className="rounded-lg border border-border bg-muted p-4">
          <div className="mb-2 flex items-center gap-2 text-xs font-medium text-foreground">
            <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />
            执行前提示
          </div>
          <div className="space-y-1.5 text-sm text-muted-foreground">
            <p>- 顺序：缺卷剧情则补卷剧情 → 缺章计划则补章计划 → 生成正文。</p>
            <p>
              - {useColdRecall
                ? `当前已开启冷层召回，最多附带 ${coldRecallItems} 条历史记忆。`
                : "当前仅使用热层记忆；如果章节跨度较大，可考虑开启冷层召回。"}
            </p>
          </div>
        </div>

        <DialogFooter className="gap-2 sm:gap-2">
          <Button
            type="button"
            variant="outline"
            disabled={busy}
            onClick={() => onOpenChange(false)}
          >
            暂不执行
          </Button>
          <Button type="button" disabled={busy} onClick={() => void onConfirm(mode)}>
            {busy ? "处理中…" : "确认开始续写"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
