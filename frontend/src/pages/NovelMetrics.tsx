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
import { clamp01 } from "@/lib/workspaceUtils";
import { ringTone } from "@/lib/statusTone";

type NovelMetrics = Awaited<ReturnType<typeof getNovelMetrics>>;

function RiskRing({
  title,
  subtitle,
  value01,
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
    <div className="glass-panel-subtle flex items-center gap-4 p-4">
      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-muted text-muted-foreground">
        <Icon className="size-4" />
      </div>
      <div className="flex flex-1 items-center justify-between gap-4">
        <div>
          <p className="text-sm font-medium">{title}</p>
          <p className="mt-0.5 font-mono text-xs text-muted-foreground">{subtitle}</p>
        </div>
        <div className="relative flex items-center justify-center">
          <svg width="100" height="100" viewBox="0 0 100 100">
            <circle
              cx="50"
              cy="50"
              r={r}
              stroke="hsl(var(--border))"
              strokeWidth="8"
              fill="none"
            />
            <circle
              cx="50"
              cy="50"
              r={r}
              stroke="hsl(var(--primary))"
              strokeWidth="8"
              strokeLinecap="round"
              strokeDasharray={`${c} ${c}`}
              strokeDashoffset={dashOffset}
              fill="none"
              transform="rotate(-90 50 50)"
            />
          </svg>
          <div className="absolute text-center">
            <div className={`text-lg font-semibold tabular-nums ${ringTone(value)}`}>
              {Math.round(value * 100)}%
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function metricChip(label: string, value: string) {
  return (
    <span className="glass-chip">
      {label}: <span className="font-medium text-foreground">{value}</span>
    </span>
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
      return { openEvidence: 0.5, timelineEvidence: 0.5, continuityEvidence: 0.5, overallEvidence: 0.5 };
    }
    const openRisk = clamp01((s.open_plots_count || 0) / 12);
    const openEvidence = 1 - openRisk;
    const approvedCount = Math.max(1, s.approved_count || 0);
    const coverage = clamp01((s.canonical_timeline_count || 0) / approvedCount);
    const timelineEvidence = coverage;
    const continuityEvidence = s.is_consecutive_last_two_approved ? 0.85 : 0.35;
    const overallEvidence = clamp01((openEvidence + timelineEvidence + continuityEvidence) / 3);
    return { openEvidence, timelineEvidence, continuityEvidence, overallEvidence };
  }, [metrics]);

  if (!metrics) {
    return (
      <div className="min-h-screen bg-background p-6">
        <div className="mx-auto max-w-5xl">
          <div className="rounded-lg border border-border bg-card p-6">
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
  const nextChapterNo = summary.next_chapter_no ?? null;
  const currentArcTitle = summary.current_arc_title || "（未命中 arcs）";
  const currentArcFrom =
    typeof summary.current_arc_from === "number" || typeof summary.current_arc_from === "string"
      ? String(summary.current_arc_from) : null;
  const currentArcTo =
    typeof summary.current_arc_to === "number" || typeof summary.current_arc_to === "string"
      ? String(summary.current_arc_to) : null;
  const currentArcRange =
    currentArcFrom != null && currentArcTo != null ? `第${currentArcFrom}—${currentArcTo}章` : null;
  const pacingFlags = summary.pacing_flags ?? [];
  const volumesCount = summary.volumes_count ?? 0;
  const plannedChaptersCount = summary.planned_chapters_count ?? 0;
  const hasNextChapterPlan = summary.has_next_chapter_plan ?? false;
  const canonicalTimelineLastAdded =
    summary.canonical_timeline_last_editable?.open_plots_added.length ?? 0;
  const canonicalTimelineLastResolved =
    summary.canonical_timeline_last_editable?.open_plots_resolved.length ?? 0;

  return (
    <div className="novel-shell">
      <div className="novel-container space-y-5">
        {/* Header */}
        <div className="glass-panel p-6 md:p-8">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-muted-foreground">
                <BookOpen className="size-4" />
                <span className="mono-label">连贯性观察指标</span>
              </div>
              <h1 className="text-3xl font-semibold tracking-tight">{novel.title}</h1>
              <p className="font-mono text-xs text-muted-foreground">
                framework: {novel.framework_confirmed ? "已确认" : "未确认"} · 状态: {novel.status}
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

        {/* Summary stats */}
        <div className="grid gap-3 md:grid-cols-4">
          {[
            ["已审定章节", String(summary.approved_count)],
            ["未完结线", String(summary.open_plots_count)],
            ["时间线账本", String(summary.canonical_timeline_count)],
            ["记忆版本", String(summary.memory_version)],
          ].map(([label, value]) => (
            <div key={label} className="glass-panel-subtle p-4">
              <p className="mono-label">{label}</p>
              <p className="mt-2 text-2xl font-semibold tracking-tight text-foreground">{value}</p>
            </div>
          ))}
        </div>

        {/* Main content */}
        <div className="grid gap-4 lg:grid-cols-3">
          <div className="space-y-4 lg:col-span-2">
            <Card>
              <CardHeader>
                <CardTitle>防偏移 · 连贯性证据</CardTitle>
                <CardDescription>越高越好 — 把漂移风险拆成可视化信号。</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="grid gap-3 md:grid-cols-2">
                  <RiskRing
                    title="未完结线 open_plots"
                    subtitle="线越少，越不容易断线"
                    value01={riskModel.openEvidence}
                    icon={Zap}
                  />
                  <RiskRing
                    title="时间线账本覆盖"
                    subtitle="越贴近审定进度越稳"
                    value01={riskModel.timelineEvidence}
                    icon={ShieldCheck}
                  />
                </div>
                <RiskRing
                  title="章节连续性"
                  subtitle={
                    summary.is_consecutive_last_two_approved
                      ? "最近两次已审定连续"
                      : "最近两次已审定不连续"
                  }
                  value01={riskModel.continuityEvidence}
                  icon={Thermometer}
                />
                <div className="glass-panel-subtle p-4">
                  <div className="flex items-center justify-between">
                    <p className="text-sm font-medium">综合证据</p>
                    <p className="font-mono text-xs text-muted-foreground">
                      {Math.round(riskModel.overallEvidence * 100)}%
                    </p>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {metricChip("总体策略", "偏连贯（tail/head/核对）")}
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>关键指标</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="glass-panel-subtle p-4">
                  <p className="text-sm font-medium">节奏对齐</p>
                  <p className="mt-1 font-mono text-xs text-muted-foreground">
                    下一章: <span className="font-semibold text-foreground">{nextChapterNo ?? "-"}</span> ·
                    当前弧线: <span className="font-semibold text-foreground">{currentArcTitle}</span>
                    {currentArcRange ? <span className="ml-1">({currentArcRange})</span> : null}
                  </p>
                  <p className="mt-1 font-mono text-xs text-muted-foreground">
                    弧线节拍: <span className="font-semibold text-foreground">{summary.current_arc_has_beats ? "已提供" : "缺失"}</span>
                  </p>
                  {pacingFlags.length ? (
                    <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-amber-600 dark:text-amber-400">
                      {pacingFlags.map((x, i) => <li key={`${i}-${x}`}>{x}</li>)}
                    </ul>
                  ) : (
                    <p className="mt-2 font-mono text-xs text-muted-foreground">暂无节奏风险提示。</p>
                  )}
                  <div className="mt-3 grid gap-2 sm:grid-cols-3">
                    <div className="glass-panel-subtle p-3">
                      <p className="mono-label">卷数</p>
                      <p className="mt-1 text-lg font-semibold">{volumesCount}</p>
                    </div>
                    <div className="glass-panel-subtle p-3">
                      <p className="mono-label">已计划章节</p>
                      <p className="mt-1 text-lg font-semibold">{plannedChaptersCount}</p>
                    </div>
                    <div className="glass-panel-subtle p-3">
                      <p className="mono-label">下一章有计划</p>
                      <p className="mt-1 text-lg font-semibold">{hasNextChapterPlan ? "是" : "否"}</p>
                    </div>
                  </div>
                </div>

                <div className="grid gap-3 md:grid-cols-2">
                  <div className="glass-panel-subtle p-4">
                    <p className="text-sm font-medium">open_plots</p>
                    <p className="mt-1 font-mono text-xs text-muted-foreground">
                      当前: <span className="font-semibold text-foreground">{summary.open_plots_count}</span>
                    </p>
                    <div className="mt-3 space-y-1.5">
                      {summary.open_plots_preview.length ? (
                        summary.open_plots_preview.map((x, i) => (
                          <p key={`${i}-${x}`} className="line-clamp-1 font-mono text-xs text-muted-foreground">{x}</p>
                        ))
                      ) : (
                        <p className="font-mono text-xs text-muted-foreground">暂无</p>
                      )}
                    </div>
                  </div>
                  <div className="glass-panel-subtle p-4">
                    <p className="text-sm font-medium">canonical_timeline</p>
                    <p className="mt-1 font-mono text-xs text-muted-foreground">
                      条目: <span className="font-semibold text-foreground">{summary.canonical_timeline_count}</span>
                      {summary.canonical_timeline_last_chapter_no != null ? (
                        <span className="ml-1">最后: 第{summary.canonical_timeline_last_chapter_no}章</span>
                      ) : null}
                    </p>
                    <p className="mt-1 font-mono text-xs text-muted-foreground">
                      新增坑 <span className="font-semibold text-foreground">{canonicalTimelineLastAdded}</span> ·
                      收束坑 <span className="font-semibold text-foreground">{canonicalTimelineLastResolved}</span>
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Sidebar */}
          <div className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle>当前设定</CardTitle>
                <CardDescription>后端当前生效的关键参数快照。</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="glass-panel-subtle p-4">
                  <p className="text-sm font-medium">摘要刷新</p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {metricChip("参与章数", String(config.novel_memory_refresh_chapters))}
                    {metricChip("mode", config.novel_chapter_summary_mode)}
                    {metricChip("tail", `${config.novel_chapter_summary_tail_chars}c`)}
                    {metricChip("head", `${config.novel_chapter_summary_head_chars}c`)}
                  </div>
                </div>
                <div className="glass-panel-subtle p-4">
                  <p className="text-sm font-medium">生成一致性核对</p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <span className={`glass-chip ${config.novel_consistency_check_chapter ? "border-primary/30 text-primary" : ""}`}>
                      {config.novel_consistency_check_chapter ? "开启" : "关闭"}
                    </span>
                    {metricChip("temperature", String(config.novel_consistency_check_temperature))}
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>观察清单</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="glass-panel-subtle p-4">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <Gauge className="size-4" />
                    偏移风险最高的三件事
                  </div>
                  <ul className="mt-2 list-disc space-y-1.5 pl-5 font-mono text-xs text-muted-foreground">
                    <li>open_plots 越多越容易断线</li>
                    <li>canonical_timeline 覆盖度不够会导致因果不一致</li>
                    <li>最近两次已审定不连续时需要更强衔接</li>
                  </ul>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}
