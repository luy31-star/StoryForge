import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowRight,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Plus,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { AICreateWizard } from "@/components/AICreateWizard";
import {
  Card,
  CardContent,
  CardDescription,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { deleteNovel, listNovels, type ShelfNovel } from "@/services/novelApi";
import { relativeTimeAgo } from "@/lib/date";

const stageLabels = ["构思", "框架", "创作", "自动"] as const;

function stageForNovel(novel: ShelfNovel) {
  if (novel.status === "failed") {
    return {
      index: novel.framework_confirmed ? 2 : 1,
      label: novel.framework_confirmed ? "续写链路待修复" : "大纲构思受阻",
      hint: novel.framework_confirmed ? "正文或记忆同步中断" : "先回到向导确认大纲",
    };
  }
  if (!novel.framework_confirmed) {
    return { index: 1, label: "框架待确认", hint: "建议先锁定世界观、人物与节拍" };
  }
  if (novel.daily_auto_chapters > 0) {
    return { index: 3, label: "自动推进中", hint: `当前每日自动 ${novel.daily_auto_chapters} 章` };
  }
  return { index: 2, label: "手动创作中", hint: "适合集中修订正文、节奏与记忆" };
}

function NovelStageRail({
  activeIndex,
  hint,
  compact = false,
}: {
  activeIndex: number;
  hint?: string;
  compact?: boolean;
}) {
  return (
    <div className={`rounded-lg border border-border bg-secondary/50 ${compact ? "p-3" : "p-4"}`}>
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-medium text-foreground">创作路径</p>
        {hint ? <span className="font-mono text-xs text-muted-foreground">{hint}</span> : null}
      </div>
      <div className="mt-3 grid grid-cols-4 gap-1.5">
        {stageLabels.map((label, index) => (
          <div
            key={`${label}-${index}`}
            className={`rounded-md border px-2.5 py-2 ${
              index <= activeIndex
                ? "border-foreground/20 bg-background"
                : "border-border bg-secondary/30"
            }`}
          >
            <div
              className={`h-1 rounded-full ${
                index <= activeIndex ? "bg-foreground" : "bg-border"
              }`}
            />
            <p className="mt-1.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
              {label}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

export function NovelShelf() {
  const navigate = useNavigate();
  const [items, setItems] = useState<ShelfNovel[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(12);
  const [searchInput, setSearchInput] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const [aiCreateOpen, setAiCreateOpen] = useState(false);
  const [taskStartedOpen, setTaskStartedOpen] = useState(false);
  const [spotlightIntroExpanded, setSpotlightIntroExpanded] = useState(false);
  const [expandedIntroIds, setExpandedIntroIds] = useState<Record<string, boolean>>({});

  const reload = useCallback(async () => {
    try {
      setErr(null);
      const data = await listNovels({
        q: searchKeyword,
        status: statusFilter,
        page,
        page_size: pageSize,
      });
      setItems(data.items);
      setTotal(data.total);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "加载作品失败");
    }
  }, [page, pageSize, searchKeyword, statusFilter]);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function onDeleteNovel(id: string, title: string) {
    const ok = window.confirm(`确认删除《${title}》？\n此操作会删除章节与记忆，且不可恢复。`);
    if (!ok) return;
    setErr(null);
    setBusyId(id);
    try {
      await deleteNovel(id);
      await reload();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "删除失败");
    } finally {
      setBusyId(null);
    }
  }

  const confirmedCount = items.filter((item) => item.framework_confirmed).length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const activeAutomationCount = useMemo(
    () => items.filter((item) => item.daily_auto_chapters > 0).length,
    [items]
  );
  const totalAutoChapters = useMemo(
    () => items.reduce((sum, item) => sum + Math.max(0, item.daily_auto_chapters || 0), 0),
    [items]
  );
  const failedCount = useMemo(
    () => items.filter((item) => item.status === "failed").length,
    [items]
  );
  const spotlightNovel = useMemo(() => {
    return [...items].sort((a, b) => {
      const aTime = a.updated_at ? Date.parse(a.updated_at) : 0;
      const bTime = b.updated_at ? Date.parse(b.updated_at) : 0;
      return bTime - aTime;
    })[0] ?? null;
  }, [items]);
  const spotlightStage = spotlightNovel ? stageForNovel(spotlightNovel) : null;

  useEffect(() => {
    setSpotlightIntroExpanded(false);
  }, [spotlightNovel?.id]);

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages);
    }
  }, [page, totalPages]);

  function submitSearch() {
    setPage(1);
    setSearchKeyword(searchInput.trim());
  }

  return (
    <div className="novel-shell">
      <div className="novel-container space-y-6">
        {/* Hero section */}
        <section className="glass-panel p-6 md:p-8">
          <div className="grid gap-6 xl:grid-cols-[1.02fr_0.98fr]">
            <div className="space-y-5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="glass-chip">
                  <Sparkles className="size-3" />
                  小说书架
                </span>
              </div>

              <div className="space-y-3">
                <h1 className="max-w-3xl text-3xl font-semibold tracking-[-0.03em] text-foreground md:text-5xl">
                  把书架做成
                  <span className="text-primary">创作控制台</span>
                  ，而不是文件列表。
                </h1>
                <p className="max-w-2xl text-sm leading-7 text-muted-foreground md:text-base">
                  在这里一眼看出每本书处在哪个阶段、有没有自动推进、哪本书最近最活跃。
                </p>
              </div>

              <div className="flex flex-wrap gap-3">
                <Button asChild size="lg">
                  <Link to="/novels/new">
                    <Plus className="size-4" />
                    新建小说
                  </Link>
                </Button>
                <Button size="lg" variant="secondary" onClick={() => setAiCreateOpen(true)}>
                  一键AI建书
                </Button>
                <Button asChild size="lg" variant="outline">
                  <Link to="/">返回首页</Link>
                </Button>
              </div>

              <div className="grid gap-3 sm:grid-cols-3">
                {[
                  ["作品总数", `${total}`, "当前查询结果下的作品总数"],
                  ["本页可推进", `${confirmedCount}`, "当前页已确认框架的作品"],
                  ["本页自动推进", `${activeAutomationCount}`, `当前页累计每日 ${totalAutoChapters} 章`],
                ].map(([label, value, hint]) => (
                  <div key={label} className="glass-panel-subtle p-4">
                    <p className="mono-label">{label}</p>
                    <p className="mt-2 text-2xl font-semibold tracking-tight text-foreground">
                      {value}
                    </p>
                    <p className="mt-1 text-sm text-muted-foreground">{hint}</p>
                  </div>
                ))}
              </div>
              {failedCount > 0 ? (
                <div className="status-badge border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400">
                  当前有 {failedCount} 本作品需要排障
                </div>
              ) : null}
            </div>

            {/* Spotlight novel */}
            <div>
              {spotlightNovel ? (
                <div className="overflow-hidden rounded-lg border border-border bg-card p-5 sm:p-6">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="mono-label">焦点作品</p>
                      <h2 className="mt-2 text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
                        《{spotlightNovel.title}》
                      </h2>
                    </div>
                    <span className="rounded border border-border bg-secondary px-2.5 py-1 font-mono text-xs text-muted-foreground">
                      {spotlightStage?.label}
                    </span>
                  </div>

                  <p className="mt-4 max-w-2xl text-sm leading-7 text-muted-foreground">
                    <span className={spotlightIntroExpanded ? "whitespace-pre-wrap" : "line-clamp-4"}>
                      {spotlightNovel.intro || "还没有简介。你可以进入工作台先补全主线、人物和核心冲突。"}
                    </span>
                  </p>
                  <button
                    type="button"
                    className="mt-1 text-xs font-medium text-primary underline-offset-4 hover:underline"
                    onClick={() => setSpotlightIntroExpanded((v) => !v)}
                  >
                    {spotlightIntroExpanded ? "收起简介" : "展开全文"}
                  </button>

                  <div className="mt-5">
                    <NovelStageRail
                      activeIndex={spotlightStage?.index ?? 0}
                      hint={spotlightStage?.hint}
                    />
                  </div>

                  <div className="mt-4 flex flex-wrap gap-2 text-xs text-muted-foreground">
                    <span className="status-badge">
                      目标 {spotlightNovel.target_chapters} 章 · {spotlightNovel.length_tag}
                    </span>
                    <span className="status-badge">
                      {spotlightNovel.daily_auto_chapters > 0
                        ? `自动 ${spotlightNovel.daily_auto_chapters} 章 / 天`
                        : "手动推进"}
                    </span>
                    <span className="status-badge">
                      最近活动 {relativeTimeAgo(spotlightNovel.updated_at)}
                    </span>
                  </div>

                  <div className="mt-5 flex flex-wrap items-center gap-3">
                    <Button asChild>
                      <Link to={`/novels/${spotlightNovel.id}`}>
                        进入工作台
                        <ArrowRight className="size-4" />
                      </Link>
                    </Button>
                    {!spotlightNovel.framework_confirmed ? (
                      <Button asChild variant="outline">
                        <Link to={`/novels/${spotlightNovel.id}?wizard=1`}>确认框架</Link>
                      </Button>
                    ) : null}
                  </div>
                </div>
              ) : (
                <Card className="h-full">
                  <CardContent className="flex h-full flex-col items-center justify-center gap-4 py-16 text-center">
                    <div className="flex size-14 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                      <BookOpen className="size-6" />
                    </div>
                    <div className="space-y-2">
                      <p className="text-lg font-semibold text-foreground">书架还没有作品</p>
                      <p className="text-sm text-muted-foreground">
                        新建一本书后，这里会出现最近最活跃的作品和整座书架的节奏概览。
                      </p>
                    </div>
                  </CardContent>
                </Card>
              )}
            </div>
          </div>
        </section>

        {/* Error */}
        {err ? (
          <div className="flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
            {err}
          </div>
        ) : null}

        {/* Novel list */}
        <section className="space-y-4">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="section-heading">你的作品</p>
              <p className="mt-1 text-sm text-muted-foreground">
                支持按标题、简介和状态快速筛选。
              </p>
            </div>
            <span className="font-mono text-xs text-muted-foreground">
              共 {total} 本作品
            </span>
          </div>

          {/* Search/filter bar */}
          <div className="glass-panel-subtle p-4">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-end">
              <div className="flex-1">
                <Label htmlFor="novel-search">搜索</Label>
                <div className="mt-2 flex gap-2">
                  <Input
                    id="novel-search"
                    value={searchInput}
                    onChange={(e) => setSearchInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        submitSearch();
                      }
                    }}
                    placeholder="搜索标题或简介"
                    className="h-10"
                  />
                  <Button type="button" onClick={submitSearch}>
                    查询
                  </Button>
                </div>
              </div>
              <div className="w-full lg:w-56">
                <Label htmlFor="novel-status">状态</Label>
                <select
                  id="novel-status"
                  value={statusFilter}
                  onChange={(e) => {
                    setPage(1);
                    setStatusFilter(e.target.value);
                  }}
                  className="mt-2 flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <option value="">全部状态</option>
                  <option value="draft">草稿</option>
                  <option value="active">进行中</option>
                  <option value="failed">失败</option>
                </select>
              </div>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setSearchInput("");
                  setSearchKeyword("");
                  setStatusFilter("");
                  setPage(1);
                }}
              >
                清空筛选
              </Button>
            </div>
          </div>

          {/* Empty states */}
          {total === 0 ? (
            <Card className="overflow-hidden">
              <CardContent className="flex flex-col items-center gap-4 py-14 text-center">
                <div className="flex size-14 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                  <BookOpen className="size-6" />
                </div>
                <div className="space-y-1">
                  <p className="text-lg font-semibold tracking-tight text-foreground">
                    还没有开始中的作品
                  </p>
                  <p className="text-sm text-muted-foreground">
                    从一本新小说开始，先确定标题和框架，再逐步生成卷计划、章节与记忆。
                  </p>
                </div>
                <Button asChild>
                  <Link to="/novels/new">
                    <Plus className="size-4" />
                    创建第一本小说
                  </Link>
                </Button>
              </CardContent>
            </Card>
          ) : null}
          {total > 0 && items.length === 0 ? (
            <Card className="overflow-hidden">
              <CardContent className="flex flex-col items-center gap-3 py-14 text-center">
                <p className="text-lg font-semibold tracking-tight text-foreground">没有匹配的作品</p>
                <p className="text-sm text-muted-foreground">试试更短的关键词，或者切换状态筛选。</p>
              </CardContent>
            </Card>
          ) : null}

          {/* Novel cards */}
          <div className="grid gap-4 lg:grid-cols-2">
            {items.map((n) => {
              const stage = stageForNovel(n);
              const statusLabel =
                n.status === "failed"
                  ? n.framework_confirmed ? "续写 / 同步失败" : "建书构思失败"
                  : n.status;

              return (
                <div
                  key={n.id}
                  className={`group list-card overflow-hidden ${
                    n.status === "failed" ? "border-destructive/30" : ""
                  }`}
                >
                  {/* Card header */}
                  <div className="border-b border-border px-5 py-4">
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0 flex-1 space-y-2">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="rounded border border-border bg-secondary px-2 py-0.5 font-mono text-[11px] text-muted-foreground">
                            {n.length_tag}
                          </span>
                          <span
                            className={`rounded border px-2 py-0.5 font-mono text-[11px] ${
                              n.status === "failed"
                                ? "border-destructive/30 bg-destructive/5 text-destructive"
                                : "border-border bg-secondary text-muted-foreground"
                            }`}
                          >
                            {statusLabel}
                          </span>
                        </div>
                        <CardTitle className="text-xl font-semibold tracking-tight">
                          <Link
                            to={`/novels/${n.id}`}
                            className="transition-colors group-hover:text-primary"
                          >
                            {n.title}
                          </Link>
                        </CardTitle>
                        <CardDescription className="text-sm text-muted-foreground">
                          <span
                            className={
                              expandedIntroIds[n.id] ? "whitespace-pre-wrap" : "line-clamp-2"
                            }
                          >
                            {n.intro || "还没有简介，可以先进入工作台补充世界观、人物与主线冲突。"}
                          </span>
                        </CardDescription>
                        <button
                          type="button"
                          className="text-xs font-medium text-primary underline-offset-4 hover:underline"
                          onClick={() =>
                            setExpandedIntroIds((prev) => ({ ...prev, [n.id]: !prev[n.id] }))
                          }
                        >
                          {expandedIntroIds[n.id] ? "收起简介" : "展开全文"}
                        </button>
                      </div>

                      <div className="shrink-0 rounded-md border border-border bg-secondary/50 px-3 py-2 text-right">
                        <p className="mono-label">最近活动</p>
                        <p className="mt-1 inline-flex items-center gap-1.5 text-sm font-medium text-foreground">
                          <Clock3 className="size-3" />
                          {relativeTimeAgo(n.updated_at)}
                        </p>
                      </div>
                    </div>
                  </div>

                  {/* Card body */}
                  <div className="space-y-3 p-5">
                    <div className="flex flex-wrap gap-1.5">
                      <span className="status-badge">目标 {n.target_chapters} 章</span>
                      <span className="status-badge">
                        {n.daily_auto_chapters > 0 ? `自动 ${n.daily_auto_chapters} 章 / 天` : "手动推进"}
                      </span>
                      <span className="status-badge">{stage.label}</span>
                    </div>
                    <NovelStageRail activeIndex={stage.index} hint={stage.hint} compact />

                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="flex flex-wrap gap-2">
                        <Button asChild variant="secondary">
                          <Link to={`/novels/${n.id}`}>
                            {n.status === "failed" ? "查看失败详情" : "进入工作台"}
                            <ArrowRight className="size-4" />
                          </Link>
                        </Button>
                        {!n.framework_confirmed && (
                          <Button asChild variant="outline">
                            <Link to={`/novels/${n.id}?wizard=1`}>修改框架</Link>
                          </Button>
                        )}
                      </div>
                      <Button
                        type="button"
                        size="sm"
                        variant="destructive"
                        disabled={busyId === n.id}
                        onClick={() => void onDeleteNovel(n.id, n.title)}
                      >
                        {busyId === n.id ? "删除中…" : "删除"}
                      </Button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Pagination */}
          {total > 0 ? (
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="font-mono text-xs text-muted-foreground">
                第 {page} / {totalPages} 页
              </div>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  disabled={page <= 1}
                  onClick={() => setPage((prev) => Math.max(1, prev - 1))}
                >
                  <ChevronLeft className="size-4" />
                  上一页
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={page >= totalPages}
                  onClick={() => setPage((prev) => Math.min(totalPages, prev + 1))}
                >
                  下一页
                  <ChevronRight className="size-4" />
                </Button>
              </div>
            </div>
          ) : null}
        </section>
      </div>

      {/* AI Create Wizard */}
      <AICreateWizard
        open={aiCreateOpen}
        onOpenChange={setAiCreateOpen}
        onCreated={(novelId) => {
          setAiCreateOpen(false);
          setTaskStartedOpen(true);
          reload();
          navigate(`/novels/${novelId}`);
        }}
      />

      {/* Task started dialog */}
      <Dialog open={taskStartedOpen} onOpenChange={setTaskStartedOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-lg">
              <Sparkles className="size-4 text-primary" />
              任务已在后台启动
            </DialogTitle>
            <DialogDescription className="pt-2 leading-relaxed">
              AI 正在为你构思小说设定与大纲。此过程可能需要几十秒，你可以留在本页等待刷新，也可以前往「我的任务」模块查看详细进度。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" onClick={() => setTaskStartedOpen(false)}>
              留在本页
            </Button>
            <Button onClick={() => { setTaskStartedOpen(false); navigate("/tasks"); }}>
              前往我的任务
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
