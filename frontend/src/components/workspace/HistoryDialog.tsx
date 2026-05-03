/**
 * Memory version history dialog for rollback.
 */
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { parseBackendUtcIso } from "@/lib/date";
import { diffChangedTypes } from "@/lib/workspaceUtils";

type HistoryEntry = {
  version: number;
  summary: string;
  created_at: string | null;
  diff_summary?: { summary?: { changed_types?: string[] } };
  source_summary?: { chapter_nos?: number[] };
};

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  entries: HistoryEntry[];
  onRollback: (version: number) => void;
};

export function HistoryDialog({ open, onOpenChange, entries, onRollback }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto text-foreground">
        <DialogHeader>
          <DialogTitle className="text-left text-base leading-snug">
            记忆版本历史
          </DialogTitle>
          <DialogDescription>
            选择一个历史版本进行回退。回退操作会产生一个包含该版本内容的新快照，并覆盖当前结构化记忆表。
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 py-2">
          {entries.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">暂无历史记录</p>
          ) : (
            entries.map((item) => (
              <div
                key={item.version}
                className="flex items-center justify-between gap-4 rounded-lg border border-border/50 bg-background/40 p-4 transition-all hover:border-primary/30 hover:bg-background"
              >
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-primary">v{item.version}</span>
                    <span className="text-[10px] text-muted-foreground">
                      {item.created_at
                        ? parseBackendUtcIso(item.created_at).toLocaleString("zh-CN", {
                            timeZone: "Asia/Shanghai",
                          })
                        : "-"}
                    </span>
                  </div>
                  <p className="line-clamp-2 text-xs text-muted-foreground">
                    {item.summary || "（无摘要）"}
                  </p>
                  <div className="flex flex-wrap gap-2 pt-1">
                    {diffChangedTypes(item.diff_summary as never).slice(0, 4).map((tag) => (
                      <span
                        key={`history-tag-${item.version}-${tag}`}
                        className="rounded-full border border-primary/15 bg-primary/8 px-2 py-0.5 text-[10px] font-medium text-primary/90"
                      >
                        {tag}
                      </span>
                    ))}
                    {item.source_summary?.chapter_nos?.length ? (
                      <span className="rounded-full border border-border bg-background px-2 py-0.5 text-[10px] text-muted-foreground">
                        来源章：{item.source_summary.chapter_nos.slice(0, 4).join(" / ")}
                      </span>
                    ) : null}
                  </div>
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-8 shrink-0"
                  onClick={() => onRollback(item.version)}
                >
                  回退到此版本
                </Button>
              </div>
            ))
          )}
        </div>
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
          >
            取消
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
