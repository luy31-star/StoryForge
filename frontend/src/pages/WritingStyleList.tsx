import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { Plus, Trash2, Edit3, Search, BookOpen, Clock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { listWritingStyles, deleteWritingStyle, WritingStyle } from "@/services/writingStyleApi";

function formatDate(dateStr: string) {
  try {
    const d = new Date(dateStr);
    return d.toLocaleDateString("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    });
  } catch {
    return dateStr;
  }
}

export function WritingStyleList() {
  const [styles, setStyles] = useState<WritingStyle[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadStyles();
  }, []);

  async function loadStyles() {
    setLoading(true);
    try {
      const data = await listWritingStyles();
      setStyles(data);
    } catch (e) {
      console.error("Failed to load styles", e);
    } finally {
      setLoading(false);
    }
  }

  async function onDelete(id: string) {
    if (!confirm("确定要删除这个文风吗？")) return;
    try {
      await deleteWritingStyle(id);
      setStyles((prev) => prev.filter((s) => s.id !== id));
    } catch (e) {
      alert("删除失败");
    }
  }

  return (
    <div className="novel-shell">
      <div className="novel-container max-w-6xl space-y-6">
        <header className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="space-y-1">
            <h1 className="text-3xl font-bold tracking-tight text-foreground">文风管理</h1>
            <p className="text-muted-foreground font-medium">
              创建和管理深度定制的写作风格，提升 AI 创作的专业度。
            </p>
          </div>
          <Button asChild className="gap-2 font-bold shadow-lg shadow-primary/20">
            <Link to="/writing-styles/new">
              <Plus className="h-4 w-4" />
              创建新文风
            </Link>
          </Button>
        </header>

        {loading ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {[1, 2, 3].map((i) => (
              <Card key={i} className="animate-pulse bg-muted/20">
                <div className="h-48" />
              </Card>
            ))}
          </div>
        ) : styles.length === 0 ? (
          <div className="glass-panel flex flex-col items-center justify-center py-20 text-center">
            <div className="rounded-full bg-primary/10 p-6">
              <BookOpen className="h-12 w-12 text-primary" />
            </div>
            <h3 className="mt-6 text-xl font-bold">还没有文风</h3>
            <p className="mt-2 text-muted-foreground max-w-sm">
              你可以参考知名作者，或者通过上传自己的写作选段来训练 AI 的文风特征。
            </p>
            <Button asChild className="mt-8" variant="outline">
              <Link to="/writing-styles/new">立即创建第一个文风</Link>
            </Button>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {styles.map((s) => (
              <Card key={s.id} className="glass-panel-subtle group overflow-hidden transition-all hover:shadow-md">
                <CardHeader className="pb-3">
                  <div className="flex items-start justify-between">
                    <CardTitle className="line-clamp-1 text-lg font-bold">{s.name}</CardTitle>
                    <div className="flex gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                      <Button size="icon" variant="ghost" className="h-8 w-8" asChild>
                        <Link to={`/writing-styles/${s.id}`}>
                          <Edit3 className="h-4 w-4" />
                        </Link>
                      </Button>
                      <Button size="icon" variant="ghost" className="h-8 w-8 text-destructive hover:bg-destructive/10" onClick={() => onDelete(s.id)}>
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                  <CardDescription className="flex items-center gap-2 font-medium">
                    {s.reference_author ? (
                      <span className="flex items-center gap-1 rounded bg-primary/10 px-1.5 py-0.5 text-xs text-primary">
                        <Search className="h-3 w-3" />
                        参考: {s.reference_author}
                      </span>
                    ) : (
                      <span className="text-xs">自建风格</span>
                    )}
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="flex flex-wrap gap-1.5">
                    {s.lexicon.tags.slice(0, 4).map((t) => (
                      <span key={t} className="rounded-full border border-border/50 bg-muted/30 px-2 py-0.5 text-[10px] font-bold text-muted-foreground">
                        {t}
                      </span>
                    ))}
                  </div>
                  {s.tone.description && (
                    <p className="line-clamp-3 text-xs text-muted-foreground leading-relaxed font-medium">
                      {s.tone.description}
                    </p>
                  )}
                  <div className="flex items-center justify-between border-t pt-3 text-[10px] text-muted-foreground font-bold">
                    <span className="flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      {formatDate(s.updated_at)}
                    </span>
                    <span>{s.snippets.length} 个示例片段</span>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
