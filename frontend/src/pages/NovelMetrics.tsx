import { useEffect, useMemo, useState, type ComponentType } from "react";
import { Link, useParams } from "react-router-dom";
import { BookOpen, Gauge, ShieldCheck, Thermometer, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { getNovelMetrics } from "@/services/novelApi";

type NovelMetrics = Awaited<ReturnType<typeof getNovelMetrics>>;

function clamp01(n: number) {
  if (Number.isNaN(n)) return 0;
  return Math.max(0, Math.min(1, n));
}

function RiskRing({
  title,
  subtitle,
  value01, // 0~1, 越高越好（证据越足）
  icon: Icon,
}: {
  title: string;
  subtitle: string;
  value01: number;
  icon: ComponentType<{ className?: string }>;
}) {
  const value = clamp01(value01);
  const r = 44;
  const c = 2 * Math.PI * r;
  const dashOffset = c * (1 - value);

  return (
    <div className="relative flex items-center gap-4 rounded-lg border border-border bg-card/60 p-4 shadow-sm">
      <div className="flex h-12 w-12 items-center justify-center rounded-md bg-primary/10 text-primary">
        <Icon className="size-5" />
      </div>
      <div className="flex flex-1 items-center justify-between gap-4">
        <div>
          <p className="text-sm font-medium">{title}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>
        </div>
        <div className="relative flex items-center justify-center">
          <svg width="110" height="110" viewBox="0 0 110 110" className="drop-shadow">
            <defs>
              <linearGradient id="ringGrad" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stopColor="hsl(var(--primary))" />
                <stop offset="100%" stopColor="hsl(var(--accent))" />
              </linearGradient>
            </defs>
            <circle
              cx="55"
              cy="55"
              r={r}
              stroke="hsl(var(--ring))"
              strokeOpacity="0.14"
              strokeWidth="10"
              fill="none"
            />
            <circle
              cx="55"
              cy="55"
              r={r}
              stroke="url(#ringGrad)"
              strokeWidth="10"
              strokeLinecap="round"
              strokeDasharray={`${c} ${c}`}
              strokeDashoffset={dashOffset}
              fill="none"
              transform="rotate(-90 55 55)"
            />
          </svg>
          <div className="absolute text-center">
            <div className="text-xl font-semibold tabular-nums">
              {Math.round(value * 100)}%
            </div>
            <div className="mt-[-2px] text-[11px] text-muted-foreground">证据</div>
          </div>
        </div>
      </div>
    </div>
  );
}

export function NovelMetricsPage() {
  const { id = "" } = useParams();
  const [metrics, setMetrics] = useState<NovelMetrics | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!id) return;
    setBusy(true);
    setErr(null);
    getNovelMetrics(id)
      .then(setMetrics)
      .catch((e: unknown) => setErr(e instanceof Error ? e.message : "加载失败"))
      .finally(() => setBusy(false));
  }, [id]);

  const riskModel = useMemo(() => {
    const s = metrics?.summary;
    if (!s) {
      return {
        openEvidence: 0.5,
        timelineEvidence: 0.5,
        continuityEvidence: 0.5,
        overallEvidence: 0.5,
      };
    }

    // open_plots 越少越好
    const openRisk = clamp01((s.open_plots_count || 0) / 12);
    const openEvidence = 1 - openRisk;

    // canonical_timeline 覆盖已审定越多越好（简单比例启发式）
    const approvedCount = Math.max(1, s.approved_count || 0);
    const coverage = clamp01((s.canonical_timeline_count || 0) / approvedCount);
    const timelineEvidence = coverage;

    // 最近两条已审定是否连续（启发式）
    const continuityEvidence = s.is_consecutive_last_two_approved ? 0.85 : 0.35;

    const overallEvidence = clamp01(
      (openEvidence + timelineEvidence + continuityEvidence) / 3
    );

    return {
      openEvidence,
      timelineEvidence,
      continuityEvidence,
      overallEvidence,
    };
  }, [metrics]);

  if (!metrics) {
    return (
      <div className="min-h-screen bg-background p-6">
        <div className="mx-auto max-w-5xl">
          <div className="rounded-xl border border-border bg-card/60 p-6">
            <p className="text-sm text-muted-foreground">
              {busy ? "加载指标中…" : err ? `错误：${err}` : "暂无数据"}
            </p>
            <Button variant="ghost" className="mt-4" asChild>
              <Link to={`/novels/${id}`}>返回书页</Link>
            </Button>
          </div>
        </div>
      </div>
    );
  }

  const { novel, config, summary } = metrics;

  return (
    <div className="min-h-screen bg-background p-6">
      <div className="mx-auto max-w-5xl space-y-4">
        <div className="relative overflow-hidden rounded-2xl border border-border bg-card/60 p-6">
          <div className="pointer-events-none absolute inset-0 bg-gradient-to-r from-primary/20 via-accent/10 to-transparent" />
          <div className="relative flex flex-wrap items-start justify-between gap-4">
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-muted-foreground">
                <BookOpen className="size-4" />
                <span className="text-sm">连贯性观察指标</span>
              </div>
              <h1 className="text-2xl font-bold tracking-tight">{novel.title}</h1>
              <p className="text-sm text-muted-foreground">
                framework：{novel.framework_confirmed ? "已确认" : "未确认"} · 状态：{novel.status}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" asChild>
                <Link to={`/novels/${novel.id}`}>返回书页</Link>
              </Button>
              <Button variant="outline" asChild>
                <Link to="/novels">书架</Link>
              </Button>
            </div>
          </div>
        </div>

        <div className="grid gap-4 lg:grid-cols-3">
          <div className="lg:col-span-2 space-y-4">
            <Card className="overflow-hidden bg-card/60">
              <CardHeader>
                <CardTitle>防偏移 · 连贯性证据（越高越好）</CardTitle>
                <CardDescription>
                  这不是“绝对正确”，而是把你最关心的漂移风险拆成可视化信号。
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="grid gap-3 md:grid-cols-2">
                  <RiskRing
                    title="未完结线 open_plots"
                    subtitle="线越少，越不容易断线/跑坑"
                    value01={riskModel.openEvidence}
                    icon={Zap}
                  />
                  <RiskRing
                    title="时间线账本覆盖"
                    subtitle="canonical_timeline 越贴近审定进度越稳"
                    value01={riskModel.timelineEvidence}
                    icon={ShieldCheck}
                  />
                </div>
                <RiskRing
                  title="章节连续性（启发式）"
                  subtitle={
                    summary.is_consecutive_last_two_approved
                      ? "最近两次已审定连续，承接证据强"
                      : "最近两次已审定不连续，承接需要更强约束"
                  }
                  value01={riskModel.continuityEvidence}
                  icon={Thermometer}
                />
                <div className="rounded-lg border border-border bg-muted/20 p-4">
                  <div className="flex items-center justify-between">
                    <p className="text-sm font-medium">综合证据</p>
                    <p className="text-sm text-muted-foreground">
                      {Math.round(riskModel.overallEvidence * 100)}%
                    </p>
                  </div>
                  <div className="mt-3 flex items-center gap-3 text-xs text-muted-foreground">
                    <span className="rounded bg-primary/10 px-2 py-1">
                      总体策略：偏连贯（tail/head/核对）
                    </span>
                    <span className="rounded bg-accent/10 px-2 py-1">
                      提示：如果长期证据偏低，建议刷新记忆/提高 tail/head 或开启核对
                    </span>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card className="bg-card/60">
              <CardHeader>
                <CardTitle>关键指标卡片</CardTitle>
                <CardDescription>把你最关心的内容直接列出来，方便肉眼检查。</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="rounded-xl border border-border bg-background/30 p-4">
                  <p className="text-sm font-medium">节奏对齐（下一章导航）</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    下一章：第{" "}
                    <span className="font-semibold">
                      {(summary as any).next_chapter_no ?? "-"}
                    </span>{" "}
                    章 · 当前弧线：{" "}
                    <span className="font-semibold">
                      {(summary as any).current_arc_title || "（未命中 arcs）"}
                    </span>
                    {(summary as any).current_arc_from != null &&
                    (summary as any).current_arc_to != null ? (
                      <span className="ml-2">
                        （第{String((summary as any).current_arc_from)}—{String((summary as any).current_arc_to)}章）
                      </span>
                    ) : null}
                  </p>
                  <p className="mt-2 text-xs text-muted-foreground">
                    弧线节拍信息：{" "}
                    <span className="font-semibold">
                      {(summary as any).current_arc_has_beats ? "已提供" : "缺失"}
                    </span>
                  </p>
                  {(summary as any).pacing_flags?.length ? (
                    <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-amber-200/90">
                      {(summary as any).pacing_flags.map((x: string, i: number) => (
                        <li key={`${i}-${x}`}>{x}</li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-2 text-xs text-muted-foreground">
                      暂无节奏风险提示。
                    </p>
                  )}
                  <div className="mt-3 grid gap-2 sm:grid-cols-3">
                    <div className="rounded-lg border border-border bg-muted/20 p-3">
                      <p className="text-xs text-muted-foreground">卷数 volumes</p>
                      <p className="mt-1 text-lg font-semibold">
                        {String((summary as any).volumes_count ?? 0)}
                      </p>
                    </div>
                    <div className="rounded-lg border border-border bg-muted/20 p-3">
                      <p className="text-xs text-muted-foreground">已计划章节</p>
                      <p className="mt-1 text-lg font-semibold">
                        {String((summary as any).planned_chapters_count ?? 0)}
                      </p>
                    </div>
                    <div className="rounded-lg border border-border bg-muted/20 p-3">
                      <p className="text-xs text-muted-foreground">下一章有计划</p>
                      <p className="mt-1 text-lg font-semibold">
                        {(summary as any).has_next_chapter_plan ? "是" : "否"}
                      </p>
                    </div>
                  </div>
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  <div className="rounded-xl border border-border bg-background/30 p-4">
                    <p className="text-sm font-medium">open_plots（未完结线）</p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      当前未完结线数量：<span className="font-semibold">{summary.open_plots_count}</span>
                    </p>
                    <div className="mt-3 space-y-2">
                      {summary.open_plots_preview.length ? (
                        <ul className="space-y-1.5 text-xs text-muted-foreground">
                          {summary.open_plots_preview.map((x, i) => (
                            <li key={`${i}-${x}`} className="line-clamp-1">
                              {x}
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="text-xs text-muted-foreground">暂无（open_plots 空）</p>
                      )}
                    </div>
                  </div>

                  <div className="rounded-xl border border-border bg-background/30 p-4">
                    <p className="text-sm font-medium">canonical_timeline（时间线账本）</p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      条目数：<span className="font-semibold">{summary.canonical_timeline_count}</span>
                      {summary.canonical_timeline_last_chapter_no != null ? (
                        <span className="ml-2">
                          最后覆盖：第{" "}
                          <span className="font-semibold">
                            {summary.canonical_timeline_last_chapter_no}
                          </span>
                          章
                        </span>
                      ) : null}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      最近一条：新增坑{" "}
                      <span className="font-semibold">
                        {String((summary as any).canonical_timeline_last_added_n ?? 0)}
                      </span>{" "}
                      · 收束坑{" "}
                      <span className="font-semibold">
                        {String((summary as any).canonical_timeline_last_resolved_n ?? 0)}
                      </span>
                    </p>
                    <div className="mt-3 space-y-2">
                      {summary.canonical_timeline_preview.length ? (
                        <ul className="space-y-1.5 text-xs text-muted-foreground">
                          {summary.canonical_timeline_preview.map((x, i) => (
                            <li key={`${i}-${x}`} className="line-clamp-2">
                              {x}
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="text-xs text-muted-foreground">
                          暂无预览（可能还未完成一次时间线账本刷新）
                        </p>
                      )}
                    </div>
                  </div>
                </div>

                <div className="rounded-xl border border-border bg-background/30 p-4">
                  <p className="text-sm font-medium">章节状态分布</p>
                  <div className="mt-3 grid gap-2 sm:grid-cols-4">
                    <div className="rounded-lg border border-border bg-muted/20 p-3">
                      <p className="text-xs text-muted-foreground">已审定 approved</p>
                      <p className="mt-1 text-lg font-semibold">{summary.approved_count}</p>
                    </div>
                    <div className="rounded-lg border border-border bg-muted/20 p-3">
                      <p className="text-xs text-muted-foreground">待审 pending_review</p>
                      <p className="mt-1 text-lg font-semibold">{summary.pending_review_count}</p>
                    </div>
                    <div className="rounded-lg border border-border bg-muted/20 p-3">
                      <p className="text-xs text-muted-foreground">最后已审定</p>
                      <p className="mt-1 text-lg font-semibold">
                        {summary.last_approved_chapter_no ?? "-"}
                      </p>
                    </div>
                    <div className="rounded-lg border border-border bg-muted/20 p-3">
                      <p className="text-xs text-muted-foreground">记忆版本</p>
                      <p className="mt-1 text-lg font-semibold">{summary.memory_version}</p>
                    </div>
                  </div>
                  <div className="mt-3 text-xs text-muted-foreground">
                    最近两条已审定是否连续：{" "}
                    <span className="font-semibold">
                      {summary.is_consecutive_last_two_approved ? "是" : "否"}
                    </span>
                    {summary.prev_approved_chapter_no != null && summary.last_approved_chapter_no != null ? (
                      <span className="ml-2">
                        （第{summary.prev_approved_chapter_no}章 → 第{summary.last_approved_chapter_no}章）
                      </span>
                    ) : null}
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          <div className="space-y-4">
            <Card className="bg-card/60">
              <CardHeader>
                <CardTitle>当前设定（连贯性策略）</CardTitle>
                <CardDescription>这是后端当前生效的关键参数快照（不含任何密钥）。</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="rounded-xl border border-border bg-background/30 p-4">
                  <p className="text-sm font-medium">摘要刷新</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <span className="rounded-full border border-border bg-muted/20 px-3 py-1 text-xs">
                      参与章数：{config.novel_memory_refresh_chapters}
                    </span>
                    <span className="rounded-full border border-border bg-muted/20 px-3 py-1 text-xs">
                      mode：{config.novel_chapter_summary_mode}
                    </span>
                    <span className="rounded-full border border-border bg-muted/20 px-3 py-1 text-xs">
                      tail：{config.novel_chapter_summary_tail_chars}c
                    </span>
                    <span className="rounded-full border border-border bg-muted/20 px-3 py-1 text-xs">
                      head：{config.novel_chapter_summary_head_chars}c
                    </span>
                  </div>
                </div>

                <div className="rounded-xl border border-border bg-background/30 p-4">
                  <p className="text-sm font-medium">生成一致性核对</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <span
                      className={
                        config.novel_consistency_check_chapter
                          ? "rounded-full border border-primary/30 bg-primary/10 px-3 py-1 text-xs text-primary"
                          : "rounded-full border border-border bg-muted/20 px-3 py-1 text-xs text-muted-foreground"
                      }
                    >
                      {config.novel_consistency_check_chapter ? "开启" : "关闭"}
                    </span>
                    <span className="rounded-full border border-border bg-muted/20 px-3 py-1 text-xs">
                      temperature：{config.novel_consistency_check_temperature}
                    </span>
                  </div>
                  <p className="mt-3 text-xs text-muted-foreground">
                    启用后每章会额外进行一次低温核对/小幅修订，显著降低设定偏移风险。
                  </p>
                </div>
              </CardContent>
            </Card>

            <Card className="bg-card/60">
              <CardHeader>
                <CardTitle>观察指标清单（你该看什么）</CardTitle>
                <CardDescription>这是一份“肉眼检查清单”，用于几十章长连载滚动复查。</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="rounded-xl border border-border bg-background/30 p-4">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <Gauge className="size-4" />
                    偏移风险最高的三件事
                  </div>
                  <ul className="mt-2 space-y-2 text-xs text-muted-foreground list-disc pl-5">
                    <li>
                      `open_plots` 越多越容易“忘记继续哪条线”，所以它越少越好。
                    </li>
                    <li>
                      `canonical_timeline` 如果更新频率/覆盖度跟不上，后文就难以保持因果一致。
                    </li>
                    <li>
                      最近两次已审定是否连续：不连续时需要更强衔接证据（时间线账本 + 核对）。
                    </li>
                  </ul>
                </div>
                <div className="rounded-xl border border-border bg-background/30 p-4">
                  <p className="text-sm font-medium">建议操作（当指标偏低）</p>
                  <p className="mt-2 text-xs text-muted-foreground">
                    先点一次“根据已审定章节刷新记忆”，再观察 `open_plots` 是否收敛；
                    若仍不稳，保留 `consistency check`，并适当提高 tail/head 或参与章数。
                  </p>
                </div>
              </CardContent>
            </Card>

          </div>
        </div>
      </div>
    </div>
  );
}

