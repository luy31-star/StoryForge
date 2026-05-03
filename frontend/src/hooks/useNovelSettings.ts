/**
 * Hook for novel settings dialog operations.
 */
import { useCallback } from "react";
import { patchNovel } from "@/services/novelApi";
import { useNovelWorkspaceStore } from "@/stores/novelWorkspaceStore";
import type { NovelDetail } from "@/types/novel";

export function useNovelSettings(reload: () => Promise<void>, reloadVolumes: () => Promise<void>) {
  const novel = useNovelWorkspaceStore((s) => s.novel);
  const setNovelSettingsDraft = useNovelWorkspaceStore((s) => s.setNovelSettingsDraft);
  const setNovelSettingsOpen = useNovelWorkspaceStore((s) => s.setNovelSettingsOpen);
  const setNovelSettingsBusy = useNovelWorkspaceStore((s) => s.setNovelSettingsBusy);
  const setErr = useNovelWorkspaceStore((s) => s.setErr);
  const setNotice = useNovelWorkspaceStore((s) => s.setNotice);

  const openSettings = useCallback(() => {
    if (!novel) return;
    const n = novel as NovelDetail;
    setNovelSettingsDraft({
      target_chapters: Number(n.target_chapters || 300),
      daily_auto_chapters: Number(n.daily_auto_chapters || 0),
      daily_auto_time: String(n.daily_auto_time || "14:30"),
      chapter_target_words: Number(n.chapter_target_words || 3000),
      auto_consistency_check: Boolean(n.auto_consistency_check),
      auto_plan_guard_check: Boolean(n.auto_plan_guard_check || n.auto_plan_guard_fix),
      auto_plan_guard_fix: Boolean(n.auto_plan_guard_fix),
      auto_style_polish: Boolean(n.auto_style_polish),
      style: String(n.style || ""),
      writing_style_id: String(n.writing_style_id || ""),
      framework_model: String(n.framework_model || ""),
      plan_model: String(n.plan_model || ""),
      chapter_model: String(n.chapter_model || ""),
    });
    setNovelSettingsOpen(true);
  }, [novel, setNovelSettingsDraft, setNovelSettingsOpen]);

  const saveSettings = useCallback(async () => {
    if (!novel) return;
    setNovelSettingsBusy(true);
    setErr(null);
    try {
      const draft = useNovelWorkspaceStore.getState().novelSettingsDraft;
      await patchNovel((novel as NovelDetail).id, draft);
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
  }, [novel, reload, reloadVolumes, setErr, setNotice, setNovelSettingsBusy, setNovelSettingsOpen]);

  return { openSettings, saveSettings };
}
