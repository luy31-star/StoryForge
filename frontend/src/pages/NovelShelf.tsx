import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { BookOpen, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { WritingStyleSelect } from "@/components/WritingStyleSelect";
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
  const [aiCreateSubject, setAiCreateSubject] = useState<string>("现言情感");
  const [aiCreatePlots, setAiCreatePlots] = useState<string[]>([]);
  const [aiCreateMoods, setAiCreateMoods] = useState<string[]>([]);
  const [aiCreateBackground, setAiCreateBackground] = useState<string>("现代");
  const [aiCreateLengthType, setAiCreateLengthType] = useState<string>("medium");
  const [aiCreateTargetChapters, setAiCreateTargetChapters] = useState<number>(150);
  const [aiCreateChapterTargetWords, setAiCreateChapterTargetWords] = useState<number>(3000);
  const [aiCreateNotes, setAiCreateNotes] = useState("");
  const [aiCreateDailyChapters, setAiCreateDailyChapters] = useState(0);
  const [aiCreateDailyTime, setAiCreateDailyTime] = useState("14:30");
  const [aiCreateWritingStyleId, setAiCreateWritingStyleId] = useState<string | undefined>(undefined);

  const [addedSubjects, setAddedSubjects] = useState<string[]>([]);
  const [addedPlots, setAddedPlots] = useState<string[]>([]);
  const [addedMoods, setAddedMoods] = useState<string[]>([]);
  const [addedBackgrounds, setAddedBackgrounds] = useState<string[]>([]);

  const [newSubject, setNewSubject] = useState("");
  const [newPlot, setNewPlot] = useState("");
  const [newMood, setNewMood] = useState("");
  const [newBackground, setNewBackground] = useState("");

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
        subjects: aiCreateSubject ? [aiCreateSubject] : [],
        plots: aiCreatePlots,
        moods: aiCreateMoods,
        backgrounds: aiCreateBackground ? [aiCreateBackground] : [],
        target_chapters: aiCreateTargetChapters,
        chapter_target_words: aiCreateChapterTargetWords,
        notes: aiCreateNotes.trim(),
        length_type: aiCreateLengthType,
        target_generate_chapters: 0,
        daily_auto_chapters: aiCreateDailyChapters,
        daily_auto_time: aiCreateDailyTime,
        writing_style_id: aiCreateWritingStyleId || undefined,
      });
      setAiCreateOpen(false);
      reload();
    } catch (e: any) {
      setErr(e.message || "一键AI建书失败");
    } finally {
      setAiCreateBusy(false);
    }
  }

  const SUBJECTS = [
    "言情",
    "现言情感",
    "悬疑",
    "惊悚",
    "科幻",
    "游戏",
    "仙侠",
    "历史",
    "玄幻",
    "都市",
    "快穿",
    "成长",
    "校园",
    "职场",
    "家庭",
    "冒险",
  ];
  const PLOTS = [
    "婚姻",
    "出轨",
    "娱乐圈",
    "重生",
    "穿越",
    "犯罪",
    "丧尸",
    "探险",
    "宫斗宅斗",
    "系统",
    "规则怪谈",
    "团宠",
    "先婚后爱",
    "追妻火葬场",
    "破镜重圆",
    "超能力/异能",
    "玄学风水",
    "种田",
    "直播",
    "萌宝",
    "鉴宝",
    "聊天群",
    "弹幕",
    "双向救赎",
    "替身",
    "强制爱",
    "全员恶人",
    "万人嫌黑化",
    "无限流",
    "读心术",
    "预知能力",
    "侦探推理",
    "全员读心",
    "逆袭成长",
    "网恋",
  ];
  const MOODS = [
    "纯爱",
    "HE",
    "BE",
    "甜宠",
    "虐恋",
    "暗恋",
    "先虐后甜",
    "沙雕",
    "爽文",
    "复仇",
    "反转",
    "逆袭",
    "励志",
    "烧脑",
    "热血",
    "求生",
    "多视角反转",
    "治愈",
    "反套路",
    "无CP",
    "虐文",
    "极限拉扯",
    "双向暗恋",
    "禁欲系",
    "自切黑",
    "事业脑",
    "冷幽默",
    "宿命感",
    "清醒感",
    "日常感",
    "群像感",
    "青春疼痛",
    "大女主",
    "大男主",
  ];
  const BACKGROUNDS = ["古代", "现代", "未来", "架空", "民国", "近现代"];
  const LENGTH_TYPES = [
    { id: "short", label: "短篇", defaultChapters: 30 },
    { id: "medium", label: "中篇", defaultChapters: 150 },
    { id: "long", label: "长篇", defaultChapters: 500 },
  ];
  const WORDS_PER_CHAPTER = [2000, 3000, 5000];

  function toggleLimit(
    current: string[],
    tag: string,
    max: number,
    setter: (next: string[]) => void
  ) {
    if (current.includes(tag)) {
      setter(current.filter((x) => x !== tag));
      return;
    }
    if (current.length >= max) {
      setErr(`最多选择 ${max} 项`);
      return;
    }
    setter([...current, tag]);
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
            <div className="grid w-full flex-1 gap-3 sm:grid-cols-3 lg:max-w-xl">
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
                      {!n.framework_confirmed && (
                        <Button asChild variant="outline" className="font-bold">
                          <Link to={`/novels/${n.id}?wizard=1`}>修改框架</Link>
                        </Button>
                      )}
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
            <DialogTitle className="text-xl font-bold text-foreground">一键 AI 建书</DialogTitle>
            <DialogDescription className="text-foreground/80 dark:text-muted-foreground leading-relaxed">
              先尽量明确题材、情节、情绪与背景偏好，AI 会先生成一版大纲草案（待确认）。你可以在工作台里用“修改向导”继续迭代并确认后再续写。
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-6 py-4">
            <div className="space-y-3">
              <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">题材（0/1）</Label>
              <div className="flex flex-wrap gap-2">
                {[...SUBJECTS, ...addedSubjects].map((p) => (
                  <button
                    key={p}
                    type="button"
                    onClick={() => setAiCreateSubject((v) => (v === p ? "" : p))}
                    className={`rounded-full px-3 py-1 text-xs border transition-colors font-medium ${
                      aiCreateSubject === p
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border/70 bg-background/50 text-foreground/70 hover:bg-muted/50 hover:text-foreground dark:text-muted-foreground"
                    }`}
                  >
                    {p}
                  </button>
                ))}
                <div className="flex items-center gap-1 ml-1">
                  <Input
                    placeholder="自定义..."
                    value={newSubject}
                    onChange={(e) => setNewSubject(e.target.value)}
                    className="h-7 w-24 text-[10px] px-2 rounded-full bg-background/50"
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        const val = newSubject.trim();
                        if (val && ![...SUBJECTS, ...addedSubjects].includes(val)) {
                          setAddedSubjects(prev => [...prev, val]);
                          setAiCreateSubject(val);
                          setNewSubject("");
                        }
                      }
                    }}
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 rounded-full bg-primary/5 text-primary hover:bg-primary/10"
                    onClick={() => {
                      const val = newSubject.trim();
                      if (val && ![...SUBJECTS, ...addedSubjects].includes(val)) {
                        setAddedSubjects(prev => [...prev, val]);
                        setAiCreateSubject(val);
                        setNewSubject("");
                      }
                    }}
                  >
                    <Plus className="h-3 w-3" />
                  </Button>
                </div>
              </div>
              <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium">
                已选择：{aiCreateSubject || "未选择"}
              </p>
            </div>

            <div className="space-y-3">
              <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">情节（0/3）</Label>
              <div className="flex flex-wrap gap-2">
                {[...PLOTS, ...addedPlots].map((p) => (
                  <button
                    key={p}
                    type="button"
                    onClick={() => toggleLimit(aiCreatePlots, p, 3, setAiCreatePlots)}
                    className={`rounded-full px-3 py-1 text-xs border transition-colors font-medium ${
                      aiCreatePlots.includes(p)
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border/70 bg-background/50 text-foreground/70 hover:bg-muted/50 hover:text-foreground dark:text-muted-foreground"
                    }`}
                  >
                    {p}
                  </button>
                ))}
                <div className="flex items-center gap-1 ml-1">
                  <Input
                    placeholder="自定义..."
                    value={newPlot}
                    onChange={(e) => setNewPlot(e.target.value)}
                    className="h-7 w-24 text-[10px] px-2 rounded-full bg-background/50"
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        const val = newPlot.trim();
                        if (val && ![...PLOTS, ...addedPlots].includes(val)) {
                          setAddedPlots(prev => [...prev, val]);
                          toggleLimit([...aiCreatePlots], val, 3, setAiCreatePlots);
                          setNewPlot("");
                        }
                      }
                    }}
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 rounded-full bg-primary/5 text-primary hover:bg-primary/10"
                    onClick={() => {
                      const val = newPlot.trim();
                      if (val && ![...PLOTS, ...addedPlots].includes(val)) {
                        setAddedPlots(prev => [...prev, val]);
                        toggleLimit([...aiCreatePlots], val, 3, setAiCreatePlots);
                        setNewPlot("");
                      }
                    }}
                  >
                    <Plus className="h-3 w-3" />
                  </Button>
                </div>
              </div>
              <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium">
                已选择：{aiCreatePlots.length ? aiCreatePlots.join("、") : "未选择"}
              </p>
            </div>

            <div className="space-y-3">
              <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">情绪（0/3）</Label>
              <div className="flex flex-wrap gap-2">
                {[...MOODS, ...addedMoods].map((p) => (
                  <button
                    key={p}
                    type="button"
                    onClick={() => toggleLimit(aiCreateMoods, p, 3, setAiCreateMoods)}
                    className={`rounded-full px-3 py-1 text-xs border transition-colors font-medium ${
                      aiCreateMoods.includes(p)
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border/70 bg-background/50 text-foreground/70 hover:bg-muted/50 hover:text-foreground dark:text-muted-foreground"
                    }`}
                  >
                    {p}
                  </button>
                ))}
                <div className="flex items-center gap-1 ml-1">
                  <Input
                    placeholder="自定义..."
                    value={newMood}
                    onChange={(e) => setNewMood(e.target.value)}
                    className="h-7 w-24 text-[10px] px-2 rounded-full bg-background/50"
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        const val = newMood.trim();
                        if (val && ![...MOODS, ...addedMoods].includes(val)) {
                          setAddedMoods(prev => [...prev, val]);
                          toggleLimit([...aiCreateMoods], val, 3, setAiCreateMoods);
                          setNewMood("");
                        }
                      }
                    }}
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 rounded-full bg-primary/5 text-primary hover:bg-primary/10"
                    onClick={() => {
                      const val = newMood.trim();
                      if (val && ![...MOODS, ...addedMoods].includes(val)) {
                        setAddedMoods(prev => [...prev, val]);
                        toggleLimit([...aiCreateMoods], val, 3, setAiCreateMoods);
                        setNewMood("");
                      }
                    }}
                  >
                    <Plus className="h-3 w-3" />
                  </Button>
                </div>
              </div>
              <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium">
                已选择：{aiCreateMoods.length ? aiCreateMoods.join("、") : "未选择"}
              </p>
            </div>

            <div className="space-y-3">
              <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">背景（0/1）</Label>
              <div className="flex flex-wrap gap-2">
                {[...BACKGROUNDS, ...addedBackgrounds].map((p) => (
                  <button
                    key={p}
                    type="button"
                    onClick={() => setAiCreateBackground((v) => (v === p ? "" : p))}
                    className={`rounded-full px-3 py-1 text-xs border transition-colors font-medium ${
                      aiCreateBackground === p
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border/70 bg-background/50 text-foreground/70 hover:bg-muted/50 hover:text-foreground dark:text-muted-foreground"
                    }`}
                  >
                    {p}
                  </button>
                ))}
                <div className="flex items-center gap-1 ml-1">
                  <Input
                    placeholder="自定义..."
                    value={newBackground}
                    onChange={(e) => setNewBackground(e.target.value)}
                    className="h-7 w-24 text-[10px] px-2 rounded-full bg-background/50"
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        const val = newBackground.trim();
                        if (val && ![...BACKGROUNDS, ...addedBackgrounds].includes(val)) {
                          setAddedBackgrounds(prev => [...prev, val]);
                          setAiCreateBackground(val);
                          setNewBackground("");
                        }
                      }
                    }}
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 rounded-full bg-primary/5 text-primary hover:bg-primary/10"
                    onClick={() => {
                      const val = newBackground.trim();
                      if (val && ![...BACKGROUNDS, ...addedBackgrounds].includes(val)) {
                        setAddedBackgrounds(prev => [...prev, val]);
                        setAiCreateBackground(val);
                        setNewBackground("");
                      }
                    }}
                  >
                    <Plus className="h-3 w-3" />
                  </Button>
                </div>
              </div>
              <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium">
                已选择：{aiCreateBackground || "未选择"}
              </p>
            </div>

            <div className="space-y-3">
              <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">写作风格 (深度定制)</Label>
              <WritingStyleSelect
                value={aiCreateWritingStyleId}
                onChange={setAiCreateWritingStyleId}
              />
              <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium">
                若不选择深度文风，系统将按题材和篇幅默认提示词进行创作。
              </p>
            </div>

            <div className="space-y-3">
              <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">篇幅规模（1/1）</Label>
              <div className="flex flex-wrap gap-2">
                {LENGTH_TYPES.map((lt) => (
                  <button
                    key={lt.id}
                    type="button"
                    onClick={() => {
                      setAiCreateLengthType(lt.id);
                      setAiCreateTargetChapters(lt.defaultChapters);
                    }}
                    className={`rounded-full px-4 py-1.5 text-xs border transition-colors font-bold ${
                      aiCreateLengthType === lt.id
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border/70 bg-background/50 text-foreground/70 hover:bg-muted/50 hover:text-foreground dark:text-muted-foreground"
                    }`}
                  >
                    {lt.label}
                  </button>
                ))}
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label className="text-xs font-semibold text-foreground/70">设定总章节数</Label>
                  <Input
                    type="number"
                    min={1}
                    max={5000}
                    value={aiCreateTargetChapters}
                    onChange={(e) => setAiCreateTargetChapters(Number(e.target.value))}
                    className="text-foreground font-bold"
                  />
                </div>
                <div className="space-y-2">
                  <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium pt-7">
                    章节数会影响大纲拆分与后续续写上限。
                  </p>
                </div>
              </div>
            </div>

            <div className="space-y-3">
              <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">每章期望字数（汉字）</Label>
              <div className="flex flex-wrap gap-2">
                {WORDS_PER_CHAPTER.map((w) => (
                  <button
                    key={w}
                    type="button"
                    onClick={() => setAiCreateChapterTargetWords(w)}
                    className={`rounded-full px-3 py-1 text-xs border transition-colors font-medium ${
                      aiCreateChapterTargetWords === w
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border/70 bg-background/50 text-foreground/70 hover:bg-muted/50 hover:text-foreground dark:text-muted-foreground"
                    }`}
                  >
                    {w} 字
                  </button>
                ))}
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label className="text-xs font-semibold text-foreground/70">自定义字数</Label>
                  <Input
                    type="number"
                    min={500}
                    max={10000}
                    step={100}
                    value={aiCreateChapterTargetWords}
                    onChange={(e) => setAiCreateChapterTargetWords(Number(e.target.value))}
                    className="text-foreground"
                  />
                </div>
                <div className="space-y-2">
                  <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium pt-7">
                    AI 在写正文时将以此为强约束。建议 2000-5000。
                  </p>
                </div>
              </div>
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

            <div className="grid gap-4 sm:grid-cols-2">
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
            <Button onClick={handleAiCreate} disabled={aiCreateBusy || !aiCreateSubject}>
              {aiCreateBusy ? "正在后台执行..." : "确认生成大纲"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
