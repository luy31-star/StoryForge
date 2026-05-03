/**
 * Collapsible sidebar with volume/chapter tree for the studio workspace.
 */
import { BookOpen, ChevronDown, ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { VolumeArcStack } from "@/components/workspace/VolumeArcStack";
import { parseVolumeOutlineJson } from "@/components/workspace/VolumeArcStack";
import type { NovelVolumeListItem } from "@/services/novelApi";

type ChapterItem = {
  id: string;
  chapter_no: number;
  title: string;
  pending_content: string;
};

type Props = {
  collapsed: boolean;
  onCollapsedChange: (v: boolean) => void;
  selectedVolumeId: string;
  onSelectVolume: (volumeId: string) => void;
  selectedChapterId: string;
  onSelectChapter: (chapterId: string, volumeId: string) => void;
  workspaceRootBook: boolean;
  onRootBookClick: () => void;
  expandedVolumeIds: Record<string, boolean>;
  onToggleVolumeExpand: (volumeId: string) => void;
  treeVolumePlotOpenId: string | null;
  onToggleVolumePlot: (volumeId: string | null) => void;
  onOpenOutlineDrawer: () => void;
  onOpenExport: () => void;
  volumes: NovelVolumeListItem[];
  chapters: ChapterItem[];
  titleDraft: string;
  novelTitle: string;
};

export function ChapterTreeSidebar({
  collapsed,
  onCollapsedChange,
  selectedVolumeId,
  onSelectVolume,
  selectedChapterId,
  onSelectChapter,
  workspaceRootBook,
  onRootBookClick,
  expandedVolumeIds,
  onToggleVolumeExpand,
  treeVolumePlotOpenId,
  onToggleVolumePlot,
  onOpenOutlineDrawer,
  onOpenExport,
  volumes,
  chapters,
  titleDraft,
  novelTitle,
}: Props) {
  return (
    <aside
      className={`shrink-0 border-border bg-muted transition-[width,max-height] duration-200 ease-out ${
        collapsed
          ? "flex w-full max-h-11 flex-row items-stretch border-b lg:max-h-none lg:min-h-0 lg:w-11 lg:flex-col lg:self-stretch lg:border-b-0 lg:border-r"
          : "flex max-h-[34vh] w-full min-h-0 flex-col border-b lg:max-h-none lg:min-h-0 lg:w-[min(18rem,92vw)] lg:self-stretch lg:border-b-0 lg:border-r"
      }`}
    >
      {collapsed ? (
        <button
          type="button"
          className="flex w-full items-center justify-center gap-2 text-foreground/70 transition-colors hover:bg-muted/45 lg:flex-1 lg:flex-col lg:gap-1.5 lg:py-4"
          aria-label="展开结构树"
          title="展开结构树"
          onClick={() => onCollapsedChange(false)}
        >
          <ChevronRight className="size-5 shrink-0 lg:size-4" />
          <span className="text-[11px] font-bold lg:hidden">结构树</span>
        </button>
      ) : (
        <>
          <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border/45 px-3 py-2 sm:px-4">
            <p className="text-[10px] font-bold uppercase tracking-wide text-foreground/45">
              结构树
            </p>
            <Button
              type="button"
              size="icon"
              variant="ghost"
              className="h-8 w-8 shrink-0 text-foreground/60 hover:text-foreground"
              aria-label="收起结构树"
              title="收起结构树"
              onClick={() => onCollapsedChange(true)}
            >
              <ChevronLeft className="size-4" />
            </Button>
          </div>
          <div className="soft-scroll min-h-0 flex-1 space-y-3 overflow-y-auto p-3 sm:p-4">
            <div
              className={`flex items-center gap-2 rounded-xl border px-2.5 py-2 ${
                workspaceRootBook || !selectedVolumeId
                  ? "border-primary/35 bg-primary/10"
                  : "border-border bg-background/50"
              }`}
            >
              <button
                type="button"
                className="flex min-w-0 flex-1 items-center gap-2 text-left"
                onClick={onRootBookClick}
              >
                <BookOpen className="size-4 shrink-0 text-primary" />
                <span className="truncate text-xs font-bold text-foreground">
                  {titleDraft.trim() || novelTitle || "本书"}
                </span>
              </button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-7 shrink-0 px-2 text-[10px] font-bold"
                onClick={onOpenOutlineDrawer}
              >
                大纲
              </Button>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-8 w-full justify-start px-2 text-[11px] font-bold text-foreground/70 hover:text-foreground"
              onClick={onOpenExport}
            >
              导出正文…
            </Button>
            <div className="space-y-2 pt-1">
              {volumes.length === 0 ? (
                <p className="text-xs text-foreground/50 dark:text-muted-foreground italic font-medium">
                  暂无分卷。请在大纲抽屉里生成分卷剧情，系统会同步卷占位。
                </p>
              ) : (
                volumes
                  .slice()
                  .sort((a, b) => a.volume_no - b.volume_no)
                  .map((v) => {
                    const volChapters = chapters
                      .filter(
                        (c) =>
                          c.chapter_no >= v.from_chapter &&
                          c.chapter_no <= v.to_chapter
                      )
                      .sort((a, b) => a.chapter_no - b.chapter_no);
                    const expanded = Boolean(expandedVolumeIds[v.id]);
                    const volHasPlot =
                      Boolean(
                        parseVolumeOutlineJson(v.outline_json)?.arcs?.length
                      ) || (v.outline_markdown || "").trim().length > 0;
                    return (
                      <div key={v.id} className="space-y-1">
                        <div className="flex items-stretch gap-0.5">
                          <button
                            type="button"
                            aria-label={expanded ? "收起本卷章节" : "展开本卷章节"}
                            className="flex w-8 shrink-0 items-center justify-center rounded-lg border border-transparent text-foreground/50 hover:bg-muted/45"
                            onClick={() => onToggleVolumeExpand(v.id)}
                          >
                            {expanded ? (
                              <ChevronDown className="size-4" />
                            ) : (
                              <ChevronRight className="size-4" />
                            )}
                          </button>
                          <button
                            type="button"
                            onClick={() => onSelectVolume(v.id)}
                            className={`min-w-0 flex-1 rounded-xl border px-2.5 py-2 text-left text-xs transition-all ${
                              selectedVolumeId === v.id
                                ? "border-primary/35 bg-primary/10 shadow-[0_10px_24px_hsl(var(--primary)/0.12)]"
                                : "border-border bg-background/45 hover:bg-muted/35"
                            }`}
                          >
                            <div className="flex items-center justify-between gap-1 font-bold text-foreground">
                              <span className="truncate">第{v.volume_no}卷</span>
                              <span className="shrink-0 text-[10px] text-foreground/50">
                                {v.chapter_plan_count} 计划
                              </span>
                            </div>
                            <p className="mt-0.5 truncate text-[10px] text-foreground/50">
                              {v.title || "未命名"}
                            </p>
                          </button>
                        </div>
                        {volHasPlot ? (
                          <div className="ml-8 flex flex-wrap items-center gap-2">
                            <button
                              type="button"
                              className={`text-[10px] font-bold ${
                                treeVolumePlotOpenId === v.id
                                  ? "text-primary underline"
                                  : "text-foreground/50 hover:text-foreground"
                              }`}
                              onClick={() =>
                                onToggleVolumePlot(
                                  treeVolumePlotOpenId === v.id ? null : v.id
                                )
                              }
                            >
                              {treeVolumePlotOpenId === v.id
                                ? "收起卷剧情"
                                : "卷剧情"}
                            </button>
                            <button
                              type="button"
                              className="text-[10px] text-foreground/40 hover:text-foreground/70"
                              onClick={onOpenOutlineDrawer}
                            >
                              在大纲抽屉编辑
                            </button>
                          </div>
                        ) : null}
                        {treeVolumePlotOpenId === v.id && volHasPlot ? (
                          <div className="ml-8 max-h-56 overflow-y-auto rounded-xl border border-border bg-muted p-2">
                            <VolumeArcStack volume={v} compact />
                          </div>
                        ) : null}
                        {expanded ? (
                          <div className="ml-9 max-h-[min(42dvh,360px)] space-y-1 overflow-y-auto border-l border-border/35 pl-2 pr-0.5">
                            {volChapters.length === 0 ? (
                              <p className="py-2 text-[10px] text-foreground/45">
                                本卷尚无章节
                              </p>
                            ) : (
                              volChapters.map((ch) => (
                                <button
                                  key={ch.id}
                                  type="button"
                                  onClick={() => onSelectChapter(ch.id, v.id)}
                                  className={`flex w-full flex-col rounded-lg border px-2 py-1.5 text-left text-[11px] transition-colors ${
                                    selectedChapterId === ch.id
                                      ? "border-primary/40 bg-primary/12 font-bold text-foreground"
                                      : "border-transparent bg-background/30 text-foreground/80 hover:bg-muted/40"
                                  }`}
                                >
                                  <span className="truncate">
                                    第{ch.chapter_no}章 {ch.title}
                                  </span>
                                  {ch.pending_content ? (
                                    <span className="mt-0.5 text-[9px] font-bold text-amber-600">
                                      待确认修订
                                    </span>
                                  ) : null}
                                </button>
                              ))
                            )}
                          </div>
                        ) : null}
                      </div>
                    );
                  })
              )}
            </div>
          </div>
        </>
      )}
    </aside>
  );
}
