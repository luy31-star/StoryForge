import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { User, Settings, Sun, Moon, Monitor, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  addChapterFeedback,
  applyChapterRevision,
  approveChapter,
  chapterContextChatStream,
  consistencyFixChapter,
  clearVolumeChapterPlans,
  confirmFramework,
  deleteChapter,
  discardChapterRevision,
  generateChapters,
  generateFramework,
  generateVolumeChapterPlan,
  generateVolumes,
  getMemory,
  getMemoryNormalized,
  rebuildMemoryNormalized,
  listGenerationLogs,
  type NormalizedMemoryPayload,
  listVolumeChapterPlan,
  listVolumes,
  manualFixMemory,
  getNovel,
  listChapters,
  patchChapter,
  patchNovel,
  refreshMemory,
  regenerateChapterPlan,
  reviseChapter,
  getLlmConfig,
  setLlmConfig,
} from "@/services/novelApi";

function formatVolumePlanBeatsText(beats: unknown): string {
  if (!beats || typeof beats !== "object" || Array.isArray(beats)) {
    return typeof beats === "string" ? beats : JSON.stringify(beats);
  }
  const b = beats as Record<string, unknown>;
  const lines: string[] = [];
  if (typeof b.plot_summary === "string" && b.plot_summary.trim()) {
    lines.push(`梗概：${b.plot_summary.trim()}`);
  }
  if (typeof b.stage_position === "string" && b.stage_position.trim()) {
    lines.push(`阶段位置：${b.stage_position.trim()}`);
  }
  if (typeof b.pacing_justification === "string" && b.pacing_justification.trim()) {
    lines.push(`节奏说明：${b.pacing_justification.trim()}`);
  }
  const pa = b.progress_allowed;
  if (typeof pa === "string" && pa.trim()) {
    lines.push(`允许推进：${pa.trim()}`);
  } else if (Array.isArray(pa) && pa.length) {
    lines.push(`允许推进：\n${pa.map((x) => `  · ${String(x)}`).join("\n")}`);
  }
  if (Array.isArray(b.must_not) && b.must_not.length) {
    lines.push(`禁止：\n${b.must_not.map((x) => `  · ${String(x)}`).join("\n")}`);
  }
  const rsv = b.reserved_for_later;
  if (Array.isArray(rsv) && rsv.length) {
    const parts = rsv
      .map((item) => {
        if (item && typeof item === "object" && !Array.isArray(item)) {
          const o = item as Record<string, unknown>;
          const it = o.item;
          const nb = o.not_before_chapter;
          if (typeof it === "string" && it.trim()) {
            return typeof nb === "number"
              ? `  · 「${it.trim()}」须第${nb}章及之后`
              : `  · 「${it.trim()}」延后`;
          }
        }
        return "";
      })
      .filter(Boolean);
    if (parts.length) lines.push(`延后解锁：\n${parts.join("\n")}`);
  }
  if (
    typeof b.goal === "string" ||
    typeof b.conflict === "string" ||
    typeof b.turn === "string" ||
    typeof b.hook === "string"
  ) {
    lines.push(
      `目标：${typeof b.goal === "string" ? b.goal : ""}\n冲突：${typeof b.conflict === "string" ? b.conflict : ""}\n转折：${typeof b.turn === "string" ? b.turn : ""}\n钩子：${typeof b.hook === "string" ? b.hook : ""}`
    );
  }
  if (!lines.length) return JSON.stringify(beats);
  return lines.join("\n\n");
}

function fmtMetaValue(v: unknown): string {
  if (v == null) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

function summarizeLogMeta(
  event: string,
  meta: Record<string, unknown>
): { summary: string[]; detail?: string } {
  const summary: string[] = [];
  if (event === "chapter_memory_delta_applied") {
    const parts = [
      typeof meta.canonical_entries === "number" ? `时间线 +${meta.canonical_entries}` : "",
      typeof meta.open_plots_added === "number" ? `新增线索 +${meta.open_plots_added}` : "",
      typeof meta.open_plots_resolved === "number" ? `收束线索 ${meta.open_plots_resolved}` : "",
      typeof meta.characters_updated === "number" ? `角色更新 ${meta.characters_updated}` : "",
    ].filter(Boolean);
    if (parts.length) summary.push(parts.join(" · "));
  } else if (
    event === "chapter_memory_delta_failed" ||
    event === "memory_refresh_validation_failed"
  ) {
    const errors = Array.isArray(meta.errors)
      ? meta.errors.map((x) => String(x).trim()).filter(Boolean)
      : [];
    if (errors.length) summary.push(...errors.slice(0, 4));
    if (typeof meta.batch === "number") summary.push(`失败批次：第 ${meta.batch} 批`);
  } else if (event === "memory_refresh_done") {
    if (typeof meta.version === "number") summary.push(`新记忆版本：v${meta.version}`);
  }

  const extraEntries = Object.entries(meta).filter(([key]) => {
    if (event === "chapter_memory_delta_applied") {
      return ![
        "canonical_entries",
        "open_plots_added",
        "open_plots_resolved",
        "characters_updated",
      ].includes(key);
    }
    if (event === "chapter_memory_delta_failed" || event === "memory_refresh_validation_failed") {
      return !["errors", "batch"].includes(key);
    }
    if (event === "memory_refresh_done") {
      return key !== "version";
    }
    return true;
  });
  const detail = extraEntries.length
    ? extraEntries.map(([k, v]) => `${k}: ${fmtMetaValue(v)}`).join("\n")
    : undefined;
  return { summary, detail };
}

export function NovelWorkspace() {
  const { id = "" } = useParams();
  const [novel, setNovel] = useState<Record<string, unknown> | null>(null);
  const [chapters, setChapters] = useState<Awaited<ReturnType<typeof listChapters>>>([]);
  const [memory, setMemory] = useState<Awaited<ReturnType<typeof getMemory>> | null>(null);
  const [memoryNorm, setMemoryNorm] = useState<NormalizedMemoryPayload | null>(null);
  const [memoryNormRebuildBusy, setMemoryNormRebuildBusy] = useState(false);
  const [fwMd, setFwMd] = useState("");
  const [fwJson, setFwJson] = useState("{}");
  const [fbDraft, setFbDraft] = useState<Record<string, string>>({});
  const [revisePrompt, setRevisePrompt] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [generateTrace, setGenerateTrace] = useState<string>("");
  const [generateCount, setGenerateCount] = useState(1);
  const [useColdRecall, setUseColdRecall] = useState(false);
  const [coldRecallItems, setColdRecallItems] = useState(5);
  const [selectedChapterId, setSelectedChapterId] = useState<string>("");
  const [editTitle, setEditTitle] = useState("");
  const [editContent, setEditContent] = useState("");
  const [memoryFixBusy, setMemoryFixBusy] = useState(false);
  const [openPlotsLines, setOpenPlotsLines] = useState<string[]>([]);
  const [keyFactsLines, setKeyFactsLines] = useState<string[]>([]);
  const [causalResultsLines, setCausalResultsLines] = useState<string[]>([]);
  const [openPlotsAddedLines, setOpenPlotsAddedLines] = useState<string[]>([]);
  const [openPlotsResolvedLines, setOpenPlotsResolvedLines] = useState<string[]>([]);
  const [memoryFixHints, setMemoryFixHints] = useState<string[]>([]);
  const [memoryRefreshPreview, setMemoryRefreshPreview] = useState<{
    errors: string[];
    version: number;
  } | null>(null);
  const [logBatchId, setLogBatchId] = useState<string>("");
  const [logBusy, setLogBusy] = useState(false);
  const [logDialogOpen, setLogDialogOpen] = useState(false);
  const [logOnlyError, setLogOnlyError] = useState(false);
  const [logViewMode, setLogViewMode] = useState<"all" | "batch">("all");
  const [latestLogBatchId, setLatestLogBatchId] = useState<string>("");
  const [refreshBatchId, setRefreshBatchId] = useState<string>("");
  const [refreshStatus, setRefreshStatus] = useState<"idle" | "queued" | "started" | "done" | "failed">("idle");
  const [refreshProgress, setRefreshProgress] = useState(0);
  const [refreshLastMessage, setRefreshLastMessage] = useState("");
  const [refreshUpdatedAt, setRefreshUpdatedAt] = useState<string | null>(null);
  const [refreshStartedAt, setRefreshStartedAt] = useState<string | null>(null);
  const [refreshElapsedSeconds, setRefreshElapsedSeconds] = useState<number | null>(null);
  const [latestRefreshVersion, setLatestRefreshVersion] = useState<number | null>(null);
  const [genLogs, setGenLogs] = useState<
    Awaited<ReturnType<typeof listGenerationLogs>>["items"]
  >([]);
  const [chapterChatOpen, setChapterChatOpen] = useState(false);
  const [chapterChatTurns, setChapterChatTurns] = useState<
    { role: "user" | "assistant"; content: string }[]
  >([]);
  const [chapterChatInput, setChapterChatInput] = useState("");
  const [chapterChatBusy, setChapterChatBusy] = useState(false);
  const [chapterChatErr, setChapterChatErr] = useState<string | null>(null);
  const [chapterChatThinking, setChapterChatThinking] = useState("");
  const [chapterThinkExpanded, setChapterThinkExpanded] = useState(false);
  const [chapterChatAbort, setChapterChatAbort] = useState<AbortController | null>(null);
  const [volumes, setVolumes] = useState<Awaited<ReturnType<typeof listVolumes>>>([]);
  const [selectedVolumeId, setSelectedVolumeId] = useState<string>("");
  const [volumePlan, setVolumePlan] = useState<
    Awaited<ReturnType<typeof listVolumeChapterPlan>>
  >([]);
  const [volumeBusy, setVolumeBusy] = useState(false);
  const [volumePlanBatchSize, setVolumePlanBatchSize] = useState<number>(10);
  const [volumePlanLastRun, setVolumePlanLastRun] = useState<{
    batch?: {
      from_chapter: number;
      to_chapter: number;
      size: number;
      requested_count?: number;
      saved_count?: number;
      partial?: boolean;
    };
    done?: boolean;
    next_from_chapter?: number | null;
    existing?: number;
  } | null>(null);
  const [titleDraft, setTitleDraft] = useState("");
  const [titleBusy, setTitleBusy] = useState(false);

  // --- 用户设置相关状态 ---
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [llmCfg, setLlmCfg] = useState<{
    provider: string;
    model: string;
    novel_web_search: boolean;
    novel_generate_web_search: boolean;
    novel_volume_plan_web_search: boolean;
    novel_memory_refresh_web_search: boolean;
    novel_inspiration_web_search: boolean;
  } | null>(null);
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [theme, setTheme] = useState<"dark" | "light" | "system">(
    (localStorage.getItem("vocalflow-theme") as "dark" | "light" | "system") || "dark"
  );

  // 初始化加载配置
  useEffect(() => {
    getLlmConfig().then(setLlmCfg).catch(() => null);
  }, []);

  // 主题切换逻辑
  useEffect(() => {
    const root = window.document.documentElement;
    root.classList.remove("light", "dark");

    if (theme === "system") {
      const systemTheme = window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light";
      root.classList.add(systemTheme);
    } else {
      root.classList.add(theme);
    }
    localStorage.setItem("vocalflow-theme", theme);
  }, [theme]);

  async function handleSaveSettings(payload: NonNullable<typeof llmCfg>) {
    setSettingsBusy(true);
    try {
      const updated = await setLlmConfig(payload);
      setLlmCfg(updated);
      setNotice("配置已更新");
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "更新配置失败");
    } finally {
      setSettingsBusy(false);
    }
  }
  // -----------------------

  const chapterQuickPrompts = [
    {
      label: "查设定冲突",
      prompt: "请检查目前已审定章节与框架设定是否有冲突，按“严重/中等/轻微”列出问题与修复建议。",
    },
    {
      label: "下一章建议",
      prompt: "请给出下一章（只出一个方案）的剧情推进建议：目标、冲突、转折、结尾钩子。",
    },
    {
      label: "伏笔回收优先级",
      prompt: "请列出当前最该优先回收的 3 条伏笔（含全书待收束线），并说明各自最佳回收章节窗口。",
    },
    {
      label: "人物动机体检",
      prompt: "请评估主角与关键配角的人物动机是否连贯，指出薄弱点并给出最小改写建议。",
    },
    {
      label: "三章节奏编排",
      prompt: "请给出接下来 3 章的节奏编排（每章一句目标 + 一句冲突 + 一句收束）。",
    },
  ] as const;

  const reload = useCallback(async () => {
    const [n, c, m, mn] = await Promise.all([
      getNovel(id),
      listChapters(id),
      getMemory(id),
      getMemoryNormalized(id).catch(() => ({ status: "empty" as const, data: null })),
    ]);
    setNovel(n);
    setChapters(c);
    setMemory(m);
    if (mn.status === "ok" && mn.data) {
      setMemoryNorm(mn.data);
    } else {
      setMemoryNorm(null);
    }
    setFwMd(String(n.framework_markdown ?? ""));
    setFwJson(String(n.framework_json ?? "{}"));
  }, [id]);

  const reloadVolumes = useCallback(async () => {
    if (!id) return;
    const vs = await listVolumes(id);
    setVolumes(vs);
    if (vs.length > 0) {
      const keep =
        selectedVolumeId && vs.some((x) => x.id === selectedVolumeId)
          ? selectedVolumeId
          : vs[0].id;
      setSelectedVolumeId(keep);
    } else {
      setSelectedVolumeId("");
    }
  }, [id, selectedVolumeId]);

  useEffect(() => {
    if (!id) return;
    reload().catch((e: Error) => setErr(e.message));
  }, [id, reload]);

  useEffect(() => {
    const t = String(novel?.title ?? "");
    if (!t) return;
    setTitleDraft(t);
  }, [novel?.title]);

  useEffect(() => {
    if (!id) return;
    void reloadVolumes().catch(() => null);
  }, [id, reloadVolumes]);

  useEffect(() => {
    if (!id || !selectedVolumeId) {
      setVolumePlan([]);
      return;
    }
    setVolumeBusy(true);
    setErr(null);
    listVolumeChapterPlan(id, selectedVolumeId)
      .then(setVolumePlan)
      .catch(() => setVolumePlan([]))
      .finally(() => setVolumeBusy(false));
  }, [id, selectedVolumeId]);


  useEffect(() => {
    if (!id) return;
    void reloadGenerationLogs();
  }, [id]);

  useEffect(() => {
    if (!chapters.length) {
      setSelectedChapterId("");
      return;
    }
    if (!selectedChapterId || !chapters.some((x) => x.id === selectedChapterId)) {
      setSelectedChapterId(chapters[0].id);
    }
  }, [chapters, selectedChapterId]);

  const selectedChapter = chapters.find((c) => c.id === selectedChapterId) ?? null;
  const frameworkConfirmed = Boolean(novel?.framework_confirmed);
  const generateDisabledReason = busy
    ? "当前有任务执行中，请稍候"
    : !frameworkConfirmed
      ? "请先在“设定与框架”中确认框架"
      : "";

  useEffect(() => {
    if (!selectedChapter) {
      setEditTitle("");
      setEditContent("");
      return;
    }
    setEditTitle(selectedChapter.title || "");
    setEditContent(selectedChapter.content || "");
  }, [selectedChapter]);

  useEffect(() => {
    if (!memory?.payload_json) {
      setOpenPlotsLines([]);
      setKeyFactsLines([]);
      setCausalResultsLines([]);
      setOpenPlotsAddedLines([]);
      setOpenPlotsResolvedLines([]);
      return;
    }
    try {
      const data = JSON.parse(memory.payload_json) as Record<string, unknown>;
      const op = Array.isArray(data.open_plots)
        ? (data.open_plots as unknown[])
            .map((x) => (typeof x === "string" ? x : JSON.stringify(x)))
            .filter(Boolean)
        : [];
      setOpenPlotsLines(op);
      const ct = Array.isArray(data.canonical_timeline)
        ? (data.canonical_timeline as unknown[])
        : Array.isArray(data.canonical_timeline_hot)
          ? (data.canonical_timeline_hot as unknown[])
          : [];
      const last = ct.length > 0 ? ct[ct.length - 1] : null;
      if (last && typeof last === "object") {
        const o = last as Record<string, unknown>;
        const toLines = (k: string) =>
          Array.isArray(o[k])
            ? (o[k] as unknown[])
                .map((x) => (typeof x === "string" ? x : JSON.stringify(x)))
                .filter(Boolean)
            : [];
        setKeyFactsLines(toLines("key_facts"));
        setCausalResultsLines(toLines("causal_results"));
        setOpenPlotsAddedLines(toLines("open_plots_added"));
        setOpenPlotsResolvedLines(toLines("open_plots_resolved"));
      } else {
        setKeyFactsLines([]);
        setCausalResultsLines([]);
        setOpenPlotsAddedLines([]);
        setOpenPlotsResolvedLines([]);
      }
    } catch {
      setOpenPlotsLines([]);
      setKeyFactsLines([]);
      setCausalResultsLines([]);
      setOpenPlotsAddedLines([]);
      setOpenPlotsResolvedLines([]);
    }
  }, [memory?.payload_json]);

  function normalizeLines(lines: string[]): string[] {
    return lines.map((x) => x.trim()).filter(Boolean);
  }

  function normalizeAndUnique(lines: string[]): {
    cleaned: string[];
    duplicates: string[];
  } {
    const cleaned = normalizeLines(lines);
    const seen = new Set<string>();
    const duplicates: string[] = [];
    const uniq: string[] = [];
    for (const raw of cleaned) {
      const key = raw.toLowerCase();
      if (seen.has(key)) {
        duplicates.push(raw);
        continue;
      }
      seen.add(key);
      uniq.push(raw);
    }
    return { cleaned: uniq, duplicates };
  }

  function renderLineEditor(
    label: string,
    lines: string[],
    setLines: (v: string[]) => void,
    placeholder: string,
    helper?: string
  ) {
    return (
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <Label>{label}</Label>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => setLines([...lines, ""])}
          >
            + 新增
          </Button>
        </div>
        {helper ? <p className="text-[11px] text-muted-foreground">{helper}</p> : null}
        <div className="space-y-2">
          {lines.length === 0 ? (
            <div className="rounded-md border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
              暂无条目，点击“新增”开始填写
            </div>
          ) : null}
          {lines.map((line, idx) => (
            <div key={`${label}-${idx}`} className="flex items-center gap-2">
              <span className="w-6 shrink-0 text-center text-xs text-muted-foreground">
                {idx + 1}
              </span>
              <input
                value={line}
                onChange={(e) => {
                  const next = [...lines];
                  next[idx] = e.target.value;
                  setLines(next);
                }}
                className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                placeholder={placeholder}
              />
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => setLines(lines.filter((_, i) => i !== idx))}
              >
                删除
              </Button>
            </div>
          ))}
        </div>
      </div>
    );
  }

  async function saveMemoryFix() {
    if (!id) return;
    setMemoryFixBusy(true);
    setErr(null);
    setMemoryFixHints([]);
    try {
      const openPlots = normalizeAndUnique(openPlotsLines);
      const keyFacts = normalizeAndUnique(keyFactsLines);
      const causalResults = normalizeAndUnique(causalResultsLines);
      const openPlotsAdded = normalizeAndUnique(openPlotsAddedLines);
      const openPlotsResolved = normalizeAndUnique(openPlotsResolvedLines);

      const hints: string[] = [];
      if (openPlots.duplicates.length) {
        hints.push(
          `「全书待收束线」中有重复条目，已自动去重（${openPlots.duplicates.length} 条）。`
        );
      }
      if (keyFacts.duplicates.length) {
        hints.push(
          `「本章关键事实」中有重复条目，已自动去重（${keyFacts.duplicates.length} 条）。`
        );
      }
      if (causalResults.duplicates.length) {
        hints.push(
          `「前因后果」中有重复条目，已自动去重（${causalResults.duplicates.length} 条）。`
        );
      }
      if (openPlotsAdded.duplicates.length) {
        hints.push(
          `「本章新埋线」中有重复条目，已自动去重（${openPlotsAdded.duplicates.length} 条）。`
        );
      }
      if (openPlotsResolved.duplicates.length) {
        hints.push(
          `「本章已收束」中有重复条目，已自动去重（${openPlotsResolved.duplicates.length} 条）。`
        );
      }

      const tooShortCausals = causalResults.cleaned.filter((x) => x.length < 8);
      if (tooShortCausals.length > 0) {
        hints.push(
          `「前因后果」里有 ${tooShortCausals.length} 条过短（少于 8 字），建议写成完整的“因 → 果”叙述。`
        );
      }

      if (
        causalResults.cleaned.length > 0 &&
        keyFacts.cleaned.length === 0
      ) {
        hints.push("已填写「前因后果」，但「本章关键事实」为空，建议补充稳定事实锚点。");
      }
      if (
        openPlotsResolved.cleaned.length > 0 &&
        openPlots.cleaned.length === 0
      ) {
        hints.push(
          "「本章已收束」有内容，但「全书待收束线」为空，请确认是否误填或已全部了结。"
        );
      }

      setMemoryFixHints(hints);

      await manualFixMemory(id, {
        open_plots: openPlots.cleaned,
        canonical_last: {
          key_facts: keyFacts.cleaned,
          causal_results: causalResults.cleaned,
          open_plots_added: openPlotsAdded.cleaned,
          open_plots_resolved: openPlotsResolved.cleaned,
        },
      });
      await reload();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "记忆保存失败");
    } finally {
      setMemoryFixBusy(false);
    }
  }

  async function run(fn: () => Promise<unknown>) {
    setErr(null);
    setNotice(null);
    setBusy(true);
    try {
      await fn();
      await reload();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "操作失败");
    } finally {
      setBusy(false);
    }
  }

  async function reloadGenerationLogs(batchId?: string) {
    if (!id) return;
    setLogBusy(true);
    try {
      const resp = await listGenerationLogs(id, {
        batch_id: logViewMode === "batch" ? batchId || logBatchId || undefined : undefined,
        level: logOnlyError ? "error" : undefined,
        limit: 300,
      });
      setGenLogs(resp.items);
      setLatestLogBatchId(resp.latest_batch_id || "");
      setRefreshBatchId(resp.latest_refresh_batch_id || "");
      setRefreshStatus(resp.refresh_status);
      setRefreshProgress(resp.refresh_progress);
      setRefreshLastMessage(resp.refresh_last_message || "");
      setRefreshUpdatedAt(resp.refresh_updated_at || null);
      setRefreshStartedAt(resp.refresh_started_at || null);
      setRefreshElapsedSeconds(resp.refresh_elapsed_seconds ?? null);
      setLatestRefreshVersion(resp.latest_refresh_success_version ?? null);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "加载生成日志失败");
    } finally {
      setLogBusy(false);
    }
  }

  async function runRefreshMemory() {
    if (!id) return;
    setErr(null);
    setNotice(null);
    setBusy(true);
    try {
      const resp = await refreshMemory(id);
      if ("status" in resp && resp.status === "validation_failed") {
        setMemoryRefreshPreview({
          errors: resp.errors,
          version: resp.version,
        });
        setNotice("记忆刷新已执行，但候选记忆未通过校验，当前生效记忆未被覆盖。");
        await reload();
        await reloadGenerationLogs(logViewMode === "batch" ? logBatchId || undefined : undefined);
        return;
      }
      setMemoryRefreshPreview(null);
      setNotice("记忆已按已审定章节刷新。");
      await reload();
      await reloadGenerationLogs(logViewMode === "batch" ? logBatchId || undefined : undefined);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "刷新记忆失败");
    } finally {
      setBusy(false);
    }
  }

  async function runRebuildMemoryNorm() {
    if (!id) return;
    setErr(null);
    setNotice(null);
    setMemoryNormRebuildBusy(true);
    try {
      const resp = await rebuildMemoryNormalized(id);
      setMemoryNorm(resp.data);
      setNotice("已用最新快照覆盖结构化表，并派生新快照（用于迁移/恢复）。");
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "从快照导入结构化记忆失败");
    } finally {
      setMemoryNormRebuildBusy(false);
    }
  }

  useEffect(() => {
    if (!logDialogOpen) return;
    void reloadGenerationLogs(logViewMode === "batch" ? logBatchId || undefined : undefined);
  }, [logOnlyError, logDialogOpen, logViewMode, logBatchId]);

  useEffect(() => {
    if (!logDialogOpen) return;
    const t = window.setInterval(() => {
      void reloadGenerationLogs(logViewMode === "batch" ? logBatchId || undefined : undefined);
    }, 3000);
    return () => window.clearInterval(t);
  }, [logDialogOpen, logBatchId, logOnlyError, logViewMode]);

  async function runGenerateChapters() {
    if (!id) return;
    setErr(null);
    setNotice(null);
    setBusy(true);
    setGenerateTrace(
      `正在发起生成请求：POST /api/novels/${id}/chapters/generate（${generateCount}章）`
    );
    try {
      const resp = await generateChapters(id, generateCount, "", {
        use_cold_recall: useColdRecall,
        cold_recall_items: coldRecallItems,
        auto_consistency_check: false,
      });
      setGenerateTrace(
        `生成请求成功返回：batch_id=${resp.batch_id ?? "无"}，chapter_ids=${resp.chapter_ids.length}`
      );
      if (resp.batch_id) {
        setRefreshBatchId(resp.batch_id);
        if (logViewMode === "batch") {
          setLogBatchId(resp.batch_id);
          await reloadGenerationLogs(resp.batch_id);
        } else {
          await reloadGenerationLogs();
        }
      } else {
        await reloadGenerationLogs();
      }
      await reload();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "生成章节失败");
      setGenerateTrace(
        `生成请求失败：${e instanceof Error ? e.message : "未知错误"}`
      );
      await reloadGenerationLogs(logBatchId || undefined);
    } finally {
      setBusy(false);
    }
  }

  async function runGenerateVolumes() {
    if (!id) return;
    setErr(null);
    setNotice(null);
    setVolumeBusy(true);
    try {
      await generateVolumes(id, { approx_size: 50 });
      await reloadVolumes();
      setNotice("卷列表已生成。请选择一卷后生成本卷章计划。");
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "生成卷列表失败");
    } finally {
      setVolumeBusy(false);
    }
  }

  async function runSaveTitle() {
    if (!id) return;
    const next = titleDraft.trim();
    if (!next) {
      setErr("书名不能为空");
      return;
    }
    setErr(null);
    setNotice(null);
    setTitleBusy(true);
    try {
      await patchNovel(id, { title: next });
      await reload();
      setNotice("书名已更新。");
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "更新书名失败");
    } finally {
      setTitleBusy(false);
    }
  }

  async function runGenerateVolumePlan(force = false) {
    if (!id || !selectedVolumeId) return;
    setErr(null);
    setNotice(null);
    setVolumeBusy(true);
    try {
      const resp = await generateVolumeChapterPlan(id, selectedVolumeId, {
        force_regen: force,
        batch_size: volumePlanBatchSize,
      });
      await reloadVolumes();
      const plan = await listVolumeChapterPlan(id, selectedVolumeId);
      setVolumePlan(plan);
      setVolumePlanLastRun({
        batch: resp.batch,
        done: resp.done,
        next_from_chapter: resp.next_from_chapter,
        existing: resp.existing ?? plan.length,
      });
      setNotice(
        resp.status === "ok"
          ? resp.done
            ? `本卷章计划已完成（本次保存 ${resp.saved ?? 0} 章）。`
            : `本次已生成一批：第${resp.batch?.from_chapter ?? "?"}—${
                resp.batch?.to_chapter ?? "?"
              }章（保存 ${resp.saved ?? 0} 章），下一批从第${
                resp.next_from_chapter ?? "?"
              }章开始。`
          : `未生成：${resp.reason ?? resp.status}`
      );
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "生成本卷章计划失败");
    } finally {
      setVolumeBusy(false);
    }
  }

  async function runRegenerateChapterPlan(chapterNo: number, instruction?: string) {
    if (!id || !selectedVolumeId) return;
    setErr(null);
    setNotice(null);
    setVolumeBusy(true);
    try {
      await regenerateChapterPlan(id, selectedVolumeId, chapterNo, { instruction });
      const plan = await listVolumeChapterPlan(id, selectedVolumeId);
      setVolumePlan(plan);
      setNotice(`第${chapterNo}章计划已重生成。`);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "重生成章计划失败");
    } finally {
      setVolumeBusy(false);
    }
  }

  async function runClearVolumePlans() {
    if (!id || !selectedVolumeId) return;
    if (
      !window.confirm(
        "确定清除本卷所有未锁定的章计划？已锁定的计划会保留。清除后可重新分批生成。"
      )
    ) {
      return;
    }
    setErr(null);
    setNotice(null);
    setVolumeBusy(true);
    try {
      const resp = await clearVolumeChapterPlans(id, selectedVolumeId);
      setVolumePlan([]);
      setVolumePlanLastRun(null);
      await reloadVolumes();
      setNotice(`已清除章计划（删除 ${resp.deleted ?? 0} 条）。`);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "清除章计划失败");
    } finally {
      setVolumeBusy(false);
    }
  }

  async function runGenerateChapterFromPlan(chapterNo: number) {
    if (!id) return;
    setErr(null);
    setNotice(null);
    setBusy(true);
    try {
      const resp = await generateChapters(id, 1, "", {
        use_cold_recall: useColdRecall,
        cold_recall_items: coldRecallItems,
        auto_consistency_check: false,
        chapter_no: chapterNo,
      });
      setNotice(`已生成第${chapterNo}章（待审），chapter_id=${resp.chapter_ids?.[0] ?? "-"}`);
      await reload();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "按章计划生成失败");
    } finally {
      setBusy(false);
    }
  }

  async function runApproveChapter(chapterId: string) {
    setErr(null);
    setNotice(null);
    setBusy(true);
    try {
      const resp = await approveChapter(chapterId);
      const incrementalNotice =
        resp.incremental_memory_status === "applied"
          ? `本章增量记忆已先写入 v${resp.incremental_memory_version ?? "?"}`
          : resp.incremental_memory_status === "failed"
            ? "本章增量记忆写入失败，已保留旧记忆"
            : "本章未执行增量记忆写入";
      if (resp.memory_refresh_status === "queued") {
        if (resp.memory_refresh_batch_id) {
          setRefreshBatchId(resp.memory_refresh_batch_id);
          if (logViewMode === "batch") {
            setLogBatchId(resp.memory_refresh_batch_id);
            await reloadGenerationLogs(resp.memory_refresh_batch_id);
          } else {
            await reloadGenerationLogs();
          }
        }
        setNotice(
          `已审定通过，${incrementalNotice}；后台全局记忆刷新已排队（task_id: ${resp.memory_refresh_task_id ?? "未知"}）。`
        );
      } else if (resp.memory_refresh_status === "skipped") {
        setNotice(`已审定通过，${incrementalNotice}；但后台全局记忆刷新入队失败，请稍后在记忆页手动刷新。`);
      } else {
        setNotice(`已审定通过，${incrementalNotice}。`);
      }
      await reload();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "审定失败");
    } finally {
      setBusy(false);
    }
  }

  async function runDeleteChapter(ch: {
    id: string;
    chapter_no: number;
    title: string;
    status: string;
  }) {
    const isApproved = ch.status === "approved";
    const title = ch.title || `第${ch.chapter_no}章`;
    if (isApproved) {
      const typed = window.prompt(
        [
          `你正在删除已审定章节：第${ch.chapter_no}章《${title}》`,
          "此操作会触发后台记忆重算，可能影响后续衔接。",
          '请输入 DELETE 以确认删除：',
        ].join("\n")
      );
      if (typed !== "DELETE") return;
    } else {
      const msg = `确认删除第${ch.chapter_no}章《${title}》吗？\n该章节未审定，删除不会影响记忆。`;
      if (!window.confirm(msg)) return;
    }

    setErr(null);
    setNotice(null);
    setBusy(true);
    try {
      const resp = await deleteChapter(ch.id);
      if (resp.was_approved) {
        if (resp.memory_refresh_status === "queued") {
          if (resp.memory_refresh_batch_id) {
            setRefreshBatchId(resp.memory_refresh_batch_id);
            if (logViewMode === "batch") {
              setLogBatchId(resp.memory_refresh_batch_id);
            }
            setLogDialogOpen(true);
            await reloadGenerationLogs(
              logViewMode === "batch" ? resp.memory_refresh_batch_id : undefined
            );
          }
          setNotice("章节已删除，记忆刷新已后台排队。");
        } else if (resp.memory_refresh_status === "skipped") {
          setNotice("章节已删除，但记忆刷新入队失败，请手动刷新记忆。");
        } else {
          setNotice("章节已删除。");
        }
      } else {
        setNotice("章节已删除（未影响记忆）。");
      }
      await reload();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "删除章节失败");
    } finally {
      setBusy(false);
    }
  }

  async function runChapterChatPrompt(userText: string) {
    if (!id || !userText.trim() || chapterChatBusy) return;
    const nextTurns = [...chapterChatTurns, { role: "user" as const, content: userText.trim() }];
    setChapterChatTurns([...nextTurns, { role: "assistant", content: "" }]);
    setChapterChatInput("");
    setChapterChatErr(null);
    setChapterChatThinking("");
    setChapterThinkExpanded(false);
    setChapterChatBusy(true);
    const controller = new AbortController();
    setChapterChatAbort(controller);
    try {
      await chapterContextChatStream(
        id,
        nextTurns.map((t) => ({ role: t.role, content: t.content })),
        {
          onThink: (delta) => {
            setChapterChatThinking((prev) => prev + delta);
          },
          onText: (delta) => {
            setChapterChatTurns((prev) => {
              const next = [...prev];
              for (let i = next.length - 1; i >= 0; i--) {
                if (next[i].role === "assistant") {
                  next[i] = { ...next[i], content: (next[i].content || "") + delta };
                  return next;
                }
              }
              next.push({ role: "assistant", content: delta });
              return next;
            });
          },
          onError: (message) => {
            setChapterChatErr(message || "章节助手对话失败");
          },
          onDone: () => {
            setChapterChatThinking("");
          },
        },
        controller.signal
      );
    } catch (e: unknown) {
      if (!(e instanceof DOMException && e.name === "AbortError")) {
        setChapterChatErr(e instanceof Error ? e.message : "章节助手对话失败");
      }
    } finally {
      setChapterChatBusy(false);
      setChapterChatAbort(null);
    }
  }

  async function sendChapterChat() {
    const userText = chapterChatInput.trim();
    if (!userText) return;
    await runChapterChatPrompt(userText);
  }

  async function sendChapterQuickPrompt(prompt: string) {
    await runChapterChatPrompt(prompt);
  }

  function formatUtc8(iso: string | null | undefined): string {
    if (!iso) return "-";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    const shifted = new Date(d.getTime() + 8 * 60 * 60 * 1000);
    const yyyy = shifted.getUTCFullYear();
    const mm = String(shifted.getUTCMonth() + 1).padStart(2, "0");
    const dd = String(shifted.getUTCDate()).padStart(2, "0");
    const hh = String(shifted.getUTCHours()).padStart(2, "0");
    const mi = String(shifted.getUTCMinutes()).padStart(2, "0");
    const ss = String(shifted.getUTCSeconds()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd} ${hh}:${mi}:${ss} GMT+8`;
  }

  function formatDuration(totalSeconds: number | null | undefined): string {
    if (totalSeconds == null || totalSeconds < 0) return "-";
    const h = Math.floor(totalSeconds / 3600);
    const m = Math.floor((totalSeconds % 3600) / 60);
    const s = totalSeconds % 60;
    if (h > 0) return `${h}h ${m}m ${s}s`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
  }

  if (!novel) {
    return (
      <div className="p-8 text-sm text-muted-foreground">
        {err ?? "加载中…"}
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background p-6 pb-32 transition-colors duration-300">
      <div className="mx-auto max-w-5xl space-y-4">
        {/* 顶部导航栏 */}
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-border pb-4">
          <div className="flex flex-col gap-1">
            <div className="flex flex-wrap items-center gap-3">
              <input
                value={titleDraft}
                onChange={(e) => setTitleDraft(e.target.value)}
                className="h-9 w-[min(420px,70vw)] rounded-md border border-input bg-background px-3 text-xl font-bold shadow-sm transition-all focus:ring-2 focus:ring-primary"
                placeholder="请输入书名"
                disabled={busy || titleBusy}
              />
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-9"
                disabled={busy || titleBusy || !titleDraft.trim()}
                onClick={() => void runSaveTitle()}
              >
                保存书名
              </Button>
            </div>
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <div className="flex items-center gap-1 rounded-full bg-muted/50 px-2 py-0.5">
                <div className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
                <span>当前模型: <span className="font-medium text-foreground">{llmCfg?.model || "加载中..."}</span></span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" asChild className="text-xs h-8">
              <Link to="/novels">书架</Link>
            </Button>
            <Button variant="ghost" size="sm" asChild className="text-xs h-8">
              <Link to={`/novels/${id}/metrics`}>指标</Link>
            </Button>
            <div className="h-4 w-[1px] bg-border mx-1" />
            <div className="flex items-center gap-2 px-2 py-1 rounded-full bg-muted/30 border border-border/50">
              <div className="h-6 w-6 rounded-full bg-primary/20 flex items-center justify-center text-primary">
                <User className="h-3.5 w-3.5" />
              </div>
              <span className="text-xs font-medium pr-1">管理员</span>
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="h-8 w-8 p-0 rounded-full"
              onClick={() => setSettingsOpen(true)}
              title="设置"
            >
              <Settings className="h-4 w-4 opacity-70 hover:opacity-100 transition-opacity" />
            </Button>
          </div>
        </div>

        {err ? (
          <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive border border-destructive/20 flex items-center gap-2">
            <div className="h-1.5 w-1.5 rounded-full bg-destructive" />
            {err}
          </div>
        ) : null}
        {notice ? (
          <div className="rounded-md bg-emerald-500/10 p-3 text-sm text-emerald-500 border border-emerald-500/20 flex items-center gap-2">
            <div className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            {notice}
          </div>
        ) : null}

        <Tabs defaultValue="framework" className="w-full">
          <TabsList>
            <TabsTrigger value="framework">设定与框架</TabsTrigger>
            <TabsTrigger value="volumes">卷与章计划</TabsTrigger>
            <TabsTrigger value="chapters">章节</TabsTrigger>
            <TabsTrigger value="memory">记忆</TabsTrigger>
          </TabsList>

          <TabsContent value="framework" className="space-y-3">
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                disabled={busy}
                onClick={() => run(() => generateFramework(id))}
              >
                AI 生成框架
              </Button>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                disabled={busy}
                onClick={() =>
                  run(() => confirmFramework(id, fwMd, fwJson))
                }
              >
                确认框架并开始创作
              </Button>
            </div>
            <div>
              <Label>框架 Markdown（可编辑后再确认）</Label>
              <textarea
                value={fwMd}
                onChange={(e) => setFwMd(e.target.value)}
                className="mt-1 min-h-[240px] w-full rounded-md border border-input bg-background p-3 font-mono text-sm"
              />
            </div>
            <div>
              <Label>框架 JSON</Label>
              <textarea
                value={fwJson}
                onChange={(e) => setFwJson(e.target.value)}
                className="mt-1 min-h-[120px] w-full rounded-md border border-input bg-background p-3 font-mono text-xs"
              />
            </div>
          </TabsContent>

          <TabsContent value="volumes" className="space-y-4">
            <p className="text-xs text-muted-foreground">
              推荐流程：先生成卷列表 → 选择一卷 → 生成本卷 50 章章计划（章名+每章节拍）→ 点击某章生成正文。
            </p>
            <div className="flex flex-wrap gap-2">
              <Button type="button" size="sm" disabled={busy || volumeBusy} onClick={() => void runGenerateVolumes()}>
                生成卷列表（每卷约50章）
              </Button>
              <div className="flex items-center gap-2 rounded-md border border-border bg-background/40 px-2 py-1 text-xs">
                <span className="text-muted-foreground">每次生成</span>
                <select
                  value={volumePlanBatchSize}
                  onChange={(e) => setVolumePlanBatchSize(Number(e.target.value))}
                  className="h-7 rounded-md border border-input bg-background px-2 text-xs"
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
                disabled={busy || volumeBusy || !selectedVolumeId}
                onClick={() => void runGenerateVolumePlan(false)}
              >
                生成本卷章计划（下一批）
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={busy || volumeBusy || !selectedVolumeId}
                onClick={() => void runGenerateVolumePlan(true)}
              >
                强制重生成本卷计划（从头下一批）
              </Button>
              <Button
                type="button"
                size="sm"
                variant="destructive"
                disabled={busy || volumeBusy || !selectedVolumeId}
                onClick={() => void runClearVolumePlans()}
              >
                一键清除本卷计划
              </Button>
            </div>
            <div className="grid gap-4 lg:grid-cols-12">
              <aside className="lg:col-span-4 rounded-lg border border-border p-3">
                <p className="mb-2 text-xs font-medium text-muted-foreground">卷列表</p>
                <div className="max-h-[70vh] space-y-2 overflow-auto pr-1">
                  {volumes.map((v) => (
                    <button
                      key={v.id}
                      type="button"
                      onClick={() => setSelectedVolumeId(v.id)}
                      className={`w-full rounded-md border px-3 py-2 text-left text-xs ${
                        selectedVolumeId === v.id
                          ? "border-primary bg-primary/10"
                          : "border-border bg-background/40 hover:bg-muted/30"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2 font-medium">
                        <span>
                          第{v.volume_no}卷 {v.title}
                        </span>
                        <span className="text-[11px] text-muted-foreground">
                          计划{v.chapter_plan_count}
                        </span>
                      </div>
                      <div className="mt-1 text-muted-foreground">
                        第{v.from_chapter}—{v.to_chapter}章 · {v.status}
                      </div>
                      {v.summary ? (
                        <div className="mt-1 line-clamp-2 text-muted-foreground">
                          {v.summary}
                        </div>
                      ) : null}
                    </button>
                  ))}
                  {volumes.length === 0 ? (
                    <p className="text-xs text-muted-foreground">暂无卷。点击上方按钮生成。</p>
                  ) : null}
                </div>
              </aside>
              <section className="lg:col-span-8 rounded-lg border border-border p-4">
                {!selectedVolumeId ? (
                  <p className="text-sm text-muted-foreground">请选择左侧卷。</p>
                ) : (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <p className="text-sm font-medium">本卷章计划</p>
                      <p className="text-xs text-muted-foreground">
                        {volumeBusy ? "加载中…" : `共 ${volumePlan.length} 章`}
                      </p>
                    </div>
                    {(() => {
                      const v = volumes.find((x) => x.id === selectedVolumeId);
                      if (!v) return null;
                      const total = v.to_chapter - v.from_chapter + 1;
                      const done = volumePlan.length >= total;
                      const last = volumePlanLastRun;
                      return (
                        <div className="rounded-md border border-border bg-background/40 p-2 text-xs text-muted-foreground">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <span>
                              进度：已生成 {volumePlan.length}/{total} 章（第{v.from_chapter}—{v.to_chapter}章）
                            </span>
                            <span>{done ? "已完成" : "未完成"}</span>
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
                    <div className="max-h-[70vh] overflow-auto rounded-md border border-border bg-muted/20 p-2">
                      {volumePlan.length === 0 ? (
                        <p className="p-2 text-xs text-muted-foreground">
                          暂无章计划。点击“生成本卷章计划（下一批）”开始生成。
                        </p>
                      ) : (
                        <div className="space-y-2">
                          {volumePlan.map((p) => (
                            <div
                              key={p.id}
                              className="rounded-md border border-border bg-background/40 p-3 text-xs"
                            >
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <div className="font-medium">
                                  第{p.chapter_no}章 · {p.chapter_title}
                                </div>
                                <div className="flex gap-2">
                                  <Button
                                    type="button"
                                    size="sm"
                                    variant="outline"
                                    disabled={busy || p.status === "locked"}
                                    onClick={() => {
                                      const msg = window.prompt("请输入重生成指令（可选，如：'让冲突更激烈些'）：", "");
                                      if (msg !== null) {
                                        void runRegenerateChapterPlan(p.chapter_no, msg);
                                      }
                                    }}
                                  >
                                    重生成计划
                                  </Button>
                                  <Button
                                    type="button"
                                    size="sm"
                                    disabled={busy}
                                    onClick={() => void runGenerateChapterFromPlan(p.chapter_no)}
                                  >
                                    生成正文
                                  </Button>
                                </div>
                              </div>
                              <div className="mt-2 text-muted-foreground whitespace-pre-wrap">
                                {formatVolumePlanBeatsText(p.beats)}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </section>
            </div>
          </TabsContent>

          <TabsContent value="chapters" className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <Label>一次生成</Label>
              <select
                value={generateCount}
                onChange={(e) => setGenerateCount(Number(e.target.value))}
                className="h-8 rounded-md border border-input bg-background px-2 text-sm"
              >
                {[1, 2, 3, 4, 5].map((n) => (
                  <option key={n} value={n}>
                    {n} 章
                  </option>
                ))}
              </select>
              <Button
                type="button"
                size="sm"
                disabled={busy || !frameworkConfirmed}
                onClick={() => void runGenerateChapters()}
              >
                自动续写 {generateCount} 章
              </Button>
              {generateDisabledReason ? (
                <span className="text-xs text-amber-500 font-medium">{generateDisabledReason}</span>
              ) : null}
              <label className="ml-2 inline-flex items-center gap-2 text-xs text-muted-foreground">
                <input
                  type="checkbox"
                  checked={useColdRecall}
                  onChange={(e) => setUseColdRecall(e.target.checked)}
                />
                按需召回冷层
              </label>
              {useColdRecall ? (
                <div className="inline-flex items-center gap-2 text-xs text-muted-foreground">
                  <span>召回条数</span>
                  <select
                    value={coldRecallItems}
                    onChange={(e) => setColdRecallItems(Number(e.target.value))}
                    className="h-8 rounded-md border border-input bg-background px-2 text-sm"
                  >
                    {[3, 5, 8, 10, 12].map((n) => (
                      <option key={n} value={n}>
                        {n}
                      </option>
                    ))}
                  </select>
                </div>
              ) : null}
              <Button
                type="button"
                size="sm"
                variant="secondary"
                onClick={() => setChapterChatOpen(true)}
              >
                章节助手对话
              </Button>
            </div>
            {generateTrace ? (
              <p className="text-[11px] text-muted-foreground bg-muted/30 p-2 rounded border border-border/50">{generateTrace}</p>
            ) : null}
            <div className="flex items-center justify-end">
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => {
                  setLogDialogOpen(true);
                  void reloadGenerationLogs(logBatchId || undefined);
                }}
              >
                查看生成日志
              </Button>
            </div>
            <Dialog open={logDialogOpen} onOpenChange={setLogDialogOpen}>
              <DialogContent className="max-h-[85vh] max-w-4xl overflow-hidden">
                <DialogHeader>
                  <DialogTitle>章节生成日志</DialogTitle>
                  <DialogDescription>
                    支持按 batch_id 过滤，避免页面被日志持续撑长。
                  </DialogDescription>
                </DialogHeader>
                <div className="space-y-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <div className="inline-flex rounded-md border border-border overflow-hidden">
                      <button
                        type="button"
                        className={`px-2 py-1 text-xs ${
                          logViewMode === "all" ? "bg-primary/20" : "bg-transparent"
                        }`}
                        onClick={() => setLogViewMode("all")}
                      >
                        全部
                      </button>
                      <button
                        type="button"
                        className={`px-2 py-1 text-xs border-l border-border ${
                          logViewMode === "batch" ? "bg-primary/20" : "bg-transparent"
                        }`}
                        onClick={() => {
                          setLogViewMode("batch");
                          if (!logBatchId && (refreshBatchId || latestLogBatchId)) {
                            setLogBatchId(refreshBatchId || latestLogBatchId);
                          }
                        }}
                      >
                        当前批次
                      </button>
                    </div>
                    <input
                      value={logBatchId}
                      onChange={(e) => setLogBatchId(e.target.value)}
                      placeholder="可填 batch_id 手动过滤"
                      className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm md:w-80"
                      disabled={logViewMode !== "batch"}
                    />
                    <label className="inline-flex items-center gap-2 text-xs text-muted-foreground">
                      <input
                        type="checkbox"
                        checked={logOnlyError}
                        onChange={(e) => setLogOnlyError(e.target.checked)}
                      />
                      仅看错误
                    </label>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={logBusy}
                      onClick={() =>
                        void reloadGenerationLogs(
                          logViewMode === "batch" ? logBatchId || undefined : undefined
                        )
                      }
                    >
                      {logBusy ? "刷新中…" : "刷新日志"}
                    </Button>
                  </div>
                  <div className="rounded-md border border-border bg-muted/20 p-2">
                    <div className="mb-1 flex items-center justify-between text-xs">
                      <span>
                        记忆刷新进度：{refreshStatus === "queued"
                          ? "已入队"
                          : refreshStatus === "started"
                            ? "执行中"
                            : refreshStatus === "done"
                              ? "已完成"
                              : refreshStatus === "failed"
                                ? "失败"
                                : "空闲"}
                      </span>
                      <span>{refreshProgress}%</span>
                    </div>
                    <div className="h-2 w-full rounded bg-muted">
                      <div
                        className={`h-2 rounded transition-all ${
                          refreshStatus === "failed" ? "bg-destructive" : "bg-primary"
                        }`}
                        style={{ width: `${Math.max(0, Math.min(100, refreshProgress))}%` }}
                      />
                    </div>
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      批次：{refreshBatchId || "-"} · 开始：{formatUtc8(refreshStartedAt)} · 更新时间：
                      {formatUtc8(refreshUpdatedAt)}
                    </p>
                    <p className="text-[11px] text-muted-foreground">
                      已运行时长：{formatDuration(refreshElapsedSeconds)} · 最近成功版本：
                      {latestRefreshVersion == null ? "-" : `v${latestRefreshVersion}`}
                    </p>
                    {refreshLastMessage ? (
                      <p className="text-[11px] text-muted-foreground">{refreshLastMessage}</p>
                    ) : null}
                  </div>
                  <div className="max-h-[55vh] overflow-auto rounded-md border border-border bg-muted/20 p-3 font-mono text-xs">
                    {genLogs.length === 0 ? (
                      <p className="text-muted-foreground">
                        暂无日志。点击“自动续写”或“审定通过”后可在此查看过程细节。
                      </p>
                    ) : (
                      genLogs.map((l) => {
                        const metaView = summarizeLogMeta(l.event, l.meta || {});
                        return (
                          <div
                            key={l.id}
                            className="border-b border-border/50 py-2 last:border-b-0"
                          >
                            <div>
                              <span className="text-muted-foreground">
                                [{formatUtc8(l.created_at)}] [{l.level}] [{l.batch_id}]
                              </span>{" "}
                              <span>
                                {l.chapter_no ? `第${l.chapter_no}章` : "-"} · {l.event} · {l.message}
                              </span>
                            </div>
                            {metaView.summary.length ? (
                              <div className="mt-2 rounded-md border border-border/60 bg-background/60 px-2 py-1.5 text-[11px] text-foreground/90">
                                {metaView.summary.map((item, idx) => (
                                  <p key={`${l.id}-summary-${idx}`}>{item}</p>
                                ))}
                              </div>
                            ) : null}
                            {metaView.detail ? (
                              <details className="mt-2 rounded-md border border-border/60 bg-background/40 px-2 py-1.5">
                                <summary className="cursor-pointer text-[11px] text-muted-foreground">
                                  查看 meta 详情
                                </summary>
                                <pre className="mt-2 whitespace-pre-wrap text-[11px] text-muted-foreground">
                                  {metaView.detail}
                                </pre>
                              </details>
                            ) : null}
                          </div>
                        );
                      })
                    )}
                  </div>
                </div>
              </DialogContent>
            </Dialog>
            <Dialog open={chapterChatOpen} onOpenChange={setChapterChatOpen}>
              <DialogContent className="max-h-[88vh] max-w-3xl overflow-hidden">
                <DialogHeader>
                  <DialogTitle>章节助手对话</DialogTitle>
                  <DialogDescription>
                    自动基于已审定章节、框架与记忆回答问题，可用于续写决策和一致性检查。
                  </DialogDescription>
                </DialogHeader>
                <div className="flex max-h-[52vh] flex-col gap-2 overflow-y-auto rounded-md border border-border bg-muted/20 p-3 text-sm">
                  {chapterChatTurns.length === 0 ? (
                    <p className="text-muted-foreground">
                      例如：\"第 7 章应该先回收哪个伏笔？和主线冲突怎么排优先级？\"
                    </p>
                  ) : null}
                  {chapterChatTurns.map((t, i) => (
                    <div
                      key={`${i}-${t.role}`}
                      className={
                        t.role === "user"
                          ? "ml-8 rounded-md bg-primary/10 px-3 py-2"
                          : "mr-4 rounded-md bg-background px-3 py-2"
                      }
                    >
                      <span className="text-xs font-medium text-muted-foreground">
                        {t.role === "user" ? "你" : "章节助手"}
                      </span>
                      <pre className="mt-1 whitespace-pre-wrap font-sans text-xs">{t.content}</pre>
                    </div>
                  ))}
                </div>
                <div className="space-y-2">
                  <p className="text-xs text-muted-foreground">快捷提问</p>
                  <div className="flex flex-wrap gap-2">
                    {chapterQuickPrompts.map((p) => (
                      <Button
                        key={p.label}
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={chapterChatBusy}
                        onClick={() => void sendChapterQuickPrompt(p.prompt)}
                        className="text-xs"
                        title={p.prompt}
                      >
                        {p.label}
                      </Button>
                    ))}
                  </div>
                  <div className="max-h-20 overflow-auto rounded border border-border/60 bg-muted/30 px-2 py-1 text-[11px] text-muted-foreground">
                    {chapterQuickPrompts.map((p) => (
                      <p key={`desc-${p.label}`} className="truncate">
                        <span className="font-medium">{p.label}：</span>
                        {p.prompt}
                      </p>
                    ))}
                  </div>
                </div>
                {chapterChatErr ? <p className="text-xs text-destructive">{chapterChatErr}</p> : null}
                {chapterChatThinking ? (
                  <div className="rounded-md border border-amber-500/40 bg-amber-500/5 p-2 text-xs">
                    <div className="flex items-center justify-between gap-2">
                      <p className="font-medium text-amber-700 dark:text-amber-300">
                        Think
                      </p>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        className="h-7 px-2 text-[11px]"
                        onClick={() => setChapterThinkExpanded((v) => !v)}
                      >
                        {chapterThinkExpanded ? "折叠" : "展开"}
                      </Button>
                    </div>
                    <pre
                      className={`mt-1 overflow-auto whitespace-pre-wrap font-sans text-[11px] text-amber-800 dark:text-amber-200 ${
                        chapterThinkExpanded ? "max-h-72" : "max-h-24"
                      }`}
                    >
                      {chapterChatThinking}
                    </pre>
                  </div>
                ) : null}
                <textarea
                  value={chapterChatInput}
                  onChange={(e) => setChapterChatInput(e.target.value)}
                  placeholder="输入你的问题…（Enter 发送，Shift+Enter 换行）"
                  className="min-h-[84px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      void sendChapterChat();
                    }
                  }}
                  disabled={chapterChatBusy}
                />
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    size="sm"
                    disabled={chapterChatBusy || !chapterChatInput.trim()}
                    onClick={() => void sendChapterChat()}
                  >
                    {chapterChatBusy ? "思考中…" : "发送"}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    disabled={!chapterChatBusy || !chapterChatAbort}
                    onClick={() => chapterChatAbort?.abort()}
                  >
                    取消生成
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={chapterChatBusy || chapterChatTurns.length === 0}
                    onClick={() => {
                      setChapterChatTurns([]);
                      setChapterChatErr(null);
                      setChapterChatThinking("");
                      setChapterThinkExpanded(false);
                    }}
                  >
                    清空会话
                  </Button>
                </div>
              </DialogContent>
            </Dialog>
            <div className="grid gap-4 lg:grid-cols-12">
              <aside className="lg:col-span-4 rounded-lg border border-border p-3">
                <p className="mb-2 text-xs font-medium text-muted-foreground">章节目录</p>
                <div className="max-h-[70vh] space-y-2 overflow-auto pr-1">
                  {chapters.map((ch) => (
                    <button
                      key={ch.id}
                      type="button"
                      onClick={() => setSelectedChapterId(ch.id)}
                      className={`w-full rounded-md border px-3 py-2 text-left text-xs ${
                        selectedChapterId === ch.id
                          ? "border-primary bg-primary/10"
                          : "border-border bg-background/40 hover:bg-muted/30"
                      }`}
                    >
                      <div className="flex items-center gap-2 font-medium">
                        <span>
                          第{ch.chapter_no}章 {ch.title}
                        </span>
                        {ch.pending_content ? (
                          <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-300">
                            <span className="inline-block h-1.5 w-1.5 rounded-full bg-amber-400" />
                            待确认修订
                          </span>
                        ) : null}
                      </div>
                      <div className="mt-1 text-muted-foreground">
                        {ch.status} · {ch.source}
                      </div>
                      <div className="mt-2">
                        <span
                          role="button"
                          tabIndex={0}
                          className={`inline-block rounded px-2 py-1 text-[11px] ${
                            busy
                              ? "cursor-not-allowed text-muted-foreground"
                              : "cursor-pointer text-destructive hover:bg-destructive/10"
                          }`}
                          onClick={(e) => {
                            e.stopPropagation();
                            if (busy) return;
                            void runDeleteChapter(ch);
                          }}
                          onKeyDown={(e) => {
                            if (e.key !== "Enter" && e.key !== " ") return;
                            e.preventDefault();
                            e.stopPropagation();
                            if (busy) return;
                            void runDeleteChapter(ch);
                          }}
                        >
                          删除
                        </span>
                      </div>
                    </button>
                  ))}
                  {chapters.length === 0 ? (
                    <p className="text-xs text-muted-foreground">暂无章节</p>
                  ) : null}
                </div>
              </aside>

              <section className="lg:col-span-8 rounded-lg border border-border p-4">
                {!selectedChapter ? (
                  <p className="text-sm text-muted-foreground">请选择左侧章节。</p>
                ) : (
                  <div className="space-y-3">
                    <div className="flex flex-wrap items-center gap-2 text-sm">
                      <span className="font-medium">
                        第{selectedChapter.chapter_no}章
                      </span>
                      <span className="text-muted-foreground">
                        {selectedChapter.status}
                      </span>
                      <span className="text-muted-foreground">
                        来源：{selectedChapter.source}
                      </span>
                    </div>
                    <div className="space-y-2">
                      <Label>章节标题</Label>
                      <input
                        value={editTitle}
                        onChange={(e) => setEditTitle(e.target.value)}
                        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>正式稿（可直接编辑）</Label>
                      <textarea
                        value={editContent}
                        onChange={(e) => setEditContent(e.target.value)}
                        className="min-h-[220px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                      />
                      <Button
                        type="button"
                        size="sm"
                        disabled={busy || !editContent.trim()}
                        onClick={() =>
                          run(() =>
                            patchChapter(selectedChapter.id, {
                              title: editTitle,
                              content: editContent,
                            })
                          )
                        }
                      >
                        保存章节修改
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="ml-2 text-destructive"
                        disabled={busy}
                        onClick={() =>
                          void runDeleteChapter({
                            id: selectedChapter.id,
                            chapter_no: selectedChapter.chapter_no,
                            title: selectedChapter.title,
                            status: selectedChapter.status,
                          })
                        }
                      >
                        删除本章
                      </Button>
                    </div>

                    {selectedChapter.pending_content ? (
                      <div className="rounded-md border border-amber-500/40 bg-amber-500/5 p-3">
                        <p className="mb-1 text-xs font-medium text-amber-800 dark:text-amber-200">
                          待确认修订稿
                        </p>
                        <pre className="mb-3 max-h-64 overflow-auto whitespace-pre-wrap text-xs">
                          {selectedChapter.pending_content}
                        </pre>
                        <div className="flex flex-wrap gap-2">
                          <Button
                            type="button"
                            size="sm"
                            disabled={busy}
                            onClick={() => run(() => applyChapterRevision(selectedChapter.id))}
                          >
                            确认覆盖正式稿
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            disabled={busy}
                            onClick={() => run(() => discardChapterRevision(selectedChapter.id))}
                          >
                            放弃修订
                          </Button>
                        </div>
                      </div>
                    ) : null}

                    <div className="space-y-2">
                      <Label>改进意见（可多条，会并入改稿模型）</Label>
                      <textarea
                        value={fbDraft[selectedChapter.id] ?? ""}
                        onChange={(e) =>
                          setFbDraft((d) => ({ ...d, [selectedChapter.id]: e.target.value }))
                        }
                        className="min-h-[72px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                      />
                      <div className="flex flex-wrap gap-2">
                        <Button
                          type="button"
                          size="sm"
                          variant="secondary"
                          disabled={busy || !selectedChapter.content?.trim()}
                          onClick={() => run(() => consistencyFixChapter(selectedChapter.id))}
                        >
                          生成一致性修订稿
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant="secondary"
                          disabled={busy || !(fbDraft[selectedChapter.id]?.trim())}
                          onClick={() =>
                            run(async () => {
                              await addChapterFeedback(
                                selectedChapter.id,
                                fbDraft[selectedChapter.id].trim()
                              );
                              setFbDraft((d) => ({ ...d, [selectedChapter.id]: "" }));
                            })
                          }
                        >
                          记录反馈
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          disabled={busy}
                          onClick={() => void runApproveChapter(selectedChapter.id)}
                        >
                          审定通过
                        </Button>
                      </div>
                    </div>

                    <div className="space-y-2 border-t border-border pt-3">
                      <Label>按指令改稿（调用大模型）</Label>
                      <textarea
                        value={revisePrompt[selectedChapter.id] ?? ""}
                        onChange={(e) =>
                          setRevisePrompt((d) => ({
                            ...d,
                            [selectedChapter.id]: e.target.value,
                          }))
                        }
                        className="min-h-[72px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                        placeholder="例如：加强对话张力、压缩环境描写、按第三条反馈改结尾……"
                      />
                      <Button
                        type="button"
                        size="sm"
                        variant="secondary"
                        disabled={busy || !(revisePrompt[selectedChapter.id]?.trim())}
                        onClick={() =>
                          run(async () => {
                            await reviseChapter(
                              selectedChapter.id,
                              revisePrompt[selectedChapter.id].trim()
                            );
                            setRevisePrompt((d) => ({ ...d, [selectedChapter.id]: "" }));
                          })
                        }
                      >
                        生成修订稿
                      </Button>
                    </div>
                  </div>
                )}
              </section>
            </div>
          </TabsContent>

          <TabsContent value="memory" className="space-y-3">
            <Button
              type="button"
              size="sm"
              disabled={busy}
              onClick={() => void runRefreshMemory()}
            >
              根据已审定章节刷新记忆
            </Button>
            {memory?.version != null && memory.version > 0 ? (
              <p className="text-xs text-muted-foreground">
                当前版本 v{memory.version}
                {memory.created_at ? ` · ${memory.created_at}` : ""}
              </p>
            ) : null}
            <div className="rounded-lg border border-border bg-muted/5 p-4 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm font-medium">结构化记忆（分表）</p>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={
                    busy || memoryNormRebuildBusy || !(memory && memory.version > 0)
                  }
                  onClick={() => void runRebuildMemoryNorm()}
                >
                  {memoryNormRebuildBusy ? "导入中…" : "从快照导入（覆盖结构化）"}
                </Button>
              </div>
              <p className="text-[11px] text-muted-foreground">
                真源为结构化表；审定与刷新会写入表并派生快照。仅在表空或需用快照救场时使用导入。
              </p>
              {!memoryNorm ? (
                <p className="text-xs text-muted-foreground">
                  暂无结构化数据（尚无记忆或尚未同步）。
                </p>
              ) : (
                <div className="max-h-[min(520px,60vh)] space-y-4 overflow-y-auto pr-1 text-xs">
                  <p className="text-[11px] text-muted-foreground">
                    规范表版本 v{memoryNorm.memory_version}
                  </p>
                  <div className="space-y-2 rounded-md border border-border/60 bg-background/40 p-3">
                    <p className="font-medium text-foreground">主线 / 世界观</p>
                    {memoryNorm.outline.main_plot.trim() ? (
                      <p className="whitespace-pre-wrap text-muted-foreground">
                        {memoryNorm.outline.main_plot}
                      </p>
                    ) : (
                      <p className="text-muted-foreground">（无 main_plot）</p>
                    )}
                    {[
                      ["世界规则", memoryNorm.outline.world_rules],
                      ["弧光 / 卷线", memoryNorm.outline.arcs],
                      ["主题", memoryNorm.outline.themes],
                      ["备注 notes", memoryNorm.outline.notes],
                      ["时间线归档摘要", memoryNorm.outline.timeline_archive_summary],
                    ].map(([label, arr]) =>
                      Array.isArray(arr) && arr.length ? (
                        <div key={String(label)} className="space-y-1">
                          <p className="text-[11px] font-medium text-foreground/80">
                            {String(label)}
                          </p>
                          <ul className="list-disc space-y-0.5 pl-4 text-muted-foreground">
                            {arr.map((x, i) => (
                              <li key={`ol-${String(label)}-${i}`}>
                                {typeof x === "string" ? x : JSON.stringify(x)}
                              </li>
                            ))}
                          </ul>
                        </div>
                      ) : null
                    )}
                  </div>
                  {memoryNorm.skills.length > 0 ? (
                    <div className="space-y-2 rounded-md border border-border/60 bg-background/40 p-3">
                      <p className="font-medium text-foreground">技能</p>
                      <ul className="space-y-2">
                        {memoryNorm.skills.map((s, i) => (
                          <li
                            key={`sk-${i}-${s.name}`}
                            className="rounded border border-border/40 bg-muted/20 p-2"
                          >
                            <span className="font-medium text-foreground">{s.name}</span>
                            {Object.keys(s.detail || {}).length ? (
                              <pre className="mt-1 overflow-x-auto text-[11px] text-muted-foreground">
                                {JSON.stringify(s.detail, null, 2)}
                              </pre>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {memoryNorm.inventory.length > 0 ? (
                    <div className="space-y-2 rounded-md border border-border/60 bg-background/40 p-3">
                      <p className="font-medium text-foreground">物品</p>
                      <ul className="space-y-2">
                        {memoryNorm.inventory.map((it, i) => (
                          <li
                            key={`inv-${i}-${it.label}`}
                            className="rounded border border-border/40 bg-muted/20 p-2"
                          >
                            <span className="font-medium text-foreground">{it.label}</span>
                            {Object.keys(it.detail || {}).length ? (
                              <pre className="mt-1 overflow-x-auto text-[11px] text-muted-foreground">
                                {JSON.stringify(it.detail, null, 2)}
                              </pre>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {memoryNorm.pets.length > 0 ? (
                    <div className="space-y-2 rounded-md border border-border/60 bg-background/40 p-3">
                      <p className="font-medium text-foreground">宠物 / 从属</p>
                      <ul className="space-y-2">
                        {memoryNorm.pets.map((p, i) => (
                          <li
                            key={`pet-${i}-${p.name}`}
                            className="rounded border border-border/40 bg-muted/20 p-2"
                          >
                            <span className="font-medium text-foreground">{p.name}</span>
                            {Object.keys(p.detail || {}).length ? (
                              <pre className="mt-1 overflow-x-auto text-[11px] text-muted-foreground">
                                {JSON.stringify(p.detail, null, 2)}
                              </pre>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {memoryNorm.characters.length > 0 ? (
                    <div className="space-y-2 rounded-md border border-border/60 bg-background/40 p-3">
                      <p className="font-medium text-foreground">人物</p>
                      <ul className="space-y-2">
                        {memoryNorm.characters.map((c, i) => (
                          <li
                            key={`ch-${i}-${c.name}`}
                            className="rounded border border-border/40 bg-muted/20 p-2"
                          >
                            <div className="font-medium text-foreground">{c.name}</div>
                            {(c.role || c.status) && (
                              <p className="text-[11px] text-muted-foreground">
                                {[c.role, c.status].filter(Boolean).join(" · ")}
                              </p>
                            )}
                            {Array.isArray(c.traits) && c.traits.length ? (
                              <p className="mt-1 text-[11px] text-muted-foreground">
                                特征：{c.traits.map(String).join("；")}
                              </p>
                            ) : null}
                            {Object.keys(c.detail || {}).length ? (
                              <pre className="mt-1 overflow-x-auto text-[11px] text-muted-foreground">
                                {JSON.stringify(c.detail, null, 2)}
                              </pre>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {memoryNorm.relations.length > 0 ? (
                    <div className="space-y-2 rounded-md border border-border/60 bg-background/40 p-3">
                      <p className="font-medium text-foreground">人物关系</p>
                      <ul className="list-disc space-y-1 pl-4 text-muted-foreground">
                        {memoryNorm.relations.map((r, i) => (
                          <li key={`rel-${i}`}>
                            {r.from} → {r.to}：{r.relation}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {memoryNorm.open_plots.length > 0 ? (
                    <div className="space-y-2 rounded-md border border-border/60 bg-background/40 p-3">
                      <p className="font-medium text-foreground">全书待收束线</p>
                      <ul className="list-disc space-y-1 pl-4 text-muted-foreground">
                        {memoryNorm.open_plots.map((line, i) => (
                          <li key={`op-${i}`}>{line}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {memoryNorm.chapters.length > 0 ? (
                    <div className="space-y-2 rounded-md border border-border/60 bg-background/40 p-3">
                      <p className="font-medium text-foreground">分章脉络（事实与因果）</p>
                      <div className="space-y-3">
                        {memoryNorm.chapters.map((ch) => (
                          <div
                            key={ch.chapter_no}
                            className="rounded border border-border/40 bg-muted/10 p-2"
                          >
                            <p className="font-medium text-foreground">
                              第{ch.chapter_no}章
                              {ch.chapter_title ? `《${ch.chapter_title}》` : ""}
                            </p>
                            {ch.key_facts.length ? (
                              <div className="mt-1">
                                <span className="text-[10px] uppercase text-muted-foreground">
                                  关键事实
                                </span>
                                <ul className="list-disc pl-4 text-muted-foreground">
                                  {ch.key_facts.map((x, i) => (
                                    <li key={`kf-${i}`}>{x}</li>
                                  ))}
                                </ul>
                              </div>
                            ) : null}
                            {ch.causal_results.length ? (
                              <div className="mt-1">
                                <span className="text-[10px] uppercase text-muted-foreground">
                                  因果
                                </span>
                                <ul className="list-disc pl-4 text-muted-foreground">
                                  {ch.causal_results.map((x, i) => (
                                    <li key={`cr-${i}`}>{x}</li>
                                  ))}
                                </ul>
                              </div>
                            ) : null}
                            {ch.open_plots_added.length ? (
                              <div className="mt-1">
                                <span className="text-[10px] text-emerald-600/90">
                                  本章新埋线
                                </span>
                                <ul className="list-disc pl-4 text-muted-foreground">
                                  {ch.open_plots_added.map((x, i) => (
                                    <li key={`oa-${i}`}>{x}</li>
                                  ))}
                                </ul>
                              </div>
                            ) : null}
                            {ch.open_plots_resolved.length ? (
                              <div className="mt-1">
                                <span className="text-[10px] text-amber-600/90">
                                  本章已收束
                                </span>
                                <ul className="list-disc pl-4 text-muted-foreground">
                                  {ch.open_plots_resolved.map((x, i) => (
                                    <li key={`or-${i}`}>{x}</li>
                                  ))}
                                </ul>
                              </div>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </div>
              )}
            </div>
            {memoryRefreshPreview ? (
              <div className="space-y-3 rounded-xl border border-amber-500/30 bg-amber-500/5 p-4">
                <div className="space-y-1">
                  <p className="text-sm font-medium text-amber-400">候选记忆已被拦截</p>
                  <p className="text-xs text-muted-foreground">
                    当前仍保留生效版本 v{memoryRefreshPreview.version}。以下为校验未通过原因（记忆未被覆盖）。
                  </p>
                </div>
                <div className="rounded-md border border-amber-500/20 bg-background/60 p-3">
                  <p className="mb-2 text-xs font-medium text-foreground">拦截原因</p>
                  <div className="space-y-1 text-xs text-amber-300">
                    {memoryRefreshPreview.errors.map((item, idx) => (
                      <p key={`mem-refresh-err-${idx}`}>- {item}</p>
                    ))}
                  </div>
                </div>
              </div>
            ) : null}
            {memory?.summary ? (
              <p className="text-xs text-muted-foreground">备注：{memory.summary}</p>
            ) : null}
            <div className="rounded-md border border-border bg-muted/10 p-3 space-y-3">
              <p className="text-sm font-medium">剧情承接与微调（面向最近一章）</p>
              <p className="text-xs text-muted-foreground">
                左侧维护全书仍未了结的剧情线；右侧对应「最近一章」在时间与因果上的锚点、新埋线与本章内已了结的线，用于衔接下一章写作。
              </p>
              <div className="grid gap-3 md:grid-cols-2">
                <div className="space-y-2">
                  {renderLineEditor(
                    "全书待收束线",
                    openPlotsLines,
                    setOpenPlotsLines,
                    "例如：顾寒答应苏青在第六章前拿到通行芯片",
                    "建议写成「谁—要做什么—截止或前提」，方便后文对照回收。"
                  )}
                </div>
                <div className="space-y-2">
                  {renderLineEditor(
                    "本章关键事实（锚点）",
                    keyFactsLines,
                    setKeyFactsLines,
                    "例如：顾寒确认“芯片需在水中激活”",
                    "只写本章已坐实的信息，后文不应自相矛盾。"
                  )}
                  {renderLineEditor(
                    "前因后果（本章）",
                    causalResultsLines,
                    setCausalResultsLines,
                    "例如：因暴露身份，顾寒被治安队列入追捕名单",
                    "用一两句写清「因何而起 → 导致何种局面」。"
                  )}
                  {renderLineEditor(
                    "本章新埋线",
                    openPlotsAddedLines,
                    setOpenPlotsAddedLines,
                    "例如：苏青被带走，去向未知",
                    "本章新抛出的悬念或待交代事项。"
                  )}
                  {renderLineEditor(
                    "本章已收束",
                    openPlotsResolvedLines,
                    setOpenPlotsResolvedLines,
                    "例如：顾寒已拿到第一枚激活芯片",
                    "本章内明确了结或兑现的剧情点。"
                  )}
                </div>
              </div>
              <div className="flex gap-2">
                <Button
                  type="button"
                  size="sm"
                  disabled={busy || memoryFixBusy}
                  onClick={() => void saveMemoryFix()}
                >
                  {memoryFixBusy ? "保存中…" : "保存承接信息"}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  asChild
                >
                  <Link to={`/novels/${id}/metrics`}>去指标页查看完整诊断</Link>
                </Button>
              </div>
              {memoryFixHints.length > 0 ? (
                <div className="rounded-md border border-amber-500/40 bg-amber-500/5 p-3">
                  <p className="text-xs font-medium text-amber-300">保存前提醒</p>
                  <ul className="mt-1 list-disc space-y-1 pl-5 text-xs text-amber-200/90">
                    {memoryFixHints.map((h, i) => (
                      <li key={`${h}-${i}`}>{h}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          </TabsContent>
        </Tabs>
      </div>
      {/* 用户设置弹窗 */}
      <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}>
        <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Settings className="h-5 w-5" />
              用户设置
            </DialogTitle>
            <DialogDescription>
              配置全局大模型参数及界面风格。
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-6 py-4">
            {/* 主题设置 */}
            <section className="space-y-3">
              <Label className="text-sm font-bold uppercase tracking-wider text-muted-foreground">
                界面风格
              </Label>
              <div className="grid grid-cols-3 gap-3">
                {[
                  { id: "light", label: "浅色", icon: Sun },
                  { id: "dark", label: "深色", icon: Moon },
                  { id: "system", label: "跟随系统", icon: Monitor },
                ].map((item) => (
                  <button
                    key={item.id}
                    onClick={() => setTheme(item.id as "dark" | "light" | "system")}
                    className={`flex flex-col items-center justify-center gap-2 rounded-lg border-2 p-3 transition-all ${
                      theme === item.id
                        ? "border-primary bg-primary/5 text-primary"
                        : "border-muted bg-transparent hover:border-muted-foreground/30 text-muted-foreground"
                    }`}
                  >
                    <item.icon className="h-5 w-5" />
                    <span className="text-xs font-medium">{item.label}</span>
                    {theme === item.id && (
                      <div className="absolute top-1 right-1">
                        <Check className="h-3 w-3" />
                      </div>
                    )}
                  </button>
                ))}
              </div>
            </section>

            {/* 模型设置 */}
            <section className="space-y-4 pt-2 border-t border-border">
              <Label className="text-sm font-bold uppercase tracking-wider text-muted-foreground">
                大模型配置
              </Label>
              
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label>Provider</Label>
                  <select
                    value={llmCfg?.provider || "ai302"}
                    onChange={(e) => setLlmCfg(prev => prev ? { ...prev, provider: e.target.value } : null)}
                    className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm focus:ring-2 focus:ring-primary outline-none"
                    disabled={settingsBusy}
                  >
                    <option value="ai302">302AI</option>
                    <option value="custom">自建代理</option>
                  </select>
                </div>

                <div className="space-y-2">
                  <Label>模型名称</Label>
                  <input
                    value={llmCfg?.model || ""}
                    onChange={(e) => setLlmCfg(prev => prev ? { ...prev, model: e.target.value } : null)}
                    className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm focus:ring-2 focus:ring-primary outline-none"
                    placeholder="例如: glm-4.7"
                    disabled={settingsBusy}
                  />
                </div>
              </div>

              <div className="space-y-3 rounded-xl border border-border bg-muted/30 p-4">
                <Label className="text-xs font-semibold text-muted-foreground italic">联网搜索 (Web Search)</Label>
                <div className="grid gap-3 pt-1">
                  {[
                    { id: "novel_generate_web_search" as const, label: "章节续写" },
                    { id: "novel_volume_plan_web_search" as const, label: "卷章计划" },
                    { id: "novel_memory_refresh_web_search" as const, label: "记忆刷新" },
                    { id: "novel_inspiration_web_search" as const, label: "灵感对话" },
                    { id: "novel_web_search" as const, label: "其他(助手/框架)" },
                  ].map((field) => (
                    <label key={field.id} className="flex items-center justify-between group cursor-pointer">
                      <span className="text-sm group-hover:text-foreground transition-colors">{field.label}</span>
                      <input
                        type="checkbox"
                        checked={Boolean(llmCfg?.[field.id])}
                        onChange={(e) => setLlmCfg(prev => prev ? { ...prev, [field.id]: e.target.checked } : null)}
                        className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"
                        disabled={settingsBusy}
                      />
                    </label>
                  ))}
                </div>
              </div>
            </section>
          </div>

          <DialogFooter className="gap-2 sm:gap-0">
            <Button
              variant="outline"
              onClick={() => setSettingsOpen(false)}
              disabled={settingsBusy}
            >
              取消
            </Button>
            <Button
              onClick={() => {
                if (llmCfg) {
                  handleSaveSettings(llmCfg).then(() => setSettingsOpen(false));
                }
              }}
              disabled={settingsBusy}
            >
              {settingsBusy ? "保存中..." : "保存配置"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
