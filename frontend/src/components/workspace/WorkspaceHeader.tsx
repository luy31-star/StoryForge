/**
 * Workspace header with title, stats grid, and action buttons.
 */
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";

type Props = {
  novelId: string;
  novel: Record<string, unknown> | null;
  titleDraft: string;
  onTitleDraftChange: (v: string) => void;
  busy: boolean;
  titleBusy: boolean;
  err: string | null;
  notice: React.ReactNode;
  workspaceStageLabel: string;
  chaptersCount: number;
  latestChapterNo: number | null;
  approvedChapterCount: number;
  draftChapterCount: number;
  activeMemoryLines: number;
  onSaveTitle: () => void;
  onOpenSettings: () => void;
  onOpenLogs: () => void;
};

export function WorkspaceHeader({
  novelId,
  novel,
  titleDraft,
  onTitleDraftChange,
  busy,
  titleBusy,
  err,
  notice,
  workspaceStageLabel,
  chaptersCount,
  latestChapterNo,
  approvedChapterCount,
  draftChapterCount,
  activeMemoryLines,
  onSaveTitle,
  onOpenSettings,
  onOpenLogs,
}: Props) {
  return (
    <>
      <section className="glass-panel overflow-hidden p-5 md:p-7">
        <div className="flex flex-col gap-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="max-w-3xl space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="glass-chip font-bold text-foreground/80">
                  <div className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  {workspaceStageLabel}
                </span>
                <span className="glass-chip text-foreground/80 font-medium">
                  预期篇幅
                  <span className="ml-1 font-bold text-primary">
                    {novel?.length_tag ? `【${novel.length_tag}】` : ""}
                  </span>
                  <span className="ml-1 font-bold text-foreground">
                    已设置目标 {Number(novel?.target_chapters || 300)} 章
                  </span>
                </span>
              </div>
              <div className="space-y-3">
                <input
                  value={titleDraft}
                  onChange={(e) => onTitleDraftChange(e.target.value)}
                  className="h-12 w-full max-w-2xl rounded-2xl border border-border bg-background px-4 text-2xl font-bold tracking-tight text-foreground transition-all duration-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 placeholder:text-foreground/30"
                  placeholder="请输入书名"
                  disabled={busy || titleBusy}
                />
                <p className="max-w-2xl text-sm leading-6 text-foreground/70 dark:text-muted-foreground font-medium">
                  以框架、章节、记忆三条主线来推进一本书。把高频操作留在首屏，把详细日志和原始数据收进分区，减少创作中断。
                </p>
              </div>
              <div className="flex flex-wrap gap-3">
                <Button
                  type="button"
                  variant="default"
                  className="font-bold"
                  disabled={busy || titleBusy || !titleDraft.trim()}
                  onClick={onSaveTitle}
                >
                  保存书名
                </Button>
                <Button variant="outline" asChild className="font-semibold">
                  <Link to="/novels">返回书架</Link>
                </Button>
                <Button variant="outline" asChild className="font-semibold">
                  <Link to={`/novels/${novelId}/metrics`}>查看指标</Link>
                </Button>
                <Button variant="outline" onClick={onOpenSettings} className="font-semibold">
                  小说设置
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  className="font-semibold"
                  onClick={onOpenLogs}
                >
                  查看生成日志
                </Button>
              </div>
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-4">
            {[
              ["已写章节", `${chaptersCount}`, latestChapterNo ? `最新至第 ${latestChapterNo} 章` : "尚未开始"],
              ["已审定", `${approvedChapterCount}`, approvedChapterCount ? "可用于记忆刷新" : "尚无已审定章节"],
              ["待处理草稿", `${draftChapterCount}`, draftChapterCount ? "建议优先审定" : "当前较为清爽"],
              ["活跃待收束线", `${activeMemoryLines}`, activeMemoryLines ? "需要持续关注" : "记忆区尚未积累"],
            ].map(([label, value, hint]) => (
              <div key={label} className="glass-panel-subtle p-4">
                <p className="text-xs text-foreground/60 dark:text-muted-foreground font-bold">{label}</p>
                <p className="mt-2 text-2xl font-bold tracking-tight text-foreground">
                  {value}
                </p>
                <p className="mt-1 text-xs text-foreground/50 dark:text-muted-foreground font-medium">{hint}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {err ? (
        <div className="glass-panel-subtle flex items-center gap-2 border-destructive/30 px-4 py-3 text-sm text-destructive">
          <div className="h-1.5 w-1.5 rounded-full bg-destructive" />
          {err}
        </div>
      ) : null}
      {notice ? (
        <div className="glass-panel-subtle flex items-center gap-2 border-emerald-500/30 px-4 py-3 text-sm text-emerald-600 dark:text-emerald-300">
          <div className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
          {notice}
        </div>
      ) : null}
    </>
  );
}
