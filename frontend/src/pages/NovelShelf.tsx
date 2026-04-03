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
import { deleteNovel, listNovels, aiCreateAndStartNovel } from "@/services/novelApi";
import { ensureLlmReady } from "@/services/llmReady";

export function NovelShelf() {
  const [items, setItems] = useState<
    Awaited<ReturnType<typeof listNovels>>
  >([]);
  const [err, setErr] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const [aiCreateOpen, setAiCreateOpen] = useState(false);
  const [aiCreateBusy, setAiCreateBusy] = useState(false);
  const [aiCreateStyles, setAiCreateStyles] = useState<string[]>(["都市修仙"]);
  const [aiCreateNotes, setAiCreateNotes] = useState("");
  const [aiCreateLength, setAiCreateLength] = useState("long");
  const [aiCreateInitChapters, setAiCreateInitChapters] = useState(10);
  const [aiCreateDailyChapters, setAiCreateDailyChapters] = useState(0);
  const [aiCreateDailyTime, setAiCreateDailyTime] = useState("14:30");

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

  async function handleAiCreate() {
    const ready = await ensureLlmReady();
    if (!ready) return;
    setErr(null);
    setAiCreateBusy(true);
    try {
      await aiCreateAndStartNovel({
        styles: aiCreateStyles,
        notes: aiCreateNotes.trim(),
        length_type: aiCreateLength,
        target_generate_chapters: aiCreateInitChapters,
        daily_auto_chapters: aiCreateDailyChapters,
        daily_auto_time: aiCreateDailyTime,
      });
      setAiCreateOpen(false);
      reload();
    } catch (e: any) {
      setErr(e.message || "一键AI建书失败");
    } finally {
      setAiCreateBusy(false);
    }
  }

  const presets = [
    "都市修仙", "爽文", "凡人修仙", "都市兵王", "霸道总裁", "穿越异世", 
    "重生复仇", "末世废土", "游戏异界", "虚拟网游", "科幻机甲", "星际战争", 
    "恐怖惊悚", "悬疑推理", "灵异奇谈", "历史架空", "军事争霸", "宫廷权谋", 
    "古言宅斗", "现言种田", "青春校园", "娱乐明星"
  ];

  function toggleAiStyle(tag: string) {
    setAiCreateStyles((current) =>
      current.includes(tag)
        ? current.filter((item) => item !== tag)
        : [...current, tag]
    );
  }

  return (
    <div className="novel-shell">
      <div className="novel-container space-y-6">
        <section className="glass-panel overflow-hidden p-6 md:p-8">
          <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-2xl space-y-4">
              <span className="glass-chip">
                <BookOpen className="size-3.5 text-primary" />
                <span className="text-foreground/80 dark:text-inherit font-medium">小说工作区</span>
              </span>
              <div className="space-y-2">
                <h1 className="text-3xl font-semibold tracking-tight text-foreground md:text-4xl">
                  把书架当作创作入口，而不是文件列表。
                </h1>
                <p className="max-w-xl text-sm leading-6 text-foreground/70 dark:text-muted-foreground md:text-base font-medium">
                  在这里管理你的世界观、创作节奏和日更任务。每本书都保留独立的框架、章节与记忆，适合持续推进长篇。
                </p>
              </div>
              <div className="flex flex-wrap gap-3">
                <Button asChild size="lg" className="min-w-36 font-semibold">
                  <Link to="/novels/new">
                    <Plus className="size-4" />
                    新建小说
                  </Link>
                </Button>
                <Button size="lg" variant="secondary" onClick={() => setAiCreateOpen(true)} className="font-semibold text-foreground/90">
                  一键AI建书
                </Button>
                <Button asChild size="lg" variant="glass" className="font-semibold">
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
                  <p className="text-xs text-foreground/60 dark:text-muted-foreground font-bold">{label}</p>
                  <p className="mt-2 text-2xl font-bold tracking-tight text-foreground">
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
              <p className="section-heading text-foreground font-bold">你的作品</p>
              <p className="mt-1 text-sm text-foreground/60 dark:text-muted-foreground font-medium">
                在这里管理您的所有创作项目。
              </p>
            </div>
            <div className="glass-chip font-bold text-foreground/80">
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
                className={`group overflow-hidden border-border/70 hover:-translate-y-1 hover:border-primary/25 hover:shadow-[0_20px_60px_rgba(15,23,42,0.12)] ${
                  n.status === 'failed' ? 'opacity-90 border-destructive/20' : ''
                }`}
              >
                <CardHeader className="pb-3">
                  <div className="flex items-start gap-4">
                    <div className={`flex size-11 shrink-0 items-center justify-center rounded-2xl shadow-[inset_0_1px_0_rgba(255,255,255,0.5)] ${
                      n.status === 'failed' ? 'bg-destructive/10 text-destructive' : 'bg-primary/10 text-primary'
                    }`}>
                      <BookOpen className="size-5" />
                    </div>
                    <div className="min-w-0 flex-1 space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="glass-chip px-2.5 py-1 text-[11px] text-primary font-bold">
                          {n.length_tag}
                        </span>
                        <span className={`glass-chip px-2.5 py-1 text-[11px] font-bold ${
                          n.status === 'failed' ? 'text-destructive bg-destructive/10' : 'text-foreground/70 dark:text-inherit'
                        }`}>
                          {n.status === 'failed' 
                            ? (n.framework_confirmed ? '续写/同步中失败' : '建书构思失败') 
                            : n.status}
                        </span>
                        <span className="glass-chip px-2.5 py-1 text-[11px] text-foreground/70 dark:text-inherit font-medium">
                          框架{n.framework_confirmed ? "已确认" : "未确认"}
                        </span>
                      </div>
                      <CardTitle className="text-xl font-bold">
                        <Link
                          to={`/novels/${n.id}`}
                          className="transition-colors group-hover:text-primary"
                        >
                          {n.title}
                        </Link>
                      </CardTitle>
                      <CardDescription className="line-clamp-3 text-foreground/70 dark:text-muted-foreground font-medium">
                        {n.intro || "还没有简介，可以先进入工作台补充世界观、人物与基调。"}
                      </CardDescription>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid gap-2 sm:grid-cols-3">
                    <div className="rounded-2xl border border-border/60 bg-background/55 px-3 py-2">
                      <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-bold">创作状态</p>
                      <p className="mt-1 text-sm font-bold text-foreground">{n.status}</p>
                    </div>
                    <div className="rounded-2xl border border-border/60 bg-background/55 px-3 py-2">
                      <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-bold">每日自动</p>
                      <p className="mt-1 text-sm font-bold text-foreground">
                        {n.daily_auto_chapters} 章
                      </p>
                    </div>
                    <div className="rounded-2xl border border-border/60 bg-background/55 px-3 py-2">
                      <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-bold">入口</p>
                      <p className="mt-1 text-sm font-bold text-foreground">
                        工作台 / 章节 / 记忆
                      </p>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex flex-wrap gap-2">
                      <Button asChild variant="glass">
                        <Link to={`/novels/${n.id}`}>
                          {n.status === 'failed' ? "查看失败详情" : "进入工作台"}
                        </Link>
                      </Button>
                      {n.status === 'failed' && (
                        <Button 
                          variant="secondary" 
                          className="font-bold"
                          onClick={() => {
                            // 重新打开建书对话框（这里由于是新小说，简单起见引导回一键建书）
                            setAiCreateOpen(true);
                          }}
                        >
                          重新建书
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
                      {busyId === n.id ? "删除中…" : "删除作品"}
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>
      </div>

      <Dialog open={aiCreateOpen} onOpenChange={setAiCreateOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="text-xl font-bold text-foreground">一键 AI 全自动建书</DialogTitle>
            <DialogDescription className="text-foreground/80 dark:text-muted-foreground leading-relaxed">
              选择你想要的小说题材和篇幅，AI 将自动构思书名、简介、背景、设定、大纲框架，并可以立即开始自动创作。
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-6 py-4">
            <div className="space-y-3">
              <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">小说题材 / 风格（可多选）</Label>
              <div className="flex flex-wrap gap-2">
                {presets.map((p) => (
                  <button
                    key={p}
                    type="button"
                    onClick={() => toggleAiStyle(p)}
                    className={`rounded-full px-3 py-1 text-xs border transition-colors font-medium ${
                      aiCreateStyles.includes(p)
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border/70 bg-background/50 text-foreground/70 hover:bg-muted/50 hover:text-foreground dark:text-muted-foreground"
                    }`}
                  >
                    {p}
                  </button>
                ))}
              </div>
              <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium">
                已选择：{aiCreateStyles.length ? aiCreateStyles.join("、") : "未选择"}
              </p>
            </div>

            <div className="space-y-2">
              <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">补充备注</Label>
              <textarea
                value={aiCreateNotes}
                onChange={(e) => setAiCreateNotes(e.target.value)}
                placeholder="可补充你希望强调的设定、人物关系、禁忌元素、节奏要求或商业化方向，这些都会进入 LLM 提示词。"
                className="field-shell-textarea min-h-[110px] text-sm text-foreground placeholder:text-foreground/40 dark:placeholder:text-muted-foreground/50"
              />
            </div>

            <div className="space-y-3">
              <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">预期篇幅</Label>
              <select
                value={aiCreateLength}
                onChange={(e) => setAiCreateLength(e.target.value)}
                className="flex h-10 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <option value="short">短篇小说（约 15-50 章）</option>
                <option value="medium">中篇小说（20-50万字，约100-250章）</option>
                <option value="long">长篇小说（约100-150万字）</option>
              </select>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">建书后立刻生成章数</Label>
                <Input
                  type="number"
                  min={0}
                  max={50}
                  value={aiCreateInitChapters}
                  onChange={(e) => setAiCreateInitChapters(Number(e.target.value))}
                  className="text-foreground"
                />
                <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium">设定为0则只生成大纲不写正文</p>
              </div>

              <div className="space-y-2">
                <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">每日定时自动写多少章</Label>
                <Input
                  type="number"
                  min={0}
                  max={20}
                  value={aiCreateDailyChapters}
                  onChange={(e) => setAiCreateDailyChapters(Number(e.target.value))}
                  className="text-foreground"
                />
                <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium">设定为0则不开启每日定时写</p>
              </div>

              {aiCreateDailyChapters > 0 && (
                <div className="space-y-2 sm:col-span-2">
                  <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">每日定时任务时间（北京时间）</Label>
                  <Input
                    type="time"
                    value={aiCreateDailyTime}
                    onChange={(e) => setAiCreateDailyTime(e.target.value)}
                    className="text-foreground"
                  />
                  <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium">
                    由后台系统自动执行。
                  </p>
                </div>
              )}
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setAiCreateOpen(false)} disabled={aiCreateBusy}>
              取消
            </Button>
            <Button onClick={handleAiCreate} disabled={aiCreateBusy || aiCreateStyles.length === 0}>
              {aiCreateBusy ? "正在后台执行..." : "确认开启全自动建书"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
