/**
 * Outline drawer dialog for viewing/editing the full book outline and volume arcs.
 */
import { ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { VolumeArcStack, parseVolumeOutlineJson } from "@/components/workspace/VolumeArcStack";
import type { NovelVolumeListItem } from "@/services/novelApi";

type NovelLike = {
  status?: string;
  base_framework_confirmed?: boolean;
} | null;

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  busy: boolean;
  frameworkConfirmed: boolean;
  latestChapterNo: number | null;
  novel: NovelLike;
  fwMd: string;
  onFwMdChange: (v: string) => void;
  onRetryFramework: () => void;
  onOpenFrameworkWizard: () => void;
  volumes: NovelVolumeListItem[];
  arcsPanelVolumeNo: number;
  onArcsPanelVolumeNoChange: (v: number) => void;
  totalStudioVolumes: number;
  arcsBusy: boolean;
  arcsInstruction: string;
  onArcsInstructionChange: (v: string) => void;
  onGenerateArcs: () => void;
};

export function OutlineDrawerDialog({
  open,
  onOpenChange,
  busy,
  frameworkConfirmed,
  latestChapterNo,
  novel,
  fwMd,
  onFwMdChange,
  onRetryFramework,
  onOpenFrameworkWizard,
  volumes,
  arcsPanelVolumeNo,
  onArcsPanelVolumeNoChange,
  totalStudioVolumes,
  arcsBusy,
  arcsInstruction,
  onArcsInstructionChange,
  onGenerateArcs,
}: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="!fixed !inset-y-2 !right-2 !left-auto !top-2 !flex !h-[min(94dvh,940px)] !max-h-[94dvh] !w-[calc(100vw-1rem)] !max-w-[min(46rem,calc(100vw-1rem))] !translate-x-0 !translate-y-0 flex-col gap-0 overflow-hidden !rounded-2xl !border-2 !border-border !bg-card !p-0 !text-card-foreground ! shadow-[0_24px_64px_-12px_rgba(15,23,42,0.22)] dark:shadow-[0_24px_64px_-8px_rgba(0,0,0,0.5)] data-[state=open]:zoom-in-100 sm:!inset-y-3 sm:!right-3 sm:!max-w-[min(46rem,calc(100vw-1.5rem))] sm:!w-[min(46rem,calc(100vw-1.5rem))]">
        <DialogHeader className="shrink-0 space-y-2 border-b-2 border-border bg-muted px-5 py-4 text-left sm:flex-row sm:items-center sm:justify-between sm:space-y-0 sm:px-6">
          <div className="min-w-0 space-y-1 pr-8 sm:pr-0">
            <DialogTitle className="text-left text-lg">大纲抽屉</DialogTitle>
            <DialogDescription className="text-left text-xs text-muted-foreground sm:max-w-xl">
              查看全书大纲与各卷剧情线；关闭抽屉后，用左侧目录切换卷和章节。
            </DialogDescription>
          </div>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            className="mt-2 w-full shrink-0 font-bold sm:mt-0 sm:w-auto"
            disabled={busy}
            onClick={onOpenFrameworkWizard}
          >
            修改向导
          </Button>
        </DialogHeader>
        <div className="min-h-0 flex-1 space-y-8 overflow-y-auto bg-background px-5 py-5 soft-scroll sm:px-6 sm:py-6">
          <div id="studio-outline-drawer" className="space-y-6">
            <div className="space-y-1">
              <p className="section-heading text-foreground font-bold">小说概览与创作基线</p>
              <p className="text-sm text-foreground/80 dark:text-muted-foreground font-medium">
                与左侧目录配合：这里管全书大纲和各卷剧情，中间主区写当前卷、当前章。
              </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-xl border border-border bg-muted p-4 shadow-sm">
                <p className="text-xs font-bold text-muted-foreground">框架状态</p>
                <p className="mt-2 text-base font-bold text-foreground">
                  {frameworkConfirmed ? "已确认" : "待确认"}
                </p>
              </div>
              <div className="rounded-xl border border-border bg-muted p-4 shadow-sm">
                <p className="text-xs font-bold text-muted-foreground">当前章节</p>
                <p className="mt-2 text-base font-bold text-foreground">
                  {latestChapterNo ? `第 ${latestChapterNo} 章` : "未开始"}
                </p>
              </div>
              <div className="rounded-xl border border-border bg-muted p-4 shadow-sm">
                <p className="text-xs font-bold text-muted-foreground">建议下一步</p>
                <p className="mt-2 text-sm font-bold text-foreground">
                  {frameworkConfirmed
                    ? "在左侧树选卷或章节，主区即切换"
                    : novel?.status === "failed"
                      ? "AI 构思似乎失败了，请尝试重试"
                      : !fwMd && novel?.status === "draft"
                        ? "AI 正在飞速构思，请稍候片刻"
                        : '进入“修改向导”确认大纲'}
                </p>
              </div>
            </div>
            <div className="relative">
              <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">
                一、基础大纲（世界观 / 人物 / 主线）
              </Label>
              <p className="mt-1 text-xs text-foreground/50 dark:text-muted-foreground">
                这里是全书层面的设定与主线；按卷写的剧情弧线在下方「分卷剧情」。
              </p>
              {!fwMd && (novel?.status === "draft" || novel?.status === "failed") ? (
                <div className="mt-2 flex min-h-[260px] w-full flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-primary/30 bg-primary/5 p-4 text-sm text-primary/70 animate-pulse text-center">
                  {novel?.status === "failed" ? (
                    <>
                      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-destructive/10">
                        <div className="h-4 w-4 rounded-full bg-destructive" />
                      </div>
                      <p className="font-bold text-base text-destructive">AI 构思似乎失败了</p>
                      <p className="text-xs opacity-60 max-w-xs mb-2">若当前还没有草案，会重试首版生成；若已有草案，则会按当前版本重写。</p>
                      <Button
                        size="sm"
                        variant="default"
                        className="font-bold"
                        onClick={onRetryFramework}
                        disabled={busy}
                      >
                        {busy ? "重试中..." : "重新生成首版大纲 / 重写当前大纲"}
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        className="font-bold border-destructive/30 text-destructive hover:bg-destructive/5"
                        onClick={onOpenFrameworkWizard}
                      >
                        进入修改向导
                      </Button>
                    </>
                  ) : (
                    <>
                      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary/10">
                        <div className="h-4 w-4 rounded-full border-2 border-primary border-t-transparent animate-spin" />
                      </div>
                      <p className="font-bold">AI 正在飞速构思全书大纲，请稍候片刻...</p>
                      <p className="text-xs opacity-60">构思完成后大纲将自动出现</p>
                    </>
                  )}
                </div>
              ) : (
                <textarea
                  value={fwMd}
                  onChange={(e) => onFwMdChange(e.target.value)}
                  className="mt-2 min-h-[280px] w-full rounded-2xl border-2 border-border bg-card p-4 font-mono text-sm text-foreground shadow-sm dark:"
                  placeholder={'暂无大纲。进入"修改向导"或等待 AI 生成。'}
                />
              )}
            </div>
            <div className="space-y-3 border-t-2 border-border pt-8">
              <div className="space-y-1">
                <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">
                  分卷剧情（概览与生成）
                </Label>
                <p className="text-xs text-foreground/70 dark:text-muted-foreground">
                  下方点选卷号后，这里只显示该卷。各段默认折叠，展开后可读「剧情 / 钩子 / 禁止推进 / 允许推进」。续写与章计划会参考此处。
                </p>
              </div>
              {volumes.length === 0 ? (
                <div className="rounded-2xl border-2 border-dashed border-border bg-muted p-6 text-sm text-muted-foreground">
                  还没有分卷占位。请先在下方选择卷号并生成分卷剧情，系统会同步卷信息。
                </div>
              ) : (
                (() => {
                  const v = volumes.find((x) => x.volume_no === arcsPanelVolumeNo);
                  const om = (v?.outline_markdown || "").trim();
                  const po = v ? parseVolumeOutlineJson(v.outline_json) : null;
                  const hasArc = Boolean(po && po.arcs.length > 0) || om.length > 0;
                  const segN =
                    po && po.arcs.length > 0
                      ? po.arcs.length
                      : (om.match(/^### /gm) || []).length;
                  if (!v) {
                    return (
                      <div className="rounded-2xl border-2 border-dashed border-border bg-muted p-6 sm:p-8">
                        <p className="text-sm font-bold text-foreground">
                          第 {arcsPanelVolumeNo} 卷
                        </p>
                        <p className="mt-2 text-sm leading-relaxed text-foreground/70">
                          该卷尚未在书中落库。请在下方保持选中该卷号，点击「生成第{" "}
                          {arcsPanelVolumeNo} 卷剧情」后会自动创建本卷并写入剧情。
                        </p>
                      </div>
                    );
                  }
                  return (
                    <div className="w-full max-w-full rounded-2xl border-2 border-border bg-card p-4 shadow-sm sm:p-6">
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <p className="text-xs font-bold uppercase tracking-wide text-foreground/50">
                            第 {v.volume_no} 卷
                          </p>
                          <p className="mt-1 text-lg font-bold text-foreground sm:text-xl">
                            {v.title || "（未命名）"}
                          </p>
                        </div>
                        <span
                          className={`shrink-0 rounded-full px-2.5 py-0.5 text-[10px] font-bold ${
                            hasArc
                              ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
                              : "bg-muted text-muted-foreground"
                          }`}
                        >
                          {hasArc ? "已有剧情" : "未生成"}
                        </span>
                      </div>
                      {v.summary ? (
                        <p className="mt-3 text-sm text-foreground/70 line-clamp-4">
                          {v.summary}
                        </p>
                      ) : null}
                      {hasArc ? (
                        <details className="group mt-4 rounded-2xl border-2 border-border bg-muted open:border-primary/25 open:bg-muted">
                          <summary className="flex cursor-pointer list-none items-center gap-2 p-3.5 text-left text-sm font-bold text-foreground sm:p-4 [&::-webkit-details-marker]:hidden">
                            <ChevronRight className="size-4 shrink-0 text-foreground/45 transition group-open:rotate-90" />
                            <span>展开本卷剧情</span>
                            {segN > 0 ? (
                              <span className="text-sm font-normal text-foreground/45">
                                （{segN} 段）
                              </span>
                            ) : null}
                          </summary>
                          <div className="min-h-0 max-h-[min(72dvh,820px)] overflow-y-auto border-t border-border/50 p-3 sm:p-4">
                            <VolumeArcStack volume={v} roomy />
                          </div>
                        </details>
                      ) : (
                        <p className="mt-4 text-sm leading-relaxed text-foreground/50">
                          本卷还没有分卷剧情。保持下方当前卷号选中，点击「生成第{" "}
                          {arcsPanelVolumeNo} 卷剧情」即可；同一卷再次生成会覆盖旧内容。
                        </p>
                      )}
                    </div>
                  );
                })()
              )}

              <div className="space-y-3 border-t-2 border-border pt-8">
                <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">
                  生成或覆盖分卷剧情
                </Label>
                <p className="text-xs text-foreground/50 dark:text-muted-foreground">
                  需先确认基础大纲。生成需要一点时间；同一卷再次生成会覆盖该卷已有内容。
                </p>
                {!novel?.base_framework_confirmed ? (
                  <p className="text-xs font-bold text-amber-600 dark:text-amber-400">
                    请先在向导中确认基础大纲，或使用确认按钮。
                  </p>
                ) : null}
                <div className="flex flex-wrap gap-2">
                  {Array.from({ length: totalStudioVolumes }, (_, i) => i + 1).map((volNo) => {
                    const hasOutline = volumes.some(
                      (vv) =>
                        vv.volume_no === volNo &&
                        ((vv.outline_markdown || "").trim().length > 0 ||
                          Boolean(parseVolumeOutlineJson(vv.outline_json)?.arcs?.length))
                    );
                    const selected = arcsPanelVolumeNo === volNo;
                    return (
                      <button
                        key={`arc-vol-${volNo}`}
                        type="button"
                        disabled={arcsBusy || busy}
                        onClick={() => onArcsPanelVolumeNoChange(volNo)}
                        className={`rounded-xl border px-3 py-1.5 text-xs font-bold transition-colors ${
                          selected
                            ? "border-primary bg-primary text-primary-foreground"
                            : hasOutline
                              ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-800 dark:text-emerald-200"
                              : "border-border bg-background text-foreground/80 hover:bg-muted/40"
                        }`}
                      >
                        第{volNo}卷{hasOutline ? " ✓" : ""}
                      </button>
                    );
                  })}
                </div>
                <Input
                  value={arcsInstruction}
                  onChange={(e) => onArcsInstructionChange(e.target.value)}
                  placeholder="可选：如「第二卷加强感情线」「第三卷节奏加快」"
                  className="mt-1"
                  disabled={arcsBusy}
                />
                <div className="mt-2 flex flex-wrap gap-2">
                  <Button
                    type="button"
                    size="sm"
                    className="font-bold"
                    disabled={arcsBusy || busy || !novel?.base_framework_confirmed}
                    onClick={onGenerateArcs}
                  >
                    {arcsBusy ? "生成中…" : `生成第 ${arcsPanelVolumeNo} 卷剧情`}
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
