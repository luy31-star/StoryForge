import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { X } from "lucide-react";
import { LlmActionConfirmDialog } from "@/components/LlmActionConfirmDialog";
import { FrameworkWizardDialog } from "@/components/FrameworkWizardDialog";
import { WritingStyleSelect } from "@/components/WritingStyleSelect";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  addChapterFeedback,
  applyRefreshMemoryCandidate,
  applyChapterRevision,
  approveChapter,
  chapterContextChatStream,
  consistencyFixChapter,
  clearVolumeChapterPlans,
  clearGenerationLogs,
  confirmFramework,
  deleteChapter,
  discardChapterRevision,
  exportChapters,
  generateChapters,
  autoGenerateChapters,
  generateVolumeChapterPlan,
  generateVolumes,
  getMemory,
  getMemoryNormalized,
  getMemoryHistory,
  clearMemory,
  rollbackMemory,
  rebuildMemoryNormalized,
  formatMemoryPlotLine,
  type MemoryHealth,
  type MemorySchemaGuide,
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
  retryChapterMemory,
  reviseChapter,
  waitForChapterConsistencyBatch,
  waitForChapterGenerationBatch,
  waitForChapterReviseBatch,
  waitForMemoryRefreshBatch,
  waitForVolumePlanBatch,
} from "@/services/novelApi";
import { ensureLlmReady } from "@/services/llmReady";

const STRUCTURED_LIST_PAGE = 8;
/** 剧情承接与微调区：每类行列表分页，避免单屏过长 */
const CONTINUITY_LINE_PAGE = 8;
const CHAPTER_PAGE_SIZE = 3;
type WorkspaceTab = "framework" | "volumes" | "chapters" | "memory";

function totalPages(n: number, pageSize: number): number {
  return Math.max(1, Math.ceil(Math.max(0, n) / pageSize));
}

function slicePage<T>(items: T[], page: number, pageSize: number): T[] {
  const start = page * pageSize;
  return items.slice(start, start + pageSize);
}

function safeJsonStringify(data: unknown): string {
  try {
    return JSON.stringify(data, null, 2);
  } catch {
    return String(data);
  }
}

function isJsonLikeText(value: string): boolean {
  const trimmed = value.trim();
  return trimmed.startsWith("{") || trimmed.startsWith("[");
}

function inventoryDisplayLabel(
  item: NormalizedMemoryPayload["inventory"][number]
): string {
  const candidates = [
    item.label,
    typeof item.detail.item_name === "string" ? item.detail.item_name : "",
    typeof item.detail.name === "string" ? item.detail.name : "",
    typeof item.detail.item === "string" ? item.detail.item : "",
    typeof item.detail.title === "string" ? item.detail.title : "",
  ];
  for (const candidate of candidates) {
    const text = String(candidate || "").trim();
    if (!text) continue;
    if (candidate === item.label && isJsonLikeText(text)) continue;
    return text;
  }
  return "未命名物品";
}

function inventoryDisplaySummary(
  item: NormalizedMemoryPayload["inventory"][number]
): string {
  const owner =
    typeof item.detail.owner === "string" ? item.detail.owner.trim() : "";
  const description =
    typeof item.detail.description === "string"
      ? item.detail.description.trim()
      : "";
  if (owner && description) return `${owner} · ${description}`;
  if (description) return description;
  if (owner) return `持有人：${owner}`;
  return "";
}

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
  } else if (event === "memory_refresh_warning") {
    const warnings = Array.isArray(meta.warnings)
      ? meta.warnings.map((x) => String(x).trim()).filter(Boolean)
      : [];
    const autoPass = Array.isArray(meta.auto_pass_notes)
      ? meta.auto_pass_notes.map((x) => String(x).trim()).filter(Boolean)
      : [];
    if (warnings.length) summary.push(...warnings.slice(0, 4));
    if (!warnings.length && autoPass.length) summary.push(...autoPass.slice(0, 2));
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
    if (
      event === "chapter_memory_delta_failed" ||
      event === "memory_refresh_validation_failed"
    ) {
      return !["errors", "batch"].includes(key);
    }
    if (event === "memory_refresh_warning") {
      return !["warnings", "auto_pass_notes"].includes(key);
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

type LlmConfirmState = {
  title: string;
  description: string;
  confirmLabel: string;
  details: string[];
};

export function NovelWorkspace() {
  const { id = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const [novel, setNovel] = useState<Record<string, unknown> | null>(null);
  const [chapters, setChapters] = useState<Awaited<ReturnType<typeof listChapters>>>([]);
  const [memory, setMemory] = useState<Awaited<ReturnType<typeof getMemory>> | null>(null);
  const [memoryNorm, setMemoryNorm] = useState<NormalizedMemoryPayload | null>(null);
  const [memorySchemaGuide, setMemorySchemaGuide] = useState<MemorySchemaGuide | null>(null);
  const [memoryHealth, setMemoryHealth] = useState<MemoryHealth | null>(null);
  const [memoryNormRebuildBusy, setMemoryNormRebuildBusy] = useState(false);
  const [fwMd, setFwMd] = useState("");
  const [fwJson, setFwJson] = useState("{}");
  const [frameworkWizardOpen, setFrameworkWizardOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("framework");
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
    tier: "blocked" | "warning";
    version: number;
    currentVersion: number;
    errors: string[];
    warnings: string[];
    autoPassNotes: string[];
    candidateJson: string;
    candidateReadableZh: string;
    confirmationToken?: string;
  } | null>(null);
  const [structuredPages, setStructuredPages] = useState<Record<string, number>>({});
  const [memoryFixListPages, setMemoryFixListPages] = useState<Record<string, number>>({});
  const [normDetailOpen, setNormDetailOpen] = useState(false);
  const [normDetailTitle, setNormDetailTitle] = useState("");
  const [normDetailBody, setNormDetailBody] = useState("");
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
  const [latestMemoryVersion, setLatestMemoryVersion] = useState<number | null>(null);
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
  const [chapterVolumeId, setChapterVolumeId] = useState<string>("");
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
  /** 为 false 时隐藏「已有正文/待审稿」的章计划卡片，便于往下续写 */
  const [showVolumePlanWithBody, setShowVolumePlanWithBody] = useState(false);
  const [memoryHistory, setMemoryHistory] = useState<
    {
      version: number;
      summary: string;
      created_at: string | null;
    }[]
  >([]);
  const [historyDialogOpen, setHistoryDialogOpen] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [titleBusy, setTitleBusy] = useState(false);
  const [llmConfirm, setLlmConfirm] = useState<LlmConfirmState | null>(null);
  const [llmConfirmBusy, setLlmConfirmBusy] = useState(false);
  const llmConfirmActionRef = useRef<null | (() => Promise<void>)>(null);

  const [novelSettingsOpen, setNovelSettingsOpen] = useState(false);
  const [novelSettingsDraft, setNovelSettingsDraft] = useState({
    target_chapters: 300,
    daily_auto_chapters: 0,
    daily_auto_time: "14:30",
    chapter_target_words: 3000,
    style: "",
    writing_style_id: "",
  });
  const [novelSettingsBusy, setNovelSettingsBusy] = useState(false);

  const [exportOpen, setExportOpen] = useState(false);
  const [exportStartNo, setExportStartNo] = useState(1);
  const [exportEndNo, setExportEndNo] = useState(9999);
  const [exportContent, setExportContent] = useState("");
  const [exportBusy, setExportBusy] = useState(false);

  const [refreshRangeOpen, setRefreshRangeOpen] = useState(false);
  const [refreshRangeMode, setRefreshRangeMode] = useState<"recent" | "full" | "custom">("recent");
  const [refreshFromNo, setRefreshFromNo] = useState(1);
  const [refreshToNo, setRefreshToNo] = useState(1);

  async function handleExport() {
    if (!id) return;
    setExportBusy(true);
    try {
      const res = await exportChapters(id, exportStartNo, exportEndNo);
      setExportContent(res.full_text);
    } catch (e: any) {
      setErr(e.message || "导出失败");
    } finally {
      setExportBusy(false);
    }
  }


  function openNovelSettings() {
    if (!novel) return;
    setNovelSettingsDraft({
      target_chapters: Number(novel.target_chapters || 300),
      daily_auto_chapters: Number(novel.daily_auto_chapters || 0),
      daily_auto_time: String(novel.daily_auto_time || "14:30"),
      chapter_target_words: Number(novel.chapter_target_words || 3000),
      style: String(novel.style || ""),
      writing_style_id: String(novel.writing_style_id || ""),
    });
    setNovelSettingsOpen(true);
  }

  async function handleSaveNovelSettings() {
    if (!novel) return;
    setNovelSettingsBusy(true);
    setErr(null);
    try {
      await patchNovel(novel.id as string, novelSettingsDraft);
      setNotice("小说设置已保存");
      setNovelSettingsOpen(false);
      await reload();
      await reloadVolumes();
      setTimeout(() => setNotice(null), 3000);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setNovelSettingsBusy(false);
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
    const normalizedSchemaGuide =
      "schema_guide" in mn ? (mn.schema_guide ?? null) : null;
    const normalizedHealth = "health" in mn ? (mn.health ?? null) : null;
    setMemorySchemaGuide(normalizedSchemaGuide ?? m.schema_guide ?? null);
    setMemoryHealth(normalizedHealth ?? m.health ?? null);
    if (mn.status === "ok" && mn.data) {
      setMemoryNorm(mn.data);
    } else {
      setMemoryNorm(null);
    }
    setFwMd(String(n.framework_markdown ?? ""));
    setFwJson(String(n.framework_json ?? "{}"));
  }, [id]);

  const openNormDetail = useCallback((title: string, data: unknown) => {
    setNormDetailTitle(title);
    setNormDetailBody(
      typeof data === "string" ? data : safeJsonStringify(data)
    );
    setNormDetailOpen(true);
  }, []);

  useEffect(() => {
    setStructuredPages({});
  }, [memoryNorm?.memory_version]);

  useEffect(() => {
    setShowVolumePlanWithBody(false);
  }, [selectedVolumeId]);

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
    const w = searchParams.get("wizard");
    if (w !== "1") return;
    setFrameworkWizardOpen(true);
    const next = new URLSearchParams(searchParams);
    next.delete("wizard");
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

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

  const filteredChapters = useMemo(() => {
    if (!volumes.length) return chapters;
    const vid = chapterVolumeId || (volumes.length > 0 ? volumes[0].id : "");
    if (!vid) return chapters;
    const v = volumes.find((x) => x.id === vid);
    if (!v) return chapters;
    return chapters.filter(
      (c) => c.chapter_no >= v.from_chapter && c.chapter_no <= v.to_chapter
    );
  }, [chapters, volumes, chapterVolumeId]);

  useEffect(() => {
    if (!selectedChapterId || !chapters.length || !volumes.length) return;
    const ch = chapters.find((x) => x.id === selectedChapterId);
    if (!ch) return;
    const v = volumes.find(
      (x) => ch.chapter_no >= x.from_chapter && ch.chapter_no <= x.to_chapter
    );
    if (v && v.id !== chapterVolumeId) {
      setChapterVolumeId(v.id);
    }
  }, [selectedChapterId, chapters, volumes, chapterVolumeId]);

  const selectedChapter = chapters.find((c) => c.id === selectedChapterId) ?? null;
  const selectedChapterWordCount = editContent.trim()
    ? editContent.trim().replace(/\s+/g, "").length
    : 0;
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
    const clearContinuity = () => {
      setOpenPlotsLines([]);
      setKeyFactsLines([]);
      setCausalResultsLines([]);
      setOpenPlotsAddedLines([]);
      setOpenPlotsResolvedLines([]);
    };

    /** 与「结构化记忆」同源：分表为真源；仅用快照时易与分表不一致导致承接区空白 */
    function fillFromNormalized(norm: NormalizedMemoryPayload) {
      const op = (norm.open_plots ?? [])
        .map((x) => formatMemoryPlotLine(x))
        .filter((s) => s.length > 0);
      const chs = [...(norm.chapters ?? [])].sort(
        (a, b) => a.chapter_no - b.chapter_no
      );
      const last = chs.length ? chs[chs.length - 1] : null;
      const toLines = (arr: unknown): string[] => {
        if (!Array.isArray(arr)) return [];
        return arr
          .map((x) =>
            typeof x === "string" ? x : formatMemoryPlotLine(x)
          )
          .filter((s) => s.length > 0);
      };
      setOpenPlotsLines(op);
      if (last) {
        setKeyFactsLines(toLines(last.key_facts));
        setCausalResultsLines(toLines(last.causal_results));
        setOpenPlotsAddedLines(toLines(last.open_plots_added));
        setOpenPlotsResolvedLines(toLines(last.open_plots_resolved));
      } else {
        setKeyFactsLines([]);
        setCausalResultsLines([]);
        setOpenPlotsAddedLines([]);
        setOpenPlotsResolvedLines([]);
      }
    }

    if (memoryNorm) {
      fillFromNormalized(memoryNorm);
      return;
    }

    if (!memory?.payload_json) {
      clearContinuity();
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
      clearContinuity();
    }
  }, [memory?.payload_json, memoryNorm]);

  const volumePlanView = useMemo(() => {
    const hasGeneratedBody = (chapterNo: number) => {
      const ch = chapters.find((c) => c.chapter_no === chapterNo);
      if (!ch) return false;
      return (ch.content || ch.pending_content || "").trim().length > 0;
    };
    const withBodyCount = volumePlan.filter((p) =>
      hasGeneratedBody(p.chapter_no)
    ).length;
    const visible = showVolumePlanWithBody
      ? volumePlan
      : volumePlan.filter((p) => !hasGeneratedBody(p.chapter_no));
    return { visible, withBodyCount };
  }, [volumePlan, chapters, showVolumePlanWithBody]);

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

  function normPager(pageKey: string, total: number, pageSize: number) {
    const page = structuredPages[pageKey] ?? 0;
    const tp = totalPages(total, pageSize);
    if (total <= pageSize) return null;
    return (
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border/40 pt-3 text-[11px] text-muted-foreground">
        <span className="status-badge">共 {total} 条</span>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-7 rounded-full px-3 text-xs"
            disabled={page <= 0}
            onClick={() =>
              setStructuredPages((s) => ({ ...s, [pageKey]: page - 1 }))
            }
          >
            上一页
          </Button>
          <span className="glass-chip px-2.5 py-1 tabular-nums">
            {page + 1} / {tp}
          </span>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-7 rounded-full px-3 text-xs"
            disabled={page >= tp - 1}
            onClick={() =>
              setStructuredPages((s) => ({ ...s, [pageKey]: page + 1 }))
            }
          >
            下一页
          </Button>
        </div>
      </div>
    );
  }

  function renderLineEditor(
    label: string,
    lines: string[],
    setLines: (v: string[]) => void,
    placeholder: string,
    helper?: string,
    pageKey?: string
  ) {
    const pageSize = CONTINUITY_LINE_PAGE;
    const page = pageKey ? (memoryFixListPages[pageKey] ?? 0) : 0;
    const nonEmpty = lines.filter((line) => line.trim()).length;
    const totalPages =
      pageKey && lines.length > 0
        ? Math.max(1, Math.ceil(lines.length / pageSize))
        : 1;
    const safePage = pageKey ? Math.min(page, totalPages - 1) : 0;
    const start = pageKey ? safePage * pageSize : 0;
    const visible = pageKey
      ? slicePage(lines, safePage, pageSize)
      : lines;

    return (
      <div className="glass-panel-subtle space-y-3 p-4">
        <div className="flex items-center justify-between">
          <div className="space-y-1">
            <Label className="text-sm font-medium text-foreground">{label}</Label>
            <p className="text-[11px] text-muted-foreground">
              当前 {nonEmpty} 条
              {pageKey && lines.length > 0
                ? ` · 第 ${safePage + 1}/${totalPages} 页`
                : null}
            </p>
          </div>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => setLines([...lines, ""])}
          >
            + 新增
          </Button>
        </div>
        {helper ? <p className="text-[11px] leading-5 text-muted-foreground">{helper}</p> : null}
        <div className="space-y-2">
          {lines.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-border/80 px-3 py-3 text-xs text-muted-foreground">
              暂无条目，点击“新增”开始填写
            </div>
          ) : null}
          {visible.map((line, localIdx) => {
            const idx = start + localIdx;
            return (
            <div
              key={`${label}-${idx}`}
              className="list-card flex items-center gap-2 px-3 py-2.5"
            >
              <span className="status-badge w-8 shrink-0 justify-center px-0">
                {idx + 1}
              </span>
              <input
                value={line}
                onChange={(e) => {
                  const next = [...lines];
                  next[idx] = e.target.value;
                  setLines(next);
                }}
                className="field-shell h-10 w-full border-0 bg-transparent px-0 py-0 shadow-none focus-visible:ring-0"
                placeholder={placeholder}
              />
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                onClick={() => setLines(lines.filter((_, i) => i !== idx))}
              >
                删除
              </Button>
            </div>
            );
          })}
        </div>
        {pageKey && lines.length > pageSize ? (
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border/60 pt-2">
            <span className="text-[11px] text-muted-foreground">
              本类共 {lines.length} 行，分页展示
            </span>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="h-7 rounded-full px-3 text-xs"
                disabled={safePage <= 0}
                onClick={() =>
                  setMemoryFixListPages((s) => ({
                    ...s,
                    [pageKey]: Math.max(0, safePage - 1),
                  }))
                }
              >
                上一页
              </Button>
              <span className="glass-chip px-2.5 py-1 tabular-nums text-[11px]">
                {safePage + 1} / {totalPages}
              </span>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="h-7 rounded-full px-3 text-xs"
                disabled={safePage >= totalPages - 1}
                onClick={() =>
                  setMemoryFixListPages((s) => ({
                    ...s,
                    [pageKey]: Math.min(totalPages - 1, safePage + 1),
                  }))
                }
              >
                下一页
              </Button>
            </div>
          </div>
        ) : null}
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

  async function openLlmConfirm(
    config: LlmConfirmState,
    action: () => Promise<void>
  ) {
    const ok = await ensureLlmReady();
    if (!ok) return;
    llmConfirmActionRef.current = action;
    setLlmConfirm(config);
  }

  function handleLlmConfirmOpenChange(open: boolean) {
    if (open || llmConfirmBusy) return;
    llmConfirmActionRef.current = null;
    setLlmConfirm(null);
  }

  async function runConfirmedLlmAction() {
    const action = llmConfirmActionRef.current;
    if (!action) return;
    setLlmConfirmBusy(true);
    try {
      await action();
      llmConfirmActionRef.current = null;
      setLlmConfirm(null);
    } finally {
      setLlmConfirmBusy(false);
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
      if (resp.latest_memory_version != null) {
        setLatestMemoryVersion(resp.latest_memory_version);
      }
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "加载生成日志失败");
    } finally {
      setLogBusy(false);
    }
  }

  async function executeRefreshMemory(options: { from_chapter_no?: number; to_chapter_no?: number; is_full?: boolean } = {}) {
    if (!id) return;
    setErr(null);
    setNotice(null);
    setBusy(true);
    setRefreshRangeOpen(false);
    try {
      const resp = await refreshMemory(id, options);
      if (resp.status !== "queued" || !resp.batch_id) {
        setErr("记忆刷新未能入队");
        return;
      }
      setRefreshBatchId(resp.batch_id);
      await reload(); // 清除失败横幅
      if (logViewMode === "batch") {
        setLogBatchId(resp.batch_id);
      }
      await reloadGenerationLogs(
        logViewMode === "batch" ? resp.batch_id : undefined
      );
      setNotice("记忆刷新已在后台执行，完成后将更新本页提示。");

      const finalLog = await waitForMemoryRefreshBatch(id, resp.batch_id);
      const outcome = finalLog.refresh_outcome ?? "idle";
      const preview = finalLog.memory_refresh_preview;

      if (outcome === "blocked" && preview && typeof preview === "object") {
        const p = preview as Record<string, unknown>;
        const cv = typeof p.current_version === "number" ? p.current_version : 0;
        setMemoryRefreshPreview({
          tier: "blocked",
          version: cv,
          currentVersion: cv,
          errors: Array.isArray(p.errors) ? (p.errors as string[]) : [],
          warnings: Array.isArray(p.warnings) ? (p.warnings as string[]) : [],
          autoPassNotes: Array.isArray(p.auto_pass_notes)
            ? (p.auto_pass_notes as string[])
            : [],
          candidateJson: String(p.candidate_json ?? "{}"),
          candidateReadableZh: String(p.candidate_readable_zh ?? ""),
        });
        setNotice(
          "候选记忆已生成，但这版风险过高，系统已自动保留当前生效记忆。"
        );
      } else if (outcome === "warning" && preview && typeof preview === "object") {
        const p = preview as Record<string, unknown>;
        const cv = typeof p.current_version === "number" ? p.current_version : 0;
        setMemoryRefreshPreview({
          tier: "warning",
          version: cv,
          currentVersion: cv,
          errors: [],
          warnings: Array.isArray(p.warnings) ? (p.warnings as string[]) : [],
          autoPassNotes: Array.isArray(p.auto_pass_notes)
            ? (p.auto_pass_notes as string[])
            : [],
          candidateJson: String(p.candidate_json ?? "{}"),
          candidateReadableZh: String(p.candidate_readable_zh ?? ""),
          confirmationToken: String(p.confirmation_token ?? ""),
        });
        setNotice(
          "候选记忆已生成，这次变更建议你先看一眼再决定是否替换当前版本。"
        );
      } else if (outcome === "ok") {
        setMemoryRefreshPreview(null);
        setNotice("记忆已按已审定章节刷新。");
      } else if (outcome === "failed") {
        setMemoryRefreshPreview(null);
        setErr("记忆刷新失败，请查看生成日志");
      } else {
        setMemoryRefreshPreview(null);
        setNotice("记忆刷新任务已结束。");
      }
      await reload();
      await reloadGenerationLogs(
        logViewMode === "batch" ? logBatchId || resp.batch_id : undefined
      );
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "刷新记忆失败");
    } finally {
      setBusy(false);
    }
  }

  async function runApplyMemoryRefreshPreview() {
    if (!id || !memoryRefreshPreview || memoryRefreshPreview.tier !== "warning") return;
    setErr(null);
    setNotice(null);
    setBusy(true);
    try {
      await applyRefreshMemoryCandidate(id, {
        current_version: memoryRefreshPreview.currentVersion,
        candidate_json: memoryRefreshPreview.candidateJson,
        confirmation_token: memoryRefreshPreview.confirmationToken || "",
      });
      setMemoryRefreshPreview(null);
      setNotice("已切换到你刚确认的候选记忆版本。");
      await reload();
      await reloadGenerationLogs(logViewMode === "batch" ? logBatchId || undefined : undefined);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "应用候选记忆失败");
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

  async function runGetMemoryHistory() {
    if (!id) return;
    setErr(null);
    try {
      const history = await getMemoryHistory(id);
      setMemoryHistory(history);
      setHistoryDialogOpen(true);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "获取记忆版本历史失败");
    }
  }

  async function runClearMemory() {
    if (!id) return;
    if (
      !window.confirm(
        "确定要一键清空全部记忆吗？此操作不可逆，将清空当前全部剧情线、硬约束和实体分表数据，并创建一个空版本（v0）。"
      )
    ) {
      return;
    }
    setErr(null);
    setNotice(null);
    setBusy(true);
    try {
      await clearMemory(id);
      setNotice("记忆已清空。你现在可以重新审定章节来重新增量生成记忆。");
      await reload();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "清空记忆失败");
    } finally {
      setBusy(false);
    }
  }

  async function runRollbackMemory(version: number) {
    if (!id) return;
    if (
      !window.confirm(
        `确定要回退到版本 v${version} 吗？这会产生一个新版本，并覆盖当前全部结构化记忆分表。`
      )
    ) {
      return;
    }
    setErr(null);
    setNotice(null);
    setBusy(true);
    setHistoryDialogOpen(false);
    try {
      const resp = await rollbackMemory(id, version);
      setNotice(`已回退到版本 v${version}（新版本 v${resp.new_version}）。`);
      await reload();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "回退记忆失败");
    } finally {
      setBusy(false);
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

  useEffect(() => {
    if (
      latestMemoryVersion != null &&
      memory?.version != null &&
      latestMemoryVersion > memory.version
    ) {
      void reload();
    }
  }, [latestMemoryVersion, memory?.version]);

  // 后台轻量轮询记忆版本，确保不打开日志弹窗也能更新记忆状态
  useEffect(() => {
    if (!id) return;
    const t = window.setInterval(async () => {
      try {
        const resp = await listGenerationLogs(id, { limit: 1 });
        if (resp.latest_memory_version != null) {
          setLatestMemoryVersion(resp.latest_memory_version);
        }
        
        // 如果当前大纲为空且未确认，尝试刷新小说数据以获取大纲
        if (!frameworkConfirmed && !fwMd) {
          await reload();
        }
      } catch (e) {
        // ignore
      }
    }, 5000);
    return () => window.clearInterval(t);
  }, [id, frameworkConfirmed, fwMd, reload]);

  async function runAutoGenerate(targetCount: number) {
    if (!id) return;
    const ready = await ensureLlmReady();
    if (!ready) return;
    setErr(null);
    setNotice(null);
    setBusy(true);
    setGenerateTrace(
      `正在发起 AI 一键续写请求...（目标：${targetCount}章）`
    );
    try {
      const resp = await autoGenerateChapters(id, targetCount);
      if (resp.status !== "queued" || !resp.batch_id) {
        setGenerateTrace("生成请求未成功启动");
        await reloadGenerationLogs();
        await reload();
        return;
      }
      setGenerateTrace(
        `已入队，后台将先消费已有章计划，再按批次补齐章计划并串行生成正文...`
      );
      setRefreshBatchId(resp.batch_id);
      await reload(); // 清除失败横幅
      if (logViewMode === "batch") {
        setLogBatchId(resp.batch_id);
        await reloadGenerationLogs(resp.batch_id);
      } else {
        await reloadGenerationLogs();
      }
      setNotice(`已开启 AI 一键续写（${targetCount}章），请在生成日志中查看进度。`);
      await reload(); // 获取最新小说状态，消除失败横幅
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "全自动生成失败");
      setGenerateTrace(
        `生成请求失败：${e instanceof Error ? e.message : "未知错误"}`
      );
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

  async function runSaveSelectedChapter() {
    if (!selectedChapter) return;
    await run(() =>
      patchChapter(selectedChapter.id, {
        title: editTitle,
        content: editContent,
      })
    );
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
      if (resp.status !== "queued" || !("batch_id" in resp) || !resp.batch_id) {
        setErr("卷章计划未能入队");
        setVolumeBusy(false);
        return;
      }
      const bid = resp.batch_id;
      setRefreshBatchId(bid);
      await reload(); // 清除失败横幅
      if (logViewMode === "batch") {
        setLogBatchId(bid);
      }
      await reloadGenerationLogs(logViewMode === "batch" ? bid : undefined);

      // 后台等待逻辑：允许弹窗立即关闭，但主界面保持 busy 状态
      (async () => {
        try {
          const outcome = await waitForVolumePlanBatch(id, bid);
          await reloadVolumes();
          const plan = await listVolumeChapterPlan(id, selectedVolumeId);
          setVolumePlan(plan);
          setVolumePlanLastRun({
            batch: undefined,
            done: outcome === "done",
            next_from_chapter: null,
            existing: plan.length,
          });
          if (outcome === "failed") {
            setErr("卷章计划生成失败，请查看生成日志");
            setNotice("卷章计划生成失败，请查看生成日志。");
          } else {
            setNotice("本批卷章计划已生成，可在章计划列表中查看。");
          }
        } catch (e: unknown) {
          console.error("Background volume plan wait failed:", e);
        } finally {
          setVolumeBusy(false);
        }
      })();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "生成本卷章计划失败");
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
        source: "manual",
      });
      if (resp.status === "queued" && resp.batch_id) {
        const bid = resp.batch_id;
        setRefreshBatchId(bid);
        await reload(); // 清除失败横幅

        // 后台等待逻辑：允许弹窗立即关闭，但主界面保持 busy 状态
        (async () => {
          try {
            const outcome = await waitForChapterGenerationBatch(id, bid);
            setNotice(
              outcome === "done"
                ? `第${chapterNo}章已生成（待审定）。`
                : `第${chapterNo}章生成失败，请查看生成日志。`
            );
            if (outcome === "failed") {
              setErr("按章计划生成失败");
            }
          } catch (e: unknown) {
            console.error("Background chapter generation wait failed:", e);
          } finally {
            setBusy(false);
            await reload();
          }
        })();
      } else {
        await reload();
        setBusy(false);
      }
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "按章计划生成失败");
      setBusy(false);
    }
  }

  function confirmApproveChapter(chapterId: string) {
    const fcRaw = memoryNorm?.outline?.forbidden_constraints;
    const fcLines = Array.isArray(fcRaw)
      ? fcRaw
          .map((x) => {
            if (typeof x === "object" && x !== null) {
              const obj = x as any;
              const iid = obj.id;
              const body = obj.body || JSON.stringify(obj);
              return iid ? `[${iid}] ${body}` : body;
            }
            return String(x).trim();
          })
          .filter(Boolean)
      : [];
    const details: string[] = [
      "审定通过后将把本章标记为已审定，并在后台排队执行增量记忆合并（可在生成日志查看进度）。",
    ];
    if (fcLines.length) {
      details.push("以下为当前规范大纲中的硬约束 forbidden_constraints（写作与设定不可违反）：");
      fcLines.slice(0, 15).forEach((x) => {
        details.push(`· ${x.length > 220 ? `${x.slice(0, 220)}…` : x}`);
      });
      if (fcLines.length > 15) {
        details.push(`… 另有 ${fcLines.length - 15} 条，可在本页「结构化记忆」大纲区查看全文。`);
      }
    } else {
      details.push(
        "当前未从规范大纲加载到硬约束列表；若你仍有多条全局禁止设定，请先在「结构化记忆」中核对 outline。"
      );
    }
    void openLlmConfirm(
      {
        title: "确认审定通过？",
        description:
          "请再次确认本章正文与框架、记忆一致。确认后将触发后台记忆处理。",
        confirmLabel: "确认审定通过",
        details,
      },
      async () => {
        await runApproveChapter(chapterId);
      }
    );
  }

  async function runApproveChapter(chapterId: string) {
    setErr(null);
    setNotice(null);
    setBusy(true);
    try {
      const resp = await approveChapter(chapterId);
      if (resp.already_approved) {
        setNotice("本章节已是审定状态，无需重复审定。");
        await reload();
        return;
      }
      const incrementalNotice =
        resp.incremental_memory_status === "applied"
          ? `本章增量记忆已先写入 v${resp.incremental_memory_version ?? "?"}`
          : resp.incremental_memory_status === "queued"
            ? `本章增量记忆已在后台排队（task: ${resp.incremental_memory_task_id ?? "?"}` +
              (resp.incremental_memory_batch_id ? `，batch: ${resp.incremental_memory_batch_id}` : "") +
              "），请稍后在生成日志查看结果"
          : resp.incremental_memory_status === "enqueue_failed"
            ? "本章增量记忆入队失败，请稍后重试或在记忆页手动刷新"
          : resp.incremental_memory_status === "failed"
            ? "本章增量记忆写入失败，已保留旧记忆"
            : "本章未执行增量记忆写入";
      if (resp.incremental_memory_status === "queued" && resp.incremental_memory_batch_id) {
        setRefreshBatchId(resp.incremental_memory_batch_id);
        if (logViewMode === "batch") {
          setLogBatchId(resp.incremental_memory_batch_id);
          await reloadGenerationLogs(resp.incremental_memory_batch_id);
        } else {
          await reloadGenerationLogs();
        }
      }
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

  async function runRetryChapterMemory(chapterId: string) {
    setErr(null);
    setNotice(null);
    setBusy(true);
    try {
      const resp = await retryChapterMemory(chapterId);
      setRefreshBatchId(resp.batch_id);
      await reload(); // 清除失败横幅
      if (logViewMode === "batch") {
        setLogBatchId(resp.batch_id);
      }
      setNotice("章节增量记忆写入已手动入队执行，请在生成日志查看进度。");
      await reloadGenerationLogs(resp.batch_id);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "重试记忆写入失败");
    } finally {
      setBusy(false);
    }
  }

  async function runClearGenerationLogs() {
    if (!id) return;
    if (!window.confirm("确认清空所有生成日志？清空后不可恢复。")) return;
    setErr(null);
    setNotice(null);
    setLogBusy(true);
    try {
      await clearGenerationLogs(id);
      setGenLogs([]);
      setNotice("生成日志已清空");
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "清空日志失败");
    } finally {
      setLogBusy(false);
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
    const ready = await ensureLlmReady();
    if (!ready) return;
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

  function confirmGenerateVolumes() {
    void openLlmConfirm(
      {
        title: "确认生成卷列表？",
        description: "这会调用大模型，根据已确认框架拆出整本书的卷结构。",
        confirmLabel: "确认生成卷列表",
        details: [
          "建议在框架稳定后再执行，避免卷级节奏被反复推倒重来。",
          "生成后你仍可继续补充章计划，不会直接写正文。",
        ],
      },
      async () => {
        await runGenerateVolumes();
      }
    );
  }

  function confirmGenerateVolumePlan(force = false) {
    void openLlmConfirm(
      {
        title: force ? "确认强制重生成本卷计划？" : "确认生成本卷下一批章计划？",
        description: force
          ? "这会调用大模型，从当前卷开头重新推演下一批章计划。"
          : "这会调用大模型，为当前卷继续补出下一批章计划。",
        confirmLabel: force ? "确认重生成计划" : "确认生成章计划",
        details: [
          "提交后任务在后台执行，关闭或离开本页不会中断。",
          `本次会按 ${volumePlanBatchSize} 章为一批生成计划。`,
          force
            ? "适合在卷节奏明显跑偏时重算；已有思路请先确认是否需要保留。"
            : "更适合逐批推进，先看一批再决定下一批是否继续。",
        ],
      },
      async () => {
        await runGenerateVolumePlan(force);
      }
    );
  }

  function confirmRegenerateChapterPlan(chapterNo: number) {
    const instruction = window.prompt("请输入重生成指令（可选，如：'让冲突更激烈些'）：", "");
    if (instruction === null) return;
    void openLlmConfirm(
      {
        title: `确认重生成第${chapterNo}章计划？`,
        description: "这会调用大模型重做当前章的节奏和剧情规划。",
        confirmLabel: "确认重生成",
        details: [
          instruction.trim()
            ? `本次附带额外指令：${instruction.trim()}`
            : "本次不附加额外指令，将直接按当前上下文重做。",
          "适合局部微调单章走向，不会直接生成正文。",
        ],
      },
      async () => {
        await runRegenerateChapterPlan(chapterNo, instruction);
      }
    );
  }

  function confirmGenerateChapterFromPlan(chapterNo: number) {
    void openLlmConfirm(
      {
        title: `确认生成第${chapterNo}章正文？`,
        description:
          "将基于该章在卷章计划中的条目，在后台生成正文（单章串行，与其它续写任务一致）；保存后为已审定，并已在流程中更新工作记忆。",
        confirmLabel: "确认生成正文",
        details: [
          "须已存在该章的章计划；若计划缺失会提示你先补计划。",
          "若你希望先出稿再人工把关，可依赖修订/一致性流程；批量自动续写与此规则一致。",
          useColdRecall
            ? `当前已开启冷层召回，最多附带 ${coldRecallItems} 条历史记忆。`
            : "当前未开启冷层召回，会以热层记忆为主生成正文。",
        ],
      },
      async () => {
        await runGenerateChapterFromPlan(chapterNo);
      }
    );
  }

  function confirmGenerateChapters() {
    void openLlmConfirm(
      {
        title: `确认 AI 一键续写 ${generateCount} 章？`,
        description:
          "将从已审定章节之后开始推进，后台会先消费已有章计划；如章计划不足，会自动补齐章计划并串行生成正文。生成完成后章节将保存为已审定，并在每章后更新工作记忆。",
        confirmLabel: "确认开始续写",
        details: [
          "会优先使用已有章计划；不足部分将自动补齐章计划。",
          "提交后任务在后台执行，关闭或离开本页不会中断生成。",
          "批量生成更省操作，但建议在关键转折前控制批次数，便于及时校正走向。",
          useColdRecall
            ? `当前已开启冷层召回，最多附带 ${coldRecallItems} 条历史记忆。`
            : "当前仅使用热层记忆；如果章节跨度较大，可考虑开启冷层召回。",
        ],
      },
      async () => {
        await runAutoGenerate(generateCount);
      }
    );
  }

  function confirmSendChapterChat() {
    if (!chapterChatInput.trim() || chapterChatBusy) return;
    void sendChapterChat();
  }

  function confirmSendChapterQuickPrompt(prompt: string) {
    void sendChapterQuickPrompt(prompt);
  }

  function confirmConsistencyFix(chapterId: string) {
    void openLlmConfirm(
      {
        title: "确认生成一致性修订稿？",
        description: "这会调用大模型检查当前章节与框架、已审定章节和记忆的衔接问题，并产出修订稿。",
        confirmLabel: "确认生成修订稿",
        details: [
          "提交后任务在后台执行，关闭或离开本页不会中断。",
          "当前不会直接覆盖正式稿，而是先生成待确认修订稿供你比对。",
          "适合处理设定冲突、时间线不顺和人物动机偏移。",
        ],
      },
      async () => {
        await run(async () => {
          const r = await consistencyFixChapter(chapterId);
          if (r.status === "queued" && r.batch_id && id) {
            const o = await waitForChapterConsistencyBatch(id, r.batch_id);
            if (o === "failed") {
              throw new Error("一致性修订失败，请查看生成日志");
            }
          }
        });
      }
    );
  }

  function confirmReviseChapter(chapterId: string, prompt: string) {
    const instruction = prompt.trim();
    if (!instruction) return;
    void openLlmConfirm(
      {
        title: "确认按指令生成修订稿？",
        description: "这会调用大模型，按你的修改要求重写当前章节的一版修订稿。",
        confirmLabel: "确认生成修订稿",
        details: [
          "提交后任务在后台执行，关闭或离开本页不会中断。",
          `本次改稿指令：${instruction}`,
          "生成结果会先放入待确认修订稿，不会直接覆盖正式稿。",
        ],
      },
      async () => {
        await run(async () => {
          const r = await reviseChapter(chapterId, instruction);
          if (r.status === "queued" && r.batch_id && id) {
            const o = await waitForChapterReviseBatch(id, r.batch_id);
            if (o === "failed") {
              throw new Error("改稿失败，请查看生成日志");
            }
          }
          setRevisePrompt((d) => ({ ...d, [chapterId]: "" }));
        });
      }
    );
  }

  function confirmRefreshMemory() {
    setRefreshRangeOpen(true);
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

  const approvedChapterCount = chapters.filter((chapter) => chapter.status === "approved").length;
  const draftChapterCount = Math.max(0, chapters.length - approvedChapterCount);
  const latestChapterNo = chapters.length
    ? Math.max(...chapters.map((chapter) => chapter.chapter_no))
    : 0;
  const activeMemoryLines = memoryNorm?.open_plots.length ?? openPlotsLines.length;
  const workspaceStageLabel = frameworkConfirmed
    ? approvedChapterCount > 0
      ? "持续创作中"
      : "框架已就绪"
    : !fwMd && novel?.status === "draft"
      ? "AI 正在构思大纲中…"
      : "待确认框架";

  if (!novel) {
    return (
      <div className="p-8 text-sm text-muted-foreground">
        {err ?? "加载中…"}
      </div>
    );
  }

  return (
    <div className="novel-shell transition-colors duration-300">
      <div className="novel-container space-y-5">
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
                    onChange={(e) => setTitleDraft(e.target.value)}
                    className="h-12 w-full max-w-2xl rounded-2xl border border-border/70 bg-background/70 px-4 text-2xl font-bold tracking-tight text-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.35)] backdrop-blur-xl transition-all duration-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 placeholder:text-foreground/30"
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
                    variant="glass"
                    className="font-bold"
                    disabled={busy || titleBusy || !titleDraft.trim()}
                    onClick={() => void runSaveTitle()}
                  >
                    保存书名
                  </Button>
                  <Button variant="outline" asChild className="font-semibold">
                    <Link to="/novels">返回书架</Link>
                  </Button>
                  <Button variant="outline" asChild className="font-semibold">
                    <Link to={`/novels/${id}/metrics`}>查看指标</Link>
                  </Button>
                  <Button variant="outline" onClick={openNovelSettings} className="font-semibold">
                    小说设置
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    className="font-semibold"
                    onClick={() => {
                      setLogDialogOpen(true);
                      void reloadGenerationLogs(logBatchId || undefined);
                    }}
                  >
                    查看生成日志
                  </Button>
                </div>
              </div>

            </div>

            <div className="grid gap-3 md:grid-cols-4">
              {[
                ["已写章节", `${chapters.length}`, latestChapterNo ? `最新至第 ${latestChapterNo} 章` : "尚未开始"],
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

        <LlmActionConfirmDialog
          open={Boolean(llmConfirm)}
          onOpenChange={handleLlmConfirmOpenChange}
          title={llmConfirm?.title ?? "确认调用大模型"}
          description={llmConfirm?.description ?? ""}
          confirmLabel={llmConfirm?.confirmLabel}
          details={llmConfirm?.details ?? []}
          busy={llmConfirmBusy}
          onConfirm={runConfirmedLlmAction}
        />

        <FrameworkWizardDialog
          novelId={id}
          open={frameworkWizardOpen}
          onOpenChange={setFrameworkWizardOpen}
          frameworkConfirmed={frameworkConfirmed}
          frameworkMarkdown={fwMd}
          frameworkJson={fwJson}
          status={String(novel?.status || "")}
          onReload={reload}
          onConfirmFramework={async () => {
            await confirmFramework(id, fwMd, fwJson);
            setNotice("框架已确认，可继续生成卷计划与正文。");
            await reload();
          }}
        />

        {novel?.status === "failed" && (
          <div className="glass-panel-subtle relative flex flex-col gap-4 border-destructive/30 bg-destructive/5 p-6 text-sm text-destructive">
            <button
              type="button"
              onClick={() => {
                // 本地临时隐藏，或者通过 patchNovel 重置状态
                if (novel?.id) {
                  void patchNovel(novel.id as string, { status: "active" }).then(() => reload());
                }
              }}
              className="absolute right-4 top-4 rounded-full p-1 text-destructive/40 hover:bg-destructive/10 hover:text-destructive transition-colors"
              title="忽略此错误"
            >
              <X className="size-5" />
            </button>
            <div className="flex items-center gap-3">
              <div className="flex size-10 shrink-0 items-center justify-center rounded-2xl bg-destructive/10 text-destructive">
                <div className="h-2 w-2 rounded-full bg-destructive animate-ping" />
              </div>
              <div className="space-y-1">
                <p className="text-base font-bold">
                  {novel.framework_confirmed ? "AI 续写或记忆同步执行失败" : "AI 全自动建书执行失败"}
                </p>
                <p className="text-foreground/70 dark:text-muted-foreground font-medium leading-relaxed">
                  {novel.framework_confirmed 
                    ? "小说大纲已构思完成，但在生成后续正文或同步背景设定记忆时遇到了问题。这通常是由于模型解析冲突或响应超时引起的。" 
                    : "在构思小说设定、大纲或初始章节时遇到了问题。这通常是由于模型接口响应超时或解析失败引起的。"}
                </p>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-3 pl-13">
              <Button
                variant="destructive"
                className="font-bold shadow-lg shadow-destructive/20"
                onClick={() => {
                  setLogDialogOpen(true);
                  void reloadGenerationLogs();
                }}
              >
                查看错误详情
              </Button>
              <Button
                variant="outline"
                className="font-bold border-destructive/30 text-destructive hover:bg-destructive/5"
                asChild
              >
                <Link to="/novels">回到书架</Link>
              </Button>
              <p className="text-[11px] text-foreground/50 dark:text-muted-foreground italic font-medium ml-2">
                建议查看错误日志，如有必要可删除当前失败的作品重新尝试。
              </p>
            </div>
          </div>
        )}

        <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as WorkspaceTab)} className="w-full">
          <TabsList className="w-full">
            <TabsTrigger value="framework">设定与框架</TabsTrigger>
            <TabsTrigger value="volumes">卷与章计划</TabsTrigger>
            <TabsTrigger value="chapters">章节</TabsTrigger>
            <TabsTrigger value="memory">记忆</TabsTrigger>
          </TabsList>

          <TabsContent value="framework" className="glass-panel space-y-4 p-5 md:p-6">
            <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
              <div className="space-y-1">
                <p className="section-heading text-foreground font-bold">小说概览与创作基线</p>
                <p className="text-sm text-foreground/70 dark:text-muted-foreground font-medium">
                  先沉淀世界观、主线和写作约束，再进入卷规划与续写。框架确认后，后续章节和记忆都会以这里为准。
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="font-bold"
                  disabled={busy}
                  onClick={() => setFrameworkWizardOpen(true)}
                >
                  修改向导
                </Button>
              </div>
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              <div className="glass-panel-subtle p-4">
                <p className="text-xs text-foreground/60 dark:text-muted-foreground font-bold">框架状态</p>
                <p className="mt-2 text-base font-bold text-foreground">
                  {frameworkConfirmed ? "已确认" : "待确认"}
                </p>
              </div>
              <div className="glass-panel-subtle p-4">
                <p className="text-xs text-foreground/60 dark:text-muted-foreground font-bold">当前章节</p>
                <p className="mt-2 text-base font-bold text-foreground">
                  {latestChapterNo ? `第 ${latestChapterNo} 章` : "未开始"}
                </p>
              </div>
              <div className="glass-panel-subtle p-4">
                <p className="text-xs text-foreground/60 dark:text-muted-foreground font-bold">建议下一步</p>
                <p className="mt-2 text-sm font-bold text-foreground">
                  {frameworkConfirmed
                    ? "去卷与计划区推进章节"
                    : novel?.status === "failed"
                      ? "AI 构思似乎失败了，请尝试重试"
                      : !fwMd && novel?.status === "draft"
                        ? "AI 正在飞速构思，请稍候片刻"
                        : "进入“修改向导”确认大纲"}
                </p>
              </div>
            </div>
            <div className="relative">
              <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">设定大纲文本（可编辑后再确认）</Label>
              {!fwMd && (novel?.status === "draft" || novel?.status === "failed") ? (
                <div className="mt-2 flex min-h-[260px] w-full flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-primary/30 bg-primary/5 p-4 text-sm text-primary/70 animate-pulse text-center">
                  {novel?.status === "failed" ? (
                    <>
                      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-destructive/10">
                        <div className="h-4 w-4 rounded-full bg-destructive" />
                      </div>
                      <p className="font-bold text-base text-destructive">AI 构思似乎失败了</p>
                      <p className="text-xs opacity-60 max-w-xs mb-2">可能是网络波动或 AI 解析错误。建议点击下方“修改向导”进行手动重试。</p>
                      <Button 
                        size="sm" 
                        variant="outline" 
                        className="font-bold border-destructive/30 text-destructive hover:bg-destructive/5"
                        onClick={() => setFrameworkWizardOpen(true)}
                      >
                        进入修改向导重试
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
                  onChange={(e) => setFwMd(e.target.value)}
                  className="mt-2 min-h-[260px] w-full rounded-2xl border border-border/70 bg-background/70 p-4 font-mono text-sm text-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.35)]"
                  placeholder="暂无大纲。进入“修改向导”或等待 AI 生成。"
                />
              )}
            </div>
            <div>
              <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">设定结构化配置</Label>
              <textarea
                value={fwJson}
                onChange={(e) => setFwJson(e.target.value)}
                className="mt-2 min-h-[140px] w-full rounded-2xl border border-border/70 bg-background/70 p-4 font-mono text-xs text-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.35)]"
              />
            </div>
          </TabsContent>

          <TabsContent value="volumes" className="glass-panel space-y-4 p-5 md:p-6">
            <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
              <div className="space-y-1">
                <p className="section-heading text-foreground font-bold">卷与计划区</p>
                <p className="text-sm text-foreground/70 dark:text-muted-foreground font-medium">
                  推荐流程：先生成卷列表，再给当前卷分批生成章计划，最后从计划直接进入正文生成。
                </p>
              </div>
              <div className="glass-chip font-bold text-foreground/80">{selectedVolumeId ? "已选择卷，适合继续铺排" : "请先选择或生成一卷"}</div>
            </div>
            <div className="glass-panel-subtle flex flex-wrap gap-2 p-3">
              <Button
                type="button"
                size="sm"
                className="font-bold"
                disabled={busy || volumeBusy}
                onClick={() => confirmGenerateVolumes()}
              >
                生成卷列表（每卷约50章）
              </Button>
              <div className="flex items-center gap-2 rounded-xl border border-border/70 bg-background/60 px-3 py-1.5 text-xs">
                <span className="text-foreground/60 dark:text-muted-foreground font-bold">每次生成</span>
                <select
                  value={volumePlanBatchSize}
                  onChange={(e) => setVolumePlanBatchSize(Number(e.target.value))}
                  className="h-8 rounded-xl border border-border/70 bg-background px-2.5 text-xs text-foreground font-bold"
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
                onClick={() => confirmGenerateVolumePlan(false)}
              >
                生成本卷章计划（下一批）
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="font-semibold"
                disabled={busy || volumeBusy || !selectedVolumeId}
                onClick={() => confirmGenerateVolumePlan(true)}
              >
                强制重生成本卷计划（从头下一批）
              </Button>
              <Button
                type="button"
                size="sm"
                variant="destructive"
                className="font-bold"
                disabled={busy || volumeBusy || !selectedVolumeId}
                onClick={() => void runClearVolumePlans()}
              >
                一键清除本卷计划
              </Button>
            </div>
            <div className="grid gap-4 lg:grid-cols-12">
              <aside className="glass-panel-subtle soft-scroll order-1 lg:col-span-4 p-4">
                <p className="mb-2 text-xs font-bold text-foreground/60 dark:text-muted-foreground">卷列表</p>
                <div className="max-h-[38vh] space-y-2 overflow-auto pr-1 sm:max-h-[48vh] lg:max-h-[70vh]">
                  {volumes.map((v) => (
                    <button
                      key={v.id}
                      type="button"
                      onClick={() => setSelectedVolumeId(v.id)}
                      className={`w-full rounded-2xl border px-3 py-3 text-left text-xs transition-all duration-300 ${
                        selectedVolumeId === v.id
                          ? "border-primary/35 bg-primary/10 shadow-[0_14px_30px_hsl(var(--primary)/0.16)]"
                          : "border-border bg-background/40 hover:bg-muted/30"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2 font-bold text-foreground">
                        <span>
                          第{v.volume_no}卷 {v.title}
                        </span>
                        <span className="text-[11px] text-foreground/60 dark:text-muted-foreground">
                          计划{v.chapter_plan_count}
                        </span>
                      </div>
                      <div className="mt-1 text-foreground/60 dark:text-muted-foreground font-medium">
                        第{v.from_chapter}—{v.to_chapter}章 · {v.status}
                      </div>
                      {v.summary ? (
                        <div className="mt-1 line-clamp-2 text-foreground/70 dark:text-muted-foreground font-medium">
                          {v.summary}
                        </div>
                      ) : null}
                    </button>
                  ))}
                  {volumes.length === 0 ? (
                    <p className="text-xs text-foreground/50 dark:text-muted-foreground italic font-medium">暂无卷。点击上方按钮生成。</p>
                  ) : null}
                </div>
              </aside>
              <section className="glass-panel-subtle order-2 lg:col-span-8 p-5">
                {!selectedVolumeId ? (
                  <p className="text-sm text-foreground/50 dark:text-muted-foreground italic font-medium">请选择左侧卷。</p>
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
                          onChange={(e) =>
                            setShowVolumePlanWithBody(e.target.checked)
                          }
                        />
                        <span>
                          显示已含正文的章节（默认关闭：已生成正文的章会隐藏，便于往下写）
                          {!showVolumePlanWithBody &&
                          volumePlanView.withBodyCount > 0 ? (
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
                    <div className="soft-scroll max-h-[70vh] overflow-auto rounded-[1.4rem] border border-border/70 bg-muted/20 p-2.5">
                      {volumePlan.length === 0 ? (
                        <p className="p-2 text-xs text-foreground/50 dark:text-muted-foreground italic font-medium">
                          暂无章计划。点击“生成本卷章计划（下一批）”开始生成。
                        </p>
                      ) : volumePlanView.visible.length === 0 ? (
                        <p className="p-2 text-xs text-foreground/50 dark:text-muted-foreground italic font-medium">
                          当前视图下没有待写章节（本卷计划均已含正文）。
                          请勾选上方「显示已含正文的章节」以查看与操作已生成章节。
                        </p>
                      ) : (
                        <div className="space-y-2">
                          {volumePlanView.visible.map((p) => (
                            <div
                              key={p.id}
                              className="list-card p-3.5 text-xs"
                            >
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <div className="space-y-1">
                                  <div className="font-bold text-foreground">
                                    第{p.chapter_no}章 · {p.chapter_title}
                                  </div>
                                  <div className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium">
                                    {p.status === "locked" ? "当前计划已锁定" : "可继续调整或直接生成正文"}
                                  </div>
                                </div>
                                <div className="flex gap-2">
                                  <Button
                                    type="button"
                                    size="sm"
                                    variant="outline"
                                    className="font-semibold"
                                    disabled={busy || p.status === "locked"}
                                    onClick={() => confirmRegenerateChapterPlan(p.chapter_no)}
                                  >
                                    重生成计划
                                  </Button>
                                  <Button
                                    type="button"
                                    size="sm"
                                    className="font-bold"
                                    disabled={busy}
                                    onClick={() => confirmGenerateChapterFromPlan(p.chapter_no)}
                                  >
                                    生成正文
                                  </Button>
                                </div>
                              </div>
                              <div className="mt-3 rounded-2xl border border-border/60 bg-background/50 px-3 py-2.5 whitespace-pre-wrap text-foreground/80 dark:text-muted-foreground font-medium">
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

          <TabsContent value="chapters" className="glass-panel space-y-4 p-5 md:p-6">
            <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
              <div className="space-y-1">
                <p className="section-heading text-foreground font-bold">创作区</p>
                <p className="text-sm text-foreground/70 dark:text-muted-foreground font-medium">
                  这里集中处理续写、审定、日志和章节助手，把最常用的动作放在页面最上方，减少反复滚动寻找按钮。
                </p>
              </div>
              <div className="glass-chip font-bold text-foreground/80">
                {frameworkConfirmed ? "框架已确认，可直接进入批量续写" : "请先确认框架，再开始续写"}
              </div>
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              <div className="glass-panel-subtle p-4">
                <p className="text-xs text-foreground/60 dark:text-muted-foreground font-bold">章节总数</p>
                <p className="mt-2 text-xl font-bold text-foreground">{chapters.length}</p>
                <p className="mt-1 text-xs text-foreground/50 dark:text-muted-foreground font-medium">包含草稿与已审定章节</p>
              </div>
              <div className="glass-panel-subtle p-4">
                <p className="text-xs text-foreground/60 dark:text-muted-foreground font-bold">已审定</p>
                <p className="mt-2 text-xl font-bold text-foreground">{approvedChapterCount}</p>
                <p className="mt-1 text-xs text-foreground/50 dark:text-muted-foreground font-medium">可参与记忆和后续衔接</p>
              </div>
              <div className="glass-panel-subtle p-4">
                <p className="text-xs text-foreground/60 dark:text-muted-foreground font-bold">当前建议</p>
                <p className="mt-2 text-sm font-bold text-foreground">
                  {draftChapterCount ? "优先审定草稿，避免记忆滞后" : "可继续续写或做一致性修订"}
                </p>
              </div>
            </div>
            <div className="glass-panel-subtle space-y-3 p-4">
              <div className="flex flex-wrap items-center gap-2">
                <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">一次生成</Label>
                <select
                  value={generateCount}
                  onChange={(e) => setGenerateCount(Number(e.target.value))}
                  className="h-8 rounded-xl border border-border/70 bg-background px-2.5 text-sm text-foreground font-bold"
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
                  className="font-bold"
                  disabled={busy || !frameworkConfirmed}
                  onClick={() => confirmGenerateChapters()}
                >
                  自动续写 {generateCount} 章
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  className="font-bold"
                  onClick={() => setChapterChatOpen(true)}
                >
                  章节助手对话
                </Button>
              </div>
              <div className="flex flex-wrap items-center gap-3 text-xs text-foreground/70 dark:text-muted-foreground font-bold">
                {generateDisabledReason ? (
                  <span className="font-bold text-amber-600">{generateDisabledReason}</span>
                ) : null}
                <label className="inline-flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={useColdRecall}
                    onChange={(e) => setUseColdRecall(e.target.checked)}
                  />
                  按需召回冷层
                </label>
                {useColdRecall ? (
                  <div className="inline-flex items-center gap-2">
                    <span>召回条数</span>
                    <select
                      value={coldRecallItems}
                      onChange={(e) => setColdRecallItems(Number(e.target.value))}
                      className="h-8 rounded-xl border border-border/70 bg-background px-2.5 text-xs text-foreground font-bold"
                    >
                      {[3, 5, 8, 10, 12].map((n) => (
                        <option key={n} value={n}>
                          {n}
                        </option>
                      ))}
                    </select>
                  </div>
                ) : null}
              </div>
            </div>
            {generateTrace ? (
              <p className="rounded-2xl border border-border/50 bg-muted/30 p-3 text-[11px] text-foreground/60 dark:text-muted-foreground font-medium italic">{generateTrace}</p>
            ) : null}
            
            <div className="grid gap-4 lg:grid-cols-12">
              <aside className={`glass-panel-subtle lg:col-span-4 p-4 flex flex-col overflow-hidden ${selectedChapter ? "order-2" : "order-1"} max-h-[45vh] sm:max-h-[52vh] lg:order-1 lg:max-h-[85vh]`}>
                <div className="mb-4 shrink-0 space-y-2">
                  <p className="text-xs font-bold text-foreground/60 dark:text-muted-foreground">按卷浏览</p>
                  {volumes.length > 0 ? (
                    <div className="no-scrollbar flex gap-1.5 overflow-x-auto pb-1">
                      {volumes.map((v, i) => (
                        <button
                          key={v.id}
                          type="button"
                          onClick={() => setChapterVolumeId(v.id)}
                          className={`rounded-full px-3 py-1 text-[10px] transition-all border font-bold ${
                            (chapterVolumeId || volumes[0].id) === v.id
                              ? "bg-primary text-primary-foreground border-primary shadow-sm"
                              : "bg-background/40 text-foreground/60 dark:text-muted-foreground border-border/50 hover:bg-muted/30"
                          }`}
                          title={v.title || `第${i + 1}卷`}
                        >
                          第{i + 1}卷
                        </button>
                      ))}
                    </div>
                  ) : (
                    <p className="text-[10px] text-foreground/50 dark:text-muted-foreground italic font-medium">尚无分卷</p>
                  )}
                </div>
                
                <div className="mb-2 flex items-center justify-between shrink-0">
                  <p className="text-xs font-bold text-foreground/60 dark:text-muted-foreground">章节目录</p>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 text-[10px] text-primary hover:text-primary hover:bg-primary/10 font-bold"
                    onClick={() => {
                      setExportContent("");
                      setExportOpen(true);
                    }}
                  >
                    一键导出正文
                  </Button>
                </div>
                <div className="soft-scroll space-y-2 overflow-auto pr-1 flex-1">
                  {filteredChapters.map((ch) => (
                    <button
                      key={ch.id}
                      type="button"
                      onClick={() => setSelectedChapterId(ch.id)}
                      className={`w-full rounded-2xl border px-3 py-3 text-left text-xs transition-all duration-300 ${
                        selectedChapterId === ch.id
                          ? "border-primary/35 bg-primary/10 shadow-[0_14px_30px_hsl(var(--primary)/0.16)]"
                          : "border-border bg-background/40 hover:bg-muted/30"
                      }`}
                    >
                      <div className="flex items-center gap-2 font-bold text-foreground">
                        <span>
                          第{ch.chapter_no}章 {ch.title}
                        </span>
                        {ch.pending_content ? (
                          <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-600 font-bold">
                            <span className="inline-block h-1.5 w-1.5 rounded-full bg-amber-400" />
                            待确认修订
                          </span>
                        ) : null}
                      </div>
                      <div className="mt-1 text-foreground/60 dark:text-muted-foreground font-medium italic">
                        {ch.status} · {ch.source}
                      </div>
                      <div className="mt-2">
                        <span
                          role="button"
                          tabIndex={0}
                          className={`inline-block rounded-full px-2.5 py-1 text-[11px] transition-colors font-bold ${
                            busy
                              ? "cursor-not-allowed text-foreground/40 dark:text-muted-foreground"
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
                  {filteredChapters.length === 0 ? (
                    <p className="text-xs text-foreground/50 dark:text-muted-foreground italic font-medium py-8 text-center">当前卷暂无章节</p>
                  ) : null}
                </div>
              </aside>

              <section className={`glass-panel-subtle lg:col-span-8 p-5 ${selectedChapter ? "order-1" : "order-2"} lg:order-2`}>
                {!selectedChapter ? (
                  <p className="text-sm text-foreground/50 dark:text-muted-foreground italic font-medium">请选择左侧章节。</p>
                ) : (
                  <div className="space-y-4">
                    <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-bold text-foreground">
                          第{selectedChapter.chapter_no}章
                        </span>
                        <span className="status-badge font-bold">
                          {selectedChapter.status}
                        </span>
                        <span className="status-badge font-bold">
                          来源：{selectedChapter.source}
                        </span>
                      </div>
                      <div className="glass-chip font-bold text-foreground/80">
                        正文约 {selectedChapterWordCount} 字
                      </div>
                    </div>
                    <div className="grid gap-3 sm:grid-cols-3">
                      <div className="glass-panel-subtle p-4">
                        <p className="text-xs text-foreground/60 dark:text-muted-foreground font-bold">当前状态</p>
                        <p className="mt-2 text-sm font-bold text-foreground">
                          {selectedChapter.status}
                        </p>
                        <p className="mt-1 text-xs text-foreground/60 dark:text-muted-foreground font-medium italic">
                          {selectedChapter.pending_content ? "存在待确认修订稿" : "正在编辑正式稿"}
                        </p>
                      </div>
                      <div className="glass-panel-subtle p-4">
                        <p className="text-xs text-foreground/60 dark:text-muted-foreground font-bold">来源</p>
                        <p className="mt-2 text-sm font-bold text-foreground">
                          {selectedChapter.source}
                        </p>
                        <p className="mt-1 text-xs text-foreground/60 dark:text-muted-foreground font-medium italic">
                          用于区分自动生成、人工编辑或修订稿来源
                        </p>
                      </div>
                      <div className="glass-panel-subtle p-4">
                        <p className="text-xs text-foreground/60 dark:text-muted-foreground font-bold">建议操作</p>
                        <p className="mt-2 text-sm font-bold text-foreground">
                          {selectedChapter.pending_content ? "先确认或放弃修订稿" : "保存后做审定或一致性修订"}
                        </p>
                      </div>
                    </div>
                    <div className="glass-panel-subtle space-y-4 p-4">
                      <div className="space-y-2">
                        <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">章节标题</Label>
                        <input
                          value={editTitle}
                          onChange={(e) => setEditTitle(e.target.value)}
                          className="field-shell w-full text-foreground font-bold"
                        />
                      </div>
                      <div className="space-y-2">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">正式稿（可直接编辑）</Label>
                          <span className="text-xs text-foreground/60 dark:text-muted-foreground font-medium italic">
                            适合直接精修正文、补对话和调整节奏
                          </span>
                        </div>
                        <textarea
                          value={editContent}
                          onChange={(e) => setEditContent(e.target.value)}
                          className="field-shell-textarea min-h-[300px] text-foreground text-sm font-medium leading-relaxed"
                        />
                        <div className="flex flex-wrap gap-2">
                          <Button
                            type="button"
                            size="sm"
                            className="font-bold"
                            disabled={busy || !editContent.trim()}
                            onClick={() => void runSaveSelectedChapter()}
                          >
                            保存章节修改
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className="text-destructive font-bold hover:border-destructive/40 hover:bg-destructive/10"
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
                      </div>
                    </div>

                    <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
                      <div className="glass-panel-subtle space-y-3 p-4">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div>
                            <p className="text-sm font-bold text-foreground">修订与审定</p>
                            <p className="mt-1 text-xs text-foreground/70 dark:text-muted-foreground font-medium italic">
                              把一致性修订、反馈记录和最终审定收拢在一起，减少来回找按钮。
                            </p>
                          </div>
                          <span className="status-badge font-bold">高频操作区</span>
                        </div>
                        {selectedChapter.pending_content ? (
                          <div className="rounded-[1.4rem] border border-amber-500/40 bg-amber-500/5 p-4">
                            <p className="mb-1 text-xs font-bold text-amber-800 dark:text-amber-200">
                              待确认修订稿
                            </p>
                            <pre className="mb-3 max-h-64 overflow-auto whitespace-pre-wrap rounded-2xl border border-amber-500/20 bg-background/50 p-3 text-xs text-foreground font-medium leading-relaxed">
                              {selectedChapter.pending_content}
                            </pre>
                            <div className="flex flex-wrap gap-2">
                              <Button
                                type="button"
                                size="sm"
                                className="font-bold"
                                disabled={busy}
                                onClick={() => run(() => applyChapterRevision(selectedChapter.id))}
                              >
                                确认覆盖正式稿
                              </Button>
                              <Button
                                type="button"
                                size="sm"
                                variant="outline"
                                className="font-bold"
                                disabled={busy}
                                onClick={() => run(() => discardChapterRevision(selectedChapter.id))}
                              >
                                放弃修订
                              </Button>
                            </div>
                          </div>
                        ) : null}

                        <div className="space-y-2">
                          <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">改进意见（可多条，会并入改稿模型）</Label>
                          <textarea
                            value={fbDraft[selectedChapter.id] ?? ""}
                            onChange={(e) =>
                              setFbDraft((d) => ({ ...d, [selectedChapter.id]: e.target.value }))
                            }
                            className="field-shell-textarea min-h-[104px] text-sm text-foreground font-medium"
                          />
                          <div className="flex flex-wrap gap-2">
                            <Button
                              type="button"
                              size="sm"
                              variant="secondary"
                              className="font-bold text-foreground/80"
                              disabled={busy || !selectedChapter.content?.trim()}
                              onClick={() => confirmConsistencyFix(selectedChapter.id)}
                            >
                              生成一致性修订稿
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              variant="secondary"
                              className="font-bold text-foreground/80"
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
                              className="font-bold"
                              disabled={busy}
                              onClick={() => confirmApproveChapter(selectedChapter.id)}
                            >
                              审定通过
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              className="font-semibold"
                              disabled={busy || !selectedChapter.content?.trim()}
                              onClick={() => void runRetryChapterMemory(selectedChapter.id)}
                              title="即使已审定，也重新提取本章增量记忆并写入记忆账本"
                            >
                              重试记忆写入
                            </Button>
                          </div>
                        </div>
                      </div>

                      <div className="glass-panel-subtle space-y-3 p-4">
                        <div>
                          <p className="text-sm font-bold text-foreground">按指令改稿</p>
                          <p className="mt-1 text-xs text-foreground/70 dark:text-muted-foreground font-medium italic">
                            给模型明确修改方向，适合做局部风格强化、节奏压缩或结尾重写。
                          </p>
                        </div>
                        <textarea
                          value={revisePrompt[selectedChapter.id] ?? ""}
                          onChange={(e) =>
                            setRevisePrompt((d) => ({
                              ...d,
                              [selectedChapter.id]: e.target.value,
                            }))
                          }
                          className="field-shell-textarea min-h-[180px] text-sm text-foreground font-medium"
                          placeholder="例如：加强对话张力、压缩环境描写、按第三条反馈改结尾……"
                        />
                        <Button
                          type="button"
                          size="sm"
                          variant="secondary"
                          className="font-bold text-foreground/80"
                          disabled={busy || !(revisePrompt[selectedChapter.id]?.trim())}
                          onClick={() =>
                            confirmReviseChapter(
                              selectedChapter.id,
                              revisePrompt[selectedChapter.id] ?? ""
                            )
                          }
                        >
                          生成修订稿
                        </Button>
                      </div>
                    </div>
                  </div>
                )}
              </section>
            </div>
          </TabsContent>

          <TabsContent value="memory" className="glass-panel space-y-4 p-5 md:p-6">
            <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
              <div className="space-y-1">
                <p className="section-heading">记忆区</p>
                <p className="text-sm text-muted-foreground">
                  这里聚合结构化记忆、健康检查和人工微调入口。适合在审定章节后刷新，再回看待收束线是否过期或偏移。
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  size="sm"
                  disabled={busy || approvedChapterCount === 0}
                  onClick={() => confirmRefreshMemory()}
                  title={approvedChapterCount === 0 ? "尚无已审定章节，无法刷新记忆" : ""}
                >
                  根据已审定章节刷新记忆
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={busy || memoryNormRebuildBusy}
                  onClick={() => void runGetMemoryHistory()}
                >
                  版本回退
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={
                    busy || memoryNormRebuildBusy || !(memory && memory.version > 0)
                  }
                  onClick={() => void runRebuildMemoryNorm()}
                >
                  {memoryNormRebuildBusy ? "导入中…" : "从快照同步分表"}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                  disabled={busy}
                  onClick={() => void runClearMemory()}
                >
                  一键清空记忆
                </Button>
              </div>
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              <div className="glass-panel-subtle p-4">
                <p className="text-xs text-muted-foreground">记忆版本</p>
                <p className="mt-2 text-xl font-semibold text-foreground">
                  {memory?.version != null && memory.version > 0 ? `v${memory.version}` : "未生成"}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {memory?.created_at ? memory.created_at : "刷新后会写入最新快照"}
                </p>
              </div>
              <div className="glass-panel-subtle p-4">
                <p className="text-xs text-muted-foreground">活跃待收束线</p>
                <p className="mt-2 text-xl font-semibold text-foreground">{activeMemoryLines}</p>
                <p className="mt-1 text-xs text-muted-foreground">跟踪跨章节持续生效的问题</p>
              </div>
              <div className="glass-panel-subtle p-4">
                <p className="text-xs text-muted-foreground">最近入账章节</p>
                <p className="mt-2 text-xl font-semibold text-foreground">
                  {memoryHealth?.latest_chapter_no ? `第 ${memoryHealth.latest_chapter_no} 章` : "-"}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">便于判断记忆是否跟上创作进度</p>
              </div>
            </div>
            <div className="glass-panel-subtle space-y-3 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm font-medium">结构化记忆（分表）</p>
                <span className="glass-chip px-2.5 py-1 text-[11px]">
                  真源为结构化表
                </span>
              </div>
              <p className="text-[11px] text-muted-foreground">
                真源为结构化表；审定与刷新会写入表并派生快照。仅在表空或需用快照救场时使用导入。
              </p>
              {!memoryNorm ? (
                <p className="text-xs text-muted-foreground">
                  暂无结构化数据（尚无记忆或尚未同步）。
                </p>
              ) : (
                <div className="space-y-4 text-xs">
                  <p className="text-[11px] text-muted-foreground">
                    规范表版本 v{memoryNorm.memory_version}
                    <span className="ml-2 text-muted-foreground/80">
                      （列表分页展示，点「详情」查看完整内容）
                    </span>
                  </p>
                  {memorySchemaGuide ? (
                    <div className="space-y-3 rounded-[1.4rem] border border-sky-500/30 bg-sky-500/5 p-4">
                      <p className="font-medium text-foreground">结构化记忆录入规范</p>
                      <div className="grid gap-3 md:grid-cols-2">
                        {[
                          ["全书待收束线", memorySchemaGuide.open_plots],
                          ["关键事实", memorySchemaGuide.key_facts],
                          ["硬约束", memorySchemaGuide.forbidden_constraints],
                          ["命名规则", memorySchemaGuide.entity_naming],
                          ["实体调度", memorySchemaGuide.entity_scheduling],
                        ].map(([label, block]) => {
                          if (!block) return null;
                          const structuredBlock =
                            typeof block === "object" && block !== null ? block : null;
                          return (
                            <div
                              key={String(label)}
                              className="list-card p-3"
                            >
                              <p className="text-[11px] font-medium text-foreground/90">
                                {String(label)}
                              </p>
                              {structuredBlock &&
                              "purpose" in structuredBlock &&
                              typeof structuredBlock.purpose === "string" ? (
                                <p className="mt-1 text-[11px] text-muted-foreground">
                                  {structuredBlock.purpose}
                                </p>
                              ) : null}
                              {structuredBlock &&
                              "rules" in structuredBlock &&
                              Array.isArray(structuredBlock.rules) &&
                              structuredBlock.rules.length ? (
                                <ul className="mt-2 space-y-1 text-[11px] text-muted-foreground">
                                  {structuredBlock.rules.slice(0, 3).map((rule, idx) => (
                                    <li key={`${String(label)}-rule-${idx}`}>- {rule}</li>
                                  ))}
                                </ul>
                              ) : null}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ) : null}
                  {memoryHealth ? (
                    <div className="space-y-3 rounded-[1.4rem] border border-amber-500/30 bg-amber-500/5 p-4">
                      <p className="font-medium text-foreground">记忆健康检查</p>
                      <p className="text-[11px] text-muted-foreground">
                        最近已进入记忆账本的章节：第 {memoryHealth.latest_chapter_no || 0} 章
                      </p>
                      <p className="text-[11px] text-muted-foreground">
                        超期线索 {memoryHealth.overdue_plots.length} 条，已 stale 线索{" "}
                        {memoryHealth.stale_plots.length} 条。
                      </p>
                      {memoryHealth.stale_plots.length > 0 ? (
                        <div className="list-card p-3">
                          <p className="mb-1 text-[11px] font-medium text-foreground/90">
                            建议优先人工确认的线索
                          </p>
                          <ul className="space-y-1 text-[11px] text-muted-foreground">
                            {memoryHealth.stale_plots.slice(0, 5).map((plot, idx) => (
                              <li key={`stale-${idx}`}>- {formatMemoryPlotLine(plot)}</li>
                            ))}
                          </ul>
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                  <div className="glass-panel-subtle space-y-3 p-4">
                    <p className="font-medium text-foreground">主线 / 世界观</p>
                    {memoryNorm.outline.main_plot.trim() ? (
                      <div className="flex items-start justify-between gap-2">
                        <p className="line-clamp-3 flex-1 whitespace-pre-wrap break-words text-muted-foreground">
                          {memoryNorm.outline.main_plot}
                        </p>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="h-7 shrink-0 text-xs"
                          onClick={() =>
                            openNormDetail("主线 main_plot", memoryNorm.outline.main_plot)
                          }
                        >
                          详情
                        </Button>
                      </div>
                    ) : (
                      <p className="text-muted-foreground">（无 main_plot）</p>
                    )}
                    {[
                      ["硬约束 forbidden_constraints", memoryNorm.outline.forbidden_constraints],
                      ["时间线归档摘要", memoryNorm.outline.timeline_archive_summary],
                    ].map(([label, arr]) => {
                      if (!Array.isArray(arr) || !arr.length) return null;
                      const lk = `outline-${String(label)}`;
                      const page = structuredPages[lk] ?? 0;
                      const slice = slicePage(arr, page, STRUCTURED_LIST_PAGE);
                      return (
                        <div key={lk} className="space-y-1 border-t border-border/30 pt-2">
                          <p className="text-[11px] font-medium text-foreground/80">
                            {String(label)}
                          </p>
                          <ul className="space-y-1.5 text-muted-foreground">
                            {slice.map((x, i) => {
                              const globalIdx = page * STRUCTURED_LIST_PAGE + i + 1;
                              let preview = "";
                              if (typeof x === "object" && x !== null) {
                                const obj = x as any;
                                const iid = obj.id;
                                const body = obj.body || JSON.stringify(obj);
                                preview = iid ? `[${iid}] ${body}` : body;
                              } else {
                                preview = String(x);
                              }
                              return (
                                <li
                                  key={`${lk}-row-${globalIdx}`}
                                  className="list-card flex items-start justify-between gap-2 px-3 py-2"
                                >
                                  <span className="line-clamp-2 flex-1 break-words">
                                    {preview}
                                  </span>
                                  <Button
                                    type="button"
                                    size="sm"
                                    variant="ghost"
                                    className="h-7 shrink-0 px-2 text-[11px]"
                                    onClick={() =>
                                      openNormDetail(
                                        `${String(label)} · 第 ${globalIdx} 条`,
                                        x
                                      )
                                    }
                                  >
                                    详情
                                  </Button>
                                </li>
                              );
                            })}
                          </ul>
                          {normPager(lk, arr.length, STRUCTURED_LIST_PAGE)}
                        </div>
                      );
                    })}
                  </div>
                  {memoryNorm.skills.length > 0 ? (
                    <div className="glass-panel-subtle space-y-2 p-4">
                      <p className="font-medium text-foreground">技能</p>
                      <ul className="space-y-2">
                        {slicePage(
                          memoryNorm.skills,
                          structuredPages.skills ?? 0,
                          STRUCTURED_LIST_PAGE
                        ).map((s, i) => (
                          <li
                            key={`sk-${s.name}-${i}`}
                            className="list-card flex items-center justify-between gap-2 px-3 py-2.5"
                          >
                            <div className="min-w-0 flex-1">
                              <span className="font-medium text-foreground">{s.name}</span>
                              <p className="text-[10px] text-muted-foreground">
                                影响力 {s.influence_score} · {s.is_active ? "活跃" : "已退场"}
                                {s.aliases.length ? ` · 别名 ${s.aliases.slice(0, 3).join(" / ")}` : ""}
                              </p>
                            </div>
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              className="h-7 text-xs"
                              onClick={() => openNormDetail(`技能 · ${s.name}`, s)}
                            >
                              详情
                            </Button>
                          </li>
                        ))}
                      </ul>
                      {normPager("skills", memoryNorm.skills.length, STRUCTURED_LIST_PAGE)}
                    </div>
                  ) : null}
                  {memoryNorm.inventory.length > 0 ? (
                    <div className="glass-panel-subtle space-y-2 p-4">
                      <p className="font-medium text-foreground">物品</p>
                      <ul className="space-y-2">
                        {slicePage(
                          memoryNorm.inventory,
                          structuredPages.inventory ?? 0,
                          STRUCTURED_LIST_PAGE
                        ).map((it, i) => (
                          <li
                            key={`inv-${it.label}-${i}`}
                            className="list-card flex items-center justify-between gap-2 px-3 py-2.5"
                          >
                            <div className="min-w-0 flex-1">
                              <span className="font-medium text-foreground">
                                {inventoryDisplayLabel(it)}
                              </span>
                              {inventoryDisplaySummary(it) ? (
                                <p className="mt-0.5 line-clamp-2 text-[11px] text-foreground/70 dark:text-muted-foreground">
                                  {inventoryDisplaySummary(it)}
                                </p>
                              ) : null}
                              <p className="text-[10px] text-muted-foreground">
                                影响力 {it.influence_score} · {it.is_active ? "活跃" : "已退场"}
                                {it.aliases.length ? ` · 别名 ${it.aliases.slice(0, 3).join(" / ")}` : ""}
                              </p>
                            </div>
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              className="h-7 text-xs"
                              onClick={() => openNormDetail(`物品 · ${inventoryDisplayLabel(it)}`, it)}
                            >
                              详情
                            </Button>
                          </li>
                        ))}
                      </ul>
                      {normPager(
                        "inventory",
                        memoryNorm.inventory.length,
                        STRUCTURED_LIST_PAGE
                      )}
                    </div>
                  ) : null}
                  {memoryNorm.pets.length > 0 ? (
                    <div className="glass-panel-subtle space-y-2 p-4">
                      <p className="font-medium text-foreground">宠物 / 从属</p>
                      <ul className="space-y-2">
                        {slicePage(
                          memoryNorm.pets,
                          structuredPages.pets ?? 0,
                          STRUCTURED_LIST_PAGE
                        ).map((p, i) => (
                          <li
                            key={`pet-${p.name}-${i}`}
                            className="list-card flex items-center justify-between gap-2 px-3 py-2.5"
                          >
                            <div className="min-w-0 flex-1">
                              <span className="font-medium text-foreground">{p.name}</span>
                              <p className="text-[10px] text-muted-foreground">
                                影响力 {p.influence_score} · {p.is_active ? "活跃" : "已退场"}
                                {p.aliases.length ? ` · 别名 ${p.aliases.slice(0, 3).join(" / ")}` : ""}
                              </p>
                            </div>
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              className="h-7 text-xs"
                              onClick={() => openNormDetail(`宠物 · ${p.name}`, p)}
                            >
                              详情
                            </Button>
                          </li>
                        ))}
                      </ul>
                      {normPager("pets", memoryNorm.pets.length, STRUCTURED_LIST_PAGE)}
                    </div>
                  ) : null}
                  {memoryNorm.characters.length > 0 ? (
                    <div className="glass-panel-subtle space-y-2 p-4">
                      <p className="font-medium text-foreground">人物</p>
                      <ul className="space-y-2">
                        {slicePage(
                          memoryNorm.characters,
                          structuredPages.characters ?? 0,
                          STRUCTURED_LIST_PAGE
                        ).map((c, i) => (
                          <li
                            key={`ch-${c.name}-${i}`}
                            className="list-card flex flex-wrap items-center justify-between gap-2 px-3 py-2.5"
                          >
                            <div className="min-w-0 flex-1">
                              <div className="font-medium text-foreground">{c.name}</div>
                              {(c.role || c.status) ? (
                                <p className="text-[11px] text-muted-foreground">
                                  {[c.role, c.status].filter(Boolean).join(" · ")}
                                </p>
                              ) : null}
                              <p className="text-[10px] text-muted-foreground">
                                影响力 {c.influence_score} · {c.is_active ? "活跃" : "已退场"}
                                {c.aliases.length ? ` · 别名 ${c.aliases.slice(0, 3).join(" / ")}` : ""}
                              </p>
                            </div>
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              className="h-7 shrink-0 text-xs"
                              onClick={() => openNormDetail(`人物 · ${c.name}`, c)}
                            >
                              详情
                            </Button>
                          </li>
                        ))}
                      </ul>
                      {normPager(
                        "characters",
                        memoryNorm.characters.length,
                        STRUCTURED_LIST_PAGE
                      )}
                    </div>
                  ) : null}
                  {memoryNorm.relations.length > 0 ? (
                    <div className="glass-panel-subtle space-y-2 p-4">
                      <p className="font-medium text-foreground">人物关系</p>
                      <ul className="space-y-2">
                        {slicePage(
                          memoryNorm.relations,
                          structuredPages.relations ?? 0,
                          STRUCTURED_LIST_PAGE
                        ).map((r, i) => (
                          <li
                            key={`rel-${i}-${r.from}-${r.to}`}
                            className="list-card flex items-start justify-between gap-2 px-3 py-2"
                          >
                            <span className="line-clamp-2 flex-1 break-words text-muted-foreground">
                              {r.from} → {r.to}：{r.relation}
                            </span>
                            <Button
                              type="button"
                              size="sm"
                              variant="ghost"
                              className="h-7 shrink-0 text-[11px]"
                              onClick={() =>
                                openNormDetail(
                                  `关系 · ${r.from} → ${r.to}`,
                                  r
                                )
                              }
                            >
                              详情
                            </Button>
                          </li>
                        ))}
                      </ul>
                      {normPager(
                        "relations",
                        memoryNorm.relations.length,
                        STRUCTURED_LIST_PAGE
                      )}
                    </div>
                  ) : null}
                  {memoryNorm.open_plots.length > 0 ? (
                    <div className="glass-panel-subtle space-y-2 p-4">
                      <p className="font-medium text-foreground">全书待收束线</p>
                      <ul className="space-y-2">
                        {slicePage(
                          memoryNorm.open_plots,
                          structuredPages.open_plots ?? 0,
                          STRUCTURED_LIST_PAGE
                        ).map((line, i) => (
                          <li
                            key={`op-${line.body}-${i}`}
                            className="list-card flex items-start justify-between gap-2 px-3 py-2"
                          >
                            <span className="line-clamp-2 flex-1 break-words text-muted-foreground">
                              {formatMemoryPlotLine(line)}
                            </span>
                            <Button
                              type="button"
                              size="sm"
                              variant="ghost"
                              className="h-7 shrink-0 text-[11px]"
                              onClick={() =>
                                openNormDetail("待收束线（原始）", line)
                              }
                            >
                              详情
                            </Button>
                          </li>
                        ))}
                      </ul>
                      {normPager(
                        "open_plots",
                        memoryNorm.open_plots.length,
                        STRUCTURED_LIST_PAGE
                      )}
                    </div>
                  ) : null}
                  {memoryNorm.chapters.length > 0 ? (
                    <div className="glass-panel-subtle space-y-2 p-4">
                      <p className="font-medium text-foreground">分章脉络（事实与因果）</p>
                      <div className="space-y-2">
                        {slicePage(
                          memoryNorm.chapters,
                          structuredPages.chapters ?? 0,
                          CHAPTER_PAGE_SIZE
                        ).map((ch) => (
                          <div
                            key={ch.chapter_no}
                            className="list-card flex flex-wrap items-center justify-between gap-2 p-3.5"
                          >
                            <div className="min-w-0">
                              <p className="font-medium text-foreground">
                                第{ch.chapter_no}章
                                {ch.chapter_title ? `《${ch.chapter_title}》` : ""}
                              </p>
                              <p className="mt-1 text-[10px] text-muted-foreground">
                                关键事实 {ch.key_facts.length} · 因果{" "}
                                {ch.causal_results.length} · 新埋线{" "}
                                {ch.open_plots_added.length} · 已收束{" "}
                                {ch.open_plots_resolved.length}
                              </p>
                            </div>
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              className="h-8 shrink-0 text-xs"
                              onClick={() =>
                                openNormDetail(
                                  `第${ch.chapter_no}章 · 分章脉络`,
                                  ch
                                )
                              }
                            >
                              查看全文
                            </Button>
                          </div>
                        ))}
                      </div>
                      {normPager(
                        "chapters",
                        memoryNorm.chapters.length,
                        CHAPTER_PAGE_SIZE
                      )}
                    </div>
                  ) : null}
                </div>
              )}
            </div>
            {memoryRefreshPreview ? (
              <div className="space-y-3 rounded-[1.4rem] border border-amber-500/30 bg-amber-500/5 p-4">
                <div className="space-y-1">
                  <p className="text-sm font-medium text-amber-400">
                    {memoryRefreshPreview.tier === "blocked"
                      ? "这版候选记忆先帮你拦下来了"
                      : "这版候选记忆建议你先看一眼"}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    当前仍保留生效版本 v{memoryRefreshPreview.currentVersion}。
                    {memoryRefreshPreview.tier === "blocked"
                      ? " 系统判断这版改动风险过高，所以没有直接覆盖。"
                      : " 这些改动更像是合理压缩或清理，是否替换由你决定。"}
                  </p>
                </div>
                {memoryRefreshPreview.errors.length > 0 ? (
                  <div className="list-card border-amber-500/20 p-3">
                    <p className="mb-2 text-xs font-medium text-foreground">需要先处理的问题</p>
                    <div className="space-y-1 text-xs text-amber-300">
                      {memoryRefreshPreview.errors.map((item, idx) => (
                        <p key={`mem-refresh-err-${idx}`}>- {item}</p>
                      ))}
                    </div>
                  </div>
                ) : null}
                {memoryRefreshPreview.warnings.length > 0 ? (
                  <div className="list-card border-amber-500/20 p-3">
                    <p className="mb-2 text-xs font-medium text-foreground">建议你留意的变化</p>
                    <div className="space-y-1 text-xs text-amber-300">
                      {memoryRefreshPreview.warnings.map((item, idx) => (
                        <p key={`mem-refresh-warn-${idx}`}>- {item}</p>
                      ))}
                    </div>
                  </div>
                ) : null}
                {memoryRefreshPreview.autoPassNotes.length > 0 ? (
                  <div className="list-card border-emerald-500/20 p-3">
                    <p className="mb-2 text-xs font-medium text-foreground">系统判断可接受的压缩</p>
                    <div className="space-y-1 text-xs text-emerald-300">
                      {memoryRefreshPreview.autoPassNotes.map((item, idx) => (
                        <p key={`mem-refresh-auto-${idx}`}>- {item}</p>
                      ))}
                    </div>
                  </div>
                ) : null}
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      openNormDetail("候选记忆预览", memoryRefreshPreview.candidateReadableZh)
                    }
                  >
                    先看候选版本
                  </Button>
                  {memoryRefreshPreview.tier === "warning" ? (
                    <>
                      <Button
                        type="button"
                        size="sm"
                        disabled={busy}
                        onClick={() => void runApplyMemoryRefreshPreview()}
                      >
                        我确认，用候选版本覆盖
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="secondary"
                        disabled={busy}
                        onClick={() => setMemoryRefreshPreview(null)}
                      >
                        先保留当前记忆
                      </Button>
                    </>
                  ) : null}
                </div>
              </div>
            ) : null}
            {memory?.summary ? (
              <p className="text-xs text-muted-foreground">备注：{memory.summary}</p>
            ) : null}
            {memoryNorm?.outline?.forbidden_constraints &&
            memoryNorm.outline.forbidden_constraints.length > 0 ? (
              <div className="glass-panel-subtle space-y-2 p-4">
                <p className="text-sm font-bold text-foreground">硬约束 forbidden_constraints</p>
                <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium italic">
                  全局禁止触碰的设定底线；续写与审定时请对照。
                </p>
                <ul className="max-h-[min(40vh,320px)] space-y-1.5 overflow-y-auto soft-scroll rounded-xl border border-border/60 bg-muted/20 p-3 text-xs text-foreground/70 dark:text-muted-foreground font-medium leading-relaxed">
                  {slicePage(
                    memoryNorm.outline.forbidden_constraints,
                    structuredPages.forbidden_fc ?? 0,
                    STRUCTURED_LIST_PAGE
                  ).map((x, i) => (
                    <li key={`fc-${i}-${String(x).slice(0, 24)}`} className="leading-relaxed">
                      · {String(x)}
                    </li>
                  ))}
                </ul>
                {memoryNorm.outline.forbidden_constraints.length > STRUCTURED_LIST_PAGE ? (
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-[11px] text-foreground/60 dark:text-muted-foreground font-bold">
                      共 {memoryNorm.outline.forbidden_constraints.length} 条
                    </span>
                    <div className="flex items-center gap-2">
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        className="h-7 text-xs font-bold"
                        disabled={(structuredPages.forbidden_fc ?? 0) <= 0}
                        onClick={() =>
                          setStructuredPages((s) => ({
                            ...s,
                            forbidden_fc: Math.max(0, (s.forbidden_fc ?? 0) - 1),
                          }))
                        }
                      >
                        上一页
                      </Button>
                      <span className="text-[11px] tabular-nums font-bold">
                        {(structuredPages.forbidden_fc ?? 0) + 1} /{" "}
                        {Math.ceil(
                          memoryNorm.outline.forbidden_constraints.length /
                            STRUCTURED_LIST_PAGE
                        )}
                      </span>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        className="h-7 text-xs font-bold"
                        disabled={
                          (structuredPages.forbidden_fc ?? 0) >=
                          Math.ceil(
                            memoryNorm.outline.forbidden_constraints.length /
                              STRUCTURED_LIST_PAGE
                          ) -
                            1
                        }
                        onClick={() =>
                          setStructuredPages((s) => ({
                            ...s,
                            forbidden_fc: Math.min(
                              Math.ceil(
                                memoryNorm.outline.forbidden_constraints.length /
                                  STRUCTURED_LIST_PAGE
                              ) - 1,
                              (s.forbidden_fc ?? 0) + 1
                            ),
                          }))
                        }
                      >
                        下一页
                      </Button>
                    </div>
                  </div>
                ) : null}
              </div>
            ) : null}
            <div className="glass-panel-subtle space-y-4 p-4">
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
                    "建议写成「谁—要做什么—截止或前提」，方便后文对照回收。",
                    "mf_open_plots"
                  )}
                </div>
                <div className="space-y-2">
                  {renderLineEditor(
                    "本章关键事实（锚点）",
                    keyFactsLines,
                    setKeyFactsLines,
                    "例如：顾寒确认“芯片需在水中激活”",
                    "只写本章已坐实的信息，后文不应自相矛盾。",
                    "mf_key_facts"
                  )}
                  {renderLineEditor(
                    "前因后果（本章）",
                    causalResultsLines,
                    setCausalResultsLines,
                    "例如：因暴露身份，顾寒被治安队列入追捕名单",
                    "用一两句写清「因何而起 → 导致何种局面」。",
                    "mf_causal"
                  )}
                  {renderLineEditor(
                    "本章新埋线",
                    openPlotsAddedLines,
                    setOpenPlotsAddedLines,
                    "例如：苏青被带走，去向未知",
                    "本章新抛出的悬念或待交代事项。",
                    "mf_added"
                  )}
                  {renderLineEditor(
                    "本章已收束",
                    openPlotsResolvedLines,
                    setOpenPlotsResolvedLines,
                    "例如：顾寒已拿到第一枚激活芯片",
                    "本章内明确了结或兑现的剧情点。",
                    "mf_resolved"
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
                <div className="rounded-[1.25rem] border border-amber-500/40 bg-amber-500/5 p-3">
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

      <div className="fixed inset-x-0 bottom-0 z-30 border-t border-border/70 bg-background/92 pb-[calc(env(safe-area-inset-bottom)+0.75rem)] pt-3 shadow-[0_-12px_30px_rgba(15,23,42,0.08)] backdrop-blur-xl md:hidden">
        <div className="novel-container space-y-2 px-4">
          <p className="text-[11px] font-medium text-foreground/60">
            {activeTab === "framework"
              ? frameworkConfirmed
                ? "框架已确认，可继续微调或查看全局设置"
                : "先确认框架，再进入卷计划和正文创作"
              : activeTab === "volumes"
                ? selectedVolumeId
                  ? "已选中当前卷，可继续按批次推进章计划"
                  : "先生成卷列表，再逐卷推进章计划"
                : activeTab === "chapters"
                  ? selectedChapter
                    ? `正在编辑第 ${selectedChapter.chapter_no} 章`
                    : "先选章节，或直接启动自动续写"
                  : approvedChapterCount > 0
                    ? "章节审定后建议及时刷新记忆"
                    : "尚无已审定章节，记忆刷新暂不可用"}
          </p>

          {activeTab === "framework" ? (
            <div className="grid grid-cols-2 gap-2">
              <Button type="button" variant="outline" className="font-semibold" onClick={() => setFrameworkWizardOpen(true)}>
                修改向导
              </Button>
              <Button type="button" className="font-bold" onClick={openNovelSettings}>
                小说设置
              </Button>
            </div>
          ) : null}

          {activeTab === "volumes" ? (
            <div className="grid grid-cols-2 gap-2">
              <Button
                type="button"
                variant="outline"
                className="font-semibold"
                disabled={busy || volumeBusy}
                onClick={() => confirmGenerateVolumes()}
              >
                生成卷列表
              </Button>
              <Button
                type="button"
                className="font-bold"
                disabled={busy || volumeBusy || !selectedVolumeId}
                onClick={() => confirmGenerateVolumePlan(false)}
              >
                下一批计划
              </Button>
            </div>
          ) : null}

          {activeTab === "chapters" ? (
            selectedChapter ? (
              <div className="grid grid-cols-3 gap-2">
                <Button
                  type="button"
                  variant="outline"
                  className="font-semibold"
                  disabled={busy || !editContent.trim()}
                  onClick={() => void runSaveSelectedChapter()}
                >
                  保存
                </Button>
                {selectedChapter.pending_content ? (
                  <Button
                    type="button"
                    className="font-bold"
                    disabled={busy}
                    onClick={() => run(() => applyChapterRevision(selectedChapter.id))}
                  >
                    确认修订
                  </Button>
                ) : (
                  <Button
                    type="button"
                    className="font-bold"
                    disabled={busy || !selectedChapter.content?.trim()}
                    onClick={() => confirmApproveChapter(selectedChapter.id)}
                  >
                    审定通过
                  </Button>
                )}
                <Button
                  type="button"
                  variant="ghost"
                  className="font-semibold"
                  onClick={() => setSelectedChapterId("")}
                >
                  章节目录
                </Button>
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-2">
                <Button
                  type="button"
                  variant="outline"
                  className="font-semibold"
                  disabled={busy || !frameworkConfirmed}
                  onClick={() => confirmGenerateChapters()}
                >
                  自动续写
                </Button>
                <Button
                  type="button"
                  className="font-bold"
                  onClick={() => setChapterChatOpen(true)}
                >
                  章节助手
                </Button>
              </div>
            )
          ) : null}

          {activeTab === "memory" ? (
            <div className="grid grid-cols-2 gap-2">
              <Button
                type="button"
                variant="outline"
                className="font-semibold"
                disabled={busy || approvedChapterCount === 0}
                onClick={() => confirmRefreshMemory()}
              >
                刷新记忆
              </Button>
              <Button
                type="button"
                className="font-bold"
                disabled={busy || memoryNormRebuildBusy}
                onClick={() => void runGetMemoryHistory()}
              >
                版本回退
              </Button>
            </div>
          ) : null}
        </div>
      </div>

      <Dialog open={logDialogOpen} onOpenChange={setLogDialogOpen}>
              <DialogContent className="max-h-[85vh] max-w-4xl overflow-hidden">
                <DialogHeader>
                  <div className="flex items-center justify-between gap-4 mr-8">
                    <div className="min-w-0 flex-1">
                      <DialogTitle className="text-xl font-bold">章节生成日志</DialogTitle>
                      <DialogDescription className="text-foreground/80 dark:text-muted-foreground font-medium">
                        支持按任务批次过滤，避免页面被日志持续撑长。
                      </DialogDescription>
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={runClearGenerationLogs}
                      className="text-destructive font-bold hover:bg-destructive/10 hover:text-destructive shrink-0"
                    >
                      清空日志
                    </Button>
                  </div>
                </DialogHeader>
                <div className="space-y-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <div className="inline-flex overflow-hidden rounded-2xl border border-border/70 bg-background/60 p-1">
                      <button
                        type="button"
                        className={`rounded-xl px-3 py-1.5 text-xs transition-all font-bold ${
                          logViewMode === "all" ? "bg-primary/15 text-foreground shadow-sm" : "bg-transparent text-foreground/60 dark:text-muted-foreground"
                        }`}
                        onClick={() => setLogViewMode("all")}
                      >
                        全部
                      </button>
                      <button
                        type="button"
                        className={`rounded-xl px-3 py-1.5 text-xs transition-all font-bold ${
                          logViewMode === "batch" ? "bg-primary/15 text-foreground shadow-sm" : "bg-transparent text-foreground/60 dark:text-muted-foreground"
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
                      placeholder="可填批次编号手动过滤"
                      className="field-shell h-10 w-full md:w-80 text-foreground font-bold placeholder:text-foreground/30"
                      disabled={logViewMode !== "batch"}
                    />
                    <label className="inline-flex items-center gap-2 text-xs text-foreground/70 dark:text-muted-foreground font-bold cursor-pointer">
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
                      className="font-bold"
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
                  <div className="glass-panel-subtle p-3">
                    <div className="mb-1 flex items-center justify-between text-xs font-bold text-foreground/80">
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
                    <div className="h-2.5 w-full rounded-full bg-muted/80">
                      <div
                        className={`h-2.5 rounded-full transition-all duration-500 ${
                          refreshStatus === "failed" ? "bg-destructive" : "bg-primary"
                        }`}
                        style={{ width: `${Math.max(0, Math.min(100, refreshProgress))}%` }}
                      />
                    </div>
                    <p className="mt-1 text-[11px] text-foreground/60 dark:text-muted-foreground font-medium">
                      任务批次：{refreshBatchId || "-"} · 开始：{formatUtc8(refreshStartedAt)} · 更新时间：
                      {formatUtc8(refreshUpdatedAt)}
                    </p>
                    <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium">
                      已运行时长：{formatDuration(refreshElapsedSeconds)} · 最近成功版本：
                      {latestRefreshVersion == null ? "-" : `v${latestRefreshVersion}`}
                    </p>
                    {refreshLastMessage ? (
                      <p className="text-[11px] text-foreground/70 dark:text-muted-foreground font-bold italic">{refreshLastMessage}</p>
                    ) : null}
                  </div>
                  <div className="soft-scroll max-h-[55vh] overflow-auto rounded-[1.4rem] border border-border/70 bg-muted/20 p-3 font-mono text-xs">
                    {genLogs.length === 0 ? (
                      <p className="text-foreground/50 dark:text-muted-foreground italic">
                        暂无日志。点击“自动续写”或“审定通过”后可在此查看过程细节。
                      </p>
                    ) : (
                      genLogs.map((l) => {
                        const metaView = summarizeLogMeta(l.event, l.meta || {});
                        return (
                          <div
                            key={l.id}
                            className="border-b border-border/50 py-3 last:border-b-0"
                          >
                            <div className="font-medium">
                              <span className="text-foreground/50 dark:text-muted-foreground">
                                [{formatUtc8(l.created_at)}] [{l.level === 'error' ? '错误' : l.level === 'warning' ? '警告' : '信息'}]
                              </span>{" "}
                              <span className="text-foreground/90 dark:text-inherit">
                                {l.chapter_no ? `第${l.chapter_no}章` : "-"} · {l.message}
                              </span>
                            </div>
                            {metaView.summary.length ? (
                              <div className="mt-2 rounded-2xl border border-border/60 bg-background/60 px-3 py-2 text-[11px] text-foreground/90 font-medium">
                                {metaView.summary.map((item, idx) => (
                                  <p key={`${l.id}-summary-${idx}`}>{item}</p>
                                ))}
                              </div>
                            ) : null}
                            {metaView.detail ? (
                              <details className="mt-2 rounded-2xl border border-border/60 bg-background/40 px-3 py-2">
                                <summary className="cursor-pointer text-[11px] text-foreground/60 dark:text-muted-foreground font-bold">
                                  查看技术详情
                                </summary>
                                <pre className="mt-2 whitespace-pre-wrap text-[11px] text-foreground/70 dark:text-muted-foreground">
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

      {/* 小说设置弹窗 */}
      <Dialog open={novelSettingsOpen} onOpenChange={setNovelSettingsOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="text-xl font-bold">小说设置</DialogTitle>
            <DialogDescription className="text-foreground/80 dark:text-muted-foreground font-medium">
              配置当前小说的总章节数和每日自动撰写计划。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="target_chapters" className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">目标总章节数</Label>
              <Input
                id="target_chapters"
                type="number"
                min={1}
                max={20000}
                value={novelSettingsDraft.target_chapters}
                onChange={(e) => setNovelSettingsDraft({ ...novelSettingsDraft, target_chapters: Number(e.target.value) })}
                className="field-shell text-foreground font-bold"
              />
              <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium italic">该小说的预计总章节数。</p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="daily_auto_chapters" className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">每日自动撰写章数</Label>
              <Input
                id="daily_auto_chapters"
                type="number"
                min={0}
                max={50}
                value={novelSettingsDraft.daily_auto_chapters}
                onChange={(e) => setNovelSettingsDraft({ ...novelSettingsDraft, daily_auto_chapters: Number(e.target.value) })}
                className="field-shell text-foreground font-bold"
              />
              <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium italic">设定为 0 表示不开启每日自动撰写。如果不为 0，系统将在指定时间自动在后台为你续写小说。</p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="daily_auto_time" className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">每日自动撰写时间（北京时间）</Label>
              <Input
                id="daily_auto_time"
                type="time"
                value={novelSettingsDraft.daily_auto_time}
                onChange={(e) => setNovelSettingsDraft({ ...novelSettingsDraft, daily_auto_time: e.target.value })}
                className="field-shell text-foreground font-bold"
              />
              <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium italic">由后台系统自动执行。</p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="chapter_target_words" className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">每章期望字数（汉字）</Label>
              <Input
                id="chapter_target_words"
                type="number"
                min={500}
                max={10000}
                step={100}
                value={novelSettingsDraft.chapter_target_words}
                onChange={(e) => setNovelSettingsDraft({ ...novelSettingsDraft, chapter_target_words: Number(e.target.value) })}
                className="field-shell text-foreground font-bold"
              />
              <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium italic">AI 在写正文时将以此为强约束。建议 2000-5000。</p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="novel_style" className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">文风描述 (简要)</Label>
              <Input
                id="novel_style"
                value={novelSettingsDraft.style}
                onChange={(e) => setNovelSettingsDraft({ ...novelSettingsDraft, style: e.target.value })}
                className="field-shell text-foreground font-bold"
                placeholder="例如：硬核推理、轻快幽默..."
              />
              <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium italic">简单描述文风关键词，会注入所有生成环节。</p>
            </div>
            <div className="space-y-2">
              <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">写作风格 (深度定制)</Label>
              <WritingStyleSelect
                value={novelSettingsDraft.writing_style_id}
                onChange={(id) => setNovelSettingsDraft({ ...novelSettingsDraft, writing_style_id: id })}
              />
              <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium italic">
                切换深度定制的文风，系统将按新文风进行后续章节创作。
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" className="font-semibold" onClick={() => setNovelSettingsOpen(false)} disabled={novelSettingsBusy}>
              取消
            </Button>
            <Button className="font-bold" onClick={handleSaveNovelSettings} disabled={novelSettingsBusy}>
              {novelSettingsBusy ? "保存中..." : "保存设置"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={normDetailOpen} onOpenChange={setNormDetailOpen}>
        <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto text-foreground">
          <DialogHeader>
            <DialogTitle className="text-left text-base leading-snug">
              {normDetailTitle}
            </DialogTitle>
            <DialogDescription className="sr-only">
              结构化记忆条目完整内容
            </DialogDescription>
          </DialogHeader>
          <pre className="soft-scroll max-h-[min(60vh,520px)] overflow-auto whitespace-pre-wrap break-words rounded-[1.2rem] border border-border/70 bg-muted/30 p-3 text-[11px] leading-relaxed text-muted-foreground">
            {normDetailBody}
          </pre>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setNormDetailOpen(false)}
            >
              关闭
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={historyDialogOpen} onOpenChange={setHistoryDialogOpen}>
        <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto text-foreground">
          <DialogHeader>
            <DialogTitle className="text-left text-base leading-snug">
              记忆版本历史
            </DialogTitle>
            <DialogDescription>
              选择一个历史版本进行回退。回退操作会产生一个包含该版本内容的新快照，并覆盖当前结构化记忆表。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            {memoryHistory.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground">暂无历史记录</p>
            ) : (
              memoryHistory.map((item) => (
                <div
                  key={item.version}
                  className="flex items-center justify-between gap-4 rounded-[1.25rem] border border-border/50 bg-background/40 p-4 transition-all hover:border-primary/30 hover:bg-background/60"
                >
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-primary">v{item.version}</span>
                      <span className="text-[10px] text-muted-foreground">
                        {item.created_at ? new Date(item.created_at).toLocaleString() : "-"}
                      </span>
                    </div>
                    <p className="line-clamp-2 text-xs text-muted-foreground">
                      {item.summary || "（无摘要）"}
                    </p>
                  </div>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-8 shrink-0"
                    onClick={() => void runRollbackMemory(item.version)}
                  >
                    回退到此版本
                  </Button>
                </div>
              ))
            )}
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setHistoryDialogOpen(false)}
            >
              取消
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={refreshRangeOpen} onOpenChange={setRefreshRangeOpen}>
        <DialogContent className="max-w-md overflow-hidden flex flex-col text-foreground">
          <DialogHeader>
            <DialogTitle>刷新记忆范围选择</DialogTitle>
            <DialogDescription>
              请选择用于汇总记忆的已审定章节范围。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="flex flex-col gap-2">
              <Label className="text-sm font-semibold">选择模式</Label>
              <div className="grid grid-cols-3 gap-2">
                <Button
                  variant={refreshRangeMode === "recent" ? "default" : "outline"}
                  size="sm"
                  onClick={() => setRefreshRangeMode("recent")}
                  className="text-xs"
                >
                  最近 15 章
                </Button>
                <Button
                  variant={refreshRangeMode === "full" ? "default" : "outline"}
                  size="sm"
                  onClick={() => setRefreshRangeMode("full")}
                  className="text-xs"
                >
                  全量刷新
                </Button>
                <Button
                  variant={refreshRangeMode === "custom" ? "default" : "outline"}
                  size="sm"
                  onClick={() => setRefreshRangeMode("custom")}
                  className="text-xs"
                >
                  自定义范围
                </Button>
              </div>
            </div>

            {refreshRangeMode === "custom" && (
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label className="text-xs">起始章号</Label>
                  <Input
                    type="number"
                    value={refreshFromNo}
                    onChange={(e) => setRefreshFromNo(Number(e.target.value))}
                    className="h-9"
                  />
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">结束章号</Label>
                  <Input
                    type="number"
                    value={refreshToNo}
                    onChange={(e) => setRefreshToNo(Number(e.target.value))}
                    className="h-9"
                  />
                </div>
              </div>
            )}

            <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-3 space-y-2">
              <div className="flex items-center gap-2 text-amber-700 dark:text-amber-400">
                <div className="h-1.5 w-1.5 rounded-full bg-amber-500" />
                <p className="text-xs font-bold text-amber-600 dark:text-amber-400">温馨提示</p>
              </div>
              <ul className="list-disc list-inside text-[11px] text-amber-700/80 dark:text-amber-400/80 space-y-1">
                <li>汇总的章节越多，AI 处理速度越慢。</li>
                <li>刷新操作会消耗较多积分（按汇总字数计费）。</li>
                <li>建议仅在产生重大剧情变更或由于逻辑偏移需要“纠偏”时进行全量刷新。</li>
              </ul>
            </div>
          </div>
          <DialogFooter className="mt-4">
            <Button variant="outline" onClick={() => setRefreshRangeOpen(false)}>
              取消
            </Button>
            <Button
              onClick={() => {
                const opts: any = {};
                if (refreshRangeMode === "full") opts.is_full = true;
                else if (refreshRangeMode === "custom") {
                  opts.from_chapter_no = refreshFromNo;
                  opts.to_chapter_no = refreshToNo;
                }
                void executeRefreshMemory(opts);
              }}
              disabled={busy}
            >
              开始刷新
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={exportOpen} onOpenChange={setExportOpen}>
        <DialogContent className="max-h-[90vh] max-w-4xl overflow-hidden flex flex-col text-foreground">
          <DialogHeader>
            <DialogTitle>全文本导出</DialogTitle>
            <DialogDescription>
              选择章节范围，一键拼接所有已审定或草稿正文，方便发布或备份。
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label>起始章号</Label>
              <Input
                type="number"
                value={exportStartNo}
                onChange={(e) => setExportStartNo(Number(e.target.value))}
              />
            </div>
            <div className="space-y-2">
              <Label>截止章号</Label>
              <Input
                type="number"
                value={exportEndNo}
                onChange={(e) => setExportEndNo(Number(e.target.value))}
              />
            </div>
          </div>
          <div className="flex-1 overflow-hidden flex flex-col mt-4 gap-3">
            <div className="flex items-center justify-between">
              <Label>导出内容预览</Label>
              {exportContent && (
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 text-xs"
                  onClick={() => {
                    void navigator.clipboard.writeText(exportContent);
                    alert("已复制到剪贴板");
                  }}
                >
                  复制全文本
                </Button>
              )}
            </div>
            <textarea
              value={exportContent}
              readOnly
              placeholder="点击“开始导出”后在此显示内容..."
              className="field-shell-textarea flex-1 font-sans text-sm leading-relaxed"
            />
          </div>
          <DialogFooter className="mt-4">
            <Button variant="outline" onClick={() => setExportOpen(false)}>
              关闭
            </Button>
            <Button onClick={handleExport} disabled={exportBusy}>
              {exportBusy ? "正在导出..." : "开始导出"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={chapterChatOpen} onOpenChange={setChapterChatOpen}>
        <DialogContent className="max-h-[88vh] max-w-3xl overflow-hidden text-foreground">
          <DialogHeader>
            <DialogTitle>章节助手对话</DialogTitle>
            <DialogDescription>
              自动基于已审定章节、框架与记忆回答问题，可用于续写决策和一致性检查。
            </DialogDescription>
          </DialogHeader>
          <div className="soft-scroll flex max-h-[52vh] flex-col gap-3 overflow-y-auto rounded-[1.4rem] border border-border/70 bg-muted/20 p-3 text-sm">
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
                    ? "ml-8 rounded-[1.25rem] border border-primary/20 bg-primary/10 px-3.5 py-3 shadow-sm"
                    : "mr-4 rounded-[1.25rem] border border-border/60 bg-background/80 px-3.5 py-3 shadow-sm"
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
                  onClick={() => confirmSendChapterQuickPrompt(p.prompt)}
                  className="text-xs"
                  title={p.prompt}
                >
                  {p.label}
                </Button>
              ))}
            </div>
            <div className="soft-scroll max-h-20 overflow-auto rounded-2xl border border-border/60 bg-muted/30 px-3 py-2 text-[11px] text-muted-foreground">
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
            <div className="rounded-[1.25rem] border border-amber-500/40 bg-amber-500/5 p-3 text-xs">
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
            className="field-shell-textarea min-h-[104px]"
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                confirmSendChapterChat();
              }
            }}
            disabled={chapterChatBusy}
          />
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              disabled={chapterChatBusy || !chapterChatInput.trim()}
              onClick={() => confirmSendChapterChat()}
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
    </div>
  );
}
