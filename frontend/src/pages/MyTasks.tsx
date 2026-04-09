import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { XCircle, ArrowUpRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cancelTask, listMyTasks, type UserTaskRow } from "@/services/taskApi";

function statusLabel(s: string) {
  if (s === "queued") return "排队中";
  if (s === "started") return "执行中";
  if (s === "cancel_requested") return "取消中";
  if (s === "done") return "已完成";
  if (s === "failed") return "失败";
  if (s === "cancelled") return "已取消";
  if (s === "skipped") return "已跳过";
  return s || "-";
}

function isRunning(s: string) {
  return s === "queued" || s === "started" || s === "cancel_requested";
}

export function MyTasks() {
  const [items, setItems] = useState<UserTaskRow[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const reload = useCallback(() => {
    listMyTasks(80)
      .then((r) => setItems(r.items || []))
      .catch((e: Error) => setErr(e.message));
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const hasRunning = useMemo(() => items.some((t) => isRunning(t.status)), [items]);

  useEffect(() => {
    if (!hasRunning) return;
    const t = window.setInterval(() => reload(), 3000);
    return () => window.clearInterval(t);
  }, [hasRunning, reload]);

  async function onCancelTask(t: UserTaskRow) {
    const ok = window.confirm(`确认结束任务「${t.title || t.kind}」？`);
    if (!ok) return;
    setErr(null);
    setBusyId(t.id);
    try {
      await cancelTask(t.id);
      reload();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "结束任务失败");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="novel-shell">
      <div className="novel-container space-y-6">
        <section className="glass-panel overflow-hidden p-6 md:p-8">
          <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
            <div className="space-y-2">
              <h1 className="text-2xl font-semibold tracking-tight text-foreground md:text-3xl">
                我的任务
              </h1>
              <p className="text-sm text-foreground/70 dark:text-muted-foreground font-medium">
                这里展示你发起的后台任务（如一键续写、一键建书、生成章计划）。离开页面不会中断任务。
              </p>
            </div>
            <Button
              type="button"
              variant="secondary"
              className="font-bold"
              onClick={() => reload()}
              disabled={Boolean(busyId)}
            >
              刷新
            </Button>
          </div>
          {err ? (
            <div className="mt-4 rounded-2xl border border-red-500/30 bg-red-500/10 p-3 text-sm font-semibold text-red-700 dark:text-red-200">
              {err}
            </div>
          ) : null}
        </section>

        <section className="glass-panel p-6 md:p-8">
          {items.length === 0 ? (
            <p className="text-sm text-foreground/70 dark:text-muted-foreground font-medium">
              暂无任务。
            </p>
          ) : (
            <div className="space-y-3">
              {items.map((t) => {
                const latest = t.latest_log;
                const msg = (latest?.message || t.last_message || "").trim();
                const canCancel = isRunning(t.status);
                return (
                  <div
                    key={t.id}
                    className="glass-panel-subtle flex flex-col gap-3 p-4 md:flex-row md:items-center md:justify-between"
                  >
                    <div className="min-w-0 space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="glass-chip font-bold">{statusLabel(t.status)}</span>
                        <span className="text-sm font-bold text-foreground truncate">
                          {t.title || t.kind}
                        </span>
                        {t.novel_id ? (
                          <Link
                            to={`/novels/${t.novel_id}`}
                            className="inline-flex items-center gap-1 text-xs font-bold text-primary"
                          >
                            打开小说 <ArrowUpRight className="size-3.5" />
                          </Link>
                        ) : null}
                      </div>
                      {msg ? (
                        <p className="text-xs text-foreground/70 dark:text-muted-foreground font-medium break-words">
                          {msg}
                        </p>
                      ) : (
                        <p className="text-xs text-foreground/50 dark:text-muted-foreground font-medium">
                          —
                        </p>
                      )}
                      {t.created_at ? (
                        <p className="text-[11px] text-foreground/50 dark:text-muted-foreground font-medium">
                          创建于 {new Date(t.created_at).toLocaleString()}
                        </p>
                      ) : null}
                    </div>
                    <div className="flex items-center gap-2 self-end md:self-auto">
                      <Button
                        type="button"
                        size="sm"
                        variant="secondary"
                        className="font-bold"
                        disabled={!canCancel || busyId === t.id}
                        onClick={() => onCancelTask(t)}
                      >
                        <XCircle className="mr-1 size-4" />
                        结束任务
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

