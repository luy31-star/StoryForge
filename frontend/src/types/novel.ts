/**
 * Novel module type definitions.
 * Consolidates types from NovelWorkspace.tsx and re-exports from novelApi.ts.
 */
import type { ReactNode } from "react";
import type {
  ChapterPlanReservedItem,
  ChapterPlanV2Beats,
  MemoryDiffSummary,
} from "@/services/novelApi";

// Re-export types from novelApi.ts for centralized access
export type {
  ShelfNovel,
  NovelVolumeListItem,
  ChapterPlanReservedItem,
  ChapterPlanSceneCard,
  ChapterPlanV2Beats,
  MemorySchemaGuide,
  MemoryHealth,
  MemoryDiffSummary,
  MemoryUpdateRun,
  NormalizedMemoryPayload,
  ChapterJudgeLatest,
  NovelWorkflowLatest,
  NovelRetrievalLogItem,
} from "@/services/novelApi";

// ─── Chapter list item (from listChapters return type) ───

export type ChapterListItem = {
  id: string;
  chapter_no: number;
  title: string;
  content: string;
  pending_content: string;
  pending_revision_prompt: string;
  status: string;
  source: string;
};

// ─── Workspace ───

export type WorkspaceTab = "studio" | "memory";

// ─── Volume Arc ───

export type VolumeArcRow = {
  title?: string;
  name?: string;
  from_chapter?: number;
  to_chapter?: number;
  summary?: string;
  description?: string;
  hook?: string;
  must_not?: string[] | string;
  progress_allowed?: string[] | string;
};

// ─── Normalized Plan Beats ───

export type NormalizedPlanBeats = {
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

// ─── Queue Status ───

export type NovelQueueStatus = {
  active_auto_pipeline_count: number;
  max_active_auto_pipeline: number;
  available_auto_pipeline_slots: number;
  is_busy: boolean;
};

// ─── Memory Refresh Preview ───

export type MemoryRefreshPreviewState = {
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
};

// ─── LLM Confirm Dialog ───

export type LlmConfirmState = {
  title: string;
  description: string | ReactNode;
  confirmLabel: string;
  details: string[];
  extraContent?: ReactNode;
};

// ─── Memory Editor ───

export type MemoryEditorState = {
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

// ─── Novel detail (for workspace, replaces Record<string, unknown>) ───

export type NovelDetail = {
  id: string;
  title: string;
  intro: string;
  background: string;
  style: string;
  status: string;
  framework_confirmed: boolean;
  base_framework_confirmed: boolean;
  framework_markdown: string;
  framework_json: string;
  target_chapters: number;
  chapter_target_words: number;
  daily_auto_chapters: number;
  daily_auto_time: string;
  length_tag: string;
  writing_style_id: string | null;
  auto_consistency_check: boolean;
  auto_plan_guard_check: boolean;
  auto_plan_guard_fix: boolean;
  auto_style_polish: boolean;
  auto_expressive_enhance: boolean;
  framework_model: string;
  plan_model: string;
  chapter_model: string;
  rag_enabled: boolean;
  story_bible_enabled: boolean;
  created_at: string;
  updated_at: string;
  [key: string]: unknown;
};
