/**
 * Zustand store for the NovelWorkspace page.
 * Replaces 132 useState hooks with structured state slices.
 */
import { create } from "zustand";
import type {
  ChapterListItem,
  ChapterJudgeLatest,
  LlmConfirmState,
  MemoryEditorState,
  MemoryRefreshPreviewState,
  NovelDetail,
  NovelQueueStatus,
  NovelRetrievalLogItem,
  NovelVolumeListItem,
  NovelWorkflowLatest,
  MemoryDiffSummary,
  MemoryUpdateRun,
  NormalizedMemoryPayload,
  MemorySchemaGuide,
  MemoryHealth,
  WorkspaceTab,
} from "@/types/novel";

// ─── Memory history entry ───
export type MemoryHistoryEntry = {
  version: number;
  summary: string;
  created_at: string | null;
  diff_summary?: MemoryDiffSummary;
  source_summary?: {
    chapter_nos?: number[];
    latest_chapter_no?: number | null;
    changed_types?: string[];
  };
};

// ─── Novel settings draft ───
export type NovelSettingsDraft = {
  target_chapters: number;
  daily_auto_chapters: number;
  daily_auto_time: string;
  chapter_target_words: number;
  auto_consistency_check: boolean;
  auto_plan_guard_check: boolean;
  auto_plan_guard_fix: boolean;
  auto_style_polish: boolean;
  style: string;
  writing_style_id: string;
  framework_model: string;
  plan_model: string;
  chapter_model: string;
};

// ─── Volume plan last run ───
export type VolumePlanLastRun = {
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
};

// ─── Plan editor state ───
export type PlanEditorDraft = {
  chapterNo: number | null;
  title: string;
  goal: string;
  conflict: string;
  turn: string;
  plotSummary: string;
  stagePosition: string;
  pacing: string;
  mustHappen: string;
  callbacks: string;
  allowedProgress: string;
  mustNot: string;
  reserved: string;
  endingHook: string;
  styleGuardrails: string;
};

// ─── Export dialog state ───
export type ExportDraft = {
  startNo: number;
  endNo: number;
  content: string;
  busy: boolean;
};

// ─── Refresh range state ───
export type RefreshRangeDraft = {
  mode: "recent" | "full" | "custom";
  fromNo: number;
  toNo: number;
};

// ─── Chapter chat state ───
export type ChapterChatState = {
  open: boolean;
  turns: { role: "user" | "assistant"; content: string }[];
  input: string;
  busy: boolean;
  err: string | null;
  thinking: string;
  thinkExpanded: boolean;
  abort: AbortController | null;
};

// ─── Generation log state ───
export type GenLogState = {
  batchId: string;
  busy: boolean;
  dialogOpen: boolean;
  onlyError: boolean;
  viewMode: "all" | "batch";
  latestBatchId: string;
};

// ─── Memory refresh state ───
export type MemoryRefreshState = {
  batchId: string;
  status: "idle" | "queued" | "started" | "done" | "failed";
  progress: number;
  lastMessage: string;
  updatedAt: string | null;
  startedAt: string | null;
  elapsedSeconds: number | null;
  latestVersion: number | null;
  latestMemoryVersion: number | null;
};

// ─── Store interface ───
interface NovelWorkspaceState {
  // Novel identity
  novelId: string;

  // Core data
  novel: NovelDetail | null;
  chapters: ChapterListItem[];
  volumes: NovelVolumeListItem[];
  memory: Record<string, unknown> | null;
  memoryNorm: NormalizedMemoryPayload | null;
  memorySchemaGuide: MemorySchemaGuide | null;
  memoryHealth: MemoryHealth | null;

  // UI - Tab & layout
  activeTab: WorkspaceTab;
  isFullScreen: boolean;
  studioTreeSidebarCollapsed: boolean;
  selectedVolumeId: string;
  selectedChapterId: string;
  expandedVolumeIds: Record<string, boolean>;

  // UI - Generation
  busy: boolean;
  generateCount: number;
  generateCountTouched: boolean;
  generateTrace: string;
  useColdRecall: boolean;
  coldRecallItems: number;

  // UI - Queue
  queueStatus: NovelQueueStatus | null;
  queueStatusLoading: boolean;

  // UI - Title editing
  titleDraft: string;
  titleBusy: boolean;

  // UI - Error/notice
  err: string | null;
  notice: string | null;

  // UI - Focus mode
  focusModeIntroOpen: boolean;
  focusTaskBusy: boolean;
  focusReviseOpen: boolean;
  continueWriteOpen: boolean;

  // UI - Chapter chat
  chapterChat: ChapterChatState;

  // UI - Volumes & arcs
  arcsPanelVolumeNo: number;
  arcsInstruction: string;
  arcsBusy: boolean;
  chapterVolumeId: string;
  volumePlan: Record<string, unknown>[];
  volumeBusy: boolean;
  volumePlanBatchSize: number;
  volumePlanLastRun: VolumePlanLastRun | null;
  showVolumePlanWithBody: boolean;

  // UI - Plan editor
  planEditor: PlanEditorDraft;
  planEditorOpen: boolean;
  planEditorSaving: boolean;

  // UI - Memory
  memoryRefresh: MemoryRefreshState;
  memoryRefreshPreview: MemoryRefreshPreviewState | null;
  structuredPages: Record<string, number>;
  memoryFixListPages: Record<string, number>;
  memoryFixBusy: boolean;
  openPlotsLines: string[];
  keyFactsLines: string[];
  causalResultsLines: string[];
  openPlotsAddedLines: string[];
  openPlotsResolvedLines: string[];
  memoryFixHints: string[];
  memoryHistory: MemoryHistoryEntry[];
  historyDialogOpen: boolean;

  // UI - Memory editor
  memoryEditor: MemoryEditorState | null;
  memoryEditorBusy: boolean;

  // UI - Norm detail
  normDetailOpen: boolean;
  normDetailTitle: string;
  normDetailBody: string;

  // UI - Gen logs
  genLog: GenLogState;
  genLogs: unknown[]; // will be typed via hook

  // UI - Intel panel
  latestWorkflow: NovelWorkflowLatest | null;
  memoryUpdateRuns: MemoryUpdateRun[];
  storyBibleSnapshot: unknown;
  retrievalIndexDocs: unknown[];
  retrievalLogs: NovelRetrievalLogItem[];
  coreEvaluation: unknown;
  chapterJudge: ChapterJudgeLatest | null;
  intelWorkflowLoading: boolean;
  intelRetrievalLoading: boolean;
  intelJudgeLoading: boolean;

  // UI - Novel settings
  novelSettingsOpen: boolean;
  novelSettingsDraft: NovelSettingsDraft;
  novelSettingsBusy: boolean;

  // UI - Export
  exportDraft: ExportDraft;
  exportOpen: boolean;

  // UI - Refresh range
  refreshRangeOpen: boolean;
  refreshRange: RefreshRangeDraft;

  // UI - Framework wizard
  frameworkWizardOpen: boolean;

  // UI - LLM confirm
  llmConfirm: LlmConfirmState | null;
  llmConfirmBusy: boolean;

  // UI - Edit content
  editTitle: string;
  editContent: string;

  // Actions (state setters)
  setNovelId: (id: string) => void;
  setNovel: (novel: NovelDetail | null) => void;
  setChapters: (chapters: ChapterListItem[]) => void;
  setVolumes: (volumes: NovelVolumeListItem[]) => void;
  setMemory: (v: Record<string, unknown> | null) => void;
  setMemoryNorm: (v: NormalizedMemoryPayload | null) => void;
  setMemorySchemaGuide: (v: MemorySchemaGuide | null) => void;
  setMemoryHealth: (v: MemoryHealth | null) => void;
  setActiveTab: (tab: WorkspaceTab) => void;
  setIsFullScreen: (v: boolean) => void;
  setStudioTreeSidebarCollapsed: (v: boolean) => void;
  setSelectedVolumeId: (v: string) => void;
  setSelectedChapterId: (v: string) => void;
  toggleExpandedVolumeId: (id: string) => void;
  setBusy: (v: boolean) => void;
  setGenerateCount: (v: number) => void;
  setGenerateCountTouched: (v: boolean) => void;
  setGenerateTrace: (v: string) => void;
  setUseColdRecall: (v: boolean) => void;
  setColdRecallItems: (v: number) => void;
  setQueueStatus: (v: NovelQueueStatus | null) => void;
  setQueueStatusLoading: (v: boolean) => void;
  setTitleDraft: (v: string) => void;
  setTitleBusy: (v: boolean) => void;
  setErr: (v: string | null) => void;
  setNotice: (v: string | null) => void;
  setFocusModeIntroOpen: (v: boolean) => void;
  setFocusTaskBusy: (v: boolean) => void;
  setFocusReviseOpen: (v: boolean) => void;
  setContinueWriteOpen: (v: boolean) => void;
  setChapterChat: (v: Partial<ChapterChatState>) => void;
  setArcsPanelVolumeNo: (v: number) => void;
  setArcsInstruction: (v: string) => void;
  setArcsBusy: (v: boolean) => void;
  setChapterVolumeId: (v: string) => void;
  setVolumePlan: (v: Record<string, unknown>[]) => void;
  setVolumeBusy: (v: boolean) => void;
  setVolumePlanBatchSize: (v: number) => void;
  setVolumePlanLastRun: (v: VolumePlanLastRun | null) => void;
  setShowVolumePlanWithBody: (v: boolean) => void;
  setPlanEditor: (v: Partial<PlanEditorDraft>) => void;
  setPlanEditorOpen: (v: boolean) => void;
  setPlanEditorSaving: (v: boolean) => void;
  setMemoryRefresh: (v: Partial<MemoryRefreshState>) => void;
  setMemoryRefreshPreview: (v: MemoryRefreshPreviewState | null) => void;
  setStructuredPages: (v: Record<string, number>) => void;
  setMemoryFixListPages: (v: Record<string, number>) => void;
  setMemoryFixBusy: (v: boolean) => void;
  setOpenPlotsLines: (v: string[]) => void;
  setKeyFactsLines: (v: string[]) => void;
  setCausalResultsLines: (v: string[]) => void;
  setOpenPlotsAddedLines: (v: string[]) => void;
  setOpenPlotsResolvedLines: (v: string[]) => void;
  setMemoryFixHints: (v: string[]) => void;
  setMemoryHistory: (v: MemoryHistoryEntry[]) => void;
  setHistoryDialogOpen: (v: boolean) => void;
  setMemoryEditor: (v: MemoryEditorState | null) => void;
  setMemoryEditorBusy: (v: boolean) => void;
  setNormDetailOpen: (v: boolean) => void;
  setNormDetailTitle: (v: string) => void;
  setNormDetailBody: (v: string) => void;
  setGenLog: (v: Partial<GenLogState>) => void;
  setGenLogs: (v: unknown[]) => void;
  setLatestWorkflow: (v: NovelWorkflowLatest | null) => void;
  setMemoryUpdateRuns: (v: MemoryUpdateRun[]) => void;
  setStoryBibleSnapshot: (v: unknown) => void;
  setRetrievalIndexDocs: (v: unknown[]) => void;
  setRetrievalLogs: (v: NovelRetrievalLogItem[]) => void;
  setCoreEvaluation: (v: unknown) => void;
  setChapterJudge: (v: ChapterJudgeLatest | null) => void;
  setIntelWorkflowLoading: (v: boolean) => void;
  setIntelRetrievalLoading: (v: boolean) => void;
  setIntelJudgeLoading: (v: boolean) => void;
  setNovelSettingsOpen: (v: boolean) => void;
  setNovelSettingsDraft: (v: Partial<NovelSettingsDraft>) => void;
  setNovelSettingsBusy: (v: boolean) => void;
  setExportDraft: (v: Partial<ExportDraft>) => void;
  setExportOpen: (v: boolean) => void;
  setRefreshRangeOpen: (v: boolean) => void;
  setRefreshRange: (v: Partial<RefreshRangeDraft>) => void;
  setFrameworkWizardOpen: (v: boolean) => void;
  setLlmConfirm: (v: LlmConfirmState | null) => void;
  setLlmConfirmBusy: (v: boolean) => void;
  setEditTitle: (v: string) => void;
  setEditContent: (v: string) => void;

  // Bulk state reset
  resetWorkspace: () => void;
}

// ─── Default values ───

const defaultPlanEditor: PlanEditorDraft = {
  chapterNo: null,
  title: "",
  goal: "",
  conflict: "",
  turn: "",
  plotSummary: "",
  stagePosition: "",
  pacing: "",
  mustHappen: "",
  callbacks: "",
  allowedProgress: "",
  mustNot: "",
  reserved: "",
  endingHook: "",
  styleGuardrails: "",
};

const defaultChapterChat: ChapterChatState = {
  open: false,
  turns: [],
  input: "",
  busy: false,
  err: null,
  thinking: "",
  thinkExpanded: false,
  abort: null,
};

const defaultGenLog: GenLogState = {
  batchId: "",
  busy: false,
  dialogOpen: false,
  onlyError: false,
  viewMode: "all",
  latestBatchId: "",
};

const defaultMemoryRefresh: MemoryRefreshState = {
  batchId: "",
  status: "idle",
  progress: 0,
  lastMessage: "",
  updatedAt: null,
  startedAt: null,
  elapsedSeconds: null,
  latestVersion: null,
  latestMemoryVersion: null,
};

const defaultNovelSettings: NovelSettingsDraft = {
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
};

const defaultExport: ExportDraft = {
  startNo: 1,
  endNo: 9999,
  content: "",
  busy: false,
};

const defaultRefreshRange: RefreshRangeDraft = {
  mode: "recent",
  fromNo: 1,
  toNo: 1,
};

// ─── Store ───

export const useNovelWorkspaceStore = create<NovelWorkspaceState>((set) => ({
  // Novel identity
  novelId: "",

  // Core data
  novel: null,
  chapters: [],
  volumes: [],
  memory: null,
  memoryNorm: null,
  memorySchemaGuide: null,
  memoryHealth: null,

  // UI - Tab & layout
  activeTab: "studio",
  isFullScreen: false,
  studioTreeSidebarCollapsed: false,
  selectedVolumeId: "",
  selectedChapterId: "",
  expandedVolumeIds: {},

  // UI - Generation
  busy: false,
  generateCount: 1,
  generateCountTouched: false,
  generateTrace: "",
  useColdRecall: false,
  coldRecallItems: 5,

  // UI - Queue
  queueStatus: null,
  queueStatusLoading: false,

  // UI - Title editing
  titleDraft: "",
  titleBusy: false,

  // UI - Error/notice
  err: null,
  notice: null,

  // UI - Focus mode
  focusModeIntroOpen: false,
  focusTaskBusy: false,
  focusReviseOpen: false,
  continueWriteOpen: false,

  // UI - Chapter chat
  chapterChat: { ...defaultChapterChat },

  // UI - Volumes & arcs
  arcsPanelVolumeNo: 1,
  arcsInstruction: "",
  arcsBusy: false,
  chapterVolumeId: "",
  volumePlan: [],
  volumeBusy: false,
  volumePlanBatchSize: 10,
  volumePlanLastRun: null,
  showVolumePlanWithBody: false,

  // UI - Plan editor
  planEditor: { ...defaultPlanEditor },
  planEditorOpen: false,
  planEditorSaving: false,

  // UI - Memory
  memoryRefresh: { ...defaultMemoryRefresh },
  memoryRefreshPreview: null,
  structuredPages: {},
  memoryFixListPages: {},
  memoryFixBusy: false,
  openPlotsLines: [],
  keyFactsLines: [],
  causalResultsLines: [],
  openPlotsAddedLines: [],
  openPlotsResolvedLines: [],
  memoryFixHints: [],
  memoryHistory: [],
  historyDialogOpen: false,

  // UI - Memory editor
  memoryEditor: null,
  memoryEditorBusy: false,

  // UI - Norm detail
  normDetailOpen: false,
  normDetailTitle: "",
  normDetailBody: "",

  // UI - Gen logs
  genLog: { ...defaultGenLog },
  genLogs: [],

  // UI - Intel panel
  latestWorkflow: null,
  memoryUpdateRuns: [],
  storyBibleSnapshot: null,
  retrievalIndexDocs: [],
  retrievalLogs: [],
  coreEvaluation: null,
  chapterJudge: null,
  intelWorkflowLoading: false,
  intelRetrievalLoading: false,
  intelJudgeLoading: false,

  // UI - Novel settings
  novelSettingsOpen: false,
  novelSettingsDraft: { ...defaultNovelSettings },
  novelSettingsBusy: false,

  // UI - Export
  exportDraft: { ...defaultExport },
  exportOpen: false,

  // UI - Refresh range
  refreshRangeOpen: false,
  refreshRange: { ...defaultRefreshRange },

  // UI - Framework wizard
  frameworkWizardOpen: false,

  // UI - LLM confirm
  llmConfirm: null,
  llmConfirmBusy: false,

  // UI - Edit content
  editTitle: "",
  editContent: "",

  // Actions
  setNovelId: (novelId) => set({ novelId }),
  setNovel: (novel) => set({ novel }),
  setChapters: (chapters) => set({ chapters }),
  setVolumes: (volumes) => set({ volumes }),
  setMemory: (memory) => set({ memory }),
  setMemoryNorm: (memoryNorm) => set({ memoryNorm }),
  setMemorySchemaGuide: (memorySchemaGuide) => set({ memorySchemaGuide }),
  setMemoryHealth: (memoryHealth) => set({ memoryHealth }),
  setActiveTab: (activeTab) => set({ activeTab }),
  setIsFullScreen: (isFullScreen) => set({ isFullScreen }),
  setStudioTreeSidebarCollapsed: (studioTreeSidebarCollapsed) => set({ studioTreeSidebarCollapsed }),
  setSelectedVolumeId: (selectedVolumeId) => set({ selectedVolumeId }),
  setSelectedChapterId: (selectedChapterId) => set({ selectedChapterId }),
  toggleExpandedVolumeId: (id) =>
    set((state) => ({
      expandedVolumeIds: {
        ...state.expandedVolumeIds,
        [id]: !state.expandedVolumeIds[id],
      },
    })),
  setBusy: (busy) => set({ busy }),
  setGenerateCount: (generateCount) => set({ generateCount }),
  setGenerateCountTouched: (generateCountTouched) => set({ generateCountTouched }),
  setGenerateTrace: (generateTrace) => set({ generateTrace }),
  setUseColdRecall: (useColdRecall) => set({ useColdRecall }),
  setColdRecallItems: (coldRecallItems) => set({ coldRecallItems }),
  setQueueStatus: (queueStatus) => set({ queueStatus }),
  setQueueStatusLoading: (queueStatusLoading) => set({ queueStatusLoading }),
  setTitleDraft: (titleDraft) => set({ titleDraft }),
  setTitleBusy: (titleBusy) => set({ titleBusy }),
  setErr: (err) => set({ err }),
  setNotice: (notice) => set({ notice }),
  setFocusModeIntroOpen: (focusModeIntroOpen) => set({ focusModeIntroOpen }),
  setFocusTaskBusy: (focusTaskBusy) => set({ focusTaskBusy }),
  setFocusReviseOpen: (focusReviseOpen) => set({ focusReviseOpen }),
  setContinueWriteOpen: (continueWriteOpen) => set({ continueWriteOpen }),
  setChapterChat: (partial) =>
    set((state) => ({ chapterChat: { ...state.chapterChat, ...partial } })),
  setArcsPanelVolumeNo: (arcsPanelVolumeNo) => set({ arcsPanelVolumeNo }),
  setArcsInstruction: (arcsInstruction) => set({ arcsInstruction }),
  setArcsBusy: (arcsBusy) => set({ arcsBusy }),
  setChapterVolumeId: (chapterVolumeId) => set({ chapterVolumeId }),
  setVolumePlan: (volumePlan) => set({ volumePlan }),
  setVolumeBusy: (volumeBusy) => set({ volumeBusy }),
  setVolumePlanBatchSize: (volumePlanBatchSize) => set({ volumePlanBatchSize }),
  setVolumePlanLastRun: (volumePlanLastRun) => set({ volumePlanLastRun }),
  setShowVolumePlanWithBody: (showVolumePlanWithBody) => set({ showVolumePlanWithBody }),
  setPlanEditor: (partial) =>
    set((state) => ({ planEditor: { ...state.planEditor, ...partial } })),
  setPlanEditorOpen: (planEditorOpen) => set({ planEditorOpen }),
  setPlanEditorSaving: (planEditorSaving) => set({ planEditorSaving }),
  setMemoryRefresh: (partial) =>
    set((state) => ({ memoryRefresh: { ...state.memoryRefresh, ...partial } })),
  setMemoryRefreshPreview: (memoryRefreshPreview) => set({ memoryRefreshPreview }),
  setStructuredPages: (structuredPages) => set({ structuredPages }),
  setMemoryFixListPages: (memoryFixListPages) => set({ memoryFixListPages }),
  setMemoryFixBusy: (memoryFixBusy) => set({ memoryFixBusy }),
  setOpenPlotsLines: (openPlotsLines) => set({ openPlotsLines }),
  setKeyFactsLines: (keyFactsLines) => set({ keyFactsLines }),
  setCausalResultsLines: (causalResultsLines) => set({ causalResultsLines }),
  setOpenPlotsAddedLines: (openPlotsAddedLines) => set({ openPlotsAddedLines }),
  setOpenPlotsResolvedLines: (openPlotsResolvedLines) => set({ openPlotsResolvedLines }),
  setMemoryFixHints: (memoryFixHints) => set({ memoryFixHints }),
  setMemoryHistory: (memoryHistory) => set({ memoryHistory }),
  setHistoryDialogOpen: (historyDialogOpen) => set({ historyDialogOpen }),
  setMemoryEditor: (memoryEditor) => set({ memoryEditor }),
  setMemoryEditorBusy: (memoryEditorBusy) => set({ memoryEditorBusy }),
  setNormDetailOpen: (normDetailOpen) => set({ normDetailOpen }),
  setNormDetailTitle: (normDetailTitle) => set({ normDetailTitle }),
  setNormDetailBody: (normDetailBody) => set({ normDetailBody }),
  setGenLog: (partial) =>
    set((state) => ({ genLog: { ...state.genLog, ...partial } })),
  setGenLogs: (genLogs) => set({ genLogs }),
  setLatestWorkflow: (latestWorkflow) => set({ latestWorkflow }),
  setMemoryUpdateRuns: (memoryUpdateRuns) => set({ memoryUpdateRuns }),
  setStoryBibleSnapshot: (storyBibleSnapshot) => set({ storyBibleSnapshot }),
  setRetrievalIndexDocs: (retrievalIndexDocs) => set({ retrievalIndexDocs }),
  setRetrievalLogs: (retrievalLogs) => set({ retrievalLogs }),
  setCoreEvaluation: (coreEvaluation) => set({ coreEvaluation }),
  setChapterJudge: (chapterJudge) => set({ chapterJudge }),
  setIntelWorkflowLoading: (intelWorkflowLoading) => set({ intelWorkflowLoading }),
  setIntelRetrievalLoading: (intelRetrievalLoading) => set({ intelRetrievalLoading }),
  setIntelJudgeLoading: (intelJudgeLoading) => set({ intelJudgeLoading }),
  setNovelSettingsOpen: (novelSettingsOpen) => set({ novelSettingsOpen }),
  setNovelSettingsDraft: (partial) =>
    set((state) => ({ novelSettingsDraft: { ...state.novelSettingsDraft, ...partial } })),
  setNovelSettingsBusy: (novelSettingsBusy) => set({ novelSettingsBusy }),
  setExportDraft: (partial) =>
    set((state) => ({ exportDraft: { ...state.exportDraft, ...partial } })),
  setExportOpen: (exportOpen) => set({ exportOpen }),
  setRefreshRangeOpen: (refreshRangeOpen) => set({ refreshRangeOpen }),
  setRefreshRange: (partial) =>
    set((state) => ({ refreshRange: { ...state.refreshRange, ...partial } })),
  setFrameworkWizardOpen: (frameworkWizardOpen) => set({ frameworkWizardOpen }),
  setLlmConfirm: (llmConfirm) => set({ llmConfirm }),
  setLlmConfirmBusy: (llmConfirmBusy) => set({ llmConfirmBusy }),
  setEditTitle: (editTitle) => set({ editTitle }),
  setEditContent: (editContent) => set({ editContent }),

  // Reset
  resetWorkspace: () =>
    set({
      novelId: "",
      novel: null,
      chapters: [],
      volumes: [],
      memory: null,
      memoryNorm: null,
      memorySchemaGuide: null,
      memoryHealth: null,
      activeTab: "studio",
      isFullScreen: false,
      studioTreeSidebarCollapsed: false,
      selectedVolumeId: "",
      selectedChapterId: "",
      expandedVolumeIds: {},
      busy: false,
      generateCount: 1,
      generateCountTouched: false,
      generateTrace: "",
      useColdRecall: false,
      coldRecallItems: 5,
      queueStatus: null,
      queueStatusLoading: false,
      titleDraft: "",
      titleBusy: false,
      err: null,
      notice: null,
      focusModeIntroOpen: false,
      focusTaskBusy: false,
      focusReviseOpen: false,
      continueWriteOpen: false,
      chapterChat: { ...defaultChapterChat },
      arcsPanelVolumeNo: 1,
      arcsInstruction: "",
      arcsBusy: false,
      chapterVolumeId: "",
      volumePlan: [],
      volumeBusy: false,
      volumePlanBatchSize: 10,
      volumePlanLastRun: null,
      showVolumePlanWithBody: false,
      planEditor: { ...defaultPlanEditor },
      planEditorOpen: false,
      planEditorSaving: false,
      memoryRefresh: { ...defaultMemoryRefresh },
      memoryRefreshPreview: null,
      structuredPages: {},
      memoryFixListPages: {},
      memoryFixBusy: false,
      openPlotsLines: [],
      keyFactsLines: [],
      causalResultsLines: [],
      openPlotsAddedLines: [],
      openPlotsResolvedLines: [],
      memoryFixHints: [],
      memoryHistory: [],
      historyDialogOpen: false,
      memoryEditor: null,
      memoryEditorBusy: false,
      normDetailOpen: false,
      normDetailTitle: "",
      normDetailBody: "",
      genLog: { ...defaultGenLog },
      genLogs: [],
      latestWorkflow: null,
      memoryUpdateRuns: [],
      storyBibleSnapshot: null,
      retrievalIndexDocs: [],
      retrievalLogs: [],
      coreEvaluation: null,
      chapterJudge: null,
      intelWorkflowLoading: false,
      intelRetrievalLoading: false,
      intelJudgeLoading: false,
      novelSettingsOpen: false,
      novelSettingsDraft: { ...defaultNovelSettings },
      novelSettingsBusy: false,
      exportDraft: { ...defaultExport },
      exportOpen: false,
      refreshRangeOpen: false,
      refreshRange: { ...defaultRefreshRange },
      frameworkWizardOpen: false,
      llmConfirm: null,
      llmConfirmBusy: false,
      editTitle: "",
      editContent: "",
    }),
}));
