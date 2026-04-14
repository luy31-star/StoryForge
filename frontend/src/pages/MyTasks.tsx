import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import {
  cancelTask,
  deleteTask,
  listMyTasks,
  type UserTaskRow,
} from "@/services/taskApi";
import { Trash2, XCircle, ArrowUpRight, ChevronLeft, ChevronRight } from "lucide-react";

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

const PAGE_SIZE = 20;

export function MyTasks() {
  const [items, setItems] = useState<UserTaskRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [err, setErr] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const reload = useCallback(() => {
    listMyTasks(PAGE_SIZE, (page - 1) * PAGE_SIZE)
      .then((r) => {
        setItems(r.items || []);
        setTotal(r.total || 0);
      })
      .catch((e: Error) => setErr(e.message));
  }, [page]);

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

  async function onDeleteTask(t: UserTaskRow) {
    const ok = window.confirm(`确认删除已结束的任务记录「${t.title || t.kind}」？`);
    if (!ok) return;
    setErr(null);
    setBusyId(t.id);
    try {
      await deleteTask(t.id);
      if (items.length === 1 && page > 1) {
        setPage(page - 1);
      } else {
        reload();
      }
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "删除任务失败");
    } finally {
      setBusyId(null);
    }
  }

  const totalPages = Math.ceil(total / PAGE_SIZE);

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
            <div className="flex items-center gap-2">
              <span className="text-xs text-foreground/50 font-bold mr-2">共 {total} 个记录</span>
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
                const running = isRunning(t.status);
                return (
                  <div
                    key={t.id}
                    className="glass-panel-subtle flex flex-col gap-3 p-4 md:flex-row md:items-center md:justify-between"
                  >
                    <div className="min-w-0 space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={`glass-chip font-bold ${
                          t.status === "done" ? "bg-green-500/10 text-green-600 border-green-500/20" :
                          t.status === "failed" ? "bg-red-500/10 text-red-600 border-red-500/20" : ""
                        }`}>
                          {statusLabel(t.status)}
                        </span>
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
                      {running ? (
                        <Button
                          type="button"
                          size="sm"
                          variant="secondary"
                          className="font-bold"
                          disabled={busyId === t.id}
                          onClick={() => onCancelTask(t)}
                        >
                          <XCircle className="mr-1 size-4" />
                          结束任务
                        </Button>
                      ) : (
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          className="text-destructive hover:bg-destructive/10 hover:text-destructive font-bold"
                          disabled={busyId === t.id}
                          onClick={() => onDeleteTask(t)}
                        >
                          <Trash2 className="mr-1 size-4" />
                          删除记录
                        </Button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {totalPages > 1 && (
            <div className="mt-8 hidden items-center justify-center gap-4 md:flex">
              <Button
                variant="outline"
                size="sm"
                className="font-bold"
                disabled={page <= 1}
                onClick={() => setPage(page - 1)}
              >
                <ChevronLeft className="mr-1 size-4" />
                上一页
              </Button>
              <span className="text-sm font-bold text-foreground/70">
                第 {page} / {totalPages} 页
              </span>
              <Button
                variant="outline"
                size="sm"
                className="font-bold"
                disabled={page >= totalPages}
                onClick={() => setPage(page + 1)}
              >
                下一页
                <ChevronRight className="ml-1 size-4" />
              </Button>
            </div>
          )}
        </section>
      </div>

      <div className="fixed inset-x-0 bottom-0 z-30 border-t border-border/70 bg-background/92 pb-[calc(env(safe-area-inset-bottom)+0.75rem)] pt-3 shadow-[0_-12px_30px_rgba(15,23,42,0.08)] backdrop-blur-xl md:hidden">
        <div className="novel-container space-y-2 px-4">
          <p className="text-[11px] font-medium text-foreground/60">
            {hasRunning ? "存在进行中的后台任务，列表会自动刷新" : `当前共 ${total} 条任务记录`}
          </p>
          <div className={`grid gap-2 ${totalPages > 1 ? "grid-cols-[auto_1fr_auto]" : "grid-cols-1"}`}>
            {totalPages > 1 ? (
              <>
                <Button
                  variant="outline"
                  className="font-semibold"
                  disabled={page <= 1}
                  onClick={() => setPage(page - 1)}
                >
                  上一页
                </Button>
                <Button
                  variant="secondary"
                  className="font-bold"
                  disabled={Boolean(busyId)}
                  onClick={() => reload()}
                >
                  刷新 · {page}/{totalPages}
                </Button>
                <Button
                  variant="outline"
                  className="font-semibold"
                  disabled={page >= totalPages}
                  onClick={() => setPage(page + 1)}
                >
                  下一页
                </Button>
              </>
            ) : (
              <Button
                variant="secondary"
                className="font-bold"
                disabled={Boolean(busyId)}
                onClick={() => reload()}
              >
                刷新任务列表
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
