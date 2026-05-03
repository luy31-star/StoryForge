/**
 * Studio tab sticky toolbar with breadcrumb, queue status, and generation controls.
 */
import { Sparkles, Maximize2, Minimize2 } from "lucide-react";
import { Button } from "@/components/ui/button";

type VolumeInfo = { volume_no: number } | null | undefined;
type ChapterInfo = { chapter_no: number; title?: string } | null | undefined;

type Props = {
  workspaceRootBook: boolean;
  selectedVolumeId: string;
  selectedVolume: VolumeInfo;
  selectedChapter: ChapterInfo;
  titleDraft: string;
  novelTitle: string;
  queueBusy: boolean;
  queueLabel: string;
  queueHint: string;
  generateCount: number;
  maxGenerateCount: number;
  onGenerateCountChange: (v: string) => void;
  busy: boolean;
  frameworkConfirmed: boolean;
  focusMode: boolean;
  onFocusModeToggle: () => void;
  onOpenOutlineDrawer: () => void;
  onGenerateChapters: () => void;
};

export function StudioToolbar({
  workspaceRootBook,
  selectedVolumeId,
  selectedVolume,
  selectedChapter,
  titleDraft,
  novelTitle,
  queueBusy,
  queueLabel,
  queueHint,
  generateCount,
  maxGenerateCount,
  onGenerateCountChange,
  busy,
  frameworkConfirmed,
  focusMode,
  onFocusModeToggle,
  onOpenOutlineDrawer,
  onGenerateChapters,
}: Props) {
  return (
    <div className="sticky top-0 z-20 border-b border-border bg-background/92 px-3 py-2 sm:px-4 md:px-6">
      <div className="novel-container flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:gap-3">
        <div className="min-w-0 flex flex-1 items-center gap-2">
          <p className="truncate text-xs font-bold text-foreground/80 sm:text-sm">
            <span className="text-foreground/45">创作</span>
            {workspaceRootBook || !selectedVolumeId ? (
              <span className="ml-1.5">· {titleDraft.trim() || novelTitle || "全书"}</span>
            ) : selectedChapter ? (
              <span className="ml-1.5">
                · 第{selectedVolume?.volume_no ?? "?"}卷 · 第{selectedChapter.chapter_no}章
                {selectedChapter.title ? ` ${selectedChapter.title}` : ""}
              </span>
            ) : (
              <span className="ml-1.5">· 第{selectedVolume?.volume_no ?? "?"}卷</span>
            )}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 sm:ml-auto">
          <div
            className={`rounded-full border px-3 py-1 text-[11px] font-bold ${
              queueBusy
                ? "border-amber-500/35 bg-amber-500/10 text-amber-700 dark:text-amber-300"
                : "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
            }`}
            title={queueHint}
          >
            {queueLabel}
          </div>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-8 w-8 shrink-0 p-0 text-foreground/60 hover:text-foreground"
            onClick={onFocusModeToggle}
            title={focusMode ? "退出专注" : "专注模式"}
          >
            {focusMode ? <Minimize2 className="size-4" /> : <Maximize2 className="size-4" />}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            className="h-8 rounded-full px-3 text-xs font-bold"
            onClick={onOpenOutlineDrawer}
          >
            大纲
          </Button>
          <div className="inline-flex h-8 items-center overflow-hidden rounded-full border border-border bg-background">
            <span className="pl-3 pr-1 text-[11px] font-bold text-foreground/60">
              续写
            </span>
            <input
              type="number"
              min={1}
              max={maxGenerateCount}
              value={generateCount}
              onChange={(e) => onGenerateCountChange(e.target.value)}
              className="h-full w-14 bg-transparent px-1 text-center text-xs font-black text-foreground outline-none"
              aria-label="一键续写章节数量"
            />
            <span className="pl-1 pr-3 text-[11px] font-bold text-foreground/60">
              章
            </span>
          </div>
          <Button
            type="button"
            size="sm"
            className="h-8 gap-1 rounded-full px-3 text-xs font-bold"
            disabled={busy || !frameworkConfirmed}
            onClick={onGenerateChapters}
            title={!frameworkConfirmed ? "请先确认框架，再开始 AI 续写" : `续写 ${generateCount} 章`}
          >
            <Sparkles className="size-3.5 shrink-0 opacity-90" />
            AI 续写
          </Button>
        </div>
      </div>
    </div>
  );
}
