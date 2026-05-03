/**
 * Volume plan section showing chapter plans with execution cards.
 */
import { BookOpen, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { ChapterPlanV2Beats, NovelVolumeListItem } from "@/services/novelApi";

type PlanItem = {
  id: string;
  chapter_no: number;
  chapter_title: string;
  status: string;
  beats: ChapterPlanV2Beats;
};

type VolumePlanView = {
  visible: PlanItem[];
  withBodyCount: number;
};

type VolumePlanLastRun = {
  batch?: {
    from_chapter: number;
    to_chapter: number;
    size: number;
  };
  done?: boolean;
  next_from_chapter?: number | null;
} | null;

type Props = {
  selectedVolumeId: string;
  busy: boolean;
  volumeBusy: boolean;
  volumePlanBatchSize: number;
  onVolumePlanBatchSizeChange: (v: number) => void;
  onGeneratePlan: () => void;
  onClearPlans: () => void;
  volumePlan: PlanItem[];
  volumePlanView: VolumePlanView;
  showVolumePlanWithBody: boolean;
  onShowVolumePlanWithBodyChange: (v: boolean) => void;
  volumes: NovelVolumeListItem[];
  volumePlanLastRun: VolumePlanLastRun;
  onOpenPlanEditor: (plan: PlanItem) => void;
  onRegeneratePlan: (chapterNo: number) => void;
  onGenerateChapter: (chapterNo: number) => void;
  normalizePlanBeats: (beats: ChapterPlanV2Beats) => {
    meta?: { edited_by_user?: boolean };
    display_summary: {
      stage_position?: string;
      plot_summary?: string;
      pacing_justification?: string;
    };
    execution_card: {
      chapter_goal?: string;
      core_conflict?: string;
      key_turn?: string;
      must_happen?: string[];
      required_callbacks?: string[];
      allowed_progress?: string[];
      ending_hook?: string;
      style_guardrails?: string[];
      scene_cards: { label?: string; goal?: string }[];
      reserved_for_later: { item?: string; not_before_chapter?: number; reason?: string }[];
      must_not?: string[];
    };
  };
  shortenText: (value: string, max?: number) => string;
  formatVolumePlanBeatsText: (beats: ChapterPlanV2Beats) => string;
};

export function VolumePlanSection({
  selectedVolumeId,
  busy,
  volumeBusy,
  volumePlanBatchSize,
  onVolumePlanBatchSizeChange,
  onGeneratePlan,
  onClearPlans,
  volumePlan,
  volumePlanView,
  showVolumePlanWithBody,
  onShowVolumePlanWithBodyChange,
  volumes,
  volumePlanLastRun,
  onOpenPlanEditor,
  onRegeneratePlan,
  onGenerateChapter,
  normalizePlanBeats,
  shortenText,
  formatVolumePlanBeatsText,
}: Props) {
  return (
    <section id="studio-volumes" className="glass-panel space-y-4 p-5 md:p-6">
      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div className="space-y-1">
          <p className="section-heading text-foreground font-bold">卷与章计划</p>
          <p className="text-sm text-foreground/70 dark:text-muted-foreground font-medium">
            卷在「大纲抽屉」里随分卷剧情落库后，可在此生成本卷章计划 → 在左侧树选章后在主区续写与编辑正文。需清空本卷计划时可用「一键清除」后重跑下一批。
          </p>
        </div>
        <div className="glass-chip font-bold text-foreground/80">{selectedVolumeId ? "已选择卷，适合继续铺排" : "请先选择或生成一卷"}</div>
      </div>
      <div className="glass-panel-subtle flex flex-wrap gap-2 p-3">
        <div className="flex items-center gap-2 rounded-xl border border-border bg-background px-3 py-1.5 text-xs">
          <span className="text-foreground/60 dark:text-muted-foreground font-bold">每次生成</span>
          <select
            value={volumePlanBatchSize}
            onChange={(e) => onVolumePlanBatchSizeChange(Number(e.target.value))}
            className="h-8 rounded-xl border border-border bg-background px-2.5 text-xs text-foreground font-bold"
            disabled={busy || volumeBusy}
          >
            {[4, 5, 6, 7, 8, 9, 10].map((n) => (
              <option key={n} value={n}>
                {n} 章
              </option>
            ))}
          </select>
        </div>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          className="font-bold"
          disabled={busy || volumeBusy || !selectedVolumeId}
          onClick={onGeneratePlan}
        >
          生成本卷章计划（下一批）
        </Button>
        <Button
          type="button"
          size="sm"
          variant="destructive"
          className="font-bold"
          disabled={busy || volumeBusy || !selectedVolumeId}
          onClick={onClearPlans}
        >
          一键清除本卷计划
        </Button>
      </div>

      <div>
        <section className="glass-panel-subtle p-5">
          {!selectedVolumeId ? (
            <p className="text-sm text-foreground/50 dark:text-muted-foreground italic font-medium">请在左侧栏选择一卷。</p>
          ) : (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm font-bold text-foreground">本卷章计划</p>
                <p className="text-xs text-foreground/60 dark:text-muted-foreground font-bold">
                  {volumeBusy
                    ? "加载中…"
                    : `共 ${volumePlan.length} 章 · 当前展示 ${volumePlanView.visible.length} 章`}
                </p>
              </div>
              {volumePlan.length > 0 ? (
                <label className="flex cursor-pointer flex-wrap items-center gap-2 text-xs text-foreground/70 dark:text-muted-foreground font-bold">
                  <input
                    type="checkbox"
                    className="rounded border-input"
                    checked={showVolumePlanWithBody}
                    onChange={(e) => onShowVolumePlanWithBodyChange(e.target.checked)}
                  />
                  <span>
                    显示已含正文的章节（默认关闭：已生成正文的章会隐藏，便于往下写）
                    {!showVolumePlanWithBody && volumePlanView.withBodyCount > 0 ? (
                      <span className="ml-1 text-amber-600 font-bold">
                        · 已隐藏 {volumePlanView.withBodyCount} 章
                      </span>
                    ) : null}
                  </span>
                </label>
              ) : null}
              {(() => {
                const v = volumes.find((x) => x.id === selectedVolumeId);
                if (!v) return null;
                const total = v.to_chapter - v.from_chapter + 1;
                const done = volumePlan.length >= total;
                const last = volumePlanLastRun;
                return (
                  <div className="glass-panel-subtle p-3 text-xs text-foreground/70 dark:text-muted-foreground font-medium">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span>
                        进度：已生成 {volumePlan.length}/{total} 章（第{v.from_chapter}—{v.to_chapter}章）
                      </span>
                      <span className="font-bold">{done ? "已完成" : "未完成"}</span>
                    </div>
                    {last?.batch ? (
                      <div className="mt-1">
                        最近一次：第{last.batch.from_chapter}—{last.batch.to_chapter}章（批次 {last.batch.size} 章）；
                        {last.done
                          ? "本卷已完成。"
                          : `下一批建议从第${last.next_from_chapter ?? "?"}章开始。`}
                      </div>
                    ) : null}
                  </div>
                );
              })()}
              <div className="soft-scroll max-h-[70vh] overflow-auto rounded-lg border border-border bg-muted p-2.5">
                {volumePlan.length === 0 ? (
                  <p className="p-2 text-xs text-foreground/50 dark:text-muted-foreground italic font-medium">
                    暂无章计划。点击"生成本卷章计划（下一批）"开始生成。
                  </p>
                ) : volumePlanView.visible.length === 0 ? (
                  <p className="p-2 text-xs text-foreground/50 dark:text-muted-foreground italic font-medium">
                    当前视图下没有待写章节（本卷计划均已含正文）。
                    请勾选上方「显示已含正文的章节」以查看与操作已生成章节。
                  </p>
                ) : (
                  <div className="space-y-2">
                    {volumePlanView.visible.map((p) => {
                      const normalized = normalizePlanBeats(p.beats);
                      return (
                        <div key={p.id} className="list-card overflow-hidden p-0 text-xs">
                          <div className="relative border-b border-border/50 px-4 py-4">
                            <div className="pointer-events-none absolute inset-0 bg-gradient-to-r from-primary/10 via-accent/6 to-transparent" />
                            <div className="relative flex flex-wrap items-start justify-between gap-3">
                              <div className="space-y-2">
                                <div className="flex flex-wrap items-center gap-2 font-bold text-foreground">
                                  第{p.chapter_no}章 · {p.chapter_title}
                                  {normalized.meta?.edited_by_user ? (
                                    <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] font-bold text-amber-700 dark:text-amber-300">
                                      已手动编辑
                                    </span>
                                  ) : null}
                                  <span className="rounded-full border border-border bg-background px-2 py-0.5 text-[10px] font-semibold text-foreground/50">
                                    {p.status === "locked" ? "Locked" : "Editable"}
                                  </span>
                                </div>
                                <div className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium">
                                  {p.status === "locked"
                                    ? "当前计划已锁定，适合直接生成正文或复盘节拍。"
                                    : "执行卡可继续微调，也可以直接把这一章推进为正文。"}
                                </div>
                              </div>
                              <div className="flex flex-wrap gap-2">
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="secondary"
                                  className="font-semibold"
                                  disabled={busy || volumeBusy || p.status === "locked"}
                                  onClick={() => onOpenPlanEditor(p)}
                                >
                                  编辑执行卡
                                </Button>
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="outline"
                                  className="font-semibold"
                                  disabled={busy || p.status === "locked"}
                                  onClick={() => onRegeneratePlan(p.chapter_no)}
                                >
                                  重生成计划
                                </Button>
                                <Button
                                  type="button"
                                  size="sm"
                                  className="font-bold"
                                  disabled={busy}
                                  onClick={() => onGenerateChapter(p.chapter_no)}
                                >
                                  生成正文
                                </Button>
                              </div>
                            </div>
                          </div>

                          <div className="grid gap-4 p-4 xl:grid-cols-[1.12fr_0.88fr]">
                            <div className="space-y-3">
                              <div className="rounded-lg border border-border bg-background p-4">
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                  <div className="flex items-center gap-2">
                                    <BookOpen className="size-4 text-primary" />
                                    <p className="text-sm font-semibold text-foreground">执行摘要</p>
                                  </div>
                                  {normalized.display_summary.stage_position ? (
                                    <span className="rounded-full border border-border bg-background px-3 py-1 text-[11px] font-semibold text-foreground/60">
                                      {normalized.display_summary.stage_position}
                                    </span>
                                  ) : (
                                    <span className="text-[11px] text-foreground/50">
                                      完整版本见线性摘要
                                    </span>
                                  )}
                                </div>
                                <div className="mt-4 space-y-3">
                                  {[
                                    ["本章目标", normalized.execution_card.chapter_goal || "待补充目标"],
                                    ["核心冲突", normalized.execution_card.core_conflict || "待补充冲突"],
                                    ["关键转折", normalized.execution_card.key_turn || "待补充转折"],
                                  ].map(([label, value]) => (
                                    <div
                                      key={`${p.id}-${label}`}
                                      className="grid gap-2 rounded-[1rem] border border-border bg-background px-3 py-3 md:grid-cols-[92px_1fr]"
                                    >
                                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-foreground/50">
                                        {label}
                                      </p>
                                      <p
                                        className="text-sm leading-6 text-foreground/80 line-clamp-3"
                                        title={String(value)}
                                      >
                                        {shortenText(String(value), 78)}
                                      </p>
                                    </div>
                                  ))}
                                </div>

                                <div className="mt-4 rounded-[1rem] border border-border bg-background px-3 py-3">
                                  <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-foreground/50">
                                    剧情推进
                                  </p>
                                  <p
                                    className="mt-2 text-sm leading-6 text-foreground/70 line-clamp-4"
                                    title={normalized.display_summary.plot_summary || "暂未生成剧情摘要。"}
                                  >
                                    {normalized.display_summary.plot_summary || "暂未生成剧情摘要。"}
                                  </p>
                                  {normalized.display_summary.pacing_justification ? (
                                    <p
                                      className="mt-2 text-[12px] leading-6 text-foreground/60 line-clamp-3"
                                      title={normalized.display_summary.pacing_justification}
                                    >
                                      {normalized.display_summary.pacing_justification}
                                    </p>
                                  ) : null}
                                </div>

                                {normalized.display_summary.pacing_justification ? (
                                  <div className="mt-3 flex flex-wrap gap-2 text-xs text-foreground/60">
                                    <span className="status-badge">已压缩长文本</span>
                                    <span className="status-badge">优先看目标 / 冲突 / 转折</span>
                                  </div>
                                ) : null}
                              </div>

                              {[
                                ["必须发生", normalized.execution_card.must_happen],
                                ["必须承接", normalized.execution_card.required_callbacks],
                                ["允许推进", normalized.execution_card.allowed_progress],
                              ].map(([label, items]) => {
                                if (!Array.isArray(items) || items.length === 0) return null;
                                return (
                                  <div
                                    key={`${p.id}-${label}`}
                                    className="rounded-lg border border-border bg-background p-4"
                                  >
                                    <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-foreground/50">
                                      {label}
                                    </p>
                                    <div className="mt-3 flex flex-wrap gap-2">
                                      {items.map((item, index) => (
                                        <span
                                          key={`${p.id}-${label}-${index}`}
                                          className="rounded-full border border-border bg-background px-3 py-1 text-[11px] font-medium text-foreground/74"
                                        >
                                          {item}
                                        </span>
                                      ))}
                                    </div>
                                  </div>
                                );
                              })}
                            </div>

                            <div className="space-y-3">
                              <div className="rounded-lg border border-border bg-background p-4">
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                  <div className="flex items-center gap-2">
                                    <Sparkles className="size-4 text-primary" />
                                    <p className="text-sm font-semibold text-foreground">章末与护栏</p>
                                  </div>
                                  {normalized.execution_card.scene_cards.length > 0 ? (
                                    <span className="status-badge">
                                      Scene {normalized.execution_card.scene_cards.length}
                                    </span>
                                  ) : null}
                                </div>
                                <div className="mt-3 space-y-3">
                                  <div className="rounded-[1rem] border border-primary/15 bg-primary/6 px-3 py-3">
                                    <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-foreground/50">
                                      Ending Hook
                                    </p>
                                    <p className="mt-2 text-sm leading-6 text-foreground/80">
                                      {normalized.execution_card.ending_hook || "暂无章末钩子。"}
                                    </p>
                                  </div>

                                  {(normalized.execution_card.style_guardrails?.length ?? 0) > 0 ? (
                                    <div>
                                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-foreground/50">
                                        风格护栏
                                      </p>
                                      <div className="mt-2 flex flex-wrap gap-2">
                                        {normalized.execution_card.style_guardrails?.map((item, index) => (
                                          <span
                                            key={`${p.id}-guardrail-${index}`}
                                            className="rounded-full border border-border bg-background px-3 py-1 text-[11px] font-medium text-foreground/74"
                                          >
                                            {item}
                                          </span>
                                        ))}
                                      </div>
                                    </div>
                                  ) : null}

                                  {normalized.execution_card.scene_cards.length > 0 ? (
                                    <div>
                                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-foreground/50">
                                        场景锚点
                                      </p>
                                      <div className="mt-2 flex flex-wrap gap-2">
                                        {normalized.execution_card.scene_cards.slice(0, 3).map((scene, index) => (
                                          <span
                                            key={`${p.id}-scene-chip-${index}`}
                                            className="rounded-full border border-border bg-background px-3 py-1 text-[11px] font-medium text-foreground/74"
                                          >
                                            {scene.label || scene.goal || `Scene ${index + 1}`}
                                          </span>
                                        ))}
                                      </div>
                                    </div>
                                  ) : null}

                                  {normalized.execution_card.reserved_for_later.length > 0 ||
                                  (normalized.execution_card.must_not?.length ?? 0) > 0 ? (
                                    <details className="rounded-[1rem] border border-border bg-background px-3 py-3">
                                      <summary className="cursor-pointer text-[11px] font-semibold uppercase tracking-[0.16em] text-foreground/50">
                                        更多约束
                                      </summary>
                                      <div className="mt-3 space-y-3">
                                        {normalized.execution_card.reserved_for_later.length > 0 ? (
                                          <div>
                                            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-foreground/50">
                                              延后解锁
                                            </p>
                                            <div className="mt-2 grid gap-2">
                                              {normalized.execution_card.reserved_for_later.map((item, index) => (
                                                <div
                                                  key={`${p.id}-reserved-${index}`}
                                                  className="rounded-[1rem] border border-border bg-background px-3 py-2 text-sm text-foreground/70"
                                                >
                                                  <span className="font-semibold text-foreground/84">
                                                    {item.item}
                                                  </span>
                                                  {item.not_before_chapter != null ? (
                                                    <span className="ml-2 text-foreground/56">
                                                      第 {item.not_before_chapter} 章后
                                                    </span>
                                                  ) : null}
                                                  {item.reason ? (
                                                    <p className="mt-1 text-sm leading-6 text-foreground/60">
                                                      {item.reason}
                                                    </p>
                                                  ) : null}
                                                </div>
                                              ))}
                                            </div>
                                          </div>
                                        ) : null}

                                        {(normalized.execution_card.must_not?.length ?? 0) > 0 ? (
                                          <div>
                                            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-foreground/50">
                                              禁止项
                                            </p>
                                            <div className="mt-2 flex flex-wrap gap-2">
                                              {normalized.execution_card.must_not?.map((item, index) => (
                                                <span
                                                  key={`${p.id}-must-not-${index}`}
                                                  className="rounded-full border border-rose-500/25 bg-rose-500/10 px-3 py-1 text-[11px] font-medium text-rose-700 dark:text-rose-300"
                                                >
                                                  {item}
                                                </span>
                                              ))}
                                            </div>
                                          </div>
                                        ) : null}
                                      </div>
                                    </details>
                                  ) : null}

                                  <details className="rounded-[1rem] border border-border bg-background px-3 py-3">
                                    <summary className="cursor-pointer text-[11px] font-semibold uppercase tracking-[0.16em] text-foreground/50">
                                      线性摘要
                                    </summary>
                                    <pre className="mt-3 whitespace-pre-wrap text-[11px] leading-6 text-foreground/60">
                                      {formatVolumePlanBeatsText(p.beats)}
                                    </pre>
                                  </details>
                                </div>
                              </div>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          )}
        </section>
      </div>
    </section>
  );
}
