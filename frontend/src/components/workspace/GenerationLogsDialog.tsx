/**
 * Generation logs dialog with batch filtering.
 */
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

type GenLog = {
  id: string;
  created_at: string | null;
  level: string;
  event: string;
  chapter_no: number | null;
  message: string;
  meta: Record<string, unknown> | null;
};

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  logs: GenLog[];
  logBusy: boolean;
  logViewMode: "all" | "batch";
  onViewModeChange: (mode: "all" | "batch") => void;
  logBatchId: string;
  onBatchIdChange: (v: string) => void;
  logOnlyError: boolean;
  onOnlyErrorChange: (v: boolean) => void;
  onRefresh: () => void;
  onClear: () => void;
  refreshStatus: string;
  refreshProgress: number;
  refreshBatchId: string;
  refreshStartedAt: string | null;
  refreshUpdatedAt: string | null;
  refreshElapsedSeconds: number | null;
  latestRefreshVersion: number | null;
  refreshLastMessage: string;
  formatUtc8: (iso: string | null | undefined) => string;
  formatDuration: (seconds: number | null | undefined) => string;
  summarizeLogMeta: (event: string, meta: Record<string, unknown>) => { summary: string[]; detail?: string };
};

export function GenerationLogsDialog({
  open,
  onOpenChange,
  logs,
  logBusy,
  logViewMode,
  onViewModeChange,
  logBatchId,
  onBatchIdChange,
  logOnlyError,
  onOnlyErrorChange,
  onRefresh,
  onClear,
  refreshStatus,
  refreshProgress,
  refreshBatchId,
  refreshStartedAt,
  refreshUpdatedAt,
  refreshElapsedSeconds,
  latestRefreshVersion,
  refreshLastMessage,
  formatUtc8,
  formatDuration,
  summarizeLogMeta,
}: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-4xl overflow-hidden">
        <DialogHeader>
          <div className="flex items-center justify-between gap-4 mr-8">
            <div className="min-w-0 flex-1">
              <DialogTitle className="text-xl font-bold">章节生成日志</DialogTitle>
              <DialogDescription className="text-foreground/80 dark:text-muted-foreground font-medium">
                支持按任务批次过滤，避免页面被日志持续撑长。
              </DialogDescription>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={onClear}
              className="text-destructive font-bold hover:bg-destructive/10 hover:text-destructive shrink-0"
            >
              清空日志
            </Button>
          </div>
        </DialogHeader>
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex overflow-hidden rounded-2xl border border-border bg-background p-1">
              <button
                type="button"
                className={`rounded-xl px-3 py-1.5 text-xs transition-all font-bold ${
                  logViewMode === "all" ? "bg-primary/15 text-foreground shadow-sm" : "bg-transparent text-foreground/60 dark:text-muted-foreground"
                }`}
                onClick={() => onViewModeChange("all")}
              >
                全部
              </button>
              <button
                type="button"
                className={`rounded-xl px-3 py-1.5 text-xs transition-all font-bold ${
                  logViewMode === "batch" ? "bg-primary/15 text-foreground shadow-sm" : "bg-transparent text-foreground/60 dark:text-muted-foreground"
                }`}
                onClick={() => onViewModeChange("batch")}
              >
                当前批次
              </button>
            </div>
            <input
              value={logBatchId}
              onChange={(e) => onBatchIdChange(e.target.value)}
              placeholder="可填批次编号手动过滤"
              className="field-shell h-10 w-full md:w-80 text-foreground font-bold placeholder:text-foreground/30"
              disabled={logViewMode !== "batch"}
            />
            <label className="inline-flex items-center gap-2 text-xs text-foreground/70 dark:text-muted-foreground font-bold cursor-pointer">
              <input
                type="checkbox"
                checked={logOnlyError}
                onChange={(e) => onOnlyErrorChange(e.target.checked)}
              />
              仅看错误
            </label>
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="font-bold"
              disabled={logBusy}
              onClick={onRefresh}
            >
              {logBusy ? "刷新中…" : "刷新日志"}
            </Button>
          </div>
          <div className="glass-panel-subtle p-3">
            <div className="mb-1 flex items-center justify-between text-xs font-bold text-foreground/80">
              <span>
                记忆刷新进度：{refreshStatus === "queued"
                  ? "已入队"
                  : refreshStatus === "started"
                    ? "执行中"
                    : refreshStatus === "done"
                      ? "已完成"
                      : refreshStatus === "failed"
                        ? "失败"
                        : "空闲"}
              </span>
              <span>{refreshProgress}%</span>
            </div>
            <div className="h-2.5 w-full rounded-full bg-muted/80">
              <div
                className={`h-2.5 rounded-full transition-all duration-500 ${
                  refreshStatus === "failed" ? "bg-destructive" : "bg-primary"
                }`}
                style={{ width: `${Math.max(0, Math.min(100, refreshProgress))}%` }}
              />
            </div>
            <p className="mt-1 text-[11px] text-foreground/60 dark:text-muted-foreground font-medium">
              任务批次：{refreshBatchId || "-"} · 开始：{formatUtc8(refreshStartedAt)} · 更新时间：
              {formatUtc8(refreshUpdatedAt)}
            </p>
            <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium">
              已运行时长：{formatDuration(refreshElapsedSeconds)} · 最近成功版本：
              {latestRefreshVersion == null ? "-" : `v${latestRefreshVersion}`}
            </p>
            {refreshLastMessage ? (
              <p className="text-[11px] text-foreground/70 dark:text-muted-foreground font-bold italic">{refreshLastMessage}</p>
            ) : null}
          </div>
          <div className="soft-scroll max-h-[55vh] overflow-auto rounded-lg border border-border bg-muted p-3 font-mono text-xs">
            {logs.length === 0 ? (
              <p className="text-foreground/50 dark:text-muted-foreground italic">
                暂无日志。点击"自动续写"或"审定通过"后可在此查看过程细节。
              </p>
            ) : (
              logs.map((l) => {
                const metaView = summarizeLogMeta(l.event, l.meta || {});
                return (
                  <div
                    key={l.id}
                    className="border-b border-border/50 py-3 last:border-b-0"
                  >
                    <div className="font-medium">
                      <span className="text-foreground/50 dark:text-muted-foreground">
                        [{formatUtc8(l.created_at)}] [{l.level === 'error' ? '错误' : l.level === 'warning' ? '警告' : '信息'}]
                      </span>{" "}
                      <span className="text-foreground/90 dark:text-inherit">
                        {l.chapter_no ? `第${l.chapter_no}章` : "-"} · {l.message}
                      </span>
                    </div>
                    {metaView.summary.length ? (
                      <div className="mt-2 rounded-2xl border border-border bg-background px-3 py-2 text-[11px] text-foreground/90 font-medium">
                        {metaView.summary.map((item, idx) => (
                          <p key={`${l.id}-summary-${idx}`}>{item}</p>
                        ))}
                      </div>
                    ) : null}
                    {metaView.detail ? (
                      <details className="mt-2 rounded-2xl border border-border bg-background/40 px-3 py-2">
                        <summary className="cursor-pointer text-[11px] text-foreground/60 dark:text-muted-foreground font-bold">
                          查看技术详情
                        </summary>
                        <pre className="mt-2 whitespace-pre-wrap text-[11px] text-foreground/70 dark:text-muted-foreground">
                          {metaView.detail}
                        </pre>
                      </details>
                    ) : null}
                  </div>
                );
              })
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
