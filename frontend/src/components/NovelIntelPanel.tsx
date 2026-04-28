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
  Sparkles
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type {
  ChapterJudgeLatest,
  MemoryUpdateRun,
  NovelRetrievalLogItem,
  NovelWorkflowLatest,
} from "@/services/novelApi";

type NovelIntelPanelProps = {
  selectedChapter?: {
    chapter_no: number;
    title: string;
  } | null;
  workflow: NovelWorkflowLatest | null;
  judge: ChapterJudgeLatest | null;
  retrievalLogs: NovelRetrievalLogItem[];
  memoryRuns?: MemoryUpdateRun[];
  evaluation?: {
    rubric?: {
      phases?: { id: string; name: string; metrics: string[] }[];
      notes?: string;
    };
    observed?: Record<string, unknown>;
  } | null;
  workflowLoading?: boolean;
  judgeLoading?: boolean;
  retrievalLoading?: boolean;
};

function formatDateTime(value?: string | null): string {
  if (!value) return "暂无";
  
  // 处理 naive UTC 字符串：如果后端没带 Z 或偏移量，补上 Z 告诉 JS 这是 UTC
  let raw = String(value);
  if (!raw.endsWith("Z") && !raw.includes("+") && !/T\d{2}:\d{2}:\d{2}(\.\d+)?$/.test(raw)) {
    raw += "Z";
  }
  
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return "暂无";
  
  // 转换为北京时间 (UTC+8)
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).format(date);
}

function statusTone(status?: string) {
  const s = (status || "").toLowerCase();
  switch (s) {
    case "done":
    case "completed":
    case "approved":
    case "success":
      return "text-emerald-500 bg-emerald-500/10 border-emerald-500/20";
    case "running":
    case "started":
    case "pending_review":
    case "queued":
    case "active":
      return "text-sky-500 bg-sky-500/10 border-sky-500/20";
    case "failed":
    case "blocked":
    case "error":
    case "critical":
    case "high":
      return "text-rose-500 bg-rose-500/10 border-rose-500/20";
    case "skipped":
    case "warning":
    case "medium":
      return "text-amber-500 bg-amber-500/10 border-amber-500/20";
    default:
      return "text-foreground/40 bg-background/60 border-border/40";
  }
}

function scoreBg(score: number) {
  if (score >= 85) return "text-emerald-500 border-emerald-500/20 bg-emerald-500/10";
  if (score >= 70) return "text-amber-500 border-amber-500/20 bg-amber-500/10";
  return "text-rose-500 border-rose-500/20 bg-rose-500/10";
}

/** 解析 Judge Summary 中的 info:N; warning:N; 等结构化信息 */
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
      {/* 1. 浮动监控条 (Sticky Monitor Bar) */}
      <div 
        onClick={() => setModalOpen(true)}
        className="group sticky top-4 z-[40] mb-6 flex cursor-pointer items-center justify-between gap-4 overflow-hidden rounded-2xl border border-white/10 bg-background/40 p-1.5 pl-4 pr-3 backdrop-blur-xl shadow-lg transition-all hover:bg-background/60 hover:shadow-xl active:scale-[0.98]"
      >
        <div className="flex items-center gap-3 min-w-0 flex-1">
          <div className="flex size-8 items-center justify-center rounded-xl bg-primary/10 text-primary shrink-0">
            <Zap className="size-4" />
          </div>
          <div className="flex items-center gap-2 overflow-hidden">
            <h4 className="text-sm font-black text-foreground/80 whitespace-nowrap">叙事智控分析</h4>
            <span className="text-[10px] font-bold text-foreground/20 uppercase tracking-widest hidden lg:inline whitespace-nowrap">• 点击开启深度分析分析终端</span>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <div className={`flex items-center gap-2 rounded-lg border px-2 py-1 ${statusTone(workflow?.status)}`}>
            <div className={`size-1.5 rounded-full ${workflow?.status === 'running' ? 'bg-current animate-pulse' : 'bg-current opacity-40'}`} />
            <span className="text-[10px] font-black uppercase tracking-tighter">{workflow?.status || "Idle"}</span>
          </div>
          <div className={`flex items-center gap-1.5 rounded-lg border px-2 py-1 ${scoreBg(score)}`}>
            <span className="text-xs font-black tracking-tighter">{score || "—"}</span>
            <span className="text-[9px] font-bold uppercase opacity-60">Pts</span>
          </div>
          <ChevronRight className="size-4 text-foreground/20 group-hover:text-foreground/40 transition-colors" />
        </div>
      </div>

      {/* 2. 全屏仪表盘弹窗 */}
      <Dialog open={modalOpen} onOpenChange={setModalOpen}>
        <DialogContent className="max-w-[92vw] w-[1200px] h-[85vh] p-0 overflow-hidden rounded-[2.5rem] border-white/10 bg-background/60 backdrop-blur-3xl shadow-[0_0_80px_rgba(0,0,0,0.3)] flex flex-col">
          <DialogHeader className="p-8 pb-4 flex flex-row items-end justify-between space-y-0 shrink-0">
            <div className="space-y-1.5 flex-1 min-w-0">
              <div className="inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/8 px-3 py-1 text-[10px] font-black uppercase tracking-widest text-primary/80">
                <Zap className="size-3" />
                Intelligence Dashboard
              </div>
              <DialogTitle className="text-3xl font-black tracking-tighter sm:text-4xl truncate">
                叙事智控分析终端
              </DialogTitle>
            </div>
            
            <div className="flex items-center gap-4 shrink-0">
               <div className="flex flex-col items-end">
                 <p className="text-[10px] font-black text-foreground/20 uppercase tracking-widest">质量分数</p>
                 <p className={`text-xl font-black ${score >= 85 ? 'text-emerald-500' : score >= 70 ? 'text-amber-500' : 'text-rose-500'}`}>{score || "—"}</p>
               </div>
               <div className="w-px h-8 bg-white/5" />
               <div className="flex flex-col items-end">
                 <p className="text-[10px] font-black text-foreground/20 uppercase tracking-widest">RAG 命中</p>
                 <p className="text-xl font-black text-violet-500">{retrievalLogs.length}</p>
               </div>
               <div className="w-px h-8 bg-white/5" />
               <div className="flex flex-col items-end">
                 <p className="text-[10px] font-black text-foreground/20 uppercase tracking-widest">最近同步</p>
                 <p className="text-sm font-black text-foreground/60">{workflow ? formatDateTime(workflow.updated_at).split(' ')[1] : "从未"}</p>
               </div>
            </div>
          </DialogHeader>

          <div className="flex-1 overflow-y-auto p-8 pt-4 custom-scrollbar">
            <div className="grid gap-8 lg:grid-cols-12">
              <div className="lg:col-span-7 space-y-8">
                <div className="rounded-[2.5rem] border border-white/5 bg-background/40 p-8 shadow-2xl space-y-8">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3 text-sky-500">
                      <Activity className="size-6" />
                      <h4 className="text-xl font-black text-foreground">实时执行态</h4>
                    </div>
                    <span className="font-mono text-[10px] font-bold text-foreground/20 bg-white/5 px-3 py-1 rounded-full uppercase tracking-widest">
                      Task: {workflow?.id?.slice(-8) || "None"}
                    </span>
                  </div>

                  {workflowLoading ? (
                    <div className="py-24 text-center animate-pulse text-foreground/20 font-black text-lg">正在建立同步链路...</div>
                  ) : !workflow ? (
                    <div className="py-24 text-center border-2 border-dashed border-white/5 rounded-[2rem]">
                      <p className="text-base font-bold text-foreground/20 italic">“等待任务入队中”</p>
                    </div>
                  ) : (
                    <div className="space-y-10">
                      <div className="grid grid-cols-2 gap-6">
                        <div className="rounded-3xl border border-sky-500/10 bg-sky-500/5 p-6">
                          <p className="text-[11px] font-black uppercase tracking-widest text-sky-500/40 mb-2">当前阶段</p>
                          <h5 className="text-2xl font-black text-sky-600 dark:text-sky-400 truncate">{workflow.current_step}</h5>
                        </div>
                        <div className="rounded-3xl border border-white/5 bg-white/5 p-6 flex flex-col justify-center">
                          <div className="flex items-end justify-between">
                            <p className="text-[11px] font-black uppercase tracking-widest text-foreground/20 mb-1">执行进度</p>
                            <p className="text-2xl font-black text-foreground/10">
                              {workflowSteps.length > 0 ? Math.round((workflowSteps.filter(s=>s.status==='done').length / workflowSteps.length) * 100) : 0}%
                            </p>
                          </div>
                          <div className="mt-3 w-full h-1.5 bg-white/5 rounded-full overflow-hidden">
                            <div 
                              className="h-full bg-sky-500 transition-all duration-1000 ease-out" 
                              style={{ width: `${(workflowSteps.filter(s=>s.status==='done').length / (workflowSteps.length || 1)) * 100}%` }}
                            />
                          </div>
                        </div>
                      </div>

                      <div className="space-y-4">
                        <p className="text-[11px] font-black uppercase text-foreground/20 tracking-[0.2em]">实时系统事件日志</p>
                        <div className="space-y-3 max-h-[360px] overflow-y-auto pr-4 custom-scrollbar">
                          {latestEvents.map(e => (
                            <div key={e.id} className="group relative flex gap-6 p-4 rounded-3xl bg-white/5 border border-white/5 hover:border-white/10 transition-all hover:translate-x-1">
                              <div className={`mt-2 size-2 rounded-full shrink-0 ${e.level === 'error' ? 'bg-rose-500 shadow-[0_0_12px_rgba(244,63,94,0.6)]' : 'bg-foreground/10'}`} />
                              <div className="min-w-0 flex-1">
                                <p className="text-sm leading-relaxed text-foreground/80 font-medium">{e.message}</p>
                                <p className="mt-2 font-mono text-[10px] font-bold text-foreground/20 uppercase">
                                  {formatDateTime(e.created_at)} • Level: {e.level}
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

              <div className="lg:col-span-5 space-y-8">
                <div className="rounded-[2.5rem] border border-white/5 bg-background/40 p-8 shadow-2xl min-h-[400px]">
                  <div className="mb-8 flex items-center justify-between">
                    <div className="flex items-center gap-3 text-emerald-500">
                      <Brain className="size-6" />
                      <h4 className="text-xl font-black text-foreground">审计分析</h4>
                    </div>
                    {selectedChapter && (
                      <span className="text-xs font-black bg-emerald-500/10 text-emerald-600 px-4 py-1.5 rounded-xl border border-emerald-500/20 uppercase tracking-widest shrink-0">
                        Ch.{selectedChapter.chapter_no}
                      </span>
                    )}
                  </div>

                  {judgeLoading ? (
                    <div className="py-20 text-center animate-pulse text-foreground/20 font-black text-lg">读取审计报告...</div>
                  ) : !judge ? (
                    <div className="py-20 text-center border-2 border-dashed border-white/5 rounded-[2rem]">
                      <p className="text-sm font-bold text-foreground/20 italic">“等待质量引擎介入”</p>
                    </div>
                  ) : (
                    <div className="space-y-8">
                      <div className="flex flex-wrap gap-2.5">
                        {infoCount > 0 && (
                          <span className="inline-flex items-center gap-2 rounded-xl border border-emerald-500/20 bg-emerald-500/5 px-3 py-1.5 text-[11px] font-black text-emerald-600 uppercase">
                            <CheckCircle2 className="size-3.5" /> 建议 {infoCount}
                          </span>
                        )}
                        {warnCount > 0 && (
                          <span className="inline-flex items-center gap-2 rounded-xl border border-amber-500/20 bg-amber-500/5 px-3 py-1.5 text-[11px] font-black text-amber-600 uppercase">
                            <AlertTriangle className="size-3.5" /> 风险 {warnCount}
                          </span>
                        )}
                      </div>

                      <div className="relative p-6 rounded-3xl bg-white/5 border border-white/5 overflow-hidden">
                        <div className="absolute top-0 right-0 p-4 opacity-5 pointer-events-none">
                          <Sparkles className="size-20" />
                        </div>
                        <p className={`text-base leading-9 text-foreground/80 font-medium italic ${!judgeExpanded ? 'line-clamp-4' : ''}`}>
                          “{judgeDesc}”
                        </p>
                        {judgeDesc.length > 120 && (
                          <button 
                            onClick={(e) => { e.stopPropagation(); setJudgeExpanded(!judgeExpanded); }}
                            className="mt-4 flex items-center gap-2 text-[11px] font-black text-emerald-500/60 hover:text-emerald-500 uppercase tracking-widest transition-all"
                          >
                            {judgeExpanded ? '折叠简报' : '查看完整摘要'}
                            <ChevronDown className={`size-3.5 transition-transform ${judgeExpanded ? 'rotate-180' : ''}`} />
                          </button>
                        )}
                      </div>

                      <div className="space-y-4">
                        {judge.issues.slice(0, 4).map(issue => (
                          <div key={issue.id} className="group/issue flex items-start gap-5 p-5 rounded-[2rem] bg-white/5 border border-white/5 hover:border-white/20 transition-all">
                            <div className={`mt-2 size-2.5 rounded-full shrink-0 ${issue.severity === 'high' || issue.severity === 'critical' ? 'bg-rose-500 shadow-[0_0_15px_rgba(244,63,94,0.7)]' : 'bg-amber-500 shadow-[0_0_15px_rgba(245,158,11,0.7)]'}`} />
                            <div className="min-w-0">
                              <p className="text-base font-black text-foreground/90 group-hover/issue:text-emerald-500 transition-colors">{issue.title}</p>
                              <p className="mt-2 text-sm leading-relaxed text-foreground/40">{issue.suggestion}</p>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                <div className="rounded-[2.5rem] border border-white/5 bg-background/40 p-8 shadow-2xl">
                  <div className="mb-6 flex items-center justify-between">
                    <div className="flex items-center gap-3 text-violet-500">
                      <Search className="size-6" />
                      <h4 className="text-xl font-black text-foreground">语义召回证据</h4>
                    </div>
                  </div>
                  
                  {retrievalLoading ? (
                    <div className="py-12 text-center animate-pulse text-foreground/10 font-bold">搜寻证据中...</div>
                  ) : retrievalLogs.length === 0 ? (
                    <p className="text-sm font-bold text-foreground/10 italic text-center py-8 underline underline-offset-8 decoration-dashed">未发生跨章检索</p>
                  ) : (
                    <div className="space-y-4 max-h-[400px] overflow-y-auto pr-2 custom-scrollbar">
                      {retrievalLogs.slice(0, 6).map(log => (
                        <div key={log.id} className="p-5 rounded-3xl bg-violet-500/5 border border-violet-500/10 space-y-4">
                          <div className="flex items-center justify-between gap-4">
                            <span className="text-[10px] font-black text-violet-500 uppercase tracking-[0.2em] truncate flex-1">{log.query_text}</span>
                            <span className="text-[10px] font-mono font-bold text-foreground/20 shrink-0">{log.latency_ms}ms</span>
                          </div>
                          
                          {log.result_json?.slice(0, 1).map((hit, idx) => (
                            <div key={idx} className="p-4 rounded-2xl bg-background/40 border border-white/5">
                              <p className="text-[11px] font-black text-foreground/50 mb-2 truncate">{hit.title || "Recall Fragment"}</p>
                              <p className="text-xs leading-relaxed text-foreground/30 line-clamp-3">{(hit.content || hit.text || "").trim()}</p>
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

          <div className="mt-auto border-t border-white/5 shrink-0 bg-background/20">
            <button 
              onClick={() => setDebugExpanded(!debugExpanded)}
              className="flex w-full items-center justify-between px-8 py-4 text-[10px] font-black uppercase tracking-[0.3em] text-foreground/20 hover:text-foreground/50 transition-colors"
            >
              <span>Developer Debug Console</span>
              <ChevronDown className={`size-4 transition-transform duration-500 ${debugExpanded ? 'rotate-180' : ''}`} />
            </button>
            
            {debugExpanded && (
              <div className="px-8 pb-8 grid gap-12 lg:grid-cols-2 animate-in fade-in slide-in-from-bottom-4 duration-500">
                <div className="space-y-4">
                  <p className="text-[11px] font-black text-foreground/40 flex items-center gap-3">
                    <span className="size-1.5 rounded-full bg-primary" /> Memory Update History
                  </p>
                  <div className="max-h-48 overflow-y-auto space-y-2 pr-4 custom-scrollbar">
                    {memoryRuns.map(run => (
                      <div key={run.id} className="flex items-center justify-between p-4 rounded-2xl bg-white/5 border border-white/5 font-mono text-[10px]">
                        <span className="text-foreground/40 truncate flex-1 pr-4">{run.source} (Ch.{run.chapter_no})</span>
                        <span className={`shrink-0 px-2 py-0.5 rounded-lg border ${statusTone(run.status)}`}>{run.status}</span>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="space-y-4">
                  <p className="text-[11px] font-black text-foreground/40 flex items-center gap-3">
                    <span className="size-1.5 rounded-full bg-primary" /> System Observations
                  </p>
                  <div className="max-h-48 overflow-y-auto grid grid-cols-2 gap-3 pr-4 custom-scrollbar font-mono text-[10px]">
                    {observedEntries.map(([k, v]) => (
                      <div key={k} className="p-3 rounded-2xl bg-white/5 border border-white/5 flex flex-col gap-1.5 overflow-hidden">
                        <span className="text-foreground/20 uppercase tracking-tighter truncate">{k}</span>
                        <span className="text-foreground/60 font-bold truncate">{String(v)}</span>
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
