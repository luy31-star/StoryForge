import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  Brain,
  GitBranch,
  Sparkles,
  X,
} from "lucide-react";
import { LlmActionConfirmDialog } from "@/components/LlmActionConfirmDialog";
import { FrameworkWizardDialog } from "@/components/FrameworkWizardDialog";
import { WritingStyleSelect } from "@/components/WritingStyleSelect";
import { Button } from "@/components/ui/button";
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
  regenerateFramework,
  formatChapter,
  generateChapters,
  autoGenerateChapters,
  generateArcs,
  generateVolumeChapterPlan,
  getMemory,
  getMemoryNormalized,
  getMemoryHistory,
  clearMemory,
  getNovelQueueStatus,
  rollbackMemory,
  rebuildMemoryNormalized,
  formatMemoryPlotLine,
  getLatestChapterJudge,
  getLatestStoryBibleSnapshot,
  getLatestWorkflowRun,
  getNovelCoreEvaluation,
  type MemoryHealth,
  type MemoryDiffSummary,
  type MemorySchemaGuide,
  type MemoryUpdateRun,
  listRetrievalLogs,
  listMemoryUpdateRuns,
  listGenerationLogs,
  type NormalizedMemoryPayload,
  type NovelRetrievalLogItem,
  type NovelWorkflowLatest,
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
  getRetrievalIndexSnapshot,
  regenerateChapterPlan,
  retryChapterMemory,
  reviseChapter,
  type ChapterJudgeLatest,
  type ChapterPlanReservedItem,
  type ChapterPlanV2Beats,
  waitForChapterConsistencyBatch,
  waitForChapterGenerationBatch,
  waitForChapterPolishBatch,
  waitForChapterReviseBatch,
  waitForArcsGenerateBatch,
  waitForFrameworkGenerateBatch,
  waitForFrameworkRegenerateBatch,
  waitForMemoryRefreshBatch,
  waitForVolumePlanBatch,
} from "@/services/novelApi";
import { ensureLlmReady } from "@/services/llmReady";
// Extracted workspace components
import { NovelSettingsDialog } from "@/components/workspace/NovelSettingsDialog";
import { MemoryEditorDialog } from "@/components/workspace/MemoryEditorDialog";
import { NormDetailDialog } from "@/components/workspace/NormDetailDialog";
import { PlanEditorDialog } from "@/components/workspace/PlanEditorDialog";
import { GenerationLogsDialog } from "@/components/workspace/GenerationLogsDialog";
import { ChapterChatDialog } from "@/components/workspace/ChapterChatDialog";
import { HistoryDialog } from "@/components/workspace/HistoryDialog";
import { RefreshRangeDialog } from "@/components/workspace/RefreshRangeDialog";
import { ExportDialog } from "@/components/workspace/ExportDialog";
import { WorkspaceHeader } from "@/components/workspace/WorkspaceHeader";
import { StudioToolbar } from "@/components/workspace/StudioToolbar";
import { ChapterTreeSidebar } from "@/components/workspace/ChapterTreeSidebar";
import { FocusMode } from "@/components/workspace/FocusMode";
import { OutlineDrawerDialog } from "@/components/workspace/OutlineDrawerDialog";
import { VolumePlanSection } from "@/components/workspace/VolumePlanSection";
import { ChapterContentSection } from "@/components/workspace/ChapterContentSection";

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

/** 后端 naive UTC 的 isoformat() 无时区；浏览器会当成本地时间。无尾部 Z/偏移时按 UTC 解析。 */
function parseBackendUtcIso(iso: string): Date {
  const s = iso.trim();
  if (!s) return new Date(NaN);
  if (/[zZ]$/.test(s)) return new Date(s);
  if (/[+-]\d{2}:\d{2}$/.test(s) || /[+-]\d{4}$/.test(s)) return new Date(s);
  const normalized = s.includes("T") ? s : s.replace(" ", "T");
  return new Date(`${normalized}Z`);
}

function formatDateTimeLabel(value?: string | null): string {
  if (!value) return "暂无";
  const date = parseBackendUtcIso(value);
  if (Number.isNaN(date.getTime())) return "暂无";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Asia/Shanghai",
  }).format(date);
}

function diffChangedTypes(diff?: MemoryDiffSummary | null): string[] {
  const list = diff?.summary?.changed_types;
  return Array.isArray(list) ? list.map((item) => String(item)) : [];
}

function diffChangeCount(diff?: MemoryDiffSummary | null): number {
  return Number(diff?.summary?.change_count ?? 0) || 0;
}

function diffChapterNos(diff?: MemoryDiffSummary | null): number[] {
  const list = diff?.summary?.chapter_nos;
  return Array.isArray(list)
    ? list.map((item) => Number(item)).filter((item) => Number.isFinite(item) && item > 0)
    : [];
}

function memoryRunStatusTone(status?: string): string {
  switch (status) {
    case "ok":
      return "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300";
    case "warning":
      return "border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-300";
    case "blocked":
    case "failed":
      return "border-rose-500/25 bg-rose-500/10 text-rose-700 dark:text-rose-300";
    case "running":
    case "queued":
      return "border-sky-500/25 bg-sky-500/10 text-sky-700 dark:text-sky-300";
    default:
      return "border-border bg-background text-foreground/60";
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

function plotBodyFromItem(item: unknown): string {
  if (typeof item === "string") return item.trim();
  if (item && typeof item === "object" && "body" in item) {
    const body = (item as { body?: unknown }).body;
    return typeof body === "string" ? body.trim() : "";
  }
  return "";
}

function summarizeDetail(detail: Record<string, unknown> | null | undefined, max = 48): string {
  if (!detail || typeof detail !== "object") return "";
  const preferredKeys = [
    "summary",
    "description",
    "effect",
    "usage",
    "status",
    "remark",
    "note",
    "current_stage",
  ];
  for (const key of preferredKeys) {
    const value = detail[key];
    if (typeof value === "string" && value.trim()) {
      return shortenText(value, max);
    }
  }
  for (const value of Object.values(detail)) {
    if (typeof value === "string" && value.trim()) {
      return shortenText(value, max);
    }
  }
  return "";
}

function detailText(detail: Record<string, unknown> | null | undefined): string {
  if (!detail || typeof detail !== "object") return "";
  return Object.values(detail)
    .map((value) => (typeof value === "string" ? value.trim() : ""))
    .filter(Boolean)
    .join(" ");
}

function includesAnyKeyword(text: string, keywords: string[]): boolean {
  return keywords.some((keyword) => text.includes(keyword));
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

type MemoryEditorState = {
  kind: "character" | "relation" | "skill" | "item";
  mode: "create" | "edit" | "delete";
  id?: string;
  title: string;
  subtitle: string;
  confirmLabel: string;
  name: string;
  role: string;
  status: string;
  traits: string;
  from: string;
  to: string;
  relation: string;
  label: string;
  owner: string;
  description: string;
  influence: string;
  isActive: boolean;
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
  /** 左侧结构树整条侧栏收起，给主区更多空间 */
  const [studioTreeSidebarCollapsed, setStudioTreeSidebarCollapsed] = useState(false);
  const [focusModeOpen, setFocusModeOpen] = useState(false);
  /** 卷下章节树是否展开 */
  const [expandedVolumeIds, setExpandedVolumeIds] = useState<Record<string, boolean>>({});
  /** 结构树内：展开查看某卷剧情（与章节列表独立） */
  const [treeVolumePlotOpenId, setTreeVolumePlotOpenId] = useState<string | null>(
    null
  );
  const [fbDraft, setFbDraft] = useState<Record<string, string>>({});
  const [revisePrompt, setRevisePrompt] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const [notice, setNotice] = useState<React.ReactNode | null>(null);

  const setTaskNotice = useCallback((msg: string) => {
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
  }, [navigate]);
  const [busy, setBusy] = useState(false);
  const [queueStatus, setQueueStatus] = useState<{
    active_auto_pipeline_count: number;
    max_active_auto_pipeline: number;
    available_auto_pipeline_slots: number;
    is_busy: boolean;
  } | null>(null);
  const [queueStatusLoading, setQueueStatusLoading] = useState(false);
  const [generateCount, setGenerateCount] = useState(1);
  const [generateCountTouched, setGenerateCountTouched] = useState(false);
  const [useColdRecall] = useState<boolean | null>(null);
  const [coldRecallItems] = useState(5);
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
    currentVersion: number;
    errors: string[];
    warnings: string[];
    autoPassNotes: string[];
    candidateJson: string;
    candidateReadableZh: string;
    confirmationToken?: string | null;
    diffSummary?: MemoryDiffSummary;
    runId?: string | null;
    applied?: boolean;
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
  const [latestWorkflow, setLatestWorkflow] = useState<NovelWorkflowLatest | null>(null);
  const [memoryUpdateRuns, setMemoryUpdateRuns] = useState<MemoryUpdateRun[]>([]);
  const [storyBibleSnapshot, setStoryBibleSnapshot] = useState<Awaited<
    ReturnType<typeof getLatestStoryBibleSnapshot>
  >["item"] | null>(null);
  const [retrievalIndexDocs, setRetrievalIndexDocs] = useState<
    Awaited<ReturnType<typeof getRetrievalIndexSnapshot>>["items"]
  >([]);
  const [retrievalLogs, setRetrievalLogs] = useState<NovelRetrievalLogItem[]>([]);
  const [coreEvaluation, setCoreEvaluation] = useState<
    Awaited<ReturnType<typeof getNovelCoreEvaluation>> | null
  >(null);
  const [chapterJudge, setChapterJudge] = useState<ChapterJudgeLatest | null>(null);
  const [intelWorkflowLoading, setIntelWorkflowLoading] = useState(false);
  const [intelRetrievalLoading, setIntelRetrievalLoading] = useState(false);
  const [intelJudgeLoading, setIntelJudgeLoading] = useState(false);
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
  /** 分卷剧情区：当前选中的卷号（1-based），与下方卷按钮单选一致 */
  const [arcsPanelVolumeNo, setArcsPanelVolumeNo] = useState(1);
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
      diff_summary?: MemoryDiffSummary;
      source_summary?: {
        chapter_nos?: number[];
        latest_chapter_no?: number | null;
        changed_types?: string[];
      };
    }[]
  >([]);
  const [historyDialogOpen, setHistoryDialogOpen] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [titleBusy, setTitleBusy] = useState(false);
  const [llmConfirm, setLlmConfirm] = useState<LlmConfirmState | null>(null);
  const [llmConfirmBusy, setLlmConfirmBusy] = useState(false);
  const llmConfirmActionRef = useRef<null | (() => Promise<void>)>(null);
  const [memoryEditor, setMemoryEditor] = useState<MemoryEditorState | null>(null);
  const [memoryEditorBusy, setMemoryEditorBusy] = useState(false);

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
    framework_model: "",
    plan_model: "",
    chapter_model: "",
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
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "导出失败");
    } finally {
      setExportBusy(false);
    }
  }

  const reloadQueueStatus = useCallback(async () => {
    setQueueStatusLoading(true);
    try {
      const status = await getNovelQueueStatus();
      setQueueStatus(status);
    } catch {
      setQueueStatus(null);
    } finally {
      setQueueStatusLoading(false);
    }
  }, []);

  useEffect(() => {
    void reloadQueueStatus();
    const timer = window.setInterval(() => {
      void reloadQueueStatus();
    }, 15000);
    return () => window.clearInterval(timer);
  }, [reloadQueueStatus]);


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
      framework_model: String(novel.framework_model || ""),
      plan_model: String(novel.plan_model || ""),
      chapter_model: String(novel.chapter_model || ""),
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
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "保存小说设置失败");
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
    setIntelWorkflowLoading(true);
    setIntelRetrievalLoading(true);
    try {
      const [
        n,
        c,
        m,
        mn,
        workflowRes,
        retrievalRes,
        evalRes,
        updateRunsRes,
        storyBibleRes,
        retrievalIndexRes,
      ] = await Promise.all([
        getNovel(id),
        listChapters(id),
        getMemory(id),
        getMemoryNormalized(id).catch(() => ({ status: "empty" as const, data: null })),
        getLatestWorkflowRun(id).catch(() => ({ status: "ok" as const, item: null })),
        listRetrievalLogs(id, 6).catch(() => ({ status: "ok" as const, items: [] })),
        getNovelCoreEvaluation(id).catch(() => null),
        listMemoryUpdateRuns(id, 12).catch(() => ({ status: "ok" as const, items: [] })),
        getLatestStoryBibleSnapshot(id, { entityLimit: 16, factLimit: 16 }).catch(() => ({
          status: "ok" as const,
          item: null,
        })),
        getRetrievalIndexSnapshot(id, 16).catch(() => ({ status: "ok" as const, items: [] })),
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
      setLatestWorkflow(workflowRes.item ?? null);
      setMemoryUpdateRuns(updateRunsRes.items ?? []);
      setStoryBibleSnapshot(storyBibleRes.item ?? null);
      setRetrievalIndexDocs(retrievalIndexRes.items ?? []);
      setRetrievalLogs(retrievalRes.items ?? []);
      setCoreEvaluation(evalRes);
    } finally {
      setIntelWorkflowLoading(false);
      setIntelRetrievalLoading(false);
    }
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

  useEffect(() => {
    setArcsPanelVolumeNo((n) => Math.min(Math.max(1, n), totalStudioVolumes));
  }, [totalStudioVolumes]);

  const runInlineGenerateArcs = useCallback(async () => {
    if (!id) return;
    if (!novel?.base_framework_confirmed) {
      setErr("请先确认基础大纲，再为各卷生成分卷剧情。");
      return;
    }
    setArcsBusy(true);
    setErr(null);
    try {
      await ensureLlmReady();
      const r = await generateArcs(id, {
        target_volume_nos: [arcsPanelVolumeNo],
        instruction: arcsInstruction.trim(),
      });
      if (r.status === "queued" && r.batch_id) {
        setTaskNotice("正在生成分卷剧情…");
        const o = await waitForArcsGenerateBatch(id, r.batch_id);
        if (o === "failed") throw new Error("分卷剧情生成失败，请查看生成记录。");
      }
      setNotice("分卷剧情已更新。");
      await reloadVolumes();
      await reload();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "分卷剧情生成失败");
    } finally {
      setArcsBusy(false);
    }
  }, [
    id,
    novel?.base_framework_confirmed,
    arcsPanelVolumeNo,
    arcsInstruction,
    reload,
    reloadVolumes,
    setTaskNotice,
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
  const queueActiveCount = queueStatus?.active_auto_pipeline_count ?? 0;
  const queueMaxActive = queueStatus?.max_active_auto_pipeline ?? 0;
  const queueSlots = queueStatus?.available_auto_pipeline_slots ?? 0;
  const queueBusy = Boolean(queueStatus?.is_busy);
  const queueLabel = queueStatusLoading && !queueStatus
    ? "读取队列中…"
    : queueActiveCount > 0
      ? `前方排队 ${queueActiveCount} 个任务`
      : "生成队列空闲";
  const queueHint = queueStatus
    ? queueBusy
      ? `已达并发上限 ${queueMaxActive}，建议稍后再发起。`
      : `可用生成槽 ${queueSlots}/${queueMaxActive || "?"}`
    : "队列状态暂不可用";

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
    if (!selectedChapter?.id) {
      setChapterJudge(null);
      setIntelJudgeLoading(false);
      return;
    }
    setIntelJudgeLoading(true);
    getLatestChapterJudge(selectedChapter.id)
      .then((res) => setChapterJudge(res.item ?? null))
      .catch(() => setChapterJudge(null))
      .finally(() => setIntelJudgeLoading(false));
  }, [selectedChapter?.id, selectedChapter?.status, selectedChapter?.pending_content]);

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

  const approvedChapterCount = chapters.filter(
    (chapter) => chapter.status === "approved"
  ).length;
  const draftChapterCount = Math.max(0, chapters.length - approvedChapterCount);
  const latestChapterNo = chapters.length
    ? Math.max(...chapters.map((chapter) => chapter.chapter_no))
    : 0;
  const maxGenerateCount = Math.max(1, Number(novel?.target_chapters || 5000));
  const remainingGenerateCount = Math.max(1, maxGenerateCount - latestChapterNo);
  const activeMemoryLines = memoryNorm?.open_plots.length ?? openPlotsLines.length;

  useEffect(() => {
    setGenerateCountTouched(false);
  }, [novel?.id]);

  useEffect(() => {
    if (generateCountTouched) return;
    setGenerateCount(remainingGenerateCount);
  }, [generateCountTouched, remainingGenerateCount]);

  const memoryVisuals = useMemo(() => {
    if (!memoryNorm) return null;

    const topCharacters = [...memoryNorm.characters]
      .sort((a, b) => b.influence_score - a.influence_score)
      .slice(0, MEMORY_ATLAS_POINTS.length);
    const topCharacterNames = new Set(topCharacters.map((character) => character.name));
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
    const topSkills = [...memoryNorm.skills]
      .sort((a, b) => {
        const active = Number(Boolean(b.is_active)) - Number(Boolean(a.is_active));
        if (active !== 0) return active;
        return (b.influence_score || 0) - (a.influence_score || 0);
      })
      .slice(0, 6);
    const topInventory = [...memoryNorm.inventory]
      .sort((a, b) => {
        const active = Number(Boolean(b.is_active)) - Number(Boolean(a.is_active));
        if (active !== 0) return active;
        return (b.influence_score || 0) - (a.influence_score || 0);
      })
      .slice(0, 6);

    const activeRelations = memoryNorm.relations.filter(
      (relation) => relation.is_active !== false
    );
    const topRelations = [...activeRelations]
      .sort((a, b) => {
        const aHot =
          topCharacterNames.has(a.from) && topCharacterNames.has(a.to) ? 1 : 0;
        const bHot =
          topCharacterNames.has(b.from) && topCharacterNames.has(b.to) ? 1 : 0;
        return bHot - aHot;
      })
      .slice(0, 6);
    const networkRelations = activeRelations
      .filter(
        (relation) =>
          topCharacterNames.has(relation.from) && topCharacterNames.has(relation.to)
      )
      .slice(0, 10);

    return {
      topCharacters,
      maxInfluence,
      topOpenPlots,
      topSkills,
      topInventory,
      topRelations,
      networkRelations,
      activeCharacters: memoryNorm.characters.filter((character) => character.is_active).length,
      activeSkills: memoryNorm.skills.filter((skill) => skill.is_active).length,
      activeInventory: memoryNorm.inventory.filter((item) => item.is_active).length,
      staleCount: memoryHealth?.stale_plots.length ?? 0,
      overdueCount: memoryHealth?.overdue_plots.length ?? 0,
    };
  }, [memoryNorm, memoryHealth]);

  const latestMemoryUpdateRun = useMemo(
    () => memoryUpdateRuns[0] ?? memory?.latest_update_run ?? null,
    [memoryUpdateRuns, memory?.latest_update_run]
  );

  const highlightedDiffSummary = useMemo(
    () => memoryRefreshPreview?.diffSummary ?? latestMemoryUpdateRun?.diff_summary ?? null,
    [memoryRefreshPreview?.diffSummary, latestMemoryUpdateRun?.diff_summary]
  );

  const memoryStoryView = useMemo(() => {
    if (!memoryNorm || !memoryVisuals) return null;

    const latestNormChapter = memoryNorm.chapters.length
      ? Math.max(...memoryNorm.chapters.map((chapter) => chapter.chapter_no))
      : 0;
    const memoryLag = Math.max(0, latestChapterNo - latestNormChapter);
    const overdueBodies = new Set(
      (memoryHealth?.overdue_plots ?? [])
        .map((plot) => plotBodyFromItem(plot))
        .filter(Boolean)
    );
    const staleBodies = new Set(
      (memoryHealth?.stale_plots ?? [])
        .map((plot) => plotBodyFromItem(plot))
        .filter(Boolean)
    );
    const latestTouchedChapter = Math.max(
      latestNormChapter,
      ...memoryNorm.open_plots.map((plot) => plot.last_touched_chapter || 0)
    );
    const freshChapterFloor = Math.max(1, latestTouchedChapter - 3);
    const sortedPlots = [...memoryNorm.open_plots].sort((a, b) => {
      const priority = (b.priority || 0) - (a.priority || 0);
      if (priority !== 0) return priority;
      return (b.last_touched_chapter || 0) - (a.last_touched_chapter || 0);
    });
    const urgentPlots = sortedPlots.filter((plot) => overdueBodies.has(plot.body)).slice(0, 4);
    const hotPlots = sortedPlots
      .filter(
        (plot) =>
          !overdueBodies.has(plot.body) &&
          (staleBodies.has(plot.body) || (plot.priority || 0) >= 70)
      )
      .slice(0, 4);
    const freshPlots = sortedPlots
      .filter(
        (plot) =>
          !overdueBodies.has(plot.body) &&
          !staleBodies.has(plot.body) &&
          (plot.introduced_chapter || 0) >= freshChapterFloor
      )
      .slice(0, 4);
    const steadyPlots = sortedPlots
      .filter(
        (plot) =>
          !urgentPlots.some((item) => item.body === plot.body) &&
          !hotPlots.some((item) => item.body === plot.body) &&
          !freshPlots.some((item) => item.body === plot.body)
      )
      .slice(0, 4);
    const chapterMoments = [...memoryNorm.chapters]
      .sort((a, b) => a.chapter_no - b.chapter_no)
      .slice(-8)
      .map((chapter) => ({
        ...chapter,
        signal:
          chapter.key_facts.length +
          chapter.causal_results.length +
          chapter.open_plots_added.length +
          chapter.open_plots_resolved.length,
      }));
    const maxChapterSignal = Math.max(
      1,
      ...chapterMoments.map((chapter) => chapter.signal || 0)
    );
    const latestFacts =
      [...memoryNorm.chapters]
        .sort((a, b) => b.chapter_no - a.chapter_no)
        .find(
          (chapter) => chapter.key_facts.length || chapter.causal_results.length
        ) ?? null;

    const nextActions: string[] = [];
    if (memoryLag > 0) {
      nextActions.push(`记忆还落后 ${memoryLag} 章，建议先刷新已审定章节。`);
    }
    if (urgentPlots.length > 0) {
      nextActions.push(`有 ${urgentPlots.length} 条线索已经逼近回收时点，续写时优先处理。`);
    }
    if (memoryVisuals.activeCharacters < 3 && memoryNorm.characters.length > 0) {
      nextActions.push("当前活跃人物偏少，可以考虑回收旧角色或补新冲突点。");
    }
    if (diffChangeCount(highlightedDiffSummary) > 0) {
      nextActions.push(
        `最近一次刷新识别到 ${diffChangeCount(highlightedDiffSummary)} 处结构变化，可回看关键章节。`
      );
    }
    if (nextActions.length === 0) {
      nextActions.push("故事记忆状态平稳，可以继续推进正文，不必频繁手动干预。");
    }

    const classifySkillGroup = (skill: (typeof memoryNorm.skills)[number]) => {
      const text = `${skill.name} ${detailText(skill.detail)} ${skill.aliases.join(" ")}`;
      if (
        !skill.is_active ||
        includesAnyKeyword(text, ["受限", "禁用", "封印", "失控", "失效", "冷却", "枯竭"])
      ) {
        return "restricted";
      }
      if (
        (skill.influence_score || 0) >= 65 ||
        includesAnyKeyword(text, ["核心", "本命", "觉醒", "主力", "杀招", "底牌"])
      ) {
        return "core";
      }
      return "support";
    };

    const classifyItemGroup = (item: (typeof memoryNorm.inventory)[number]) => {
      const text = `${item.label} ${detailText(item.detail)} ${item.aliases.join(" ")}`;
      if (
        !item.is_active ||
        includesAnyKeyword(text, ["失去", "丢失", "损毁", "碎裂", "交出", "封存", "已毁", "耗尽"])
      ) {
        return "lost";
      }
      if (
        (item.influence_score || 0) >= 65 ||
        includesAnyKeyword(text, ["钥匙", "证据", "地图", "令牌", "碎片", "卷轴", "信物", "机关", "线索"])
      ) {
        return "quest";
      }
      return "carried";
    };

    const skillGroups = {
      core: memoryNorm.skills.filter((skill) => classifySkillGroup(skill) === "core").slice(0, 4),
      support: memoryNorm.skills
        .filter((skill) => classifySkillGroup(skill) === "support")
        .slice(0, 4),
      restricted: memoryNorm.skills
        .filter((skill) => classifySkillGroup(skill) === "restricted")
        .slice(0, 4),
    };

    const itemGroups = {
      carried: memoryNorm.inventory
        .filter((item) => classifyItemGroup(item) === "carried")
        .slice(0, 4),
      quest: memoryNorm.inventory.filter((item) => classifyItemGroup(item) === "quest").slice(0, 4),
      lost: memoryNorm.inventory.filter((item) => classifyItemGroup(item) === "lost").slice(0, 4),
    };

    return {
      latestNormChapter,
      memoryLag,
      freshnessRatio:
        approvedChapterCount > 0
          ? clamp01(latestNormChapter / approvedChapterCount)
          : 0,
      draftPressureRatio:
        latestChapterNo > 0 ? clamp01(approvedChapterCount / latestChapterNo) : 0,
      mainNarrative:
        memoryNorm.outline.main_plot.trim() ||
        latestFacts?.key_facts?.[0] ||
        "记忆已建立，但主线摘要还比较克制。",
      latestFacts,
      chapterMoments,
      maxChapterSignal,
      plotBuckets: [
        {
          key: "urgent",
          title: "优先回收",
          hint: "越拖越容易失控",
          items: urgentPlots,
        },
        {
          key: "hot",
          title: "持续推进",
          hint: "仍在拉动主线",
          items: hotPlots,
        },
        {
          key: "fresh",
          title: "新近埋下",
          hint: "最近几章新出现",
          items: freshPlots,
        },
        {
          key: "steady",
          title: "平稳挂起",
          hint: "先记着，不必急改",
          items: steadyPlots,
        },
      ],
      skillGroups,
      itemGroups,
      nextActions: nextActions.slice(0, 3),
    };
  }, [
    approvedChapterCount,
    highlightedDiffSummary,
    latestChapterNo,
    memoryHealth,
    memoryNorm,
    memoryVisuals,
  ]);

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
            <div className="rounded-2xl border border-dashed border-border px-3 py-3 text-xs text-muted-foreground">
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
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-2">
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

  const reloadGenerationLogs = useCallback(async (batchId?: string) => {
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
  }, [id, logViewMode, logBatchId, logOnlyError]);

  useEffect(() => {
    if (!id) return;
    void reloadGenerationLogs();
  }, [id, reloadGenerationLogs]);

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
          currentVersion: cv,
          errors: Array.isArray(p.errors) ? (p.errors as string[]) : [],
          warnings: Array.isArray(p.warnings) ? (p.warnings as string[]) : [],
          autoPassNotes: Array.isArray(p.auto_pass_notes)
            ? (p.auto_pass_notes as string[])
            : [],
          candidateJson: String(p.candidate_json ?? "{}"),
          candidateReadableZh: String(p.candidate_readable_zh ?? ""),
          diffSummary: (p.diff_summary ?? {}) as MemoryDiffSummary,
          runId: p.run_id == null ? null : String(p.run_id),
          applied: false,
        });
        setNotice(
          "候选记忆已生成，但这版风险过高，系统已自动保留当前生效记忆。"
        );
      } else if (outcome === "warning" && preview && typeof preview === "object") {
        const p = preview as Record<string, unknown>;
        const cv = typeof p.current_version === "number" ? p.current_version : 0;
        setMemoryRefreshPreview({
          tier: "warning",
          currentVersion: cv,
          errors: [],
          warnings: Array.isArray(p.warnings) ? (p.warnings as string[]) : [],
          autoPassNotes: Array.isArray(p.auto_pass_notes)
            ? (p.auto_pass_notes as string[])
            : [],
          candidateJson: String(p.candidate_json ?? "{}"),
          candidateReadableZh: String(p.candidate_readable_zh ?? ""),
          confirmationToken:
            p.confirmation_token == null ? null : String(p.confirmation_token),
          diffSummary: (p.diff_summary ?? {}) as MemoryDiffSummary,
          runId: p.run_id == null ? null : String(p.run_id),
          applied: p.applied === true,
        });
        setNotice(
          p.applied === true
            ? "记忆已刷新，但这次变更带有 warning，建议先看结构化差异。"
            : "候选记忆已生成，这次变更建议你先看一眼再决定是否替换当前版本。"
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
    if (
      !id ||
      !memoryRefreshPreview ||
      memoryRefreshPreview.tier !== "warning" ||
      !memoryRefreshPreview.confirmationToken
    )
      return;
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

  function closeMemoryEditor() {
    if (memoryEditorBusy) return;
    setMemoryEditor(null);
  }

  async function submitMemoryEditor() {
    if (!id || !memoryEditor) return;
    setErr(null);
    setNotice(null);
    setMemoryEditorBusy(true);
    try {
      if (memoryEditor.kind === "character") {
        const traits = memoryEditor.traits
          .split(/[，,\n]/)
          .map((item) => item.trim())
          .filter(Boolean);
        if (memoryEditor.mode === "create") {
          await createMemoryCharacter(id, {
            name: memoryEditor.name.trim(),
            role: memoryEditor.role.trim(),
            status: memoryEditor.status.trim(),
            traits,
            influence_score: Number(memoryEditor.influence || 0),
            is_active: memoryEditor.isActive,
          });
          setNotice("人物已新增");
        } else if (memoryEditor.mode === "edit" && memoryEditor.id) {
          const current = memoryNorm?.characters.find((item) => item.id === memoryEditor.id);
          await patchMemoryCharacter(id, memoryEditor.id, {
            name: memoryEditor.name.trim(),
            role: memoryEditor.role.trim(),
            status: memoryEditor.status.trim(),
            traits,
            detail: current?.detail ?? {},
            influence_score: Number(memoryEditor.influence || 0),
            is_active: memoryEditor.isActive,
          });
          setNotice("人物已更新");
        } else if (memoryEditor.mode === "delete" && memoryEditor.id) {
          await deleteMemoryCharacter(id, memoryEditor.id);
          setNotice("人物已标记为退场");
        }
      } else if (memoryEditor.kind === "relation") {
        if (memoryEditor.mode === "create") {
          await createMemoryRelation(id, {
            from_name: memoryEditor.from.trim(),
            to_name: memoryEditor.to.trim(),
            relation: memoryEditor.relation.trim(),
            is_active: memoryEditor.isActive,
          });
          setNotice("关系已新增");
        } else if (memoryEditor.mode === "edit" && memoryEditor.id) {
          await patchMemoryRelation(id, memoryEditor.id, {
            from_name: memoryEditor.from.trim(),
            to_name: memoryEditor.to.trim(),
            relation: memoryEditor.relation.trim(),
            is_active: memoryEditor.isActive,
          });
          setNotice("关系已更新");
        } else if (memoryEditor.mode === "delete" && memoryEditor.id) {
          await deleteMemoryRelation(id, memoryEditor.id);
          setNotice("关系已标记为失效");
        }
      } else if (memoryEditor.kind === "skill") {
        const detail = memoryEditor.description.trim()
          ? { description: memoryEditor.description.trim() }
          : {};
        if (memoryEditor.mode === "create") {
          await createMemorySkill(id, {
            name: memoryEditor.name.trim(),
            detail,
            influence_score: Number(memoryEditor.influence || 0),
            is_active: memoryEditor.isActive,
          });
          setNotice("技能已新增");
        } else if (memoryEditor.mode === "edit" && memoryEditor.id) {
          const current = memoryNorm?.skills.find((item) => item.id === memoryEditor.id);
          await patchMemorySkill(id, memoryEditor.id, {
            name: memoryEditor.name.trim(),
            detail: { ...(current?.detail ?? {}), ...detail },
            influence_score: Number(memoryEditor.influence || 0),
            is_active: memoryEditor.isActive,
          });
          setNotice("技能已更新");
        } else if (memoryEditor.mode === "delete" && memoryEditor.id) {
          await deleteMemorySkill(id, memoryEditor.id);
          setNotice("技能已删除");
        }
      } else if (memoryEditor.kind === "item") {
        const detail = {
          ...(memoryEditor.owner.trim() ? { owner: memoryEditor.owner.trim() } : {}),
          ...(memoryEditor.description.trim()
            ? { description: memoryEditor.description.trim() }
            : {}),
        };
        if (memoryEditor.mode === "create") {
          await createMemoryItem(id, {
            label: memoryEditor.label.trim(),
            detail,
            influence_score: Number(memoryEditor.influence || 0),
            is_active: memoryEditor.isActive,
          });
          setNotice("物品已新增");
        } else if (memoryEditor.mode === "edit" && memoryEditor.id) {
          const current = memoryNorm?.inventory.find((item) => item.id === memoryEditor.id);
          await patchMemoryItem(id, memoryEditor.id, {
            label: memoryEditor.label.trim(),
            detail: { ...(current?.detail ?? {}), ...detail },
            influence_score: Number(memoryEditor.influence || 0),
            is_active: memoryEditor.isActive,
          });
          setNotice("物品已更新");
        } else if (memoryEditor.mode === "delete" && memoryEditor.id) {
          await deleteMemoryItem(id, memoryEditor.id);
          setNotice("物品已删除");
        }
      }
      setMemoryEditor(null);
      await reload();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "记忆编辑失败");
    } finally {
      setMemoryEditorBusy(false);
    }
  }

  async function runCreateCharacter() {
    setMemoryEditor({
      kind: "character",
      mode: "create",
      title: "新增人物",
      subtitle: "用结构化表单录入人物名称、身份与影响力。",
      confirmLabel: "创建人物",
      name: "",
      role: "",
      status: "",
      traits: "",
      from: "",
      to: "",
      relation: "",
      label: "",
      owner: "",
      description: "",
      influence: "0",
      isActive: true,
    });
  }

  async function runEditCharacter(character: NormalizedMemoryPayload["characters"][number]) {
    if (!character.id) {
      setErr("当前人物缺少唯一标识，请先点击“从快照同步分表”后重试");
      return;
    }
    const currentTraits = Array.isArray(character.traits)
      ? character.traits.map((x) => String(x || "").trim()).filter(Boolean).join("，")
      : "";
    setMemoryEditor({
      kind: "character",
      mode: "edit",
      id: character.id,
      title: `编辑人物 · ${character.name}`,
      subtitle: "直接修改真源结构化表，再由系统派生快照。",
      confirmLabel: "保存人物",
      name: character.name,
      role: character.role || "",
      status: character.status || "",
      traits: currentTraits,
      from: "",
      to: "",
      relation: "",
      label: "",
      owner: "",
      description: "",
      influence: String(character.influence_score ?? 0),
      isActive: Boolean(character.is_active),
    });
  }

  async function runDeleteCharacter(character: NormalizedMemoryPayload["characters"][number]) {
    if (!character.id) {
      setErr("当前人物缺少唯一标识，请先点击“从快照同步分表”后重试");
      return;
    }
    setMemoryEditor({
      kind: "character",
      mode: "delete",
      id: character.id,
      title: `下线人物 · ${character.name}`,
      subtitle: "人物不会物理删除，只会标记为退场/不活跃。",
      confirmLabel: "确认下线",
      name: character.name,
      role: character.role || "",
      status: character.status || "",
      traits: "",
      from: "",
      to: "",
      relation: "",
      label: "",
      owner: "",
      description: "",
      influence: String(character.influence_score ?? 0),
      isActive: false,
    });
  }

  async function runCreateRelation() {
    setMemoryEditor({
      kind: "relation",
      mode: "create",
      title: "新增人物关系",
      subtitle: "补录结构化关系，供快照 / Story Bible / RAG 共用。",
      confirmLabel: "创建关系",
      name: "",
      role: "",
      status: "",
      traits: "",
      from: "",
      to: "",
      relation: "",
      label: "",
      owner: "",
      description: "",
      influence: "0",
      isActive: true,
    });
  }

  async function runEditRelation(relation: NormalizedMemoryPayload["relations"][number]) {
    if (!relation.id) {
      setErr("当前关系缺少唯一标识，请先点击“从快照同步分表”后重试");
      return;
    }
    setMemoryEditor({
      kind: "relation",
      mode: "edit",
      id: relation.id,
      title: `编辑关系 · ${relation.from} → ${relation.to}`,
      subtitle: "修改关系的主体、客体和当前状态。",
      confirmLabel: "保存关系",
      name: "",
      role: "",
      status: "",
      traits: "",
      from: relation.from,
      to: relation.to,
      relation: relation.relation,
      label: "",
      owner: "",
      description: "",
      influence: "0",
      isActive: relation.is_active !== false,
    });
  }

  async function runDeleteRelation(relation: NormalizedMemoryPayload["relations"][number]) {
    if (!relation.id) {
      setErr("当前关系缺少唯一标识，请先点击“从快照同步分表”后重试");
      return;
    }
    setMemoryEditor({
      kind: "relation",
      mode: "delete",
      id: relation.id,
      title: `失效关系 · ${relation.from} → ${relation.to}`,
      subtitle: "关系不会物理删除，只会切换为失效态。",
      confirmLabel: "确认失效",
      name: "",
      role: "",
      status: "",
      traits: "",
      from: relation.from,
      to: relation.to,
      relation: relation.relation,
      label: "",
      owner: "",
      description: "",
      influence: "0",
      isActive: false,
    });
  }

  async function runCreateSkill() {
    setMemoryEditor({
      kind: "skill",
      mode: "create",
      title: "新增技能",
      subtitle: "录入技能描述与影响力，让检索和设定引用更稳定。",
      confirmLabel: "创建技能",
      name: "",
      role: "",
      status: "",
      traits: "",
      from: "",
      to: "",
      relation: "",
      label: "",
      owner: "",
      description: "",
      influence: "0",
      isActive: true,
    });
  }

  async function runEditSkill(skill: NormalizedMemoryPayload["skills"][number]) {
    if (!skill.id) {
      setErr("当前技能缺少唯一标识，请先点击“从快照同步分表”后重试");
      return;
    }
    const currentDesc =
      typeof skill.detail.description === "string" ? skill.detail.description : "";
    setMemoryEditor({
      kind: "skill",
      mode: "edit",
      id: skill.id,
      title: `编辑技能 · ${skill.name}`,
      subtitle: "直接修改技能明细与影响力。",
      confirmLabel: "保存技能",
      name: skill.name,
      role: "",
      status: "",
      traits: "",
      from: "",
      to: "",
      relation: "",
      label: "",
      owner: "",
      description: currentDesc,
      influence: String(skill.influence_score ?? 0),
      isActive: Boolean(skill.is_active),
    });
  }

  async function runDeleteSkill(skill: NormalizedMemoryPayload["skills"][number]) {
    if (!skill.id) {
      setErr("当前技能缺少唯一标识，请先点击“从快照同步分表”后重试");
      return;
    }
    setMemoryEditor({
      kind: "skill",
      mode: "delete",
      id: skill.id,
      title: `删除技能 · ${skill.name}`,
      subtitle: "删除后会从结构化真源中移除，并影响后续快照与检索。",
      confirmLabel: "确认删除",
      name: skill.name,
      role: "",
      status: "",
      traits: "",
      from: "",
      to: "",
      relation: "",
      label: "",
      owner: "",
      description: "",
      influence: String(skill.influence_score ?? 0),
      isActive: false,
    });
  }

  async function runCreateItem() {
    setMemoryEditor({
      kind: "item",
      mode: "create",
      title: "新增物品",
      subtitle: "录入物品名称、持有人与描述，补齐后续引用语境。",
      confirmLabel: "创建物品",
      name: "",
      role: "",
      status: "",
      traits: "",
      from: "",
      to: "",
      relation: "",
      label: "",
      owner: "",
      description: "",
      influence: "0",
      isActive: true,
    });
  }

  async function runEditItem(item: NormalizedMemoryPayload["inventory"][number]) {
    if (!item.id) {
      setErr("当前物品缺少唯一标识，请先点击“从快照同步分表”后重试");
      return;
    }
    const currentLabel = inventoryDisplayLabel(item);
    const currentOwner =
      typeof item.detail.owner === "string" ? item.detail.owner : "";
    const currentDescription =
      typeof item.detail.description === "string" ? item.detail.description : "";
    setMemoryEditor({
      kind: "item",
      mode: "edit",
      id: item.id,
      title: `编辑物品 · ${currentLabel}`,
      subtitle: "修改持有人、描述和活跃状态。",
      confirmLabel: "保存物品",
      name: "",
      role: "",
      status: "",
      traits: "",
      from: "",
      to: "",
      relation: "",
      label: currentLabel,
      owner: currentOwner,
      description: currentDescription,
      influence: String(item.influence_score ?? 0),
      isActive: Boolean(item.is_active),
    });
  }

  async function runDeleteItem(item: NormalizedMemoryPayload["inventory"][number]) {
    if (!item.id) {
      setErr("当前物品缺少唯一标识，请先点击“从快照同步分表”后重试");
      return;
    }
    const label = inventoryDisplayLabel(item);
    setMemoryEditor({
      kind: "item",
      mode: "delete",
      id: item.id,
      title: `删除物品 · ${label}`,
      subtitle: "删除后会同步影响快照、Story Bible 与 RAG。",
      confirmLabel: "确认删除",
      name: "",
      role: "",
      status: "",
      traits: "",
      from: "",
      to: "",
      relation: "",
      label,
      owner: "",
      description: "",
      influence: String(item.influence_score ?? 0),
      isActive: false,
    });
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
  }, [logOnlyError, logDialogOpen, logViewMode, logBatchId, reloadGenerationLogs]);

  useEffect(() => {
    if (!logDialogOpen) return;
    const t = window.setInterval(() => {
      void reloadGenerationLogs(logViewMode === "batch" ? logBatchId || undefined : undefined);
    }, 3000);
    return () => window.clearInterval(t);
  }, [logDialogOpen, logBatchId, logOnlyError, logViewMode, reloadGenerationLogs]);

  useEffect(() => {
    if (
      latestMemoryVersion != null &&
      memory?.version != null &&
      latestMemoryVersion > memory.version
    ) {
      void reload();
    }
  }, [latestMemoryVersion, memory?.version, reload]);

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
      } catch {
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
    try {
      await reloadQueueStatus();
      const resp = await autoGenerateChapters(id, targetCount);
      if (resp.status !== "queued" || !resp.batch_id) {
        const message = resp.message || "生成请求未成功启动，请查看生成日志或稍后重试";
        setErr(message);
        await reloadGenerationLogs();
        await reload();
        return;
      }
      setRefreshBatchId(resp.batch_id);
      await reload(); // 清除失败横幅
      if (logViewMode === "batch") {
        setLogBatchId(resp.batch_id);
        await reloadGenerationLogs(resp.batch_id);
      } else {
        await reloadGenerationLogs();
      }
      setTaskNotice(`已开启 AI 一键续写（${targetCount}章）。`);
      await reloadQueueStatus();
      await reload(); // 获取最新小说状态，消除失败横幅
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "全自动生成失败");
      await reloadQueueStatus();
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
      const frameworkMarkdown =
        typeof novel?.framework_markdown === "string" ? novel.framework_markdown : "";
      const frameworkJson =
        typeof novel?.framework_json === "string" ? novel.framework_json : "";
      const hasExistingFramework =
        Boolean(frameworkMarkdown.trim()) ||
        Boolean(frameworkJson.trim() && frameworkJson !== "{}");
      const defaultRegenInstruction =
        "请在保留当前书名、题材方向、文风与核心主题的前提下，完整重写基础大纲。" +
        "输出必须继续保持《一、世界观与核心设定》《二、核心人物》《三、主线剧情与长期矛盾》三部分结构，" +
        "并把设定、人物动机、长期矛盾写得更完整、更具体、更可用于后续续写。";

      if (hasExistingFramework) {
        const resp = await regenerateFramework(id, defaultRegenInstruction);
        if (resp.status === "queued" && resp.batch_id) {
          const outcome = await waitForFrameworkRegenerateBatch(id, resp.batch_id);
          if (outcome === "failed") {
            throw new Error("大纲重写不完整或失败，请点击「基于当前版本重写大纲」再试，并在生成记录里查看详情。");
          }
        }
      } else {
        const resp = await generateFramework(id);
        if (resp.status === "queued" && resp.batch_id) {
          const outcome = await waitForFrameworkGenerateBatch(id, resp.batch_id);
          if (outcome === "failed") {
            throw new Error("首版大纲生成不完整或失败，请点击「重新生成首版大纲」再试，并在生成记录里查看详情。");
          }
        }
      }
      await reload();
      setNotice(
        hasExistingFramework
          ? "大纲已按当前版本重新入队重写，请稍候自动刷新。"
          : "大纲已重新入队生成，请稍候自动刷新。"
      );
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "重试大纲生成失败");
      await reload();
    } finally {
      setBusy(false);
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

  async function runGenerateVolumePlan() {
    if (!id || !selectedVolumeId) return;
    setErr(null);
    setNotice(null);
    setVolumeBusy(true);
    try {
      const resp = await generateVolumeChapterPlan(id, selectedVolumeId, {
        force_regen: false,
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
              const obj = x as Record<string, unknown>;
              const iid = obj.id;
              const body =
                typeof obj.body === "string" && obj.body.trim()
                  ? obj.body
                  : JSON.stringify(obj);
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
        "当前未从大纲里加载到全局禁止设定；若你仍有多条这类设定，请先在「记忆」里打开结构化记忆核对。"
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

  function confirmGenerateVolumePlan() {
    void openLlmConfirm(
      {
        title: "确认生成本卷下一批章计划？",
        description: "这会调用大模型，为当前卷继续补出下一批章计划。",
        confirmLabel: "确认生成章计划",
        details: [
          "提交后任务在后台执行，关闭或离开本页不会中断。",
          `本次会按 ${volumePlanBatchSize} 章为一批生成计划。`,
          "更适合逐批推进，先看一批再决定下一批是否继续。",
        ],
      },
      async () => {
        await runGenerateVolumePlan();
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
          "将基于该章在卷章计划中的条目，在后台串行生成正文；本次走手动单章生成链路，生成结果默认为待审定，不会直接自动审定，也不会立即自动更新工作记忆。",
        confirmLabel: "确认生成正文",
        details: [
          "须已存在该章的章计划；若计划缺失会提示你先补计划。",
          "生成完成后建议先人工审定；只有审定通过后，才会走后续记忆写入或其它衍生流程。",
          "这条链路与 AI 一键续写不同：AI 一键续写默认每章生成后直接审定，并尝试更新工作记忆。",
          useColdRecall === true
            ? `当前已开启冷层召回，最多附带 ${coldRecallItems} 条历史记忆。`
            : useColdRecall === false
              ? "当前未开启冷层召回，会以热层记忆为主生成正文。"
              : "冷层召回为自动模式：章节数 ≥30 时自动开启。",
        ],
      },
      async () => {
        await runGenerateChapterFromPlan(chapterNo);
      }
    );
  }

  function confirmGenerateChapters() {
    const safeGenerateCount = Math.max(
      1,
      Math.min(maxGenerateCount, Math.round(Number(generateCount) || remainingGenerateCount))
    );
    void openLlmConfirm(
      {
        title: `确认 AI 一键续写 ${safeGenerateCount} 章？`,
        description:
          "从已审定章节之后开始：若当前卷尚无分卷剧情，会先生成该卷剧情弧线；若缺少章计划，会自动分批补齐章计划；再按章串行生成正文。默认每章生成后直接审定并更新工作记忆；若开启执行卡校验/纠偏，可能被门禁拦截。",
        confirmLabel: "确认开始续写",
        details: [
          "顺序：缺卷剧情则补卷剧情 → 缺章计划则补章计划 → 生成正文；已有内容会尽量复用。",
          "提交后任务在后台执行，关闭或离开本页不会中断生成。",
          "批量生成更省操作，但建议在关键转折前控制批次数，便于及时校正走向。",
          useColdRecall === true
            ? `当前已开启冷层召回，最多附带 ${coldRecallItems} 条历史记忆。`
            : useColdRecall === false
              ? "当前仅使用热层记忆；如果章节跨度较大，可考虑开启冷层召回。"
              : "冷层召回为自动模式：章节数 ≥30 时自动开启。",
        ],
      },
      async () => {
        await runAutoGenerate(safeGenerateCount);
      }
    );
  }

  function updateGenerateCountInput(rawValue: string) {
    setGenerateCountTouched(true);
    const parsed = Number.parseInt(rawValue, 10);
    if (!Number.isFinite(parsed)) {
      setGenerateCount(1);
      return;
    }
    setGenerateCount(Math.max(1, Math.min(maxGenerateCount, Math.round(parsed))));
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
    const d = parseBackendUtcIso(iso);
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
        <WorkspaceHeader
          novelId={id}
          novel={novel as Record<string, unknown> | null}
          titleDraft={titleDraft}
          onTitleDraftChange={setTitleDraft}
          busy={busy}
          titleBusy={titleBusy}
          err={err}
          notice={notice}
          workspaceStageLabel={workspaceStageLabel}
          chaptersCount={chapters.length}
          latestChapterNo={latestChapterNo}
          approvedChapterCount={approvedChapterCount}
          draftChapterCount={draftChapterCount}
          activeMemoryLines={activeMemoryLines}
          onSaveTitle={() => void runSaveTitle()}
          onOpenSettings={openNovelSettings}
          onOpenLogs={() => {
            setLogDialogOpen(true);
            void reloadGenerationLogs(logBatchId || undefined);
          }}
        />

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
          onReload={reload}
          onConfirmFramework={async () => {
            await confirmFramework(id, fwMd, fwJson);
            setNotice("全书框架已确认，可继续生成章计划与正文。");
            await reload();
          }}
          onConfirmBaseFramework={async () => {
            await confirmBaseFramework(id, fwMd, fwJson);
            setNotice("基础大纲已确认。请打开「大纲抽屉」为各卷生成分卷剧情。");
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
                  {busy ? "重试中…" : "重新生成首版大纲 / 重写当前大纲"}
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
                  ? "若当前还没有可用大纲，会重试首版生成；若已存在草案，则会基于当前版本重写。"
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
            <StudioToolbar
              workspaceRootBook={workspaceRootBook}
              selectedVolumeId={selectedVolumeId}
              selectedVolume={selectedVolume}
              selectedChapter={selectedChapter}
              titleDraft={titleDraft}
              novelTitle={String(novel?.title || "未命名")}
              queueBusy={queueBusy}
              queueLabel={queueLabel}
              queueHint={queueHint}
              generateCount={generateCount}
              maxGenerateCount={maxGenerateCount}
              onGenerateCountChange={updateGenerateCountInput}
              busy={busy}
              frameworkConfirmed={frameworkConfirmed}
              focusMode={focusModeOpen}
              onFocusModeToggle={() => setFocusModeOpen((f) => !f)}
              onOpenOutlineDrawer={() => setOutlineDrawerOpen(true)}
              onGenerateChapters={() => confirmGenerateChapters()}
            />

            <div className="novel-container py-4 md:py-5">
              <div className="flex max-h-[min(85dvh,920px)] min-h-[min(52dvh,420px)] flex-col overflow-hidden rounded-2xl border border-border bg-background/25">
                <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
                  <ChapterTreeSidebar
                    collapsed={studioTreeSidebarCollapsed}
                    onCollapsedChange={setStudioTreeSidebarCollapsed}
                    selectedVolumeId={selectedVolumeId}
                    onSelectVolume={(volumeId) => {
                      setWorkspaceRootBook(false);
                      setSelectedVolumeId(volumeId);
                      setChapterVolumeId(volumeId);
                      setSelectedChapterId("");
                    }}
                    selectedChapterId={selectedChapterId}
                    onSelectChapter={(chapterId, volumeId) => {
                      setWorkspaceRootBook(false);
                      setSelectedVolumeId(volumeId);
                      setChapterVolumeId(volumeId);
                      setSelectedChapterId(chapterId);
                    }}
                    workspaceRootBook={workspaceRootBook}
                    onRootBookClick={() => {
                      setWorkspaceRootBook(true);
                      setSelectedVolumeId("");
                      setSelectedChapterId("");
                      setChapterVolumeId("");
                    }}
                    expandedVolumeIds={expandedVolumeIds}
                    onToggleVolumeExpand={(volumeId) =>
                      setExpandedVolumeIds((m) => ({
                        ...m,
                        [volumeId]: !m[volumeId],
                      }))
                    }
                    treeVolumePlotOpenId={treeVolumePlotOpenId}
                    onToggleVolumePlot={(id) => setTreeVolumePlotOpenId(id)}
                    onOpenOutlineDrawer={() => setOutlineDrawerOpen(true)}
                    onOpenExport={() => {
                      setExportContent("");
                      setExportOpen(true);
                    }}
                    volumes={volumes}
                    chapters={chapters}
                    titleDraft={titleDraft}
                    novelTitle={String(novel?.title || "")}
                  />
                  <div className="min-h-0 flex-1 overflow-y-auto soft-scroll p-4 md:p-5">
            <OutlineDrawerDialog
              open={outlineDrawerOpen}
              onOpenChange={setOutlineDrawerOpen}
              busy={busy}
              frameworkConfirmed={frameworkConfirmed}
              latestChapterNo={latestChapterNo}
              novel={novel}
              fwMd={fwMd}
              onFwMdChange={setFwMd}
              onRetryFramework={() => void runRetryFrameworkGeneration()}
              onOpenFrameworkWizard={() => setFrameworkWizardOpen(true)}
              volumes={volumes}
              arcsPanelVolumeNo={arcsPanelVolumeNo}
              onArcsPanelVolumeNoChange={setArcsPanelVolumeNo}
              totalStudioVolumes={totalStudioVolumes}
              arcsBusy={arcsBusy}
              arcsInstruction={arcsInstruction}
              onArcsInstructionChange={setArcsInstruction}
              onGenerateArcs={() => void runInlineGenerateArcs()}
            />
            {studioRight === "volume" ? (
            <VolumePlanSection
              selectedVolumeId={selectedVolumeId}
              busy={busy}
              volumeBusy={volumeBusy}
              volumePlanBatchSize={volumePlanBatchSize}
              onVolumePlanBatchSizeChange={setVolumePlanBatchSize}
              onGeneratePlan={() => confirmGenerateVolumePlan()}
              onClearPlans={() => void runClearVolumePlans()}
              volumePlan={volumePlan}
              volumePlanView={volumePlanView}
              showVolumePlanWithBody={showVolumePlanWithBody}
              onShowVolumePlanWithBodyChange={setShowVolumePlanWithBody}
              volumes={volumes}
              volumePlanLastRun={volumePlanLastRun}
              onOpenPlanEditor={openPlanEditor}
              onRegeneratePlan={confirmRegenerateChapterPlan}
              onGenerateChapter={confirmGenerateChapterFromPlan}
              normalizePlanBeats={normalizePlanBeats}
              shortenText={shortenText}
              formatVolumePlanBeatsText={formatVolumePlanBeatsText}
            />
            ) : studioRight === "chapter" ? (
            <ChapterContentSection
              selectedChapter={selectedChapter}
              selectedChapterWordCount={selectedChapterWordCount}
              busy={busy}
              editTitle={editTitle}
              onEditTitleChange={setEditTitle}
              editContent={editContent}
              onEditContentChange={setEditContent}
              fbDraft={fbDraft}
              onFbDraftChange={setFbDraft}
              revisePrompt={revisePrompt}
              onRevisePromptChange={setRevisePrompt}
              latestWorkflow={latestWorkflow}
              chapterJudge={chapterJudge}
              retrievalLogs={retrievalLogs}
              memoryUpdateRuns={memoryUpdateRuns}
              coreEvaluation={coreEvaluation}
              intelWorkflowLoading={intelWorkflowLoading}
              intelJudgeLoading={intelJudgeLoading}
              intelRetrievalLoading={intelRetrievalLoading}
              onOpenChapterChat={() => setChapterChatOpen(true)}
              onSaveChapter={() => void runSaveSelectedChapter()}
              onFormatChapter={() => void runFormatSelectedChapter()}
              onDeleteChapter={() => void runDeleteChapter({
                id: selectedChapter?.id ?? "",
                chapter_no: selectedChapter?.chapter_no ?? 0,
                title: selectedChapter?.title ?? "",
                status: selectedChapter?.status ?? "",
              })}
              onApplyRevision={() => run(() => applyChapterRevision(selectedChapter?.id ?? ""))}
              onDiscardRevision={() => run(() => discardChapterRevision(selectedChapter?.id ?? ""))}
              onConsistencyFix={() => confirmConsistencyFix(selectedChapter?.id ?? "")}
              onPolishChapter={() => confirmPolishChapter(selectedChapter?.id ?? "")}
              onRecordFeedback={() => {
                if (selectedChapter && fbDraft[selectedChapter.id]?.trim()) {
                  void addChapterFeedback(selectedChapter.id, fbDraft[selectedChapter.id].trim());
                  setFbDraft((d) => ({ ...d, [selectedChapter.id]: "" }));
                }
              }}
              onApproveChapter={() => confirmApproveChapter(selectedChapter?.id ?? "")}
              onRetryMemory={() => void runRetryChapterMemory(selectedChapter?.id ?? "")}
              onReviseChapter={(chapterId, prompt) => confirmReviseChapter(chapterId, prompt)}
            />
            ) : (
            <section className="glass-panel space-y-5 p-5 md:p-6">
              <div className="space-y-1">
                <p className="section-heading text-foreground font-bold">全书入口</p>
                <p className="text-sm text-foreground/65 dark:text-muted-foreground font-medium">
                  在左侧树选择某一卷可查看章计划与轨道；展开卷后点章节进入正文编辑。需要改世界观、人物、主线或各卷剧情线时，用大纲抽屉。
                </p>
              </div>
              {!frameworkConfirmed ? (
                <div className="relative overflow-hidden rounded-lg border border-amber-500/35 bg-amber-500/10 p-4 shadow-[0_18px_50px_rgba(245,158,11,0.10)] md:p-5">
                  <div className="pointer-events-none absolute -right-16 -top-20 h-44 w-44 rounded-full bg-amber-300/25 blur-3xl" />
                  <div className="relative flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                    <div className="space-y-2">
                      <div className="inline-flex rounded-full border border-amber-500/35 bg-background px-3 py-1 text-[11px] font-bold text-amber-700 dark:text-amber-300">
                        下一步：确认框架
                      </div>
                      <div>
                        <p className="text-lg font-black text-foreground">
                          大纲已生成，但还没有确认，暂时不能开始 AI 续写
                        </p>
                        <p className="mt-1 max-w-2xl text-sm leading-6 text-foreground/70 dark:text-muted-foreground">
                          确认框架后，系统才会把世界观、人物和主线当成正式约束，并继续生成分卷剧情、章计划和正文。
                          {fwMd.trim()
                            ? "建议先快速扫一遍大纲，再进入向导确认。"
                            : "如果大纲内容还没出现，请稍等后台生成完成或在向导中重试。"}
                        </p>
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-2 lg:justify-end">
                      <Button
                        type="button"
                        size="sm"
                        className="gap-1 font-black shadow-lg shadow-amber-500/15"
                        onClick={() => setFrameworkWizardOpen(true)}
                      >
                        <Sparkles className="size-3.5 shrink-0 opacity-90" />
                        确认框架（进入向导）
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="secondary"
                        className="font-bold"
                        onClick={() => setOutlineDrawerOpen(true)}
                      >
                        先检查大纲
                      </Button>
                    </div>
                  </div>
                </div>
              ) : null}
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
              {frameworkConfirmed ? (
                <p className="rounded-2xl border border-border bg-muted p-3 text-xs font-semibold text-foreground/60 dark:text-muted-foreground">
                  可使用顶部工具条的「AI 一键续写」继续生成；默认目标为剩余 {remainingGenerateCount} 章，不超过全书目标 {maxGenerateCount} 章。
                </p>
              ) : null}
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
                <p className="section-heading">小说态势面板</p>
                <p className="text-sm text-muted-foreground">
                  默认只看故事当前讲到哪、谁在推动剧情、哪些线索最该处理；更细的日志和结构化数据都收进下方高级视图。
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
            <div className="grid gap-3 md:grid-cols-4">
              <div className="glass-panel-subtle p-4">
                <p className="text-xs text-muted-foreground">故事推进</p>
                <p className="mt-2 text-xl font-semibold text-foreground">
                  {latestChapterNo ? `第 ${latestChapterNo} 章` : "未开始"}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {approvedChapterCount > 0
                    ? `${approvedChapterCount} 章已审定`
                    : "先完成首批章节审定"}
                </p>
              </div>
              <div className="glass-panel-subtle p-4">
                <p className="text-xs text-muted-foreground">记忆已追到</p>
                <p className="mt-2 text-xl font-semibold text-foreground">
                  {memoryStoryView?.latestNormChapter
                    ? `第 ${memoryStoryView.latestNormChapter} 章`
                    : "尚未同步"}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {memoryStoryView
                    ? memoryStoryView.memoryLag > 0
                      ? `比正文落后 ${memoryStoryView.memoryLag} 章`
                      : "已基本跟上正文进度"
                    : "刷新记忆后会自动补齐"}
                </p>
              </div>
              <div className="glass-panel-subtle p-4">
                <p className="text-xs text-muted-foreground">活跃角色</p>
                <p className="mt-2 text-xl font-semibold text-foreground">
                  {memoryVisuals?.activeCharacters ?? 0}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {memoryNorm?.characters.length
                    ? `共 ${memoryNorm.characters.length} 名已入账人物`
                    : "角色会在刷新后逐步成型"}
                </p>
              </div>
              <div className="glass-panel-subtle p-4">
                <p className="text-xs text-muted-foreground">待回收线索</p>
                <p className="mt-2 text-xl font-semibold text-foreground">{activeMemoryLines}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {memoryVisuals
                    ? `${memoryVisuals.overdueCount} 条临近超期，${memoryVisuals.staleCount} 条略显停滞`
                    : "跨章节悬念会集中显示在这里"}
                </p>
              </div>
            </div>

            {memoryNorm && memoryStoryView && memoryVisuals ? (
              <>
              <div className="grid gap-4 xl:grid-cols-[1.08fr_0.92fr]">
                <div className="signal-surface story-mesh p-5">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="space-y-2">
                      <span className="glass-chip border-primary/25 bg-primary/10 text-primary">
                        <Sparkles className="size-3.5" />
                        Story Pulse
                      </span>
                      <h3 className="text-2xl font-semibold tracking-tight text-foreground">
                        先看整体局势，再决定是否深入调整记忆。
                      </h3>
                      <p className="max-w-2xl text-sm leading-7 text-foreground/70">
                        {shortenText(memoryStoryView.mainNarrative, 120)}
                      </p>
                    </div>
                    <div className="rounded-lg border border-border bg-background px-4 py-3 text-right">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-foreground/50">
                        最近变化
                      </p>
                      <p className="mt-2 text-2xl font-semibold text-foreground">
                        {diffChangeCount(highlightedDiffSummary)}
                      </p>
                      <p className="mt-1 text-sm text-foreground/60">
                        最近一次刷新识别到的结构变化
                      </p>
                    </div>
                  </div>

                  <div className="mt-5 grid gap-4 lg:grid-cols-[1fr_0.9fr]">
                    <div className="rounded-lg border border-border bg-background p-4">
                      <div className="space-y-3">
                        <div>
                          <p className="text-sm font-semibold text-foreground">进度条</p>
                          <p className="text-[11px] text-muted-foreground">
                            一眼判断记忆有没有追上正文。
                          </p>
                        </div>
                        <div className="space-y-3">
                          <div>
                            <div className="mb-1 flex items-center justify-between text-[11px] text-foreground/60">
                              <span>已审定章节覆盖</span>
                              <span>{Math.round(memoryStoryView.freshnessRatio * 100)}%</span>
                            </div>
                            <div className="h-2 rounded-full bg-background">
                              <div
                                className="h-full rounded-full bg-gradient-to-r from-primary via-accent to-cyan-300"
                                style={{ width: `${Math.max(8, Math.round(memoryStoryView.freshnessRatio * 100))}%` }}
                              />
                            </div>
                          </div>
                          <div>
                            <div className="mb-1 flex items-center justify-between text-[11px] text-foreground/60">
                              <span>正文审定进度</span>
                              <span>{Math.round(memoryStoryView.draftPressureRatio * 100)}%</span>
                            </div>
                            <div className="h-2 rounded-full bg-background">
                              <div
                                className="h-full rounded-full bg-gradient-to-r from-emerald-400 via-primary to-sky-400"
                                style={{ width: `${Math.max(8, Math.round(memoryStoryView.draftPressureRatio * 100))}%` }}
                              />
                            </div>
                          </div>
                        </div>
                      </div>

                      <div className="mt-4 grid gap-3 sm:grid-cols-2">
                        <div className="rounded-lg border border-border bg-background p-3">
                          <p className="text-[11px] uppercase tracking-[0.16em] text-foreground/45">
                            当前建议
                          </p>
                          <ul className="mt-2 space-y-2 text-sm text-foreground/70">
                            {memoryStoryView.nextActions.map((item, index) => (
                              <li key={`memory-next-${index}`}>- {item}</li>
                            ))}
                          </ul>
                        </div>
                        <div className="rounded-lg border border-border bg-background p-3">
                          <p className="text-[11px] uppercase tracking-[0.16em] text-foreground/45">
                            最近章节摘要
                          </p>
                          <p className="mt-2 text-sm leading-6 text-foreground/70">
                            {memoryStoryView.latestFacts
                              ? shortenText(
                                  memoryStoryView.latestFacts.key_facts[0] ||
                                    memoryStoryView.latestFacts.causal_results[0] ||
                                    memoryStoryView.latestFacts.chapter_title ||
                                    `第 ${memoryStoryView.latestFacts.chapter_no} 章`,
                                  78
                                )
                              : "最近还没有足够的章节摘要。"}
                          </p>
                        </div>
                      </div>
                    </div>

                    <div className="rounded-lg border border-border bg-background p-4">
                      <div className="flex items-center justify-between gap-2">
                        <div>
                          <p className="text-sm font-semibold text-foreground">最近 8 章走势</p>
                          <p className="text-[11px] text-muted-foreground">
                            哪几章信息量高、哪几章埋了更多线索。
                          </p>
                        </div>
                        <span className="glass-chip px-2.5 py-1 text-[11px]">
                          {memoryStoryView.chapterMoments.length} 章
                        </span>
                      </div>
                      <div className="mt-4 flex min-h-[220px] items-end gap-2">
                        {memoryStoryView.chapterMoments.map((chapter) => {
                          const height = Math.max(
                            24,
                            Math.round((chapter.signal / memoryStoryView.maxChapterSignal) * 152)
                          );
                          return (
                            <div
                              key={`chapter-signal-${chapter.chapter_no}`}
                              className="flex flex-1 flex-col items-center gap-2"
                            >
                              <div className="text-[10px] text-foreground/45">
                                {chapter.signal}
                              </div>
                              <div
                                className="w-full rounded-t-2xl bg-gradient-to-t from-primary via-accent to-cyan-300/85"
                                style={{ height }}
                              />
                              <div className="text-center text-[10px] text-foreground/50">
                                <div>第{chapter.chapter_no}章</div>
                                <div>
                                  +{chapter.open_plots_added.length} / -{chapter.open_plots_resolved.length}
                                </div>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                </div>

                <div className="glass-panel-subtle space-y-3 p-4">
                  <div className="flex items-center justify-between gap-2">
                    <div>
                      <p className="text-sm font-semibold text-foreground">线索看板</p>
                      <p className="text-[11px] text-muted-foreground">
                        直接按紧急程度看，不必理解底层字段。
                      </p>
                    </div>
                    <span className="glass-chip px-2.5 py-1 text-[11px]">
                      共 {memoryNorm.open_plots.length} 条
                    </span>
                  </div>
                  <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-1">
                    {memoryStoryView.plotBuckets.map((bucket) => (
                      <div
                        key={`plot-bucket-${bucket.key}`}
                        className="rounded-lg border border-border bg-background p-4"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div>
                            <p className="text-sm font-semibold text-foreground">
                              {bucket.title}
                            </p>
                            <p className="text-[11px] text-muted-foreground">
                              {bucket.hint}
                            </p>
                          </div>
                          <span className="rounded-full border border-border bg-background px-2.5 py-1 text-[11px] text-foreground/60">
                            {bucket.items.length}
                          </span>
                        </div>
                        {bucket.items.length > 0 ? (
                          <div className="mt-3 space-y-2">
                            {bucket.items.map((plot) => (
                              <div
                                key={`plot-card-${bucket.key}-${plot.body}`}
                                className="rounded-[1rem] border border-border bg-background p-3"
                              >
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                  <span className="rounded-full border border-primary/20 bg-primary/10 px-2.5 py-1 text-[11px] font-semibold text-primary">
                                    {plot.plot_type || "线索"}
                                  </span>
                                  <span className="text-[11px] text-foreground/50">
                                    优先级 {plot.priority ?? 0}
                                  </span>
                                </div>
                                <p className="mt-2 text-sm leading-6 text-foreground/70">
                                  {shortenText(formatMemoryPlotLine(plot), 84)}
                                </p>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className="mt-3 text-sm text-foreground/50">当前没有这一类线索。</p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className="grid gap-4 xl:grid-cols-2">
                <div className="signal-surface p-4">
                  <div className="flex items-center justify-between gap-2">
                    <div>
                      <p className="text-sm font-semibold text-foreground">能力面板</p>
                      <p className="text-[11px] text-muted-foreground">
                        直接分成核心、支援、受限三类，不用自己读字段。
                      </p>
                    </div>
                    <span className="glass-chip px-2.5 py-1 text-[11px]">
                      活跃 {memoryVisuals.activeSkills} / 共 {memoryNorm.skills.length}
                    </span>
                  </div>
                  {memoryNorm.skills.length > 0 ? (
                    <div className="mt-4 grid gap-3">
                      {[
                        ["core", "核心能力", "这批技能决定当前主角或核心角色的上限"],
                        ["support", "支援能力", "常用但不一定决定胜负，偏日常或辅助推进"],
                        ["restricted", "受限能力", "目前受伤、封印、失效或暂时不宜直接调用"],
                      ].map(([key, title, hint]) => {
                        const items = memoryStoryView.skillGroups[
                          key as keyof typeof memoryStoryView.skillGroups
                        ];
                        return (
                          <div
                            key={`skill-group-${key}`}
                            className="rounded-lg border border-border bg-background p-4"
                          >
                            <div className="flex items-center justify-between gap-2">
                              <div>
                                <p className="text-sm font-semibold text-foreground">{title}</p>
                                <p className="text-[11px] text-muted-foreground">{hint}</p>
                              </div>
                              <span className="rounded-full border border-border bg-background px-2.5 py-1 text-[11px] text-foreground/60">
                                {items.length}
                              </span>
                            </div>
                            {items.length > 0 ? (
                              <div className="mt-3 grid gap-3">
                                {items.map((skill) => {
                                  const summary = summarizeDetail(skill.detail, 72);
                                  const owner =
                                    typeof skill.detail?.["owner"] === "string"
                                      ? String(skill.detail["owner"]).trim()
                                      : "";
                                  return (
                                    <div
                                      key={`skill-card-${key}-${skill.id || skill.name}`}
                                      className="rounded-[1rem] border border-border bg-background p-3"
                                    >
                                      <div className="flex flex-wrap items-center justify-between gap-2">
                                        <p className="text-sm font-semibold text-foreground">
                                          {skill.name}
                                        </p>
                                        <span className="text-[11px] text-foreground/50">
                                          热度 {skill.influence_score ?? 0}
                                        </span>
                                      </div>
                                      <p className="mt-2 text-sm leading-6 text-foreground/70">
                                        {summary || "已入账，但暂时没有更多可展示的说明。"}
                                      </p>
                                      <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-foreground/56">
                                        {skill.aliases?.length ? (
                                          <span>别名：{skill.aliases.slice(0, 2).join(" / ")}</span>
                                        ) : null}
                                        {owner ? <span>归属：{owner}</span> : null}
                                      </div>
                                    </div>
                                  );
                                })}
                              </div>
                            ) : (
                              <p className="mt-3 text-sm text-foreground/50">当前没有落在这一类的技能。</p>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <p className="mt-4 text-sm text-foreground/60">当前还没有可展示的技能。</p>
                  )}
                </div>

                <div className="signal-surface p-4">
                  <div className="flex items-center justify-between gap-2">
                    <div>
                      <p className="text-sm font-semibold text-foreground">关键道具面板</p>
                      <p className="text-[11px] text-muted-foreground">
                        分成随身、剧情触发、已离场三类，更接近创作时的直觉。
                      </p>
                    </div>
                    <span className="glass-chip px-2.5 py-1 text-[11px]">
                      活跃 {memoryVisuals.activeInventory} / 共 {memoryNorm.inventory.length}
                    </span>
                  </div>
                  {memoryNorm.inventory.length > 0 ? (
                    <div className="mt-4 grid gap-3">
                      {[
                        ["carried", "随身关键物", "当前还在角色手里，后续随时可能再次使用"],
                        ["quest", "剧情触发物", "更像钥匙、证据、信物或推进剧情的开关"],
                        ["lost", "已离场道具", "已经遗失、损毁、交出或暂时失去作用"],
                      ].map(([key, title, hint]) => {
                        const items = memoryStoryView.itemGroups[
                          key as keyof typeof memoryStoryView.itemGroups
                        ];
                        return (
                          <div
                            key={`item-group-${key}`}
                            className="rounded-lg border border-border bg-background p-4"
                          >
                            <div className="flex items-center justify-between gap-2">
                              <div>
                                <p className="text-sm font-semibold text-foreground">{title}</p>
                                <p className="text-[11px] text-muted-foreground">{hint}</p>
                              </div>
                              <span className="rounded-full border border-border bg-background px-2.5 py-1 text-[11px] text-foreground/60">
                                {items.length}
                              </span>
                            </div>
                            {items.length > 0 ? (
                              <div className="mt-3 grid gap-3">
                                {items.map((item) => {
                                  const summary = summarizeDetail(item.detail, 72);
                                  const holder =
                                    typeof item.detail?.["holder"] === "string"
                                      ? String(item.detail["holder"]).trim()
                                      : "";
                                  return (
                                    <div
                                      key={`inventory-card-${key}-${item.id || item.label}`}
                                      className="rounded-[1rem] border border-border bg-background p-3"
                                    >
                                      <div className="flex flex-wrap items-center justify-between gap-2">
                                        <p className="text-sm font-semibold text-foreground">
                                          {item.label}
                                        </p>
                                        <span className="text-[11px] text-foreground/50">
                                          重要度 {item.influence_score ?? 0}
                                        </span>
                                      </div>
                                      <p className="mt-2 text-sm leading-6 text-foreground/70">
                                        {summary || "已登记为关键物品，后续剧情可能继续调用。"}
                                      </p>
                                      <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-foreground/56">
                                        {item.aliases?.length ? (
                                          <span>别名：{item.aliases.slice(0, 2).join(" / ")}</span>
                                        ) : null}
                                        {holder ? <span>持有者：{holder}</span> : null}
                                      </div>
                                    </div>
                                  );
                                })}
                              </div>
                            ) : (
                              <p className="mt-3 text-sm text-foreground/50">当前没有落在这一类的道具。</p>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <p className="mt-4 text-sm text-foreground/60">当前还没有可展示的关键道具。</p>
                  )}
                </div>
              </div>
              </>
            ) : null}

            <details className="rounded-lg border border-border bg-background/35 p-4">
              <summary className="cursor-pointer list-none text-sm font-semibold text-foreground">
                高级视图：更新审计与结构化差异
                <span className="ml-2 text-[11px] font-normal text-muted-foreground">
                  需要排查记忆刷新问题时再展开
                </span>
              </summary>
              <div className="mt-4 grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
                <div className="glass-panel-subtle space-y-3 p-4">
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <p className="text-sm font-semibold text-foreground">更新记录</p>
                    <p className="text-[11px] text-muted-foreground">
                      把 delta、真源写入和派生层同步拆开看，定位卡点更快。
                    </p>
                  </div>
                  <span className="glass-chip px-2.5 py-1 text-[11px]">
                    最近 {memoryUpdateRuns.length}
                  </span>
                </div>
                {memoryUpdateRuns.length === 0 ? (
                  <p className="text-xs text-muted-foreground">暂无记忆更新 run。</p>
                ) : (
                  <div className="space-y-2">
                    {memoryUpdateRuns.slice(0, 6).map((run) => (
                      <div
                        key={run.id}
                        className="rounded-lg border border-border bg-background p-3"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="flex flex-wrap items-center gap-2">
                            <span
                              className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold ${memoryRunStatusTone(run.status)}`}
                            >
                              {run.status}
                            </span>
                            <span className="text-xs font-semibold text-foreground/80">
                              {run.source}
                              {run.chapter_no ? ` · 第 ${run.chapter_no} 章` : ""}
                            </span>
                          </div>
                          <span className="text-[11px] text-muted-foreground">
                            {formatDateTimeLabel(run.created_at)}
                          </span>
                        </div>
                        <div className="mt-2 grid gap-2 md:grid-cols-5">
                          {[
                            ["delta", run.delta_status],
                            ["validation", run.validation_status],
                            ["norm", run.norm_status],
                            ["snapshot", run.snapshot_status],
                            ["assets", `${run.story_bible_status}/${run.rag_status}`],
                          ].map(([label, value]) => (
                            <div
                              key={`${run.id}-${label}`}
                              className="rounded-xl border border-border/50 bg-background px-2.5 py-2"
                            >
                              <p className="text-[10px] uppercase tracking-[0.16em] text-foreground/45">
                                {label}
                              </p>
                              <p className="mt-1 text-xs font-semibold text-foreground/80">
                                {value || "--"}
                              </p>
                            </div>
                          ))}
                        </div>
                        <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-muted-foreground">
                          <span>v{run.base_memory_version} → v{run.target_memory_version || run.base_memory_version}</span>
                          <span>阶段：{run.current_stage || "queued"}</span>
                          {diffChapterNos(run.diff_summary).length > 0 ? (
                            <span>来源章：{diffChapterNos(run.diff_summary).join(" / ")}</span>
                          ) : null}
                        </div>
                        {run.warnings && run.warnings.length > 0 ? (
                          <p className="mt-2 text-[11px] text-amber-600 dark:text-amber-300">
                            Warning: {run.warnings.slice(0, 2).join("；")}
                          </p>
                        ) : null}
                        {run.errors && run.errors.length > 0 ? (
                          <p className="mt-2 text-[11px] text-rose-600 dark:text-rose-300">
                            Error: {run.errors.slice(0, 2).join("；")}
                          </p>
                        ) : null}
                      </div>
                    ))}
                  </div>
                )}
                </div>

                <div className="glass-panel-subtle space-y-3 p-4">
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <p className="text-sm font-semibold text-foreground">结构化变更</p>
                    <p className="text-[11px] text-muted-foreground">
                      当前高亮最近一次刷新或当前候选，避免直接翻整包 JSON。
                    </p>
                  </div>
                  <span className="glass-chip px-2.5 py-1 text-[11px]">
                    变更 {diffChangeCount(highlightedDiffSummary)}
                  </span>
                </div>
                {!highlightedDiffSummary ? (
                  <p className="text-xs text-muted-foreground">暂无结构化 diff。</p>
                ) : (
                  <div className="space-y-3">
                    <div className="flex flex-wrap gap-2">
                      {diffChangedTypes(highlightedDiffSummary).length > 0 ? (
                        diffChangedTypes(highlightedDiffSummary).map((item) => (
                          <span
                            key={`changed-type-${item}`}
                            className="rounded-full border border-primary/20 bg-primary/10 px-2.5 py-1 text-[11px] font-semibold text-primary"
                          >
                            {item}
                          </span>
                        ))
                      ) : (
                        <span className="text-xs text-muted-foreground">没有显著结构变化</span>
                      )}
                    </div>
                    {(
                      [
                        ["characters", highlightedDiffSummary.characters],
                        ["inventory", highlightedDiffSummary.inventory],
                        ["skills", highlightedDiffSummary.skills],
                        ["relations", highlightedDiffSummary.relations],
                        ["open_plots", highlightedDiffSummary.open_plots],
                        ["chapters", highlightedDiffSummary.chapters],
                      ] as const
                    ).map(([label, section]) => {
                      const counts =
                        section && typeof section === "object" && "counts" in section
                          ? (section as { counts?: Record<string, unknown> }).counts
                          : null;
                      const added =
                        section && typeof section === "object" && "added" in section
                          ? ((section as { added?: unknown[] }).added ?? [])
                          : [];
                      const changed =
                        section && typeof section === "object" && "changed" in section
                          ? ((section as { changed?: unknown[] }).changed ?? [])
                          : [];
                      if (!counts && added.length === 0 && changed.length === 0) return null;
                      return (
                        <div
                          key={`diff-${label}`}
                          className="rounded-lg border border-border bg-background p-3"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <p className="text-xs font-semibold text-foreground/80">{label}</p>
                            <span className="text-[11px] text-muted-foreground">
                              {counts
                                ? Object.entries(counts)
                                    .map(([k, v]) => `${k}:${v}`)
                                    .join(" · ")
                                : `${added.length} added · ${changed.length} changed`}
                            </span>
                          </div>
                          {added.length > 0 ? (
                            <div className="mt-2 flex flex-wrap gap-2">
                              {added.slice(0, 4).map((item, index) => (
                                <span
                                  key={`diff-${label}-added-${index}`}
                                  className="rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2 py-1 text-[11px] text-emerald-700 dark:text-emerald-300"
                                >
                                  {shortenText(
                                    typeof item === "object" && item && "label" in (item as Record<string, unknown>)
                                      ? String((item as Record<string, unknown>).label)
                                      : safeJsonStringify(item),
                                    32
                                  )}
                                </span>
                              ))}
                            </div>
                          ) : null}
                          {changed.length > 0 ? (
                            <ul className="mt-2 space-y-1 text-[11px] text-muted-foreground">
                              {changed.slice(0, 3).map((item, index) => {
                                const row = item as Record<string, unknown>;
                                const name = typeof row.label === "string" ? row.label : `#${index + 1}`;
                                const fields = Array.isArray(row.fields)
                                  ? row.fields.map((field) => String(field)).join(" / ")
                                  : "字段变更";
                                return <li key={`diff-${label}-changed-${index}`}>- {name}：{fields}</li>;
                              })}
                            </ul>
                          ) : null}
                        </div>
                      );
                    })}
                  </div>
                )}
                </div>
              </div>
            </details>

            {memoryNorm?.chapters?.length ? (
              <div className="glass-panel-subtle space-y-3 p-4">
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <p className="text-sm font-semibold text-foreground">章节演化时间线</p>
                    <p className="text-[11px] text-muted-foreground">
                      按章回看“发生了什么变化”，方便快速恢复剧情上下文。
                    </p>
                  </div>
                  <span className="glass-chip px-2.5 py-1 text-[11px]">
                    最近 {Math.min(6, memoryNorm.chapters.length)} 章
                  </span>
                </div>
                <div className="grid gap-3 lg:grid-cols-3">
                  {[...memoryNorm.chapters]
                    .sort((a, b) => b.chapter_no - a.chapter_no)
                    .slice(0, 6)
                    .map((chapter) => (
                      <div
                        key={`timeline-${chapter.chapter_no}`}
                        className="rounded-lg border border-border bg-background p-4"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <p className="text-sm font-semibold text-foreground">
                            第{chapter.chapter_no}章
                          </p>
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            className="h-7 px-2 text-[11px]"
                            onClick={() =>
                              openNormDetail(`第${chapter.chapter_no}章 · 分章脉络`, chapter)
                            }
                          >
                            展开
                          </Button>
                        </div>
                        <p className="mt-1 line-clamp-1 text-[11px] text-muted-foreground">
                          {chapter.chapter_title || "未命名章节"}
                        </p>
                        <div className="mt-3 space-y-2 text-[11px] text-foreground/70">
                          <p>关键事实：{chapter.key_facts.slice(0, 2).join("；") || "暂无"}</p>
                          <p>因果结果：{chapter.causal_results.slice(0, 2).join("；") || "暂无"}</p>
                          <p>
                            埋线变化：+{chapter.open_plots_added.length} / -{chapter.open_plots_resolved.length}
                          </p>
                          {chapter.unresolved_hooks?.length ? (
                            <p>未收钩子：{chapter.unresolved_hooks.slice(0, 2).join("；")}</p>
                          ) : null}
                        </div>
                      </div>
                    ))}
                </div>
              </div>
            ) : null}

            <details className="rounded-lg border border-border bg-background/35 p-4">
              <summary className="cursor-pointer list-none text-sm font-semibold text-foreground">
                高级视图：Story Bible 与 RAG 派生层
                <span className="ml-2 text-[11px] font-normal text-muted-foreground">
                  主要用于确认派生层是否跟上真源
                </span>
              </summary>
              <div className="mt-4 grid gap-4 xl:grid-cols-2">
              <div className="glass-panel-subtle space-y-3 p-4">
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <p className="text-sm font-semibold text-foreground">Story Bible 只读视图</p>
                    <p className="text-[11px] text-muted-foreground">
                      直接看最新快照里的实体与事实，检查派生层是否跟上了真源。
                    </p>
                  </div>
                  <span className="glass-chip px-2.5 py-1 text-[11px]">
                    {storyBibleSnapshot ? `v${storyBibleSnapshot.version}` : "暂无"}
                  </span>
                </div>
                {!storyBibleSnapshot ? (
                  <p className="text-xs text-muted-foreground">暂无 Story Bible 快照。</p>
                ) : (
                  <div className="space-y-3">
                    <div className="grid gap-3 sm:grid-cols-3">
                      {Object.entries(storyBibleSnapshot.stats || {}).slice(0, 3).map(([key, value]) => (
                        <div
                          key={`story-bible-stat-${key}`}
                          className="rounded-xl border border-border/50 bg-background p-3"
                        >
                          <p className="text-[10px] uppercase tracking-[0.16em] text-foreground/45">
                            {key}
                          </p>
                          <p className="mt-1 text-sm font-semibold text-foreground">{String(value)}</p>
                        </div>
                      ))}
                    </div>
                    <div className="space-y-2">
                      {(storyBibleSnapshot.entities || []).slice(0, 6).map((entity, index) => (
                        <div
                          key={`story-entity-${index}`}
                          className="rounded-lg border border-border bg-background p-3"
                        >
                          <p className="text-xs font-semibold text-foreground">
                            {String(entity.canonical_name || "未命名实体")}
                          </p>
                          <p className="mt-1 text-[11px] text-muted-foreground">
                            {String(entity.entity_type || "entity")} · {String(entity.status || "unknown")}
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              <div className="glass-panel-subtle space-y-3 p-4">
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <p className="text-sm font-semibold text-foreground">RAG 索引视图</p>
                    <p className="text-[11px] text-muted-foreground">
                      看已入索引文档和 chunk 数，结合检索日志判断索引是否新鲜。
                    </p>
                  </div>
                  <span className="glass-chip px-2.5 py-1 text-[11px]">
                    文档 {retrievalIndexDocs.length}
                  </span>
                </div>
                {retrievalIndexDocs.length === 0 ? (
                  <p className="text-xs text-muted-foreground">暂无检索索引文档。</p>
                ) : (
                  <div className="space-y-2">
                    {retrievalIndexDocs.slice(0, 6).map((doc) => (
                      <div
                        key={doc.id}
                        className="rounded-lg border border-border bg-background p-3"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <p className="text-xs font-semibold text-foreground">
                            {doc.title || doc.source_id || doc.id}
                          </p>
                          <span className="text-[11px] text-muted-foreground">
                            {doc.chunk_count} chunks
                          </span>
                        </div>
                        <p className="mt-1 text-[11px] text-muted-foreground">
                          {doc.source_type} · {formatDateTimeLabel(doc.updated_at)}
                        </p>
                        {doc.summary ? (
                          <p className="mt-2 line-clamp-2 text-[11px] text-foreground/70">
                            {doc.summary}
                          </p>
                        ) : null}
                      </div>
                    ))}
                  </div>
                )}
              </div>
              </div>
            </details>

            {memoryNorm && memoryVisuals ? (
              <div className="grid gap-4 xl:grid-cols-[1.06fr_0.94fr]">
                <div className="signal-surface story-mesh p-5">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="space-y-2">
                      <span className="glass-chip border-primary/25 bg-primary/10 text-primary">
                        <Sparkles className="size-3.5" />
                        Character Web
                      </span>
                      <h3 className="text-2xl font-semibold tracking-tight text-foreground">
                        把人物关系直接画出来，而不是堆成一排列表。
                      </h3>
                      <p className="max-w-2xl text-sm leading-7 text-foreground/70">
                        谁最活跃、谁和谁绑定最深、当前故事重心落在哪几个人身上，这里一眼就能看懂。
                      </p>
                    </div>
                    <div className="rounded-lg border border-border bg-background px-4 py-3 text-right">
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
                    <div className="relative min-h-[320px] rounded-lg border border-border bg-background p-4">
                      <svg
                        viewBox="0 0 100 100"
                        className="pointer-events-none absolute inset-0 h-full w-full"
                        aria-hidden="true"
                      >
                        {memoryVisuals.networkRelations.map((relation, index) => {
                          const fromIndex = memoryVisuals.topCharacters.findIndex(
                            (character) => character.name === relation.from
                          );
                          const toIndex = memoryVisuals.topCharacters.findIndex(
                            (character) => character.name === relation.to
                          );
                          if (fromIndex < 0 || toIndex < 0) return null;
                          const fromPoint = MEMORY_ATLAS_POINTS[fromIndex];
                          const toPoint = MEMORY_ATLAS_POINTS[toIndex];
                          return (
                            <line
                              key={`relation-line-${index}-${relation.from}-${relation.to}`}
                              x1={Number.parseFloat(fromPoint.left)}
                              y1={Number.parseFloat(fromPoint.top)}
                              x2={Number.parseFloat(toPoint.left)}
                              y2={Number.parseFloat(toPoint.top)}
                              stroke="hsl(var(--accent) / 0.42)"
                              strokeWidth="0.9"
                            />
                          );
                        })}
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

                      <div className="absolute left-1/2 top-1/2 flex h-24 w-24 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border border-primary/20 bg-background text-center shadow-[0_18px_40px_rgba(15,23,42,0.12)]">
                        <div className="px-3">
                          <p className="text-[10px] uppercase tracking-[0.16em] text-foreground/40">
                            故事核心
                          </p>
                          <p className="mt-1 text-xs font-semibold text-foreground">
                            {shortenText(titleDraft.trim() || String(novel?.title || "本书"), 10)}
                          </p>
                        </div>
                      </div>

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
                            className="absolute -translate-x-1/2 -translate-y-1/2 rounded-full border border-border bg-background/82 shadow-[0_18px_40px_rgba(15,23,42,0.14)]"
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
                              <p className="mt-1 text-[10px] text-foreground/60">
                                影响力 {character.influence_score}
                              </p>
                            </div>
                          </div>
                        );
                      })}

                      <div className="absolute bottom-4 left-4 rounded-lg border border-border bg-background px-3 py-2 text-xs text-foreground/60">
                        活跃人物 {memoryVisuals.activeCharacters} · 活跃物品 {memoryVisuals.activeInventory}
                      </div>
                    </div>

                    <div className="space-y-3">
                      <div className="grid gap-3 sm:grid-cols-3">
                        {[
                          ["人物", `${memoryNorm.characters.length}`, `${memoryVisuals.activeCharacters} 名活跃中`],
                          ["关系", `${memoryNorm.relations.length}`, memoryVisuals.topRelations.length > 0 ? "已提炼人物脉络" : "等待关系沉淀"],
                          ["故事重压", `${memoryVisuals.staleCount + memoryVisuals.overdueCount}`, `${memoryVisuals.staleCount} 条停滞 / ${memoryVisuals.overdueCount} 条紧急`],
                        ].map(([label, value, hint]) => (
                          <div key={label} className="rounded-lg border border-border bg-background px-4 py-3">
                            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-foreground/50">
                              {label}
                            </p>
                            <p className="mt-2 text-xl font-semibold text-foreground">{value}</p>
                            <p className="mt-1 text-sm text-foreground/60">{hint}</p>
                          </div>
                        ))}
                      </div>

                      <div className="rounded-lg border border-border bg-background p-4">
                        <div className="flex items-center gap-2">
                          <GitBranch className="size-4 text-primary" />
                          <p className="text-sm font-semibold text-foreground">关系脉络</p>
                        </div>
                        {memoryVisuals.topRelations.length > 0 ? (
                          <div className="mt-4 space-y-2">
                            {memoryVisuals.topRelations.map((relation, index) => (
                              <div
                                key={`relation-atlas-${index}-${relation.from}-${relation.to}`}
                                className="rounded-lg border border-border bg-background px-3 py-3"
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
                                <p className="mt-2 text-sm text-foreground/60">{relation.relation}</p>
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
                      <p className="text-sm font-semibold text-foreground">角色热度榜</p>
                    </div>
                    {memoryVisuals.topCharacters.length > 0 ? (
                      <div className="mt-4 space-y-3">
                        {memoryVisuals.topCharacters.map((character, index) => {
                          const progress = clamp01(
                            character.influence_score / memoryVisuals.maxInfluence
                          );
                          return (
                            <div
                              key={`character-heat-${index}-${character.name}`}
                              className="rounded-lg border border-border bg-background p-4"
                            >
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <span className="rounded-full border border-border bg-background px-3 py-1 text-[11px] font-semibold text-foreground/60">
                                  {character.role || "角色"}
                                </span>
                                <span className="text-[11px] font-semibold text-foreground/56">
                                  热度 {character.influence_score}
                                </span>
                              </div>
                              <p className="mt-3 text-sm leading-7 text-foreground/70">
                                {character.status
                                  ? `${character.name} · ${shortenText(character.status, 48)}`
                                  : character.name}
                              </p>
                              <div className="mt-3 h-2 rounded-full bg-background">
                                <div
                                  className="h-full rounded-full bg-gradient-to-r from-primary via-accent to-cyan-300"
                                  style={{ width: `${Math.max(14, Math.round(progress * 100))}%` }}
                                />
                              </div>
                              <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-foreground/56">
                                {character.traits?.length ? (
                                  <span>
                                    特征：{character.traits.slice(0, 2).map((item) => String(item)).join(" / ")}
                                  </span>
                                ) : null}
                                {character.aliases?.length ? (
                                  <span>别名：{character.aliases.slice(0, 2).join(" / ")}</span>
                                ) : null}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <p className="mt-4 text-sm text-foreground/60">当前还没有形成稳定角色热度。</p>
                    )}
                  </div>
                </div>
              </div>
            ) : null}

            <details className="rounded-lg border border-border bg-background/35 p-4">
              <summary className="cursor-pointer list-none text-sm font-semibold text-foreground">
                高级视图：结构化记忆真源与人工精修
                <span className="ml-2 text-[11px] font-normal text-muted-foreground">
                  适合排查和手动修补，不建议普通创作时频繁使用
                </span>
              </summary>
              <div className="mt-4 glass-panel-subtle space-y-3 p-4">
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
                    <details className="rounded-lg border border-sky-500/30 bg-sky-500/5 p-4">
                      <summary className="cursor-pointer text-[11px] font-semibold uppercase tracking-[0.16em] text-foreground/60">
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
                    <div className="space-y-3 rounded-lg border border-amber-500/30 bg-amber-500/5 p-4">
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
                                const obj = x as Record<string, unknown>;
                                const iid = obj.id;
                                const body =
                                  typeof obj.body === "string" && obj.body.trim()
                                    ? obj.body
                                    : JSON.stringify(obj);
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
            </details>
            {memoryRefreshPreview ? (
              <div className="space-y-3 rounded-lg border border-amber-500/30 bg-amber-500/5 p-4">
                <div className="space-y-1">
                  <p className="text-sm font-medium text-amber-400">
                    {memoryRefreshPreview.tier === "blocked"
                      ? "这版候选记忆先帮你拦下来了"
                      : memoryRefreshPreview.applied
                        ? "这次刷新已经落库，但建议你先看一下 warning"
                        : "这版候选记忆建议你先看一眼"}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    当前基线版本 v{memoryRefreshPreview.currentVersion}。
                    {memoryRefreshPreview.tier === "blocked"
                      ? " 系统判断这版改动风险过高，所以没有直接覆盖。"
                      : memoryRefreshPreview.applied
                        ? " 这次 warning 不会阻断写入，但建议你检查结构化差异与来源章节。"
                        : " 这些改动更像是合理压缩或清理，是否替换由你决定。"}
                  </p>
                </div>
                {memoryRefreshPreview.diffSummary ? (
                  <div className="list-card border-amber-500/20 p-3">
                    <p className="mb-2 text-xs font-medium text-foreground">结构化差异摘要</p>
                    <div className="flex flex-wrap gap-2">
                      {diffChangedTypes(memoryRefreshPreview.diffSummary).map((item) => (
                        <span
                          key={`preview-diff-${item}`}
                          className="rounded-full border border-amber-500/20 bg-amber-500/10 px-2 py-1 text-[11px] text-amber-700 dark:text-amber-300"
                        >
                          {item}
                        </span>
                      ))}
                      {diffChapterNos(memoryRefreshPreview.diffSummary).length > 0 ? (
                        <span className="rounded-full border border-border bg-background px-2 py-1 text-[11px] text-muted-foreground">
                          来源章：{diffChapterNos(memoryRefreshPreview.diffSummary).join(" / ")}
                        </span>
                      ) : null}
                    </div>
                  </div>
                ) : null}
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
                  {memoryRefreshPreview.tier === "warning" &&
                  !memoryRefreshPreview.applied &&
                  memoryRefreshPreview.confirmationToken ? (
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
                <ul className="max-h-[min(40vh,320px)] space-y-1.5 overflow-y-auto soft-scroll rounded-xl border border-border bg-muted p-3 text-xs text-foreground/70 dark:text-muted-foreground font-medium leading-relaxed">
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
                <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3">
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

      <div className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-background/92 pb-[calc(env(safe-area-inset-bottom)+0.75rem)] pt-3 shadow-[0_-12px_30px_rgba(15,23,42,0.08)] md:hidden">
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
                  className="font-bold"
                  disabled={busy || volumeBusy || !selectedVolumeId}
                  onClick={() => confirmGenerateVolumePlan()}
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

      <GenerationLogsDialog
        open={logDialogOpen}
        onOpenChange={setLogDialogOpen}
        logs={genLogs}
        logBusy={logBusy}
        logViewMode={logViewMode}
        onViewModeChange={(mode) => {
          setLogViewMode(mode);
          if (mode === "batch" && !logBatchId && (refreshBatchId || latestLogBatchId)) {
            setLogBatchId(refreshBatchId || latestLogBatchId);
          }
        }}
        logBatchId={logBatchId}
        onBatchIdChange={setLogBatchId}
        logOnlyError={logOnlyError}
        onOnlyErrorChange={setLogOnlyError}
        onRefresh={() => void reloadGenerationLogs(logViewMode === "batch" ? logBatchId || undefined : undefined)}
        onClear={runClearGenerationLogs}
        refreshStatus={refreshStatus}
        refreshProgress={refreshProgress}
        refreshBatchId={refreshBatchId}
        refreshStartedAt={refreshStartedAt}
        refreshUpdatedAt={refreshUpdatedAt}
        refreshElapsedSeconds={refreshElapsedSeconds}
        latestRefreshVersion={latestRefreshVersion}
        refreshLastMessage={refreshLastMessage}
        formatUtc8={formatUtc8}
        formatDuration={formatDuration}
        summarizeLogMeta={summarizeLogMeta}
      />

      {/* 小说设置弹窗 */}
      <NovelSettingsDialog
        open={novelSettingsOpen}
        onOpenChange={setNovelSettingsOpen}
        draft={novelSettingsDraft}
        onDraftChange={(partial) => setNovelSettingsDraft({ ...novelSettingsDraft, ...partial })}
        busy={novelSettingsBusy}
        onSave={handleSaveNovelSettings}
        writingStyleSlot={
          <WritingStyleSelect
            value={novelSettingsDraft.writing_style_id}
            onChange={(id) => setNovelSettingsDraft({ ...novelSettingsDraft, writing_style_id: id })}
          />
        }
      />

      <MemoryEditorDialog
        editor={memoryEditor}
        onChange={(partial) => memoryEditor && setMemoryEditor({ ...memoryEditor, ...partial })}
        busy={memoryEditorBusy}
        onClose={closeMemoryEditor}
        onSubmit={() => void submitMemoryEditor()}
      />

      <NormDetailDialog
        open={normDetailOpen}
        onOpenChange={setNormDetailOpen}
        title={normDetailTitle}
        body={normDetailBody}
      />

      <HistoryDialog
        open={historyDialogOpen}
        onOpenChange={setHistoryDialogOpen}
        entries={memoryHistory}
        onRollback={(version) => void runRollbackMemory(version)}
      />

      <RefreshRangeDialog
        open={refreshRangeOpen}
        onOpenChange={setRefreshRangeOpen}
        mode={refreshRangeMode}
        onModeChange={setRefreshRangeMode}
        fromNo={refreshFromNo}
        toNo={refreshToNo}
        onFromNoChange={setRefreshFromNo}
        onToNoChange={setRefreshToNo}
        busy={busy}
        onConfirm={(opts) => void executeRefreshMemory(opts)}
      />

      <PlanEditorDialog
        open={planEditorOpen}
        onOpenChange={setPlanEditorOpen}
        draft={{
          chapterNo: planEditorChapterNo,
          title: planEditorTitle,
          goal: planEditorGoal,
          conflict: planEditorConflict,
          turn: planEditorTurn,
          plotSummary: planEditorPlotSummary,
          stagePosition: planEditorStagePosition,
          pacing: planEditorPacing,
          mustHappen: planEditorMustHappen,
          callbacks: planEditorCallbacks,
          allowedProgress: planEditorAllowedProgress,
          mustNot: planEditorMustNot,
          reserved: planEditorReserved,
          endingHook: planEditorEndingHook,
          styleGuardrails: planEditorStyleGuardrails,
        }}
        onChange={(p) => {
          if (p.title !== undefined) setPlanEditorTitle(p.title);
          if (p.goal !== undefined) setPlanEditorGoal(p.goal);
          if (p.conflict !== undefined) setPlanEditorConflict(p.conflict);
          if (p.turn !== undefined) setPlanEditorTurn(p.turn);
          if (p.plotSummary !== undefined) setPlanEditorPlotSummary(p.plotSummary);
          if (p.stagePosition !== undefined) setPlanEditorStagePosition(p.stagePosition);
          if (p.pacing !== undefined) setPlanEditorPacing(p.pacing);
          if (p.mustHappen !== undefined) setPlanEditorMustHappen(p.mustHappen);
          if (p.callbacks !== undefined) setPlanEditorCallbacks(p.callbacks);
          if (p.allowedProgress !== undefined) setPlanEditorAllowedProgress(p.allowedProgress);
          if (p.mustNot !== undefined) setPlanEditorMustNot(p.mustNot);
          if (p.reserved !== undefined) setPlanEditorReserved(p.reserved);
          if (p.endingHook !== undefined) setPlanEditorEndingHook(p.endingHook);
          if (p.styleGuardrails !== undefined) setPlanEditorStyleGuardrails(p.styleGuardrails);
        }}
        saving={planEditorSaving}
        onSave={() => void savePlanEditor()}
      />

      <ExportDialog
        open={exportOpen}
        onOpenChange={setExportOpen}
        startNo={exportStartNo}
        endNo={exportEndNo}
        content={exportContent}
        busy={exportBusy}
        onStartNoChange={setExportStartNo}
        onEndNoChange={setExportEndNo}
        onExport={handleExport}
      />

      <ChapterChatDialog
        open={chapterChatOpen}
        onOpenChange={setChapterChatOpen}
        turns={chapterChatTurns}
        input={chapterChatInput}
        onInputChange={setChapterChatInput}
        busy={chapterChatBusy}
        err={chapterChatErr}
        thinking={chapterChatThinking}
        thinkExpanded={chapterThinkExpanded}
        onThinkExpandedChange={setChapterThinkExpanded}
        onSend={confirmSendChapterChat}
        onAbort={() => chapterChatAbort?.abort()}
        onClear={() => {
          setChapterChatTurns([]);
          setChapterChatErr(null);
          setChapterChatThinking("");
          setChapterThinkExpanded(false);
        }}
        canAbort={Boolean(chapterChatAbort)}
        quickPrompts={chapterQuickPrompts}
        onQuickPrompt={confirmSendChapterQuickPrompt}
      />
      <FocusMode
        open={focusModeOpen}
        onExit={() => setFocusModeOpen(false)}
        chapters={chapters}
        selectedChapterId={selectedChapterId}
        onSelectChapter={setSelectedChapterId}
        editTitle={editTitle}
        editContent={editContent}
        onEditTitleChange={setEditTitle}
        onEditContentChange={setEditContent}
        onSave={() => void runSaveSelectedChapter()}
        busy={busy}
        novelId={id}
        volumes={volumes}
        onChapterCreated={(chapterId) => {
          setSelectedChapterId(chapterId);
        }}
        onReloadChapters={async () => {
          if (!id) return;
          const c = await listChapters(id);
          setChapters(c);
        }}
      />
    </div>
  );
}
