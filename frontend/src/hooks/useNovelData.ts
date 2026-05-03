/**
 * Hook for loading novel, chapters, volumes, memory, and intel data.
 */
import { useCallback, useEffect, useMemo } from "react";
import {
  getNovel,
  listChapters,
  getMemory,
  getMemoryNormalized,
  listVolumes,
  listVolumeChapterPlan,
  getLatestChapterJudge,
  getLatestWorkflowRun,
  listRetrievalLogs,
  getNovelCoreEvaluation,
  listMemoryUpdateRuns,
  getLatestStoryBibleSnapshot,
  getRetrievalIndexSnapshot,
} from "@/services/novelApi";
import { useNovelWorkspaceStore } from "@/stores/novelWorkspaceStore";

export function useNovelData(novelId: string) {
  const {
    chapters, memoryNorm,
    selectedVolumeId, selectedChapterId,
    setNovel, setChapters, setVolumes, setMemory, setMemoryNorm,
    setMemorySchemaGuide, setMemoryHealth,
    setSelectedVolumeId, setVolumePlan, setVolumeBusy,
    setLatestWorkflow, setMemoryUpdateRuns, setStoryBibleSnapshot,
    setRetrievalIndexDocs, setRetrievalLogs, setCoreEvaluation,
    setChapterJudge,
    setIntelWorkflowLoading, setIntelRetrievalLoading, setIntelJudgeLoading,
    setErr, setTitleDraft,
    setShowVolumePlanWithBody, setStructuredPages,
    toggleExpandedVolumeId,
  } = useNovelWorkspaceStore();

  // We use setState directly for fields not in the typed store interface
  const setFrameworkState = useCallback((fwMd: string, fwJson: string) => {
    useNovelWorkspaceStore.setState({ fwMd, fwJson } as unknown as Parameters<typeof useNovelWorkspaceStore.setState>[0]);
  }, []);

  // Primary reload: novel + chapters + memory + intel data
  const reload = useCallback(async () => {
    if (!novelId) return;
    setIntelWorkflowLoading(true);
    setIntelRetrievalLoading(true);
    try {
      const [n, c, m, mn, workflowRes, retrievalRes, evalRes, updateRunsRes, storyBibleRes, retrievalIndexRes] =
        await Promise.all([
          getNovel(novelId),
          listChapters(novelId),
          getMemory(novelId),
          getMemoryNormalized(novelId).catch(() => ({ status: "empty" as const, data: null })),
          getLatestWorkflowRun(novelId).catch(() => ({ status: "ok" as const, item: null })),
          listRetrievalLogs(novelId, 6).catch(() => ({ status: "ok" as const, items: [] })),
          getNovelCoreEvaluation(novelId).catch(() => null),
          listMemoryUpdateRuns(novelId, 12).catch(() => ({ status: "ok" as const, items: [] })),
          getLatestStoryBibleSnapshot(novelId, { entityLimit: 16, factLimit: 16 }).catch(() => ({
            status: "ok" as const,
            item: null,
          })),
          getRetrievalIndexSnapshot(novelId, 16).catch(() => ({ status: "ok" as const, items: [] })),
        ]);
      setNovel(n as never);
      setChapters(c);
      setMemory(m);
      const normalizedSchemaGuide = "schema_guide" in mn ? (mn.schema_guide ?? null) : null;
      const normalizedHealth = "health" in mn ? (mn.health ?? null) : null;
      setMemorySchemaGuide(normalizedSchemaGuide ?? m.schema_guide ?? null);
      setMemoryHealth(normalizedHealth ?? m.health ?? null);
      if (mn.status === "ok" && mn.data) {
        setMemoryNorm(mn.data);
      } else {
        setMemoryNorm(null);
      }
      const nRecord = n as Record<string, unknown>;
      setFrameworkState(
        String(nRecord.framework_markdown ?? ""),
        String((nRecord.framework_json_base as string) ?? nRecord.framework_json ?? "{}")
      );
      setTitleDraft(String(nRecord.title ?? ""));
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
  }, [novelId]);

  // Reload volumes
  const reloadVolumes = useCallback(async () => {
    if (!novelId) return;
    const vs = await listVolumes(novelId);
    setVolumes(vs);
    const state = useNovelWorkspaceStore.getState();
    const current = state.selectedVolumeId;
    // workspaceRootBook is local state in the component, default to false
    const rootBook = false;
    if (vs.length === 0) {
      setSelectedVolumeId("");
    } else if (rootBook) {
      setSelectedVolumeId(current && vs.some((x) => x.id === current) ? current : "");
    } else {
      setSelectedVolumeId(current && vs.some((x) => x.id === current) ? current : vs[0].id);
    }
  }, [novelId]);

  // Load volume chapter plan when selected volume changes
  useEffect(() => {
    if (!novelId || !selectedVolumeId) {
      setVolumePlan([]);
      return;
    }
    setVolumeBusy(true);
    setErr(null);
    listVolumeChapterPlan(novelId, selectedVolumeId)
      .then((plan) => setVolumePlan(plan as Record<string, unknown>[]))
      .catch(() => setVolumePlan([]))
      .finally(() => setVolumeBusy(false));
  }, [novelId, selectedVolumeId]);

  // Load chapter judge when selected chapter changes
  const selectedChapter = useMemo(
    () => chapters.find((c) => c.id === selectedChapterId) ?? null,
    [chapters, selectedChapterId]
  );

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

  // Auto-expand selected volume in sidebar
  useEffect(() => {
    if (!selectedVolumeId) return;
    toggleExpandedVolumeId(selectedVolumeId);
  }, [selectedVolumeId]);

  // Reset showVolumePlanWithBody when volume changes
  useEffect(() => {
    setShowVolumePlanWithBody(false);
  }, [selectedVolumeId]);

  // Reset structuredPages when memory version changes
  useEffect(() => {
    setStructuredPages({});
  }, [memoryNorm?.memory_version]);

  // Initial load
  useEffect(() => {
    if (!novelId) return;
    reload().catch((e: Error) => setErr(e.message));
  }, [novelId, reload]);

  useEffect(() => {
    if (!novelId) return;
    void reloadVolumes().catch(() => null);
  }, [novelId, reloadVolumes]);

  return { reload, reloadVolumes, selectedChapter };
}
