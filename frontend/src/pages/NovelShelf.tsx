import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { BookOpen, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { deleteNovel, listNovels } from "@/services/novelApi";

export function NovelShelf() {
  const [items, setItems] = useState<
    Awaited<ReturnType<typeof listNovels>>
  >([]);
  const [err, setErr] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const reload = useCallback(() => {
    listNovels()
      .then(setItems)
      .catch((e: Error) => setErr(e.message));
  }, []);

  useEffect(() => {
    reload();
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
  const draftingCount = items.filter((item) => item.status !== "archived").length;

  return (
    <div className="novel-shell">
      <div className="novel-container space-y-6">
        <section className="glass-panel overflow-hidden p-6 md:p-8">
          <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-2xl space-y-4">
              <span className="glass-chip">
                <BookOpen className="size-3.5 text-primary" />
                小说工作区
              </span>
              <div className="space-y-2">
                <h1 className="text-3xl font-semibold tracking-tight text-foreground md:text-4xl">
                  把书架当作创作入口，而不是文件列表。
                </h1>
                <p className="max-w-xl text-sm leading-6 text-muted-foreground md:text-base">
                  在这里管理你的世界观、创作节奏和日更任务。每本书都保留独立的框架、章节与记忆，适合持续推进长篇。
                </p>
              </div>
              <div className="flex flex-wrap gap-3">
                <Button asChild size="lg" className="min-w-36">
                  <Link to="/novels/new">
                    <Plus className="size-4" />
                    新建小说
                  </Link>
                </Button>
                <Button asChild size="lg" variant="glass">
                  <Link to="/">返回首页</Link>
                </Button>
              </div>
            </div>
            <div className="grid min-w-[280px] flex-1 gap-3 sm:grid-cols-3">
              {[
                ["作品数", `${items.length}`],
                ["框架已确认", `${confirmedCount}`],
                ["创作中", `${draftingCount}`],
              ].map(([label, value]) => (
                <div key={label} className="glass-panel-subtle p-4">
                  <p className="text-xs text-muted-foreground">{label}</p>
                  <p className="mt-2 text-2xl font-semibold tracking-tight text-foreground">
                    {value}
                  </p>
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
        <section className="space-y-4">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="section-heading">你的作品</p>
              <p className="mt-1 text-sm text-muted-foreground">
                多用户隔离；每日自动章数在书中设置，需运行 Celery Worker + Beat。
              </p>
            </div>
            <div className="glass-chip">
              当前共 {items.length} 本作品
            </div>
          </div>
          {items.length === 0 ? (
            <Card className="overflow-hidden">
              <CardContent className="flex flex-col items-center gap-4 py-14 text-center">
                <div className="flex size-14 items-center justify-center rounded-2xl bg-primary/10 text-primary">
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
          <div className="grid gap-4 lg:grid-cols-2">
            {items.map((n) => (
              <Card
                key={n.id}
                className="group overflow-hidden border-border/70 hover:-translate-y-1 hover:border-primary/25 hover:shadow-[0_20px_60px_rgba(15,23,42,0.12)]"
              >
                <CardHeader className="pb-3">
                  <div className="flex items-start gap-4">
                    <div className="flex size-11 shrink-0 items-center justify-center rounded-2xl bg-primary/10 text-primary shadow-[inset_0_1px_0_rgba(255,255,255,0.5)]">
                      <BookOpen className="size-5" />
                    </div>
                    <div className="min-w-0 flex-1 space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="glass-chip px-2.5 py-1 text-[11px]">
                          {n.status}
                        </span>
                        <span className="glass-chip px-2.5 py-1 text-[11px]">
                          框架{n.framework_confirmed ? "已确认" : "未确认"}
                        </span>
                      </div>
                      <CardTitle className="text-xl">
                        <Link
                          to={`/novels/${n.id}`}
                          className="transition-colors group-hover:text-primary"
                        >
                          {n.title}
                        </Link>
                      </CardTitle>
                      <CardDescription className="line-clamp-3">
                        {n.intro || "还没有简介，可以先进入工作台补充世界观、人物与基调。"}
                      </CardDescription>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid gap-2 sm:grid-cols-3">
                    <div className="rounded-2xl border border-border/60 bg-background/55 px-3 py-2">
                      <p className="text-[11px] text-muted-foreground">创作状态</p>
                      <p className="mt-1 text-sm font-medium text-foreground">{n.status}</p>
                    </div>
                    <div className="rounded-2xl border border-border/60 bg-background/55 px-3 py-2">
                      <p className="text-[11px] text-muted-foreground">每日自动</p>
                      <p className="mt-1 text-sm font-medium text-foreground">
                        {n.daily_auto_chapters} 章
                      </p>
                    </div>
                    <div className="rounded-2xl border border-border/60 bg-background/55 px-3 py-2">
                      <p className="text-[11px] text-muted-foreground">入口</p>
                      <p className="mt-1 text-sm font-medium text-foreground">
                        工作台 / 章节 / 记忆
                      </p>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <Button asChild variant="glass">
                      <Link to={`/novels/${n.id}`}>进入工作台</Link>
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="destructive"
                      disabled={busyId === n.id}
                      onClick={() => void onDeleteNovel(n.id, n.title)}
                    >
                      {busyId === n.id ? "删除中…" : "删除作品"}
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
