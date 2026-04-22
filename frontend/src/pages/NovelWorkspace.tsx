import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { BookOpen, Brain, ChevronDown, ChevronRight, GitBranch, Sparkles, X } from "lucide-react";
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
  createMemoryCharacter,
  createMemoryItem,
  createMemoryRelation,
  createMemorySkill,
  applyRefreshMemoryCandidate,
  applyChapterRevision,
  approveChapter,
  chapterContextChatStream,
  consistencyFixChapter,
  clearVolumeChapterPlans,
  clearGenerationLogs,
  confirmFramework,
  confirmBaseFramework,
  deleteChapter,
  deleteMemoryCharacter,
  deleteMemoryItem,
  deleteMemoryRelation,
  deleteMemorySkill,
  discardChapterRevision,
  exportChapters,
  generateFramework,
  formatChapter,
  generateChapters,
  autoGenerateChapters,
  generateArcs,
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
  patchChapterPlan,
  patchMemoryCharacter,
  patchMemoryItem,
  patchMemoryRelation,
  patchMemorySkill,
  patchNovel,
  polishChapter,
  refreshMemory,
  regenerateChapterPlan,
  retryChapterMemory,
  reviseChapter,
  type ChapterPlanReservedItem,
  type ChapterPlanV2Beats,
  waitForChapterConsistencyBatch,
  waitForChapterGenerationBatch,
  waitForChapterPolishBatch,
  waitForChapterReviseBatch,
  waitForArcsGenerateBatch,
  waitForFrameworkGenerateBatch,
  waitForMemoryRefreshBatch,
  waitForVolumePlanBatch,
} from "@/services/novelApi";
import { ensureLlmReady } from "@/services/llmReady";

const STRUCTURED_LIST_PAGE = 8;
/** 剧情承接与微调区：每类行列表分页，避免单屏过长 */
const CONTINUITY_LINE_PAGE = 8;
const CHAPTER_PAGE_SIZE = 3;
type WorkspaceTab = "studio" | "memory";

const MEMORY_ATLAS_POINTS = [
  { left: "10%", top: "18%" },
  { left: "34%", top: "10%" },
  { left: "62%", top: "14%" },
  { left: "78%", top: "32%" },
  { left: "66%", top: "58%" },
  { left: "42%", top: "70%" },
  { left: "16%", top: "62%" },
  { left: "26%", top: "38%" },
] as const;

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

function clamp01(value: number) {
  if (Number.isNaN(value)) return 0;
  return Math.max(0, Math.min(1, value));
}

function shortenText(value: string, max = 88) {
  const trimmed = value.trim();
  if (trimmed.length <= max) return trimmed;
  return `${trimmed.slice(0, max - 1)}…`;
}

type NormalizedPlanBeats = {
  schema_version: number;
  meta: {
    edited_by_user: boolean;
    last_editor_id: string | null;
    last_edited_at: string | null;
  };
  display_summary: {
    plot_summary: string;
    stage_position: string;
    pacing_justification: string;
  };
  execution_card: {
    chapter_goal: string;
    core_conflict: string;
    key_turn: string;
    must_happen: string[];
    required_callbacks: string[];
    scene_cards: ChapterPlanV2Beats["execution_card"] extends infer T
      ? T extends { scene_cards?: infer S }
        ? NonNullable<S>
        : []
      : [];
    allowed_progress: string[];
    must_not: string[];
    reserved_for_later: ChapterPlanReservedItem[];
    end_state_targets: {
      characters: string[];
      relations: string[];
      items: string[];
      plots: string[];
    };
    ending_hook: string;
    style_guardrails: string[];
  };
};

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

function readPromptNumber(
  message: string,
  defaultValue: number,
  min = 0,
  max = 100
): number | null {
  const raw = window.prompt(message, String(defaultValue));
  if (raw == null) return null;
  const parsed = Number(String(raw).trim() || String(defaultValue));
  if (!Number.isFinite(parsed)) return null;
  return Math.max(min, Math.min(max, Math.round(parsed)));
}

function formatVolumePlanBeatsText(beats: unknown): string {
  const b = normalizePlanBeats(beats);
  const lines: string[] = [];
  if (b.meta.edited_by_user) lines.push("已由用户手动编辑执行卡");
  if (b.execution_card.chapter_goal) lines.push(`本章目标：${b.execution_card.chapter_goal}`);
  if (b.execution_card.core_conflict) lines.push(`核心冲突：${b.execution_card.core_conflict}`);
  if (b.execution_card.key_turn) lines.push(`关键转折：${b.execution_card.key_turn}`);
  if (b.display_summary.plot_summary) lines.push(`剧情梗概：${b.display_summary.plot_summary}`);
  if (b.display_summary.stage_position) lines.push(`阶段位置：${b.display_summary.stage_position}`);
  if (b.display_summary.pacing_justification) {
    lines.push(`节奏说明：${b.display_summary.pacing_justification}`);
  }
  const mustHappen = b.execution_card.must_happen;
  if (mustHappen.length) {
    lines.push(`必须发生：\n${mustHappen.map((x) => `  · ${x}`).join("\n")}`);
  }
  const callbacks = b.execution_card.required_callbacks;
  if (callbacks.length) {
    lines.push(`必须承接：\n${callbacks.map((x) => `  · ${x}`).join("\n")}`);
  }
  const pa = b.execution_card.allowed_progress;
  if (pa.length) {
    lines.push(`允许推进：\n${pa.map((x) => `  · ${x}`).join("\n")}`);
  }
  if (b.execution_card.must_not.length) {
    lines.push(`禁止：\n${b.execution_card.must_not.map((x) => `  · ${x}`).join("\n")}`);
  }
  const rsv = b.execution_card.reserved_for_later;
  if (rsv.length) {
    const parts = rsv
      .map((item) => {
        const note = item.reason?.trim() ? `（${item.reason.trim()}）` : "";
        return typeof item.not_before_chapter === "number"
          ? `  · 「${item.item}」须第${item.not_before_chapter}章及之后${note}`
          : `  · 「${item.item}」延后${note}`;
      })
      .filter(Boolean);
    if (parts.length) lines.push(`延后解锁：\n${parts.join("\n")}`);
  }
  if (b.execution_card.style_guardrails.length) {
    lines.push(
      `风格护栏：\n${b.execution_card.style_guardrails.map((x) => `  · ${x}`).join("\n")}`
    );
  }
  if (b.execution_card.ending_hook) lines.push(`章末钩子：${b.execution_card.ending_hook}`);
  if (!lines.length) return typeof beats === "string" ? beats : JSON.stringify(beats);
  return lines.join("\n\n");
}

function cleanPlanText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function toPlanTextList(value: unknown): string[] {
  if (typeof value === "string") {
    const text = value.trim();
    return text ? [text] : [];
  }
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => (typeof item === "string" ? item.trim() : ""))
    .filter(Boolean);
}

function toReservedItems(value: unknown): ChapterPlanReservedItem[] {
  if (!Array.isArray(value)) return [];
  const out: ChapterPlanReservedItem[] = [];
  for (const item of value) {
    if (!item || typeof item !== "object" || Array.isArray(item)) continue;
    const row = item as Record<string, unknown>;
    const name = cleanPlanText(row.item);
    if (!name) continue;
    const chapter =
      typeof row.not_before_chapter === "number"
        ? row.not_before_chapter
        : typeof row.not_before_chapter === "string" &&
            row.not_before_chapter.trim() &&
            Number.isFinite(Number(row.not_before_chapter))
          ? Number(row.not_before_chapter)
          : undefined;
    const reason = cleanPlanText(row.reason);
    out.push({
      item: name,
      not_before_chapter: chapter,
      reason: reason || undefined,
    });
  }
  return out;
}

function normalizePlanBeats(beats: unknown): NormalizedPlanBeats {
  const raw =
    beats && typeof beats === "object" && !Array.isArray(beats)
      ? (beats as Record<string, unknown>)
      : {};
  const meta =
    raw.meta && typeof raw.meta === "object" && !Array.isArray(raw.meta)
      ? (raw.meta as Record<string, unknown>)
      : {};
  const display =
    raw.display_summary &&
    typeof raw.display_summary === "object" &&
    !Array.isArray(raw.display_summary)
      ? (raw.display_summary as Record<string, unknown>)
      : {};
  const card =
    raw.execution_card &&
    typeof raw.execution_card === "object" &&
    !Array.isArray(raw.execution_card)
      ? (raw.execution_card as Record<string, unknown>)
      : {};
  const reservedFromCard = toReservedItems(card.reserved_for_later);
  const reservedFromLegacy = toReservedItems(raw.reserved_for_later);
  return {
    schema_version:
      typeof raw.schema_version === "number" ? raw.schema_version : 2,
    meta: {
      edited_by_user: Boolean(meta.edited_by_user),
      last_editor_id: cleanPlanText(meta.last_editor_id) || null,
      last_edited_at: cleanPlanText(meta.last_edited_at) || null,
    },
    display_summary: {
      plot_summary:
        cleanPlanText(display.plot_summary) ||
        (typeof raw.plot_summary === "string" ? raw.plot_summary.trim() : ""),
      stage_position:
        cleanPlanText(display.stage_position) ||
        cleanPlanText(raw.stage_position),
      pacing_justification:
        cleanPlanText(display.pacing_justification) ||
        cleanPlanText(raw.pacing_justification),
    },
    execution_card: {
      chapter_goal:
        cleanPlanText(card.chapter_goal) || cleanPlanText(raw.goal),
      core_conflict:
        cleanPlanText(card.core_conflict) || cleanPlanText(raw.conflict),
      key_turn: cleanPlanText(card.key_turn) || cleanPlanText(raw.turn),
      must_happen: toPlanTextList(card.must_happen),
      required_callbacks: toPlanTextList(card.required_callbacks),
      scene_cards: Array.isArray(card.scene_cards) ? card.scene_cards : [],
      allowed_progress:
        toPlanTextList(card.allowed_progress).length > 0
          ? toPlanTextList(card.allowed_progress)
          : toPlanTextList(raw.progress_allowed),
      must_not:
        toPlanTextList(card.must_not).length > 0
          ? toPlanTextList(card.must_not)
          : toPlanTextList(raw.must_not),
      reserved_for_later:
        reservedFromCard.length > 0 ? reservedFromCard : reservedFromLegacy,
      end_state_targets:
        card.end_state_targets &&
        typeof card.end_state_targets === "object" &&
        !Array.isArray(card.end_state_targets)
          ? {
              characters: toPlanTextList(
                (card.end_state_targets as Record<string, unknown>).characters
              ),
              relations: toPlanTextList(
                (card.end_state_targets as Record<string, unknown>).relations
              ),
              items: toPlanTextList(
                (card.end_state_targets as Record<string, unknown>).items
              ),
              plots: toPlanTextList(
                (card.end_state_targets as Record<string, unknown>).plots
              ),
            }
          : { characters: [], relations: [], items: [], plots: [] },
      ending_hook:
        cleanPlanText(card.ending_hook) || cleanPlanText(raw.hook),
      style_guardrails: toPlanTextList(card.style_guardrails),
    },
  };
}

function linesToEditorText(items: string[]): string {
  return items.join("\n");
}

function editorTextToLines(value: string): string[] {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function reservedItemsToEditorText(items: ChapterPlanReservedItem[]): string {
  return items
    .map((item) => {
      const chapter =
        typeof item.not_before_chapter === "number"
          ? String(item.not_before_chapter)
          : "";
      const reason = item.reason?.trim() ?? "";
      return [item.item.trim(), chapter, reason].filter(Boolean).join(" | ");
    })
    .join("\n");
}

function editorTextToReservedItems(value: string): ChapterPlanReservedItem[] {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [itemRaw, chapterRaw = "", reasonRaw = ""] = line
        .split("|")
        .map((part) => part.trim());
      const chapterNo =
        chapterRaw && Number.isFinite(Number(chapterRaw))
          ? Number(chapterRaw)
          : undefined;
      return {
        item: itemRaw,
        not_before_chapter: chapterNo,
        reason: reasonRaw || undefined,
      };
    })
    .filter((item) => item.item);
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
  const navigate = useNavigate();
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
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("studio");
  /** 左侧树点到「本书」根：不强制选中某一卷，主区显示全书入口 */
  const [workspaceRootBook, setWorkspaceRootBook] = useState(false);
  const [outlineDrawerOpen, setOutlineDrawerOpen] = useState(false);
  /** 卷下章节树是否展开 */
  const [expandedVolumeIds, setExpandedVolumeIds] = useState<Record<string, boolean>>({});
  const [fbDraft, setFbDraft] = useState<Record<string, string>>({});
  const [revisePrompt, setRevisePrompt] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const [notice, setNotice] = useState<React.ReactNode | null>(null);

  function setTaskNotice(msg: string) {
    setNotice(
      <div className="flex items-center justify-between w-full">
        <span>{msg}</span>
        <Button
          variant="ghost"
          size="sm"
          className="h-auto p-0 text-emerald-600 dark:text-emerald-300 font-bold underline decoration-2 underline-offset-4 ml-2 hover:bg-transparent"
          onClick={() => navigate("/tasks")}
        >
          查看任务状态
        </Button>
      </div>
    );
  }
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
  const [arcsTargetVolumes, setArcsTargetVolumes] = useState<number[]>([]);
  const [arcsInstruction, setArcsInstruction] = useState("");
  const [arcsBusy, setArcsBusy] = useState(false);
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
  const [planEditorOpen, setPlanEditorOpen] = useState(false);
  const [planEditorSaving, setPlanEditorSaving] = useState(false);
  const [planEditorChapterNo, setPlanEditorChapterNo] = useState<number | null>(null);
  const [planEditorTitle, setPlanEditorTitle] = useState("");
  const [planEditorGoal, setPlanEditorGoal] = useState("");
  const [planEditorConflict, setPlanEditorConflict] = useState("");
  const [planEditorTurn, setPlanEditorTurn] = useState("");
  const [planEditorPlotSummary, setPlanEditorPlotSummary] = useState("");
  const [planEditorStagePosition, setPlanEditorStagePosition] = useState("");
  const [planEditorPacing, setPlanEditorPacing] = useState("");
  const [planEditorMustHappen, setPlanEditorMustHappen] = useState("");
  const [planEditorCallbacks, setPlanEditorCallbacks] = useState("");
  const [planEditorAllowedProgress, setPlanEditorAllowedProgress] = useState("");
  const [planEditorMustNot, setPlanEditorMustNot] = useState("");
  const [planEditorReserved, setPlanEditorReserved] = useState("");
  const [planEditorEndingHook, setPlanEditorEndingHook] = useState("");
  const [planEditorStyleGuardrails, setPlanEditorStyleGuardrails] = useState("");
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
    auto_consistency_check: false,
    auto_plan_guard_check: false,
    auto_plan_guard_fix: false,
    auto_style_polish: false,
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
      auto_consistency_check: Boolean(novel.auto_consistency_check),
      auto_plan_guard_check: Boolean(
        novel.auto_plan_guard_check || novel.auto_plan_guard_fix
      ),
      auto_plan_guard_fix: Boolean(novel.auto_plan_guard_fix),
      auto_style_polish: Boolean(novel.auto_style_polish),
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
    // 优先编辑「基础大纲」JSON；无该字段时回退到 framework_json（旧客户端/旧数据）
    const baseJson = (n as { framework_json_base?: string }).framework_json_base;
    setFwJson(String(baseJson ?? n.framework_json ?? "{}"));
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
    setSelectedVolumeId((current) => {
      if (vs.length === 0) return "";
      if (workspaceRootBook) {
        return current && vs.some((x) => x.id === current) ? current : "";
      }
      return current && vs.some((x) => x.id === current) ? current : vs[0].id;
    });
  }, [id, workspaceRootBook]);

  const totalStudioVolumes = useMemo(() => {
    const tc = Number(novel?.target_chapters || 0);
    if (!tc || tc <= 0) return 1;
    return Math.max(1, Math.ceil(tc / 50));
  }, [novel?.target_chapters]);

  const runInlineGenerateArcs = useCallback(async () => {
    if (!id) return;
    if (!novel?.base_framework_confirmed) {
      setErr("请先确认基础大纲，再生成分卷 Arcs。");
      return;
    }
    if (arcsTargetVolumes.length === 0) {
      setErr("请在大纲抽屉里至少选择一卷。");
      return;
    }
    setArcsBusy(true);
    setErr(null);
    try {
      await ensureLlmReady();
      const r = await generateArcs(id, {
        target_volume_nos: arcsTargetVolumes,
        instruction: arcsInstruction.trim(),
      });
      if (r.status === "queued" && r.batch_id) {
        setTaskNotice("正在生成分卷 Arcs…");
        const o = await waitForArcsGenerateBatch(id, r.batch_id);
        if (o === "failed") throw new Error("分卷 Arcs 生成失败，请查看生成日志");
      }
      setNotice("分卷 Arcs 已更新。");
      await reloadVolumes();
      await reload();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "分卷 Arcs 生成失败");
    } finally {
      setArcsBusy(false);
    }
  }, [
    id,
    novel?.base_framework_confirmed,
    arcsTargetVolumes,
    arcsInstruction,
    reload,
    reloadVolumes,
  ]);

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

  const activeChapterVolume = useMemo(() => {
    if (!chapterVolumeId) return null;
    return volumes.find((x) => x.id === chapterVolumeId) ?? null;
  }, [volumes, chapterVolumeId]);

  const filteredChapters = useMemo(() => {
    if (!volumes.length) return chapters;
    if (!activeChapterVolume) return [];
    return chapters.filter(
      (c) =>
        c.chapter_no >= activeChapterVolume.from_chapter &&
        c.chapter_no <= activeChapterVolume.to_chapter
    );
  }, [chapters, volumes, activeChapterVolume]);

  useEffect(() => {
    if (workspaceRootBook) return;
    if (!volumes.length) {
      setChapterVolumeId("");
      return;
    }
    if (!chapterVolumeId || !volumes.some((x) => x.id === chapterVolumeId)) {
      setChapterVolumeId(volumes[0].id);
    }
  }, [volumes, chapterVolumeId, workspaceRootBook]);

  useEffect(() => {
    if (!selectedChapterId) return;
    if (!filteredChapters.some((c) => c.id === selectedChapterId)) {
      setSelectedChapterId("");
    }
  }, [filteredChapters, selectedChapterId]);

  useEffect(() => {
    if (!selectedVolumeId) return;
    setExpandedVolumeIds((m) => ({ ...m, [selectedVolumeId]: true }));
  }, [selectedVolumeId]);

  const selectedChapter =
    filteredChapters.find((c) => c.id === selectedChapterId) ?? null;
  /** 主区展示：章 > 卷 > 全书入口（与左侧结构树一致） */
  const studioRight = useMemo(() => {
    if (selectedChapter) return "chapter" as const;
    if (selectedVolumeId) return "volume" as const;
    return "book" as const;
  }, [selectedChapter, selectedVolumeId]);
  const selectedChapterWordCount = editContent.trim()
    ? editContent.trim().replace(/\s+/g, "").length
    : 0;
  const frameworkConfirmed = Boolean(novel?.framework_confirmed);
  const generateDisabledReason = busy
    ? "当前有任务执行中，请稍候"
    : !frameworkConfirmed
      ? "请先在向导或流程中确认框架"
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

  const selectedVolume = useMemo(
    () => volumes.find((v) => v.id === selectedVolumeId) ?? null,
    [volumes, selectedVolumeId]
  );

  const selectedVolumeTotalChapters = selectedVolume
    ? selectedVolume.to_chapter - selectedVolume.from_chapter + 1
    : 0;

  const selectedVolumeCoverage = selectedVolumeTotalChapters
    ? clamp01(volumePlan.length / selectedVolumeTotalChapters)
    : 0;

  const selectedVolumeSlots = useMemo(() => {
    if (!selectedVolume || selectedVolumeTotalChapters <= 0) return [];
    const planSet = new Set(volumePlan.map((plan) => plan.chapter_no));
    const bodySet = new Set(
      chapters
        .filter(
          (chapter) =>
            chapter.chapter_no >= selectedVolume.from_chapter &&
            chapter.chapter_no <= selectedVolume.to_chapter &&
            (chapter.content || chapter.pending_content || "").trim().length > 0
        )
        .map((chapter) => chapter.chapter_no)
    );

    return Array.from({ length: selectedVolumeTotalChapters }, (_, index) => {
      const chapterNo = selectedVolume.from_chapter + index;
      return {
        chapterNo,
        hasPlan: planSet.has(chapterNo),
        hasBody: bodySet.has(chapterNo),
      };
    });
  }, [chapters, selectedVolume, selectedVolumeTotalChapters, volumePlan]);

  const volumePlanMetrics = useMemo(() => {
    const normalizedPlans = volumePlan.map((plan) => normalizePlanBeats(plan.beats));
    return {
      editedCount: normalizedPlans.filter((plan) => plan.meta.edited_by_user).length,
      pendingWriteCount: volumePlanView.visible.length,
    };
  }, [volumePlan, volumePlanView.visible.length]);

  const memoryVisuals = useMemo(() => {
    if (!memoryNorm) return null;

    const topCharacters = [...memoryNorm.characters]
      .sort((a, b) => b.influence_score - a.influence_score)
      .slice(0, MEMORY_ATLAS_POINTS.length);
    const maxInfluence = Math.max(
      1,
      ...topCharacters.map((character) => character.influence_score || 0)
    );
    const topOpenPlots = [...memoryNorm.open_plots]
      .sort((a, b) => {
        const priority = (b.priority || 0) - (a.priority || 0);
        if (priority !== 0) return priority;
        return (b.last_touched_chapter || 0) - (a.last_touched_chapter || 0);
      })
      .slice(0, 6);

    return {
      topCharacters,
      maxInfluence,
      topOpenPlots,
      topRelations: memoryNorm.relations.filter((relation) => relation.is_active !== false).slice(0, 6),
      activeCharacters: memoryNorm.characters.filter((character) => character.is_active).length,
      activeInventory: memoryNorm.inventory.filter((item) => item.is_active).length,
      staleCount: memoryHealth?.stale_plots.length ?? 0,
      overdueCount: memoryHealth?.overdue_plots.length ?? 0,
    };
  }, [memoryNorm, memoryHealth]);

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
    llmConfirmActionRef.current = null;
    setLlmConfirm(null);
    setLlmConfirmBusy(true);
    try {
      await action();
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
      setTaskNotice("记忆刷新已在后台执行。");

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

  async function runCreateCharacter() {
    if (!id) return;
    const name = (window.prompt("请输入人物主名") || "").trim();
    if (!name) return;
    const role = (window.prompt("人物角色（可选）", "") || "").trim();
    const status = (window.prompt("人物状态（可选）", "") || "").trim();
    const traitsRaw = (window.prompt("人物特征（可选，逗号分隔）", "") || "").trim();
    const influence = readPromptNumber("人物影响力（0-100）", 0, 0, 100);
    if (influence == null) {
      setErr("影响力需为 0-100 的数字");
      return;
    }
    const isActive = window.confirm("是否标记为活跃人物？（确定=活跃，取消=已退场）");
    setErr(null);
    setBusy(true);
    try {
      await createMemoryCharacter(id, {
        name,
        role,
        status,
        traits: traitsRaw
          ? traitsRaw
              .split(/[，,]/)
              .map((x) => x.trim())
              .filter(Boolean)
          : [],
        influence_score: influence,
        is_active: isActive,
      });
      setNotice("人物已新增");
      await reload();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "新增人物失败");
    } finally {
      setBusy(false);
    }
  }

  async function runEditCharacter(character: NormalizedMemoryPayload["characters"][number]) {
    if (!id) return;
    if (!character.id) {
      setErr("当前人物缺少唯一标识，请先点击“从快照同步分表”后重试");
      return;
    }
    const name = (window.prompt("人物主名", character.name) || "").trim();
    if (!name) return;
    const role = (window.prompt("人物角色（可选）", character.role || "") || "").trim();
    const status = (window.prompt("人物状态（可选）", character.status || "") || "").trim();
    const currentTraits = Array.isArray(character.traits)
      ? character.traits.map((x) => String(x || "").trim()).filter(Boolean).join("，")
      : "";
    const traitsRaw = (window.prompt("人物特征（可选，逗号分隔）", currentTraits) || "").trim();
    const influence = readPromptNumber(
      "人物影响力（0-100）",
      character.influence_score ?? 0,
      0,
      100
    );
    if (influence == null) {
      setErr("影响力需为 0-100 的数字");
      return;
    }
    const isActive = window.confirm(
      `当前状态：${character.is_active ? "活跃" : "已退场"}。点击“确定”设置为活跃，点击“取消”设置为已退场。`
    );
    setErr(null);
    setBusy(true);
    try {
      await patchMemoryCharacter(id, character.id, {
        name,
        role,
        status,
        traits: traitsRaw
          ? traitsRaw
              .split(/[，,]/)
              .map((x) => x.trim())
              .filter(Boolean)
          : [],
        detail: character.detail,
        influence_score: influence,
        is_active: isActive,
      });
      setNotice("人物已更新");
      await reload();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "更新人物失败");
    } finally {
      setBusy(false);
    }
  }

  async function runDeleteCharacter(character: NormalizedMemoryPayload["characters"][number]) {
    if (!id) return;
    if (!character.id) {
      setErr("当前人物缺少唯一标识，请先点击“从快照同步分表”后重试");
      return;
    }
    if (!window.confirm(`确认将人物「${character.name}」标记为已退场吗？`)) return;
    setErr(null);
    setBusy(true);
    try {
      await deleteMemoryCharacter(id, character.id);
      setNotice("人物已标记为退场");
      await reload();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "人物下线失败");
    } finally {
      setBusy(false);
    }
  }

  async function runCreateRelation() {
    if (!id) return;
    const fromName = (window.prompt("关系起点人物") || "").trim();
    if (!fromName) return;
    const toName = (window.prompt("关系终点人物") || "").trim();
    if (!toName) return;
    const relation = (window.prompt("关系描述") || "").trim();
    if (!relation) return;
    const isActive = window.confirm("是否标记为当前生效关系？（确定=生效，取消=失效）");
    setErr(null);
    setBusy(true);
    try {
      await createMemoryRelation(id, {
        from_name: fromName,
        to_name: toName,
        relation,
        is_active: isActive,
      });
      setNotice("关系已新增");
      await reload();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "新增关系失败");
    } finally {
      setBusy(false);
    }
  }

  async function runEditRelation(relation: NormalizedMemoryPayload["relations"][number]) {
    if (!id) return;
    if (!relation.id) {
      setErr("当前关系缺少唯一标识，请先点击“从快照同步分表”后重试");
      return;
    }
    const fromName = (window.prompt("关系起点人物", relation.from) || "").trim();
    if (!fromName) return;
    const toName = (window.prompt("关系终点人物", relation.to) || "").trim();
    if (!toName) return;
    const relText = (window.prompt("关系描述", relation.relation) || "").trim();
    if (!relText) return;
    const isActive = window.confirm(
      `当前状态：${relation.is_active === false ? "失效" : "生效"}。点击“确定”设置为生效，点击“取消”设置为失效。`
    );
    setErr(null);
    setBusy(true);
    try {
      await patchMemoryRelation(id, relation.id, {
        from_name: fromName,
        to_name: toName,
        relation: relText,
        is_active: isActive,
      });
      setNotice("关系已更新");
      await reload();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "更新关系失败");
    } finally {
      setBusy(false);
    }
  }

  async function runDeleteRelation(relation: NormalizedMemoryPayload["relations"][number]) {
    if (!id) return;
    if (!relation.id) {
      setErr("当前关系缺少唯一标识，请先点击“从快照同步分表”后重试");
      return;
    }
    if (!window.confirm(`确认将关系「${relation.from} → ${relation.to}」标记为失效吗？`)) return;
    setErr(null);
    setBusy(true);
    try {
      await deleteMemoryRelation(id, relation.id);
      setNotice("关系已标记为失效");
      await reload();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "关系失效失败");
    } finally {
      setBusy(false);
    }
  }

  async function runCreateSkill() {
    if (!id) return;
    const name = (window.prompt("请输入技能名称") || "").trim();
    if (!name) return;
    const desc = (window.prompt("技能描述（可选）", "") || "").trim();
    const influence = readPromptNumber("技能影响力（0-100）", 0, 0, 100);
    if (influence == null) {
      setErr("影响力需为 0-100 的数字");
      return;
    }
    const isActive = window.confirm("是否标记为活跃技能？（确定=活跃，取消=已退场）");
    setErr(null);
    setBusy(true);
    try {
      await createMemorySkill(id, {
        name,
        detail: desc ? { description: desc } : {},
        influence_score: influence,
        is_active: isActive,
      });
      setNotice("技能已新增");
      await reload();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "新增技能失败");
    } finally {
      setBusy(false);
    }
  }

  async function runEditSkill(skill: NormalizedMemoryPayload["skills"][number]) {
    if (!id) return;
    if (!skill.id) {
      setErr("当前技能缺少唯一标识，请先点击“从快照同步分表”后重试");
      return;
    }
    const name = (window.prompt("技能名称", skill.name) || "").trim();
    if (!name) return;
    const currentDesc =
      typeof skill.detail.description === "string" ? skill.detail.description : "";
    const desc = (window.prompt("技能描述（可选）", currentDesc) || "").trim();
    const influence = readPromptNumber(
      "技能影响力（0-100）",
      skill.influence_score ?? 0,
      0,
      100
    );
    if (influence == null) {
      setErr("影响力需为 0-100 的数字");
      return;
    }
    const isActive = window.confirm(
      `当前状态：${skill.is_active ? "活跃" : "已退场"}。点击“确定”设置为活跃，点击“取消”设置为已退场。`
    );
    setErr(null);
    setBusy(true);
    try {
      await patchMemorySkill(id, skill.id, {
        name,
        detail: { ...skill.detail, description: desc },
        influence_score: influence,
        is_active: isActive,
      });
      setNotice("技能已更新");
      await reload();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "更新技能失败");
    } finally {
      setBusy(false);
    }
  }

  async function runDeleteSkill(skill: NormalizedMemoryPayload["skills"][number]) {
    if (!id) return;
    if (!skill.id) {
      setErr("当前技能缺少唯一标识，请先点击“从快照同步分表”后重试");
      return;
    }
    if (!window.confirm(`确认删除技能「${skill.name}」吗？`)) return;
    setErr(null);
    setBusy(true);
    try {
      await deleteMemorySkill(id, skill.id);
      setNotice("技能已删除");
      await reload();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "删除技能失败");
    } finally {
      setBusy(false);
    }
  }

  async function runCreateItem() {
    if (!id) return;
    const label = (window.prompt("请输入物品名称") || "").trim();
    if (!label) return;
    const owner = (window.prompt("持有人（可选）", "") || "").trim();
    const description = (window.prompt("物品描述（可选）", "") || "").trim();
    const influence = readPromptNumber("物品影响力（0-100）", 0, 0, 100);
    if (influence == null) {
      setErr("影响力需为 0-100 的数字");
      return;
    }
    const isActive = window.confirm("是否标记为活跃物品？（确定=活跃，取消=已退场）");
    setErr(null);
    setBusy(true);
    try {
      await createMemoryItem(id, {
        label,
        detail: {
          ...(owner ? { owner } : {}),
          ...(description ? { description } : {}),
        },
        influence_score: influence,
        is_active: isActive,
      });
      setNotice("物品已新增");
      await reload();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "新增物品失败");
    } finally {
      setBusy(false);
    }
  }

  async function runEditItem(item: NormalizedMemoryPayload["inventory"][number]) {
    if (!id) return;
    if (!item.id) {
      setErr("当前物品缺少唯一标识，请先点击“从快照同步分表”后重试");
      return;
    }
    const currentLabel = inventoryDisplayLabel(item);
    const label = (window.prompt("物品名称", currentLabel) || "").trim();
    if (!label) return;
    const currentOwner =
      typeof item.detail.owner === "string" ? item.detail.owner : "";
    const currentDescription =
      typeof item.detail.description === "string" ? item.detail.description : "";
    const owner = (window.prompt("持有人（可选）", currentOwner) || "").trim();
    const description = (window.prompt("物品描述（可选）", currentDescription) || "").trim();
    const influence = readPromptNumber(
      "物品影响力（0-100）",
      item.influence_score ?? 0,
      0,
      100
    );
    if (influence == null) {
      setErr("影响力需为 0-100 的数字");
      return;
    }
    const isActive = window.confirm(
      `当前状态：${item.is_active ? "活跃" : "已退场"}。点击“确定”设置为活跃，点击“取消”设置为已退场。`
    );
    setErr(null);
    setBusy(true);
    try {
      await patchMemoryItem(id, item.id, {
        label,
        detail: {
          ...item.detail,
          ...(owner ? { owner } : { owner: "" }),
          ...(description ? { description } : { description: "" }),
        },
        influence_score: influence,
        is_active: isActive,
      });
      setNotice("物品已更新");
      await reload();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "更新物品失败");
    } finally {
      setBusy(false);
    }
  }

  async function runDeleteItem(item: NormalizedMemoryPayload["inventory"][number]) {
    if (!id) return;
    if (!item.id) {
      setErr("当前物品缺少唯一标识，请先点击“从快照同步分表”后重试");
      return;
    }
    const label = inventoryDisplayLabel(item);
    if (!window.confirm(`确认删除物品「${label}」吗？`)) return;
    setErr(null);
    setBusy(true);
    try {
      await deleteMemoryItem(id, item.id);
      setNotice("物品已删除");
      await reload();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "删除物品失败");
    } finally {
      setBusy(false);
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
      setTaskNotice(`已开启 AI 一键续写（${targetCount}章）。`);
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

  async function runRetryFrameworkGeneration() {
    if (!id) return;
    const ready = await ensureLlmReady();
    if (!ready) return;
    setErr(null);
    setNotice(null);
    setBusy(true);
    try {
      const resp = await generateFramework(id);
      if (resp.status === "queued" && resp.batch_id) {
        const outcome = await waitForFrameworkGenerateBatch(id, resp.batch_id);
        if (outcome === "failed") {
          throw new Error("大纲 JSON 不完整或生成失败，请点击“重新生成大纲”再次尝试，并查看生成日志。");
        }
      }
      await reload();
      setNotice("大纲已重新入队生成，请稍候自动刷新。");
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "重新生成大纲失败");
      await reload();
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
      const resp = await generateVolumes(id, {
        approx_size: 50,
        total_chapters: Number(novel?.target_chapters || 0) || undefined,
      });
      await reloadVolumes();
      if (resp.status === "extended") {
        setNotice(
          `已补生成后续卷 ${resp.added ?? 0} 个，现已覆盖到第${resp.covered_to ?? resp.total_chapters ?? "?"}章。`
        );
      } else if (resp.status === "skipped") {
        setNotice(
          resp.reason
            ? `未新增卷：${resp.reason}。`
            : "未新增卷：当前卷列表已经覆盖目标章节范围。"
        );
      } else {
        setNotice("卷列表已生成。请选择一卷后生成本卷章计划。");
      }
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

  async function runFormatSelectedChapter() {
    if (!selectedChapter || !editContent.trim()) return;
    setErr(null);
    setNotice(null);
    setBusy(true);
    try {
      const result = await formatChapter(selectedChapter.id, {
        content: editContent,
      });
      setEditContent(result.formatted_content);
      setNotice(
        `正文已按小说段落规则格式化：${result.before_paragraphs} 段 -> ${result.after_paragraphs} 段`
      );
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "格式化失败");
    } finally {
      setBusy(false);
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
            setTaskNotice("卷章计划生成失败。");
          } else {
            setTaskNotice("本批卷章计划已生成，可在章计划列表中查看。");
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
      setTaskNotice(`第${chapterNo}章计划已重生成。`);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "重生成章计划失败");
    } finally {
      setVolumeBusy(false);
    }
  }

  function openPlanEditor(plan: Awaited<ReturnType<typeof listVolumeChapterPlan>>[number]) {
    const beats = normalizePlanBeats(plan.beats);
    setPlanEditorChapterNo(plan.chapter_no);
    setPlanEditorTitle(plan.chapter_title || `第${plan.chapter_no}章`);
    setPlanEditorGoal(beats.execution_card?.chapter_goal ?? "");
    setPlanEditorConflict(beats.execution_card?.core_conflict ?? "");
    setPlanEditorTurn(beats.execution_card?.key_turn ?? "");
    setPlanEditorPlotSummary(beats.display_summary?.plot_summary ?? "");
    setPlanEditorStagePosition(beats.display_summary?.stage_position ?? "");
    setPlanEditorPacing(beats.display_summary?.pacing_justification ?? "");
    setPlanEditorMustHappen(linesToEditorText(beats.execution_card?.must_happen ?? []));
    setPlanEditorCallbacks(linesToEditorText(beats.execution_card?.required_callbacks ?? []));
    setPlanEditorAllowedProgress(
      linesToEditorText(beats.execution_card?.allowed_progress ?? [])
    );
    setPlanEditorMustNot(linesToEditorText(beats.execution_card?.must_not ?? []));
    setPlanEditorReserved(
      reservedItemsToEditorText(beats.execution_card?.reserved_for_later ?? [])
    );
    setPlanEditorEndingHook(beats.execution_card?.ending_hook ?? "");
    setPlanEditorStyleGuardrails(
      linesToEditorText(beats.execution_card?.style_guardrails ?? [])
    );
    setPlanEditorOpen(true);
  }

  async function savePlanEditor() {
    if (!id || !selectedVolumeId || planEditorChapterNo == null) return;
    setErr(null);
    setNotice(null);
    setPlanEditorSaving(true);
    try {
      await patchChapterPlan(id, selectedVolumeId, planEditorChapterNo, {
        chapter_title: planEditorTitle.trim(),
        beats: {
          display_summary: {
            plot_summary: planEditorPlotSummary.trim(),
            stage_position: planEditorStagePosition.trim(),
            pacing_justification: planEditorPacing.trim(),
          },
          execution_card: {
            chapter_goal: planEditorGoal.trim(),
            core_conflict: planEditorConflict.trim(),
            key_turn: planEditorTurn.trim(),
            must_happen: editorTextToLines(planEditorMustHappen),
            required_callbacks: editorTextToLines(planEditorCallbacks),
            allowed_progress: editorTextToLines(planEditorAllowedProgress),
            must_not: editorTextToLines(planEditorMustNot),
            reserved_for_later: editorTextToReservedItems(planEditorReserved),
            ending_hook: planEditorEndingHook.trim(),
            style_guardrails: editorTextToLines(planEditorStyleGuardrails),
          },
        },
      });
      const plan = await listVolumeChapterPlan(id, selectedVolumeId);
      setVolumePlan(plan);
      setPlanEditorOpen(false);
      setNotice(`第${planEditorChapterNo}章执行卡已保存。`);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "保存执行卡失败");
    } finally {
      setPlanEditorSaving(false);
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
            if (outcome === "done") {
              setTaskNotice(`第${chapterNo}章已生成（待审定）。`);
            } else {
              setTaskNotice(`第${chapterNo}章生成失败。`);
            }
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

  async function runApproveChapter(chapterId: string, forcePass = false) {
    setErr(null);
    setNotice(null);
    setBusy(true);
    try {
      const resp = await approveChapter(chapterId, { force_pass: forcePass });
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
          `${forcePass ? "已强行审定通过" : "已审定通过"}，${incrementalNotice}；后台全局记忆刷新已排队（task_id: ${resp.memory_refresh_task_id ?? "未知"}）。`
        );
      } else if (resp.memory_refresh_status === "skipped") {
        setNotice(`${forcePass ? "已强行审定通过" : "已审定通过"}，${incrementalNotice}；但后台全局记忆刷新入队失败，请稍后在记忆页手动刷新。`);
      } else {
        setNotice(`${forcePass ? "已强行审定通过" : "已审定通过"}，${incrementalNotice}。`);
      }
      await reload();
    } catch (e: unknown) {
      const guardErr = e as Error & {
        code?: string;
        issues?: string[];
        canForce?: boolean;
      };
      if (
        !forcePass &&
        guardErr?.code === "approve_guard_failed" &&
        guardErr.canForce &&
        Array.isArray(guardErr.issues) &&
        guardErr.issues.length
      ) {
        const issues = guardErr.issues;
        setTimeout(() => {
          void openLlmConfirm(
            {
              title: "检测到硬条件未满足，是否强行通过？",
              description:
                "当前章节未满足执行卡或字数硬条件。你仍可强行审定通过，但后果需要自行承担。",
              confirmLabel: "强行审定通过",
              details: issues.map((item) => `· ${item}`),
            },
            async () => {
              await runApproveChapter(chapterId, true);
            }
          );
        }, 0);
        return;
      }
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
      setTaskNotice("章节增量记忆写入已手动入队执行。");
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
    let updateMemory = true;
    if (isApproved) {
      const typed = window.prompt(
        [
          `你正在删除已审定章节：第${ch.chapter_no}章《${title}》`,
          "该章节已经进入记忆体系。",
          '请输入 DELETE 以确认删除：',
        ].join("\n")
      );
      if (typed !== "DELETE") return;
      updateMemory = window.confirm(
        [
          `是否同时更新记忆？`,
          "确定：删除章节，并在后台刷新记忆。",
          "取消：只删除章节，不更新记忆。",
        ].join("\n")
      );
    } else {
      const msg = `确认删除第${ch.chapter_no}章《${title}》吗？\n该章节未审定，删除不会影响记忆。`;
      if (!window.confirm(msg)) return;
    }

    setErr(null);
    setNotice(null);
    setBusy(true);
    try {
      const resp = await deleteChapter(ch.id, { update_memory: updateMemory });
      if (resp.was_approved) {
        if (!resp.update_memory) {
          setNotice("章节已删除，记忆未更新。");
        } else if (resp.memory_refresh_status === "queued") {
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
          "将从已审定章节之后开始推进，后台会先消费已有章计划；如章计划不足，会自动补齐章计划并串行生成正文。默认会在每章生成后直接审定并更新工作记忆；若你开启了执行卡校验/纠偏，则该流程可能被校验拦截。",
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
            setTaskNotice("一致性修订已在后台启动。");
            const o = await waitForChapterConsistencyBatch(id, r.batch_id);
            if (o === "failed") {
              setTaskNotice("一致性修订失败。");
              throw new Error("一致性修订失败，请查看生成日志");
            }
            setTaskNotice("一致性修订已完成。");
          }
        });
      }
    );
  }

  function confirmPolishChapter(chapterId: string) {
    void openLlmConfirm(
      {
        title: "确认进行去AI味润色？",
        description: "这会调用大模型优化当前章节的表达方式，去除AI痕迹，同时严格保持原剧情不变。",
        confirmLabel: "确认润色",
        details: [
          "提交后任务在后台执行，关闭或离开本页不会中断。",
          "润色结果会先放入待确认修订稿，不会直接覆盖正式稿。",
          "大模型会尝试压缩废话、优化分段，并使文风更符合中文网文习惯。",
        ],
      },
      async () => {
        await run(async () => {
          const r = await polishChapter(chapterId);
          if (r.status === "queued" && r.batch_id && id) {
            setTaskNotice("去AI味润色已在后台启动。");
            const o = await waitForChapterPolishBatch(id, r.batch_id);
            if (o === "failed") {
              setTaskNotice("去AI味润色失败。");
              throw new Error("去AI味润色失败，请查看生成日志");
            }
            setTaskNotice("去AI味润色已完成。");
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
            setTaskNotice("按指令改稿已在后台启动。");
            const o = await waitForChapterReviseBatch(id, r.batch_id);
            if (o === "failed") {
              setTaskNotice("改稿失败。");
              throw new Error("改稿失败，请查看生成日志");
            }
            setTaskNotice("改稿已完成。");
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
          baseFrameworkConfirmed={Boolean(novel?.base_framework_confirmed)}
          frameworkMarkdown={fwMd}
          frameworkJson={fwJson}
          status={String(novel?.status || "")}
          targetChapters={Number(novel?.target_chapters || 0)}
          volumes={volumes.map((v) => ({
            volume_no: v.volume_no,
            title: v.title,
            outline_json: v.outline_json,
            outline_markdown: v.outline_markdown,
          }))}
          onReload={reload}
          onConfirmFramework={async () => {
            await confirmFramework(id, fwMd, fwJson);
            setNotice("框架已确认，可继续生成卷计划与正文。");
            await reload();
          }}
          onConfirmBaseFramework={async () => {
            await confirmBaseFramework(id, fwMd, fwJson);
            setNotice("基础大纲已确认，现在可以为各卷生成 Arcs。");
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
              {!novel.framework_confirmed ? (
                <Button
                  variant="outline"
                  className="font-bold border-destructive/30 text-destructive hover:bg-destructive/5"
                  disabled={busy}
                  onClick={() => void runRetryFrameworkGeneration()}
                >
                  {busy ? "重新生成中…" : "重新生成大纲"}
                </Button>
              ) : null}
              <Button
                variant="outline"
                className="font-bold border-destructive/30 text-destructive hover:bg-destructive/5"
                asChild
              >
                <Link to="/novels">回到书架</Link>
              </Button>
              <p className="text-[11px] text-foreground/50 dark:text-muted-foreground italic font-medium ml-2">
                {!novel.framework_confirmed
                  ? "如果报错里提到 JSON 不完整或截断，直接点击“重新生成大纲”即可。"
                  : "建议先查看错误日志，再决定是否继续重试。"}
              </p>
            </div>
          </div>
        )}

        <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as WorkspaceTab)} className="w-full">
          <TabsList className="w-full">
            <TabsTrigger value="studio" className="flex-1 sm:flex-none">
              创作工作台
            </TabsTrigger>
            <TabsTrigger value="memory" className="flex-1 sm:flex-none">
              记忆
            </TabsTrigger>
          </TabsList>

          <TabsContent value="studio" className="mt-4 border-0 bg-transparent p-0 shadow-none">
            <div className="sticky top-0 z-20 border-b border-border/70 bg-background/92 px-3 py-2 backdrop-blur-xl sm:px-4 md:px-6">
              <div className="novel-container flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:gap-3">
                <div className="min-w-0 flex flex-1 flex-col gap-0.5 sm:flex-row sm:items-center sm:gap-2">
                  <p className="truncate text-xs font-bold text-foreground/80 sm:text-sm">
                    <span className="text-foreground/45">创作</span>
                    {workspaceRootBook || !selectedVolumeId ? (
                      <span className="ml-1.5">· 全书</span>
                    ) : selectedChapter ? (
                      <span className="ml-1.5">
                        · 第{selectedVolume?.volume_no ?? "?"}卷 · 第{selectedChapter.chapter_no}章
                      </span>
                    ) : (
                      <span className="ml-1.5">· 第{selectedVolume?.volume_no ?? "?"}卷</span>
                    )}
                  </p>
                  <p className="truncate text-[10px] text-foreground/50 sm:text-xs">
                    {titleDraft.trim() || String(novel?.title || "未命名")}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-1.5 sm:ml-auto">
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    className="h-8 rounded-full px-3 text-xs font-bold"
                    onClick={() => setOutlineDrawerOpen(true)}
                  >
                    大纲抽屉
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-8 rounded-full px-3 text-xs font-bold"
                    onClick={() => setFrameworkWizardOpen(true)}
                  >
                    完整向导
                  </Button>
                </div>
              </div>
            </div>

            <div className="novel-container py-4 md:py-5">
              <div className="flex max-h-[min(85dvh,920px)] min-h-[min(52dvh,420px)] flex-col overflow-hidden rounded-2xl border border-border/60 bg-background/25 shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]">
                <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
                  <aside className="flex max-h-[34vh] w-full shrink-0 flex-col border-b border-border/60 bg-muted/15 lg:max-h-none lg:w-[min(18rem,92vw)] lg:border-b-0 lg:border-r border-border/60">
                    <div className="soft-scroll min-h-0 flex-1 space-y-3 overflow-y-auto p-3 sm:p-4">
                      <p className="text-[10px] font-bold uppercase tracking-wide text-foreground/45">
                        结构树
                      </p>
                      <div
                        className={`flex items-center gap-2 rounded-xl border px-2.5 py-2 ${
                          workspaceRootBook || !selectedVolumeId
                            ? "border-primary/35 bg-primary/10"
                            : "border-border/60 bg-background/50"
                        }`}
                      >
                        <button
                          type="button"
                          className="flex min-w-0 flex-1 items-center gap-2 text-left"
                          onClick={() => {
                            setWorkspaceRootBook(true);
                            setSelectedVolumeId("");
                            setSelectedChapterId("");
                            setChapterVolumeId("");
                          }}
                        >
                          <BookOpen className="size-4 shrink-0 text-primary" />
                          <span className="truncate text-xs font-bold text-foreground">
                            {titleDraft.trim() || String(novel?.title || "本书")}
                          </span>
                        </button>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="h-7 shrink-0 px-2 text-[10px] font-bold"
                          onClick={() => setOutlineDrawerOpen(true)}
                        >
                          大纲
                        </Button>
                      </div>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-8 w-full justify-start px-2 text-[11px] font-bold text-foreground/70 hover:text-foreground"
                        onClick={() => {
                          setExportContent("");
                          setExportOpen(true);
                        }}
                      >
                        导出正文…
                      </Button>
                      <div className="space-y-2 pt-1">
                        {volumes.length === 0 ? (
                          <p className="text-xs text-foreground/50 dark:text-muted-foreground italic font-medium">
                            暂无分卷。在右侧主区生成卷列表。
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
                              return (
                                <div key={v.id} className="space-y-1">
                                  <div className="flex items-stretch gap-0.5">
                                    <button
                                      type="button"
                                      aria-label={expanded ? "收起本卷章节" : "展开本卷章节"}
                                      className="flex w-8 shrink-0 items-center justify-center rounded-lg border border-transparent text-foreground/55 hover:bg-muted/45"
                                      onClick={() =>
                                        setExpandedVolumeIds((m) => ({
                                          ...m,
                                          [v.id]: !expanded,
                                        }))
                                      }
                                    >
                                      {expanded ? (
                                        <ChevronDown className="size-4" />
                                      ) : (
                                        <ChevronRight className="size-4" />
                                      )}
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => {
                                        setWorkspaceRootBook(false);
                                        setSelectedVolumeId(v.id);
                                        setChapterVolumeId(v.id);
                                        setSelectedChapterId("");
                                      }}
                                      className={`min-w-0 flex-1 rounded-xl border px-2.5 py-2 text-left text-xs transition-all ${
                                        selectedVolumeId === v.id
                                          ? "border-primary/35 bg-primary/10 shadow-[0_10px_24px_hsl(var(--primary)/0.12)]"
                                          : "border-border/60 bg-background/45 hover:bg-muted/35"
                                      }`}
                                    >
                                      <div className="flex items-center justify-between gap-1 font-bold text-foreground">
                                        <span className="truncate">第{v.volume_no}卷</span>
                                        <span className="shrink-0 text-[10px] text-foreground/50">
                                          {v.chapter_plan_count} 计划
                                        </span>
                                      </div>
                                      <p className="mt-0.5 truncate text-[10px] text-foreground/55">
                                        {v.title || "未命名"}
                                      </p>
                                    </button>
                                  </div>
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
                                            onClick={() => {
                                              setWorkspaceRootBook(false);
                                              setSelectedVolumeId(v.id);
                                              setChapterVolumeId(v.id);
                                              setSelectedChapterId(ch.id);
                                            }}
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
                  </aside>
                  <div className="min-h-0 flex-1 overflow-y-auto soft-scroll p-4 md:p-5">
            <Dialog open={outlineDrawerOpen} onOpenChange={setOutlineDrawerOpen}>
              <DialogContent className="!fixed !inset-y-3 !right-3 !left-auto !top-3 !flex !h-[min(92dvh,900px)] !max-h-[92dvh] !w-[min(28rem,calc(100vw-1.5rem))] !max-w-none !translate-x-0 !translate-y-0 flex-col gap-0 overflow-hidden rounded-2xl border border-border/60 bg-background/98 p-0 shadow-2xl data-[state=open]:zoom-in-100 sm:!max-w-none">
                <DialogHeader className="shrink-0 space-y-1 border-b border-border/60 px-5 py-4 text-left">
                  <DialogTitle>大纲抽屉</DialogTitle>
                  <DialogDescription className="text-left text-xs">
                    全书基线 Markdown 与分卷 Arcs；关闭后用左侧树切换卷/章。
                  </DialogDescription>
                </DialogHeader>
                <div className="min-h-0 flex-1 space-y-6 overflow-y-auto px-5 py-4 soft-scroll">
            <div
              id="studio-outline-drawer"
              className="space-y-4"
            >
            <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
              <div className="space-y-1">
                <p className="section-heading text-foreground font-bold">小说概览与创作基线</p>
                <p className="text-sm text-foreground/70 dark:text-muted-foreground font-medium">
                  与左侧结构树配合：此处管全书与分卷 Arcs，主区管当前卷/章。
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
                    ? "在左侧树选卷或章节，主区即切换"
                    : novel?.status === "failed"
                      ? "AI 构思似乎失败了，请尝试重试"
                      : !fwMd && novel?.status === "draft"
                        ? "AI 正在飞速构思，请稍候片刻"
                        : "进入“修改向导”确认大纲"}
                </p>
              </div>
            </div>
            <>
            <div className="relative">
              <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">
                一、基础大纲（世界观 / 人物 / 主线）
              </Label>
              <p className="mt-1 text-xs text-foreground/55 dark:text-muted-foreground">
                不包含分卷 Arcs；分卷剧情见本抽屉下方「分卷 Arcs」。
              </p>
              {!fwMd && (novel?.status === "draft" || novel?.status === "failed") ? (
                <div className="mt-2 flex min-h-[260px] w-full flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-primary/30 bg-primary/5 p-4 text-sm text-primary/70 animate-pulse text-center">
                  {novel?.status === "failed" ? (
                    <>
                      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-destructive/10">
                        <div className="h-4 w-4 rounded-full bg-destructive" />
                      </div>
                      <p className="font-bold text-base text-destructive">AI 构思似乎失败了</p>
                      <p className="text-xs opacity-60 max-w-xs mb-2">如果是大纲 JSON 不完整或输出截断，直接点击下方重新生成即可。</p>
                      <Button 
                        size="sm" 
                        variant="default" 
                        className="font-bold"
                        onClick={() => void runRetryFrameworkGeneration()}
                        disabled={busy}
                      >
                        {busy ? "重新生成中..." : "重新生成大纲"}
                      </Button>
                      <Button 
                        size="sm" 
                        variant="outline" 
                        className="font-bold border-destructive/30 text-destructive hover:bg-destructive/5"
                        onClick={() => setFrameworkWizardOpen(true)}
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
                  onChange={(e) => setFwMd(e.target.value)}
                  className="mt-2 min-h-[260px] w-full rounded-2xl border border-border/70 bg-background/70 p-4 font-mono text-sm text-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.35)]"
                  placeholder="暂无大纲。进入“修改向导”或等待 AI 生成。"
                />
              )}
            </div>
            </>
            <div className="space-y-3 border-t border-border/60 pt-6">
              <div className="space-y-1">
                <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">
                  分卷 Arcs（概览与生成）
                </Label>
                <p className="text-xs text-foreground/55 dark:text-muted-foreground">
                  每卷单独保存；下方可勾选卷并生成/覆盖 Arcs，也可用顶部「完整向导」。续写与章计划会优先读卷上的 outline。
                </p>
              </div>
              {volumes.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-border/70 bg-background/40 p-6 text-sm text-foreground/60">
                  尚未生成卷列表。请关闭抽屉后在主区生成卷列表。
                </div>
              ) : (
                <div className="grid gap-3 md:grid-cols-2">
                  {volumes
                    .slice()
                    .sort((a, b) => a.volume_no - b.volume_no)
                    .map((v) => {
                      const om = (v.outline_markdown || "").trim();
                      const hasArc = om.length > 0;
                      return (
                        <div
                          key={v.id}
                          className="rounded-2xl border border-border/70 bg-background/60 p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.2)]"
                        >
                          <div className="flex items-start justify-between gap-2">
                            <div>
                              <p className="text-xs font-bold uppercase tracking-wide text-foreground/50">
                                第 {v.volume_no} 卷
                              </p>
                              <p className="mt-1 text-base font-bold text-foreground">
                                {v.title || "（未命名）"}
                              </p>
                            </div>
                            <span
                              className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold ${
                                hasArc
                                  ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
                                  : "bg-muted text-muted-foreground"
                              }`}
                            >
                              {hasArc ? "已有 Arcs" : "未生成"}
                            </span>
                          </div>
                          {v.summary ? (
                            <p className="mt-2 text-xs text-foreground/65 line-clamp-3">{v.summary}</p>
                          ) : null}
                          {hasArc ? (
                            <pre className="mt-3 max-h-[200px] overflow-auto whitespace-pre-wrap rounded-xl border border-border/50 bg-background/80 p-3 font-mono text-[11px] leading-relaxed text-foreground/90">
                              {om}
                            </pre>
                          ) : (
                            <p className="mt-3 text-xs text-foreground/50">暂无卷级 Arcs，可在下方选卷生成或使用「完整向导」。</p>
                          )}
                        </div>
                      );
                    })}
                </div>
              )}

              <div className="space-y-3 border-t border-border/50 pt-6">
                <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">
                  生成或覆盖 Arcs
                </Label>
                <p className="text-xs text-foreground/55 dark:text-muted-foreground">
                  需已确认基础大纲。异步生成，选中卷上已有 Arcs 会被覆盖。
                </p>
                {!Boolean(novel?.base_framework_confirmed) ? (
                  <p className="text-xs font-bold text-amber-600 dark:text-amber-400">
                    请先在向导中确认基础大纲，或使用确认按钮。
                  </p>
                ) : null}
                <div className="flex flex-wrap gap-2">
                  {Array.from({ length: totalStudioVolumes }, (_, i) => i + 1).map((volNo) => {
                    const hasOutline = volumes.some(
                      (vv) =>
                        vv.volume_no === volNo && (vv.outline_markdown || "").trim().length > 0
                    );
                    const selected = arcsTargetVolumes.includes(volNo);
                    return (
                      <button
                        key={`arc-vol-${volNo}`}
                        type="button"
                        disabled={arcsBusy || busy}
                        onClick={() =>
                          setArcsTargetVolumes((prev) =>
                            prev.includes(volNo)
                              ? prev.filter((x) => x !== volNo)
                              : [...prev, volNo].sort((a, b) => a - b)
                          )
                        }
                        className={`rounded-xl border px-3 py-1.5 text-xs font-bold transition-colors ${
                          selected
                            ? "border-primary bg-primary text-primary-foreground"
                            : hasOutline
                              ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-800 dark:text-emerald-200"
                              : "border-border/70 bg-background/70 text-foreground/80 hover:bg-muted/40"
                        }`}
                      >
                        第{volNo}卷{hasOutline ? " ✓" : ""}
                      </button>
                    );
                  })}
                </div>
                <Input
                  value={arcsInstruction}
                  onChange={(e) => setArcsInstruction(e.target.value)}
                  placeholder="可选：如「第二卷加强感情线」「第三卷节奏加快」"
                  className="mt-1"
                  disabled={arcsBusy}
                />
                <div className="mt-2 flex flex-wrap gap-2">
                  <Button
                    type="button"
                    size="sm"
                    className="font-bold"
                    disabled={
                      arcsBusy ||
                      busy ||
                      !Boolean(novel?.base_framework_confirmed) ||
                      arcsTargetVolumes.length === 0
                    }
                    onClick={() => void runInlineGenerateArcs()}
                  >
                    {arcsBusy ? "生成中…" : `生成第 ${arcsTargetVolumes.join("、")} 卷 Arcs`}
                  </Button>
                </div>
              </div>
            </div>
            </div>
                </div>
              </DialogContent>
            </Dialog>
            {studioRight === "volume" ? (
            <section
              id="studio-volumes"
              className="glass-panel space-y-4 p-5 md:p-6"
            >
            <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
              <div className="space-y-1">
                <p className="section-heading text-foreground font-bold">卷与章计划</p>
                <p className="text-sm text-foreground/70 dark:text-muted-foreground font-medium">
                  生成卷列表 → 为本卷分批生成章计划 → 在左侧树选章后在主区续写与编辑正文。
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

            {selectedVolume ? (
              <div className="grid gap-4 xl:grid-cols-[1.08fr_0.92fr]">
                <div className="signal-surface story-mesh p-5">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="space-y-2">
                      <span className="glass-chip border-primary/25 bg-primary/10 text-primary">
                        <Sparkles className="size-3.5" />
                        Volume Atlas
                      </span>
                      <h3 className="text-2xl font-semibold tracking-tight text-foreground">
                        第{selectedVolume.volume_no}卷 · {selectedVolume.title}
                      </h3>
                      <p className="max-w-2xl text-sm leading-7 text-foreground/68">
                        {selectedVolume.summary ||
                          "为当前卷生成章节轨道后，这里会显示本卷的节奏分布、缺口与正文覆盖情况。"}
                      </p>
                    </div>
                    <div className="rounded-[1.3rem] border border-border/60 bg-background/70 px-4 py-3 text-right backdrop-blur-xl">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-foreground/50">
                        轨道覆盖
                      </p>
                      <p className="mt-2 text-2xl font-semibold text-foreground">
                        {Math.round(selectedVolumeCoverage * 100)}%
                      </p>
                      <p className="mt-1 text-sm text-foreground/60">
                        第{selectedVolume.from_chapter}—{selectedVolume.to_chapter}章
                      </p>
                    </div>
                  </div>

                  <div className="mt-5 grid gap-3 sm:grid-cols-3">
                    {[
                      ["计划章节", `${volumePlan.length}`, "已生成执行卡"],
                      ["待写正文", `${volumePlanMetrics.pendingWriteCount}`, "默认隐藏已有正文章节"],
                      ["已人工调整", `${volumePlanMetrics.editedCount}`, "说明本卷已经进入精修阶段"],
                    ].map(([label, value, hint]) => (
                      <div key={label} className="rounded-[1.2rem] border border-border/60 bg-background/65 px-4 py-3">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-foreground/50">
                          {label}
                        </p>
                        <p className="mt-2 text-xl font-semibold text-foreground">{value}</p>
                        <p className="mt-1 text-sm text-foreground/60">{hint}</p>
                      </div>
                    ))}
                  </div>

                  <div className="mt-5 rounded-[1.6rem] border border-border/60 bg-background/58 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <GitBranch className="size-4 text-primary" />
                        <p className="text-sm font-semibold text-foreground">章节轨道</p>
                      </div>
                      <span className="status-badge">覆盖 {Math.round(selectedVolumeCoverage * 100)}%</span>
                    </div>

                    <div className="mt-4 grid grid-cols-5 gap-2 sm:grid-cols-8 lg:grid-cols-10">
                      {selectedVolumeSlots.map((slot) => (
                        <div
                          key={`slot-${slot.chapterNo}`}
                          className={`rounded-[1rem] border px-2 py-2 text-center ${
                            slot.hasBody
                              ? "border-accent/30 bg-accent/12"
                              : slot.hasPlan
                                ? "border-primary/25 bg-primary/10"
                                : "border-border/50 bg-background/44"
                          }`}
                        >
                          <div
                            className={`mx-auto h-1.5 w-full rounded-full ${
                              slot.hasBody
                                ? "bg-gradient-to-r from-accent via-primary to-cyan-200"
                                : slot.hasPlan
                                  ? "bg-gradient-to-r from-primary via-accent to-cyan-300"
                                  : "bg-border/60"
                            }`}
                          />
                          <p className="mt-2 text-[11px] font-semibold text-foreground/62">
                            {slot.chapterNo}
                          </p>
                        </div>
                      ))}
                    </div>
                    <div className="mt-4 flex flex-wrap gap-2 text-xs text-foreground/60">
                      <span className="status-badge">亮色已写正文</span>
                      <span className="status-badge">主色仅有计划</span>
                      <span className="status-badge">暗色尚未生成</span>
                    </div>
                  </div>

                  <div className="glass-panel-subtle mt-4 flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm text-foreground/68">
                    <span>
                      {volumePlan.length === 0
                        ? "先生成本卷章计划，让每章目标、冲突和转折先被看见。"
                        : volumePlanView.visible.length === 0
                          ? "当前视图下没有待写章节，可以切换显示已有正文的章节继续复盘。"
                          : `下一步优先处理第 ${volumePlanView.visible[0]?.chapter_no ?? "?"} 章。`}
                    </span>
                    <span className="text-xs text-foreground/56">
                      {selectedVolumeCoverage >= 1
                        ? "本卷计划已铺满"
                        : `还差 ${Math.max(0, selectedVolumeTotalChapters - volumePlan.length)} 章执行卡`}
                    </span>
                  </div>
                </div>
              </div>
            ) : null}

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
                            (() => {
                              const normalized = normalizePlanBeats(p.beats);
                              return (
                            <div
                              key={p.id}
                              className="list-card overflow-hidden p-0 text-xs"
                            >
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
                                      <span className="rounded-full border border-border/70 bg-background/70 px-2 py-0.5 text-[10px] font-semibold text-foreground/55">
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
                                      onClick={() => openPlanEditor(p)}
                                    >
                                      编辑执行卡
                                    </Button>
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
                              </div>

                              <div className="grid gap-4 p-4 xl:grid-cols-[1.12fr_0.88fr]">
                                <div className="space-y-3">
                                  <div className="rounded-[1.4rem] border border-border/60 bg-background/58 p-4">
                                    <div className="flex flex-wrap items-center justify-between gap-2">
                                      <div className="flex items-center gap-2">
                                        <BookOpen className="size-4 text-primary" />
                                        <p className="text-sm font-semibold text-foreground">执行摘要</p>
                                      </div>
                                      {normalized.display_summary.stage_position ? (
                                        <span className="rounded-full border border-border/70 bg-background/74 px-3 py-1 text-[11px] font-semibold text-foreground/58">
                                          {normalized.display_summary.stage_position}
                                        </span>
                                      ) : (
                                        <span className="text-[11px] text-foreground/52">
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
                                          className="grid gap-2 rounded-[1rem] border border-border/55 bg-background/68 px-3 py-3 md:grid-cols-[92px_1fr]"
                                        >
                                          <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-foreground/50">
                                            {label}
                                          </p>
                                          <p
                                            className="text-sm leading-6 text-foreground/82 line-clamp-3"
                                            title={String(value)}
                                          >
                                            {shortenText(String(value), 78)}
                                          </p>
                                        </div>
                                      ))}
                                    </div>

                                    <div className="mt-4 rounded-[1rem] border border-border/55 bg-background/68 px-3 py-3">
                                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-foreground/50">
                                        剧情推进
                                      </p>
                                      <p
                                        className="mt-2 text-sm leading-6 text-foreground/72 line-clamp-4"
                                        title={normalized.display_summary.plot_summary || "暂未生成剧情摘要。"}
                                      >
                                        {normalized.display_summary.plot_summary || "暂未生成剧情摘要。"}
                                      </p>
                                      {normalized.display_summary.pacing_justification ? (
                                        <p
                                          className="mt-2 text-[12px] leading-6 text-foreground/58 line-clamp-3"
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
                                        className="rounded-[1.3rem] border border-border/60 bg-background/55 p-4"
                                      >
                                        <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-foreground/50">
                                          {label}
                                        </p>
                                        <div className="mt-3 flex flex-wrap gap-2">
                                          {items.map((item, index) => (
                                            <span
                                              key={`${p.id}-${label}-${index}`}
                                              className="rounded-full border border-border/70 bg-background/72 px-3 py-1 text-[11px] font-medium text-foreground/74"
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
                                  <div className="rounded-[1.4rem] border border-border/60 bg-background/58 p-4">
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
                                        <p className="mt-2 text-sm leading-6 text-foreground/82">
                                          {normalized.execution_card.ending_hook || "暂无章末钩子。"}
                                        </p>
                                      </div>

                                      {normalized.execution_card.style_guardrails.length > 0 ? (
                                        <div>
                                          <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-foreground/50">
                                            风格护栏
                                          </p>
                                          <div className="mt-2 flex flex-wrap gap-2">
                                            {normalized.execution_card.style_guardrails.map((item, index) => (
                                              <span
                                                key={`${p.id}-guardrail-${index}`}
                                                className="rounded-full border border-border/70 bg-background/72 px-3 py-1 text-[11px] font-medium text-foreground/74"
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
                                                className="rounded-full border border-border/70 bg-background/72 px-3 py-1 text-[11px] font-medium text-foreground/74"
                                              >
                                                {scene.label || scene.goal || `Scene ${index + 1}`}
                                              </span>
                                            ))}
                                          </div>
                                        </div>
                                      ) : null}

                                      {normalized.execution_card.reserved_for_later.length > 0 ||
                                      normalized.execution_card.must_not.length > 0 ? (
                                        <details className="rounded-[1rem] border border-border/55 bg-background/68 px-3 py-3">
                                          <summary className="cursor-pointer text-[11px] font-semibold uppercase tracking-[0.16em] text-foreground/52">
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
                                                      className="rounded-[1rem] border border-border/55 bg-background/68 px-3 py-2 text-sm text-foreground/72"
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
                                                        <p className="mt-1 text-sm leading-6 text-foreground/62">
                                                          {item.reason}
                                                        </p>
                                                      ) : null}
                                                    </div>
                                                  ))}
                                                </div>
                                              </div>
                                            ) : null}

                                            {normalized.execution_card.must_not.length > 0 ? (
                                              <div>
                                                <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-foreground/50">
                                                  禁止项
                                                </p>
                                                <div className="mt-2 flex flex-wrap gap-2">
                                                  {normalized.execution_card.must_not.map((item, index) => (
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

                                      <details className="rounded-[1rem] border border-border/55 bg-background/68 px-3 py-3">
                                        <summary className="cursor-pointer text-[11px] font-semibold uppercase tracking-[0.16em] text-foreground/52">
                                          线性摘要
                                        </summary>
                                        <pre className="mt-3 whitespace-pre-wrap text-[11px] leading-6 text-foreground/64">
                                          {formatVolumePlanBeatsText(p.beats)}
                                        </pre>
                                      </details>
                                    </div>
                                  </div>
                                </div>
                              </div>
                            </div>
                              );
                            })()
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </section>
            </div>
            </section>
            ) : studioRight === "chapter" ? (
            <section
              id="studio-chapters"
              className="glass-panel space-y-4 p-5 md:p-6"
            >
            <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
              <div className="space-y-1">
                <p className="section-heading text-foreground font-bold">章节创作</p>
                <p className="text-sm text-foreground/70 dark:text-muted-foreground font-medium">
                  续写、审定、章节助手与单章编辑；章计划里也可点「生成正文」打开对应章节。
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
                {(() => {
                  const maxGenerateCount = Math.max(1, Number(novel?.target_chapters || 5000));
                  return (
                <input
                  type="number"
                  min={1}
                  max={maxGenerateCount}
                  value={generateCount}
                  onChange={(e) => {
                    const parsed = Number.parseInt(e.target.value, 10);
                    if (!Number.isFinite(parsed)) {
                      setGenerateCount(1);
                      return;
                    }
                    setGenerateCount(Math.max(1, Math.min(maxGenerateCount, Math.round(parsed))));
                  }}
                  className="h-8 w-24 rounded-xl border border-border/70 bg-background px-2.5 text-sm text-foreground font-bold"
                />
                  );
                })()}
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
            
            <div>
              <section className="glass-panel-subtle p-5">
                {!selectedChapter ? (
                  <p className="text-sm text-foreground/50 dark:text-muted-foreground italic font-medium">请在左侧栏选择一章。</p>
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
                            variant="secondary"
                            className="font-bold text-foreground/80"
                            disabled={busy || !editContent.trim()}
                            onClick={() => void runFormatSelectedChapter()}
                            title="纯规则格式化：自动拆段、对白单独成段、场景切换换段，不调用大模型"
                          >
                            一键格式化段落
                          </Button>
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
                              disabled={busy || !(selectedChapter.content || selectedChapter.pending_content)?.trim()}
                              onClick={() => confirmPolishChapter(selectedChapter.id)}
                              title="去除正文中的 AI 味，压缩废话，优化表达，保持剧情不变"
                            >
                              去AI味
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
            </section>
            ) : (
            <section className="glass-panel space-y-5 p-5 md:p-6">
              <div className="space-y-1">
                <p className="section-heading text-foreground font-bold">全书入口</p>
                <p className="text-sm text-foreground/65 dark:text-muted-foreground font-medium">
                  在左侧树选择某一卷可查看章计划与轨道；展开卷后点章节进入正文编辑。需要改世界观/人物/主线或分卷 Arcs 时，用大纲抽屉。
                </p>
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
                  <p className="text-xs text-foreground/60 dark:text-muted-foreground font-bold">分卷</p>
                  <p className="mt-2 text-base font-bold text-foreground">{volumes.length} 卷</p>
                  <p className="mt-1 text-xs text-foreground/50">在树中展开可浏览章节</p>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  className="font-bold"
                  onClick={() => setOutlineDrawerOpen(true)}
                >
                  大纲抽屉
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="font-bold"
                  onClick={() => setFrameworkWizardOpen(true)}
                >
                  完整向导
                </Button>
              </div>
            </section>
            )}
                  </div>
                </div>
              </div>
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
                  {memoryHealth?.latest_chapter_no
                    ? `最近入账第 ${memoryHealth.latest_chapter_no} 章`
                    : memory?.created_at || "刷新后会写入最新快照"}
                </p>
              </div>
              <div className="glass-panel-subtle p-4">
                <p className="text-xs text-muted-foreground">活跃待收束线</p>
                <p className="mt-2 text-xl font-semibold text-foreground">{activeMemoryLines}</p>
                <p className="mt-1 text-xs text-muted-foreground">跟踪跨章节持续生效的问题</p>
              </div>
              <div className="glass-panel-subtle p-4">
                <p className="text-xs text-muted-foreground">风险信号</p>
                <p className="mt-2 text-xl font-semibold text-foreground">
                  {memoryHealth ? `${memoryHealth.stale_plots.length} / ${memoryHealth.overdue_plots.length}` : "-"}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">stale / overdue 线索数量</p>
              </div>
            </div>

            {memoryNorm && memoryVisuals ? (
              <div className="grid gap-4 xl:grid-cols-[1.06fr_0.94fr]">
                <div className="signal-surface story-mesh p-5">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="space-y-2">
                      <span className="glass-chip border-primary/25 bg-primary/10 text-primary">
                        <Sparkles className="size-3.5" />
                        Memory Atlas
                      </span>
                      <h3 className="text-2xl font-semibold tracking-tight text-foreground">
                        把角色、关系和线索放回同一张记忆星图。
                      </h3>
                      <p className="max-w-2xl text-sm leading-7 text-foreground/68">
                        先看谁最活跃、哪条线最危险，再决定要不要往下钻进结构化明细。
                      </p>
                    </div>
                    <div className="rounded-[1.3rem] border border-border/60 bg-background/70 px-4 py-3 text-right backdrop-blur-xl">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-foreground/50">
                        实体总览
                      </p>
                      <p className="mt-2 text-2xl font-semibold text-foreground">
                        {memoryNorm.characters.length + memoryNorm.inventory.length + memoryNorm.skills.length}
                      </p>
                      <p className="mt-1 text-sm text-foreground/60">
                        人物 + 物品 + 技能
                      </p>
                    </div>
                  </div>

                  <div className="mt-5 grid gap-4 lg:grid-cols-[0.98fr_1.02fr]">
                    <div className="relative min-h-[320px] rounded-[1.7rem] border border-border/60 bg-background/58 p-4">
                      <svg
                        viewBox="0 0 100 100"
                        className="pointer-events-none absolute inset-0 h-full w-full"
                        aria-hidden="true"
                      >
                        {MEMORY_ATLAS_POINTS.slice(0, 6).map((point, index) => {
                          const next = MEMORY_ATLAS_POINTS[(index + 1) % 6];
                          return (
                            <line
                              key={`atlas-line-${index}`}
                              x1={point.left}
                              y1={point.top}
                              x2={next.left}
                              y2={next.top}
                              stroke="hsl(var(--primary) / 0.16)"
                              strokeWidth="0.6"
                            />
                          );
                        })}
                        <circle cx="50" cy="50" r="28" fill="none" stroke="hsl(var(--primary) / 0.15)" />
                        <circle cx="50" cy="50" r="18" fill="none" stroke="hsl(var(--accent) / 0.15)" />
                      </svg>

                      {memoryVisuals.topCharacters.map((character, index) => {
                        const point = MEMORY_ATLAS_POINTS[index];
                        const size =
                          62 +
                          Math.round(
                            clamp01(character.influence_score / memoryVisuals.maxInfluence) * 30
                          );

                        return (
                          <div
                            key={`atlas-character-${character.name}-${index}`}
                            className="absolute -translate-x-1/2 -translate-y-1/2 rounded-full border border-border/60 bg-background/82 shadow-[0_18px_40px_rgba(15,23,42,0.14)] backdrop-blur-xl"
                            style={{
                              left: point.left,
                              top: point.top,
                              width: `${size}px`,
                              height: `${size}px`,
                            }}
                          >
                            <div className="flex h-full flex-col items-center justify-center px-3 text-center">
                              <p className="text-xs font-semibold text-foreground">
                                {shortenText(character.name, 9)}
                              </p>
                              <p className="mt-1 text-[10px] text-foreground/58">
                                影响力 {character.influence_score}
                              </p>
                            </div>
                          </div>
                        );
                      })}

                      <div className="absolute bottom-4 left-4 rounded-[1.1rem] border border-border/60 bg-background/76 px-3 py-2 text-xs text-foreground/62 backdrop-blur-xl">
                        活跃人物 {memoryVisuals.activeCharacters} · 活跃物品 {memoryVisuals.activeInventory}
                      </div>
                    </div>

                    <div className="space-y-3">
                      <div className="grid gap-3 sm:grid-cols-3">
                        {[
                          ["人物", `${memoryNorm.characters.length}`, `${memoryVisuals.activeCharacters} 名活跃中`],
                          ["关系", `${memoryNorm.relations.length}`, memoryVisuals.topRelations.length > 0 ? "已提炼人物脉络" : "等待关系沉淀"],
                          ["线索风险", `${memoryVisuals.staleCount + memoryVisuals.overdueCount}`, `${memoryVisuals.staleCount} stale / ${memoryVisuals.overdueCount} overdue`],
                        ].map(([label, value, hint]) => (
                          <div key={label} className="rounded-[1.2rem] border border-border/60 bg-background/64 px-4 py-3">
                            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-foreground/50">
                              {label}
                            </p>
                            <p className="mt-2 text-xl font-semibold text-foreground">{value}</p>
                            <p className="mt-1 text-sm text-foreground/60">{hint}</p>
                          </div>
                        ))}
                      </div>

                      <div className="rounded-[1.4rem] border border-border/60 bg-background/58 p-4">
                        <div className="flex items-center gap-2">
                          <GitBranch className="size-4 text-primary" />
                          <p className="text-sm font-semibold text-foreground">关系脉络</p>
                        </div>
                        {memoryVisuals.topRelations.length > 0 ? (
                          <div className="mt-4 space-y-2">
                            {memoryVisuals.topRelations.map((relation, index) => (
                              <div
                                key={`relation-atlas-${index}-${relation.from}-${relation.to}`}
                                className="rounded-[1.1rem] border border-border/55 bg-background/68 px-3 py-3"
                              >
                                <div className="flex items-center gap-3">
                                  <span className="min-w-0 shrink text-sm font-semibold text-foreground/84">
                                    {relation.from}
                                  </span>
                                  <div className="h-[1px] flex-1 bg-gradient-to-r from-primary via-accent to-cyan-300" />
                                  <span className="min-w-0 shrink text-sm font-semibold text-foreground/84">
                                    {relation.to}
                                  </span>
                                </div>
                                <p className="mt-2 text-sm text-foreground/62">{relation.relation}</p>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className="mt-3 text-sm text-foreground/60">还没有提炼出人物关系。</p>
                        )}
                      </div>
                    </div>
                  </div>
                </div>

                <div className="grid gap-3">
                  <div className="signal-surface p-4">
                    <div className="flex items-center gap-2">
                      <Brain className="size-4 text-primary" />
                      <p className="text-sm font-semibold text-foreground">待收束线雷达</p>
                    </div>
                    {memoryVisuals.topOpenPlots.length > 0 ? (
                      <div className="mt-4 space-y-3">
                        {memoryVisuals.topOpenPlots.map((plot, index) => {
                          const progress =
                            plot.estimated_duration && plot.introduced_chapter != null && plot.last_touched_chapter != null
                              ? clamp01(
                                  (plot.last_touched_chapter - plot.introduced_chapter + 1) /
                                    Math.max(1, plot.estimated_duration)
                                )
                              : clamp01((plot.priority || 0) / 5);
                          return (
                            <div
                              key={`plot-radar-${index}-${plot.body}`}
                              className="rounded-[1.3rem] border border-border/60 bg-background/62 p-4"
                            >
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <span className="rounded-full border border-border/70 bg-background/74 px-3 py-1 text-[11px] font-semibold text-foreground/58">
                                  {plot.plot_type || "Open Plot"}
                                </span>
                                <span className="text-[11px] font-semibold text-foreground/56">
                                  Priority {plot.priority ?? 0}
                                </span>
                              </div>
                              <p className="mt-3 text-sm leading-7 text-foreground/72">
                                {shortenText(formatMemoryPlotLine(plot), 92)}
                              </p>
                              <div className="mt-3 h-2 rounded-full bg-background/70">
                                <div
                                  className="h-full rounded-full bg-gradient-to-r from-primary via-accent to-cyan-300"
                                  style={{ width: `${Math.max(14, Math.round(progress * 100))}%` }}
                                />
                              </div>
                              <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-foreground/56">
                                {plot.introduced_chapter != null ? (
                                  <span>引入于第 {plot.introduced_chapter} 章</span>
                                ) : null}
                                {plot.last_touched_chapter != null ? (
                                  <span>最近触达第 {plot.last_touched_chapter} 章</span>
                                ) : null}
                                {plot.resolve_when ? <span>{plot.resolve_when}</span> : null}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <p className="mt-4 text-sm text-foreground/60">当前没有待收束线。</p>
                    )}
                  </div>
                </div>
              </div>
            ) : null}

            <div className="glass-panel-subtle space-y-3 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm font-medium">结构化记忆（分表）</p>
                <span className="glass-chip px-2.5 py-1 text-[11px]">
                  真源为结构化表
                </span>
              </div>
              <p className="text-[11px] text-muted-foreground">
                审定与刷新会写入结构化表，再派生快照；这里只保留便于排查和人工修正的入口。
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
                    <details className="rounded-[1.4rem] border border-sky-500/30 bg-sky-500/5 p-4">
                      <summary className="cursor-pointer text-[11px] font-semibold uppercase tracking-[0.16em] text-foreground/62">
                        结构化记忆录入规范
                      </summary>
                      <div className="mt-3 grid gap-3 md:grid-cols-2">
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
                    </details>
                  ) : null}
                  {memoryHealth ? (
                    <div className="space-y-3 rounded-[1.4rem] border border-amber-500/30 bg-amber-500/5 p-4">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="font-medium text-foreground">记忆健康检查</p>
                        <span className="text-[11px] text-muted-foreground">
                          最近入账第 {memoryHealth.latest_chapter_no || 0} 章
                        </span>
                      </div>
                      <p className="text-[11px] text-muted-foreground">
                        超期线索 {memoryHealth.overdue_plots.length} 条，已 stale 线索{" "}
                        {memoryHealth.stale_plots.length} 条。
                      </p>
                      {memoryHealth.stale_plots.length > 0 ? (
                        <ul className="space-y-1 text-[11px] text-muted-foreground">
                          {memoryHealth.stale_plots.slice(0, 3).map((plot, idx) => (
                            <li key={`stale-${idx}`}>- {formatMemoryPlotLine(plot)}</li>
                          ))}
                        </ul>
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
                  <div className="glass-panel-subtle space-y-2 p-4">
                    <div className="flex items-center justify-between gap-2">
                      <p className="font-medium text-foreground">技能</p>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-7 text-xs"
                        disabled={busy}
                        onClick={() => void runCreateSkill()}
                      >
                        新增技能
                      </Button>
                    </div>
                    {memoryNorm.skills.length > 0 ? (
                      <>
                        <ul className="space-y-2">
                          {slicePage(
                            memoryNorm.skills,
                            structuredPages.skills ?? 0,
                            STRUCTURED_LIST_PAGE
                          ).map((s, i) => (
                            <li
                              key={`sk-${s.id ?? s.name}-${i}`}
                              className="list-card flex items-center justify-between gap-2 px-3 py-2.5"
                            >
                              <div className="min-w-0 flex-1">
                                <span className="font-medium text-foreground">{s.name}</span>
                                <p className="text-[10px] text-muted-foreground">
                                  影响力 {s.influence_score} · {s.is_active ? "活跃" : "已退场"}
                                  {s.aliases.length
                                    ? ` · 别名 ${s.aliases.slice(0, 3).join(" / ")}`
                                    : ""}
                                </p>
                              </div>
                              <div className="flex items-center gap-1.5">
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="ghost"
                                  className="h-7 text-xs"
                                  disabled={busy}
                                  onClick={() => void runEditSkill(s)}
                                >
                                  编辑
                                </Button>
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="ghost"
                                  className="h-7 text-xs text-destructive hover:text-destructive"
                                  disabled={busy}
                                  onClick={() => void runDeleteSkill(s)}
                                >
                                  删除
                                </Button>
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="outline"
                                  className="h-7 text-xs"
                                  onClick={() => openNormDetail(`技能 · ${s.name}`, s)}
                                >
                                  详情
                                </Button>
                              </div>
                            </li>
                          ))}
                        </ul>
                        {normPager("skills", memoryNorm.skills.length, STRUCTURED_LIST_PAGE)}
                      </>
                    ) : (
                      <p className="text-xs text-muted-foreground">暂无技能，点击右上角新增。</p>
                    )}
                  </div>
                  <div className="glass-panel-subtle space-y-2 p-4">
                    <div className="flex items-center justify-between gap-2">
                      <p className="font-medium text-foreground">物品</p>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-7 text-xs"
                        disabled={busy}
                        onClick={() => void runCreateItem()}
                      >
                        新增物品
                      </Button>
                    </div>
                    {memoryNorm.inventory.length > 0 ? (
                      <>
                        <ul className="space-y-2">
                          {slicePage(
                            memoryNorm.inventory,
                            structuredPages.inventory ?? 0,
                            STRUCTURED_LIST_PAGE
                          ).map((it, i) => (
                            <li
                              key={`inv-${it.id ?? it.label}-${i}`}
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
                                  {it.aliases.length
                                    ? ` · 别名 ${it.aliases.slice(0, 3).join(" / ")}`
                                    : ""}
                                </p>
                              </div>
                              <div className="flex items-center gap-1.5">
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="ghost"
                                  className="h-7 text-xs"
                                  disabled={busy}
                                  onClick={() => void runEditItem(it)}
                                >
                                  编辑
                                </Button>
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="ghost"
                                  className="h-7 text-xs text-destructive hover:text-destructive"
                                  disabled={busy}
                                  onClick={() => void runDeleteItem(it)}
                                >
                                  删除
                                </Button>
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="outline"
                                  className="h-7 text-xs"
                                  onClick={() =>
                                    openNormDetail(`物品 · ${inventoryDisplayLabel(it)}`, it)
                                  }
                                >
                                  详情
                                </Button>
                              </div>
                            </li>
                          ))}
                        </ul>
                        {normPager(
                          "inventory",
                          memoryNorm.inventory.length,
                          STRUCTURED_LIST_PAGE
                        )}
                      </>
                    ) : (
                      <p className="text-xs text-muted-foreground">暂无物品，点击右上角新增。</p>
                    )}
                  </div>
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
                  <div className="glass-panel-subtle space-y-2 p-4">
                      <div className="flex items-center justify-between gap-2">
                        <p className="font-medium text-foreground">人物</p>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="h-7 text-xs"
                          disabled={busy}
                          onClick={() => void runCreateCharacter()}
                        >
                          新增人物
                        </Button>
                      </div>
                      {memoryNorm.characters.length > 0 ? (
                        <>
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
                                <div className="flex items-center gap-1.5">
                                  <Button
                                    type="button"
                                    size="sm"
                                    variant="ghost"
                                    className="h-7 text-xs"
                                    disabled={busy}
                                    onClick={() => void runEditCharacter(c)}
                                  >
                                    编辑
                                  </Button>
                                  <Button
                                    type="button"
                                    size="sm"
                                    variant="ghost"
                                    className="h-7 text-xs text-destructive hover:text-destructive"
                                    disabled={busy}
                                    onClick={() => void runDeleteCharacter(c)}
                                  >
                                    下线
                                  </Button>
                                  <Button
                                    type="button"
                                    size="sm"
                                    variant="outline"
                                    className="h-7 shrink-0 text-xs"
                                    onClick={() => openNormDetail(`人物 · ${c.name}`, c)}
                                  >
                                    详情
                                  </Button>
                                </div>
                              </li>
                            ))}
                          </ul>
                          {normPager(
                            "characters",
                            memoryNorm.characters.length,
                            STRUCTURED_LIST_PAGE
                          )}
                        </>
                      ) : (
                        <p className="text-xs text-muted-foreground">暂无人物，点击右上角新增。</p>
                      )}
                    </div>
                  <div className="glass-panel-subtle space-y-2 p-4">
                      <div className="flex items-center justify-between gap-2">
                        <p className="font-medium text-foreground">人物关系</p>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="h-7 text-xs"
                          disabled={busy}
                          onClick={() => void runCreateRelation()}
                        >
                          新增关系
                        </Button>
                      </div>
                      {memoryNorm.relations.length > 0 ? (
                        <>
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
                                <div className="min-w-0 flex-1">
                                  <span className="line-clamp-2 block break-words text-muted-foreground">
                                    {r.from} → {r.to}：{r.relation}
                                  </span>
                                  <p className="text-[10px] text-muted-foreground">
                                    {r.is_active === false ? "已失效" : "生效中"}
                                  </p>
                                </div>
                                <div className="flex items-center gap-1.5">
                                  <Button
                                    type="button"
                                    size="sm"
                                    variant="ghost"
                                    className="h-7 text-xs"
                                    disabled={busy}
                                    onClick={() => void runEditRelation(r)}
                                  >
                                    编辑
                                  </Button>
                                  <Button
                                    type="button"
                                    size="sm"
                                    variant="ghost"
                                    className="h-7 text-xs text-destructive hover:text-destructive"
                                    disabled={busy}
                                    onClick={() => void runDeleteRelation(r)}
                                  >
                                    失效
                                  </Button>
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
                                </div>
                              </li>
                            ))}
                          </ul>
                          {normPager(
                            "relations",
                            memoryNorm.relations.length,
                            STRUCTURED_LIST_PAGE
                          )}
                        </>
                      ) : (
                        <p className="text-xs text-muted-foreground">暂无关系，点击右上角新增。</p>
                      )}
                    </div>
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
            {activeTab === "studio"
              ? selectedChapter
                ? `正在编辑第 ${selectedChapter.chapter_no} 章 · 左侧树可换章`
                : selectedVolumeId
                  ? "已选卷 · 左侧树展开可点章节"
                  : frameworkConfirmed
                    ? "点左侧树选卷/章；大纲在抽屉"
                    : "先确认框架，再生成卷与章节"
              : approvedChapterCount > 0
                ? "章节审定后建议到「记忆」页刷新"
                : "尚无已审定章节，记忆刷新暂不可用"}
          </p>

          {activeTab === "studio" ? (
            selectedChapter ? (
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Button
                  type="button"
                  variant="outline"
                  className="font-semibold"
                  disabled={busy || !editContent.trim()}
                  onClick={() => void runSaveSelectedChapter()}
                >
                  保存
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  className="font-semibold"
                  disabled={busy || !editContent.trim()}
                  onClick={() => void runFormatSelectedChapter()}
                >
                  格式化
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
                  目录
                </Button>
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-2">
                <Button
                  type="button"
                  variant="outline"
                  className="font-semibold"
                  disabled={busy || volumeBusy}
                  onClick={() => confirmGenerateVolumes()}
                >
                  生成卷
                </Button>
                <Button
                  type="button"
                  className="font-bold"
                  disabled={busy || volumeBusy || !selectedVolumeId}
                  onClick={() => confirmGenerateVolumePlan(false)}
                >
                  下一批计划
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  className="font-bold"
                  disabled={busy || !frameworkConfirmed}
                  onClick={() => confirmGenerateChapters()}
                >
                  自动续写
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  className="font-semibold"
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
        <DialogContent className="max-h-[85vh] max-w-md overflow-hidden">
          <DialogHeader>
            <DialogTitle className="text-xl font-bold">小说设置</DialogTitle>
            <DialogDescription className="text-foreground/80 dark:text-muted-foreground font-medium">
              配置当前小说的总章节数和每日自动撰写计划。
            </DialogDescription>
          </DialogHeader>
          <div className="max-h-[calc(85vh-9rem)] space-y-4 overflow-y-auto py-4 pr-2">
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
                min={300}
                max={10000}
                step={1}
                value={novelSettingsDraft.chapter_target_words}
                onChange={(e) => setNovelSettingsDraft({ ...novelSettingsDraft, chapter_target_words: Number(e.target.value) })}
                className="field-shell text-foreground font-bold"
              />
              <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium italic">提示词会强力要求正文紧贴目标字数，只允许轻微浮动。当前默认规则为上下约 5%，至少 30 字、最多 150 字。</p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="auto_consistency_check" className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">
                生成前一致性修订
              </Label>
              <label
                htmlFor="auto_consistency_check"
                className="flex cursor-pointer items-start gap-3 rounded-xl border border-border/70 bg-muted/30 px-3 py-3"
              >
                <input
                  id="auto_consistency_check"
                  type="checkbox"
                  checked={novelSettingsDraft.auto_consistency_check}
                  onChange={(e) =>
                    setNovelSettingsDraft({
                      ...novelSettingsDraft,
                      auto_consistency_check: e.target.checked,
                    })
                  }
                  className="mt-0.5 h-4 w-4"
                />
                <div className="space-y-1">
                  <p className="text-sm font-semibold text-foreground">生成正文后，追加一次一致性修订</p>
                  <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium italic">
                    默认关闭。开启后会多一次 LLM 调用，速度更慢，但会先做一轮通顺性与设定衔接修订。
                  </p>
                </div>
              </label>
            </div>
            <div className="space-y-2">
              <Label htmlFor="auto_plan_guard_check" className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">
                执行卡硬校验
              </Label>
              <label
                htmlFor="auto_plan_guard_check"
                className="flex cursor-pointer items-start gap-3 rounded-xl border border-border/70 bg-muted/30 px-3 py-3"
              >
                <input
                  id="auto_plan_guard_check"
                  type="checkbox"
                  checked={novelSettingsDraft.auto_plan_guard_check}
                  onChange={(e) =>
                    setNovelSettingsDraft({
                      ...novelSettingsDraft,
                      auto_plan_guard_check: e.target.checked,
                      auto_plan_guard_fix: e.target.checked
                        ? novelSettingsDraft.auto_plan_guard_fix
                        : false,
                    })
                  }
                  className="mt-0.5 h-4 w-4"
                />
                <div className="space-y-1">
                  <p className="text-sm font-semibold text-foreground">生成正文初稿后，按执行卡做一次硬校验</p>
                  <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium italic">
                    默认关闭。开启后会额外消耗一次 LLM 调用；若同时未开启纠偏，校验失败会直接终止当前批次。
                  </p>
                </div>
              </label>
            </div>
            <div className="space-y-2">
              <Label htmlFor="auto_plan_guard_fix" className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">
                执行卡纠偏
              </Label>
              <label
                htmlFor="auto_plan_guard_fix"
                className="flex cursor-pointer items-start gap-3 rounded-xl border border-border/70 bg-muted/30 px-3 py-3"
              >
                <input
                  id="auto_plan_guard_fix"
                  type="checkbox"
                  checked={novelSettingsDraft.auto_plan_guard_fix}
                  onChange={(e) =>
                    setNovelSettingsDraft({
                      ...novelSettingsDraft,
                      auto_plan_guard_fix: e.target.checked,
                      auto_plan_guard_check: e.target.checked
                        ? true
                        : novelSettingsDraft.auto_plan_guard_check,
                    })
                  }
                  className="mt-0.5 h-4 w-4"
                />
                <div className="space-y-1">
                  <p className="text-sm font-semibold text-foreground">硬校验失败时，自动按执行卡重写纠偏</p>
                  <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium italic">
                    默认关闭。开启后会自动联动硬校验，并在失败时追加一次纠偏调用，进一步增加耗时与 token。
                  </p>
                </div>
              </label>
            </div>
            <div className="space-y-2">
              <Label htmlFor="auto_style_polish" className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">
                AI 润色
              </Label>
              <label
                htmlFor="auto_style_polish"
                className="flex cursor-pointer items-start gap-3 rounded-xl border border-border/70 bg-muted/30 px-3 py-3"
              >
                <input
                  id="auto_style_polish"
                  type="checkbox"
                  checked={novelSettingsDraft.auto_style_polish}
                  onChange={(e) =>
                    setNovelSettingsDraft({
                      ...novelSettingsDraft,
                      auto_style_polish: e.target.checked,
                    })
                  }
                  className="mt-0.5 h-4 w-4"
                />
                <div className="space-y-1">
                  <p className="text-sm font-semibold text-foreground">保存前追加一次去 AI 味风格润色</p>
                  <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium italic">
                    默认关闭。开启后会在正文初稿完成后再做一轮风格整理，速度更慢但文面更细。
                  </p>
                </div>
              </label>
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

      <Dialog open={planEditorOpen} onOpenChange={setPlanEditorOpen}>
        <DialogContent className="max-h-[90vh] max-w-3xl overflow-hidden text-foreground">
          <DialogHeader>
            <DialogTitle>
              编辑执行卡
              {planEditorChapterNo != null ? ` · 第${planEditorChapterNo}章` : ""}
            </DialogTitle>
            <DialogDescription>
              这里修改的是当前章计划的执行卡。保存后会覆盖本章计划内容，但仍兼容旧版计划结构和正文生成链路。
            </DialogDescription>
          </DialogHeader>
          <div className="soft-scroll max-h-[62vh] space-y-4 overflow-y-auto pr-1">
            <div className="space-y-2">
              <Label>章节标题</Label>
              <Input
                value={planEditorTitle}
                onChange={(e) => setPlanEditorTitle(e.target.value)}
                placeholder="例如：暗潮初显"
              />
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label>本章目标</Label>
                <textarea
                  value={planEditorGoal}
                  onChange={(e) => setPlanEditorGoal(e.target.value)}
                  className="field-shell-textarea min-h-[110px] text-sm"
                  placeholder="这一章必须完成的核心目标"
                />
              </div>
              <div className="space-y-2">
                <Label>核心冲突</Label>
                <textarea
                  value={planEditorConflict}
                  onChange={(e) => setPlanEditorConflict(e.target.value)}
                  className="field-shell-textarea min-h-[110px] text-sm"
                  placeholder="这一章最主要的对抗、阻碍或张力"
                />
              </div>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label>关键转折</Label>
                <textarea
                  value={planEditorTurn}
                  onChange={(e) => setPlanEditorTurn(e.target.value)}
                  className="field-shell-textarea min-h-[104px] text-sm"
                  placeholder="本章中段或后段发生的关键变化"
                />
              </div>
              <div className="space-y-2">
                <Label>章末钩子</Label>
                <textarea
                  value={planEditorEndingHook}
                  onChange={(e) => setPlanEditorEndingHook(e.target.value)}
                  className="field-shell-textarea min-h-[104px] text-sm"
                  placeholder="下一章必须自然承接的钩子"
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label>剧情梗概</Label>
              <textarea
                value={planEditorPlotSummary}
                onChange={(e) => setPlanEditorPlotSummary(e.target.value)}
                className="field-shell-textarea min-h-[140px] text-sm"
                placeholder="用 5-12 句写清楚本章实际会发生什么"
              />
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label>阶段位置</Label>
                <textarea
                  value={planEditorStagePosition}
                  onChange={(e) => setPlanEditorStagePosition(e.target.value)}
                  className="field-shell-textarea min-h-[96px] text-sm"
                  placeholder="例如：第一弧 35%，本卷仍在蓄势"
                />
              </div>
              <div className="space-y-2">
                <Label>节奏说明</Label>
                <textarea
                  value={planEditorPacing}
                  onChange={(e) => setPlanEditorPacing(e.target.value)}
                  className="field-shell-textarea min-h-[96px] text-sm"
                  placeholder="说明为什么这一章不应越级推进"
                />
              </div>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label>必须发生</Label>
                <textarea
                  value={planEditorMustHappen}
                  onChange={(e) => setPlanEditorMustHappen(e.target.value)}
                  className="field-shell-textarea min-h-[120px] text-sm"
                  placeholder={"每行一条\n例如：主角确认账册中的异常签名"}
                />
              </div>
              <div className="space-y-2">
                <Label>必须承接</Label>
                <textarea
                  value={planEditorCallbacks}
                  onChange={(e) => setPlanEditorCallbacks(e.target.value)}
                  className="field-shell-textarea min-h-[120px] text-sm"
                  placeholder={"每行一条\n例如：承接上一章雨夜仓库的未解释异响"}
                />
              </div>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label>允许推进</Label>
                <textarea
                  value={planEditorAllowedProgress}
                  onChange={(e) => setPlanEditorAllowedProgress(e.target.value)}
                  className="field-shell-textarea min-h-[120px] text-sm"
                  placeholder={"每行一条\n例如：只允许确认身份可疑，不允许直接揭穿"}
                />
              </div>
              <div className="space-y-2">
                <Label>绝对禁止</Label>
                <textarea
                  value={planEditorMustNot}
                  onChange={(e) => setPlanEditorMustNot(e.target.value)}
                  className="field-shell-textarea min-h-[120px] text-sm"
                  placeholder={"每行一条\n例如：不能让配角知道主角真实能力"}
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label>延后解锁</Label>
              <textarea
                value={planEditorReserved}
                onChange={(e) => setPlanEditorReserved(e.target.value)}
                className="field-shell-textarea min-h-[120px] text-sm"
                placeholder={"每行一条，格式：条目 | 最早章节 | 原因\n例如：玉佩真名 | 18 | 需要等祠堂线揭开"}
              />
            </div>
            <div className="space-y-2">
              <Label>风格护栏</Label>
              <textarea
                value={planEditorStyleGuardrails}
                onChange={(e) => setPlanEditorStyleGuardrails(e.target.value)}
                className="field-shell-textarea min-h-[120px] text-sm"
                placeholder={"每行一条\n例如：减少解释腔，改为动作和对话落地"}
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setPlanEditorOpen(false)}
              disabled={planEditorSaving}
            >
              取消
            </Button>
            <Button
              type="button"
              onClick={() => void savePlanEditor()}
              disabled={planEditorSaving || planEditorChapterNo == null}
            >
              {planEditorSaving ? "保存中..." : "保存执行卡"}
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
