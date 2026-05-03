import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Brain,
  ChevronDown,
  ChevronRight,
  Search,
  Zap,
  CheckCircle2,
  Activity,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { formatDateTime } from "@/lib/date";
import { statusTone, scoreBg } from "@/lib/statusTone";
import type {
  ChapterJudgeLatest,
  MemoryUpdateRun,
  NovelRetrievalLogItem,
  NovelWorkflowLatest,
} from "@/services/novelApi";

type NovelIntelPanelProps = {
  selectedChapter?: { chapter_no: number; title: string } | null;
  workflow: NovelWorkflowLatest | null;
  judge: ChapterJudgeLatest | null;
  retrievalLogs: NovelRetrievalLogItem[];
  memoryRuns?: MemoryUpdateRun[];
  evaluation?: {
    rubric?: { phases?: { id: string; name: string; metrics: string[] }[]; notes?: string };
    observed?: Record<string, unknown>;
  } | null;
  workflowLoading?: boolean;
  judgeLoading?: boolean;
  retrievalLoading?: boolean;
};

function parseJudgeSummary(summary: string) {
  const raw = summary || "";
  const infoMatch = raw.match(/info:(\d+)/);
  const warnMatch = raw.match(/warning:(\d+)/);
  const infoCount = infoMatch ? Number(infoMatch[1]) : 0;
  const warnCount = warnMatch ? Number(warnMatch[1]) : 0;
  let desc = raw.replace(/[\d.]+,?\s*info:\d+;?\s*warning:\d+,?\s*/, "").trim();
  if (desc.startsWith("重点关注:")) desc = desc.replace("重点关注:", "").trim();
  return { infoCount, warnCount, desc };
}

export function NovelIntelPanel({
  selectedChapter,
  workflow,
  judge,
  retrievalLogs,
  memoryRuns = [],
  evaluation,
  workflowLoading = false,
  judgeLoading = false,
  retrievalLoading = false,
}: NovelIntelPanelProps) {
  const [judgeExpanded, setJudgeExpanded] = useState(false);
  const [debugExpanded, setDebugExpanded] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);

  useEffect(() => {
    setJudgeExpanded(false);
  }, [selectedChapter?.chapter_no, judge?.id]);

  const workflowSteps = workflow?.steps ?? [];
  const latestEvents = workflow?.events.slice(-12) ?? [];
  const { infoCount, warnCount, desc: judgeDesc } = useMemo(
    () => parseJudgeSummary(judge?.summary || ""),
    [judge?.summary]
  );
  const score = Math.max(0, Math.min(100, Number(judge?.score ?? 0)));
  const observedEntries = Object.entries(evaluation?.observed ?? {});

  return (
    <>
      {/* Sticky monitor bar */}
      <div
        onClick={() => setModalOpen(true)}
        className="group sticky top-4 z-[40] mb-6 flex cursor-pointer items-center justify-between gap-4 overflow-hidden rounded-lg border border-border bg-card p-2 pl-4 pr-3 shadow-sm transition-all hover:border-foreground/20"
      >
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <div className="flex size-7 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
            <Zap className="size-3.5" />
          </div>
          <div className="flex items-center gap-2 overflow-hidden">
            <h4 className="whitespace-nowrap text-sm font-semibold text-foreground">叙事智控分析</h4>
            <span className="hidden whitespace-nowrap font-mono text-[10px] text-muted-foreground lg:inline">
              点击开启深度分析
            </span>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <div className={`flex items-center gap-1.5 rounded border px-2 py-0.5 ${statusTone(workflow?.status)}`}>
            <div className={`size-1.5 rounded-full ${workflow?.status === "running" ? "bg-current animate-pulse" : "bg-current opacity-40"}`} />
            <span className="font-mono text-[10px] uppercase">{workflow?.status || "idle"}</span>
          </div>
          <div className={`flex items-center gap-1 rounded border px-2 py-0.5 ${scoreBg(score)}`}>
            <span className="font-mono text-xs font-semibold">{score || "—"}</span>
          </div>
          <ChevronRight className="size-4 text-muted-foreground transition-colors group-hover:text-foreground" />
        </div>
      </div>

      {/* Full-screen dashboard dialog */}
      <Dialog open={modalOpen} onOpenChange={setModalOpen}>
        <DialogContent className="flex h-[85vh] w-[1200px] max-w-[92vw] flex-col overflow-hidden p-0">
          <DialogHeader className="shrink-0 border-b border-border p-6 pb-4">
            <div className="flex items-end justify-between gap-4">
              <div className="min-w-0 flex-1 space-y-1">
                <div className="inline-flex items-center gap-1.5 rounded border border-border bg-secondary px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                  <Zap className="size-3" />
                  Intelligence Dashboard
                </div>
                <DialogTitle className="truncate text-2xl font-semibold tracking-tight">
                  叙事智控分析终端
                </DialogTitle>
              </div>
              <div className="flex shrink-0 items-center gap-4">
                <div className="flex flex-col items-end">
                  <p className="mono-label">质量分数</p>
                  <p className={`text-lg font-semibold ${score >= 85 ? "text-emerald-500" : score >= 70 ? "text-amber-500" : "text-rose-500"}`}>
                    {score || "—"}
                  </p>
                </div>
                <div className="h-8 w-px bg-border" />
                <div className="flex flex-col items-end">
                  <p className="mono-label">RAG 命中</p>
                  <p className="text-lg font-semibold text-foreground">{retrievalLogs.length}</p>
                </div>
                <div className="h-8 w-px bg-border" />
                <div className="flex flex-col items-end">
                  <p className="mono-label">最近同步</p>
                  <p className="font-mono text-xs text-muted-foreground">
                    {workflow ? formatDateTime(workflow.updated_at).split(" ")[1] : "从未"}
                  </p>
                </div>
              </div>
            </div>
          </DialogHeader>

          <div className="flex-1 overflow-y-auto p-6">
            <div className="grid gap-6 lg:grid-cols-12">
              {/* Left: workflow */}
              <div className="space-y-6 lg:col-span-7">
                <div className="rounded-lg border border-border bg-card p-6 space-y-6">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 text-foreground">
                      <Activity className="size-4" />
                      <h4 className="text-sm font-semibold">实时执行态</h4>
                    </div>
                    <span className="rounded border border-border bg-secondary px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
                      Task: {workflow?.id?.slice(-8) || "None"}
                    </span>
                  </div>

                  {workflowLoading ? (
                    <div className="py-16 text-center font-mono text-xs text-muted-foreground animate-pulse">
                      正在建立同步链路...
                    </div>
                  ) : !workflow ? (
                    <div className="rounded-md border border-dashed border-border py-16 text-center">
                      <p className="text-sm text-muted-foreground">等待任务入队中</p>
                    </div>
                  ) : (
                    <div className="space-y-6">
                      <div className="grid grid-cols-2 gap-4">
                        <div className="rounded-md border border-border bg-secondary/50 p-4">
                          <p className="mono-label">当前阶段</p>
                          <h5 className="mt-1 truncate text-lg font-semibold">{workflow.current_step}</h5>
                        </div>
                        <div className="rounded-md border border-border bg-secondary/50 p-4">
                          <div className="flex items-end justify-between">
                            <p className="mono-label">执行进度</p>
                            <p className="font-mono text-xs text-muted-foreground">
                              {workflowSteps.length > 0
                                ? Math.round((workflowSteps.filter((s) => s.status === "done").length / workflowSteps.length) * 100)
                                : 0}%
                            </p>
                          </div>
                          <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-border">
                            <div
                              className="h-full bg-foreground transition-all duration-1000"
                              style={{ width: `${(workflowSteps.filter((s) => s.status === "done").length / (workflowSteps.length || 1)) * 100}%` }}
                            />
                          </div>
                        </div>
                      </div>

                      <div className="space-y-3">
                        <p className="mono-label">实时事件日志</p>
                        <div className="max-h-[360px] space-y-2 overflow-y-auto">
                          {latestEvents.map((e) => (
                            <div key={e.id} className="flex gap-4 rounded-md border border-border bg-secondary/30 p-3 transition-colors hover:border-foreground/20">
                              <div className={`mt-1.5 size-1.5 shrink-0 rounded-full ${e.level === "error" ? "bg-rose-500" : "bg-muted-foreground/30"}`} />
                              <div className="min-w-0 flex-1">
                                <p className="text-sm text-foreground">{e.message}</p>
                                <p className="mt-1 font-mono text-[10px] text-muted-foreground">
                                  {formatDateTime(e.created_at)} · {e.level}
                                </p>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* Right: judge + retrieval */}
              <div className="space-y-6 lg:col-span-5">
                {/* Judge */}
                <div className="rounded-lg border border-border bg-card p-6">
                  <div className="mb-4 flex items-center justify-between">
                    <div className="flex items-center gap-2 text-foreground">
                      <Brain className="size-4" />
                      <h4 className="text-sm font-semibold">审计分析</h4>
                    </div>
                    {selectedChapter && (
                      <span className="rounded border border-border bg-secondary px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
                        Ch.{selectedChapter.chapter_no}
                      </span>
                    )}
                  </div>

                  {judgeLoading ? (
                    <div className="py-16 text-center font-mono text-xs text-muted-foreground animate-pulse">
                      读取审计报告...
                    </div>
                  ) : !judge ? (
                    <div className="rounded-md border border-dashed border-border py-16 text-center">
                      <p className="text-sm text-muted-foreground">等待质量引擎介入</p>
                    </div>
                  ) : (
                    <div className="space-y-4">
                      <div className="flex flex-wrap gap-2">
                        {infoCount > 0 && (
                          <span className="inline-flex items-center gap-1.5 rounded border border-emerald-500/20 bg-emerald-500/5 px-2 py-0.5 font-mono text-[10px] text-emerald-600 dark:text-emerald-400">
                            <CheckCircle2 className="size-3" /> 建议 {infoCount}
                          </span>
                        )}
                        {warnCount > 0 && (
                          <span className="inline-flex items-center gap-1.5 rounded border border-amber-500/20 bg-amber-500/5 px-2 py-0.5 font-mono text-[10px] text-amber-600 dark:text-amber-400">
                            <AlertTriangle className="size-3" /> 风险 {warnCount}
                          </span>
                        )}
                      </div>

                      <div className="rounded-md border border-border bg-secondary/30 p-4">
                        <p className={`text-sm leading-relaxed text-muted-foreground ${!judgeExpanded ? "line-clamp-4" : ""}`}>
                          {judgeDesc}
                        </p>
                        {judgeDesc.length > 120 && (
                          <button
                            onClick={(e) => { e.stopPropagation(); setJudgeExpanded(!judgeExpanded); }}
                            className="mt-2 flex items-center gap-1 font-mono text-[10px] text-primary hover:underline"
                          >
                            {judgeExpanded ? "折叠" : "查看完整"}
                            <ChevronDown className={`size-3 transition-transform ${judgeExpanded ? "rotate-180" : ""}`} />
                          </button>
                        )}
                      </div>

                      <div className="space-y-2">
                        {judge.issues.slice(0, 4).map((issue) => (
                          <div key={issue.id} className="flex items-start gap-3 rounded-md border border-border bg-secondary/30 p-3 transition-colors hover:border-foreground/20">
                            <div className={`mt-1.5 size-1.5 shrink-0 rounded-full ${issue.severity === "high" || issue.severity === "critical" ? "bg-rose-500" : "bg-amber-500"}`} />
                            <div className="min-w-0">
                              <p className="text-sm font-medium text-foreground">{issue.title}</p>
                              <p className="mt-0.5 text-xs text-muted-foreground">{issue.suggestion}</p>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                {/* Retrieval */}
                <div className="rounded-lg border border-border bg-card p-6">
                  <div className="mb-4 flex items-center gap-2 text-foreground">
                    <Search className="size-4" />
                    <h4 className="text-sm font-semibold">语义召回证据</h4>
                  </div>
                  {retrievalLoading ? (
                    <div className="py-8 text-center font-mono text-xs text-muted-foreground animate-pulse">
                      搜寻证据中...
                    </div>
                  ) : retrievalLogs.length === 0 ? (
                    <p className="py-8 text-center font-mono text-xs text-muted-foreground">
                      未发生跨章检索
                    </p>
                  ) : (
                    <div className="max-h-[400px] space-y-3 overflow-y-auto">
                      {retrievalLogs.slice(0, 6).map((log) => (
                        <div key={log.id} className="space-y-2 rounded-md border border-border bg-secondary/30 p-3">
                          <div className="flex items-center justify-between gap-3">
                            <span className="flex-1 truncate font-mono text-[10px] text-muted-foreground">
                              {log.query_text}
                            </span>
                            <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
                              {log.latency_ms}ms
                            </span>
                          </div>
                          {log.result_json?.slice(0, 1).map((hit, idx) => (
                            <div key={idx} className="rounded border border-border bg-background p-2">
                              <p className="truncate font-mono text-[10px] text-muted-foreground">
                                {hit.title || "Recall Fragment"}
                              </p>
                              <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                                {(hit.content || hit.text || "").trim()}
                              </p>
                            </div>
                          ))}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* Debug console */}
          <div className="shrink-0 border-t border-border">
            <button
              onClick={() => setDebugExpanded(!debugExpanded)}
              className="flex w-full items-center justify-between px-6 py-3 font-mono text-[10px] uppercase tracking-wider text-muted-foreground hover:text-foreground transition-colors"
            >
              <span>Developer Debug Console</span>
              <ChevronDown className={`size-3.5 transition-transform ${debugExpanded ? "rotate-180" : ""}`} />
            </button>
            {debugExpanded && (
              <div className="grid gap-6 border-t border-border p-6 lg:grid-cols-2">
                <div className="space-y-3">
                  <p className="mono-label">Memory Update History</p>
                  <div className="max-h-48 space-y-1.5 overflow-y-auto">
                    {memoryRuns.map((run) => (
                      <div key={run.id} className="flex items-center justify-between rounded border border-border bg-secondary/30 p-2 font-mono text-[10px]">
                        <span className="flex-1 truncate text-muted-foreground">{run.source} (Ch.{run.chapter_no})</span>
                        <span className={`shrink-0 rounded border px-1.5 py-0.5 ${statusTone(run.status)}`}>{run.status}</span>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="space-y-3">
                  <p className="mono-label">System Observations</p>
                  <div className="grid max-h-48 grid-cols-2 gap-1.5 overflow-y-auto font-mono text-[10px]">
                    {observedEntries.map(([k, v]) => (
                      <div key={k} className="flex flex-col gap-1 overflow-hidden rounded border border-border bg-secondary/30 p-2">
                        <span className="truncate text-muted-foreground">{k}</span>
                        <span className="truncate font-medium text-foreground">{String(v)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
