/**
 * Hook for polling novel queue status.
 */
import { useCallback, useEffect } from "react";
import { getNovelQueueStatus } from "@/services/novelApi";
import { useNovelWorkspaceStore } from "@/stores/novelWorkspaceStore";

export function useQueueStatus() {
  const setQueueStatus = useNovelWorkspaceStore((s) => s.setQueueStatus);
  const setQueueStatusLoading = useNovelWorkspaceStore((s) => s.setQueueStatusLoading);

  const reload = useCallback(async () => {
    setQueueStatusLoading(true);
    try {
      const status = await getNovelQueueStatus();
      setQueueStatus(status);
    } catch {
      setQueueStatus(null);
    } finally {
      setQueueStatusLoading(false);
    }
  }, [setQueueStatus, setQueueStatusLoading]);

  useEffect(() => {
    void reload();
    const timer = window.setInterval(() => {
      void reload();
    }, 15000);
    return () => window.clearInterval(timer);
  }, [reload]);

  return { reload };
}
