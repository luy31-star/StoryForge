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

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="mx-auto max-w-3xl space-y-6">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">小说书架</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              单用户本地创作；每日自动章数在书中设置，需运行 Celery Worker + Beat。
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" asChild>
              <Link to="/settings">设置</Link>
            </Button>
            <Button asChild>
              <Link to="/novels/new">
                <Plus className="size-4" />
                新建小说
              </Link>
            </Button>
          </div>
        </div>
        {err ? (
          <p className="text-sm text-destructive">{err}</p>
        ) : null}
        <div className="space-y-3">
          {items.length === 0 ? (
            <Card>
              <CardContent className="py-8 text-center text-sm text-muted-foreground">
                暂无小说，点击「新建小说」开始。
              </CardContent>
            </Card>
          ) : null}
          {items.map((n) => (
            <Card key={n.id}>
              <CardHeader className="pb-2">
                <div className="flex items-start gap-3">
                  <BookOpen className="mt-0.5 size-5 text-primary" />
                  <div className="flex-1">
                    <CardTitle className="text-lg">
                      <Link
                        to={`/novels/${n.id}`}
                        className="hover:text-primary hover:underline"
                      >
                        {n.title}
                      </Link>
                    </CardTitle>
                    <CardDescription className="line-clamp-2">
                      {n.intro || "暂无简介"}
                    </CardDescription>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                <span>状态：{n.status}</span>
                <span>
                  框架{n.framework_confirmed ? "已确认" : "未确认"}
                </span>
                <span>每日自动：{n.daily_auto_chapters} 章</span>
                <div className="ml-auto">
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
              </CardContent>
            </Card>
          ))}
        </div>
        <Button variant="ghost" size="sm" asChild>
          <Link to="/">返回首页</Link>
        </Button>
      </div>
    </div>
  );
}
