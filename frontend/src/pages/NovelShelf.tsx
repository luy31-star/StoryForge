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
import { WritingStyleSelect } from "@/components/WritingStyleSelect";
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
import { deleteNovel, listNovels, aiCreateAndStartNovel, type ShelfNovel } from "@/services/novelApi";
import { ensureLlmReady } from "@/services/llmReady";

const shelfThemes = [
  {
    cover: "from-sky-500/24 via-cyan-400/10 to-transparent",
    chip: "border-sky-500/28 bg-sky-500/12 text-sky-700 dark:text-sky-200",
    stripe: "from-sky-400 via-cyan-300 to-sky-200",
    glow: "bg-sky-400/16",
  },
  {
    cover: "from-emerald-500/22 via-teal-400/10 to-transparent",
    chip: "border-emerald-500/28 bg-emerald-500/12 text-emerald-700 dark:text-emerald-200",
    stripe: "from-emerald-400 via-teal-300 to-cyan-200",
    glow: "bg-emerald-400/16",
  },
  {
    cover: "from-fuchsia-500/20 via-violet-400/10 to-transparent",
    chip: "border-fuchsia-500/25 bg-fuchsia-500/12 text-fuchsia-700 dark:text-fuchsia-200",
    stripe: "from-fuchsia-400 via-violet-300 to-indigo-200",
    glow: "bg-fuchsia-400/16",
  },
  {
    cover: "from-amber-500/20 via-orange-400/10 to-transparent",
    chip: "border-amber-500/28 bg-amber-500/12 text-amber-700 dark:text-amber-200",
    stripe: "from-amber-400 via-orange-300 to-yellow-200",
    glow: "bg-amber-400/16",
  },
] as const;

const stageLabels = ["构思", "框架", "创作", "自动"] as const;

function hashText(value: string) {
  let hash = 0;
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash << 5) - hash + value.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
}

function themeForNovel(key: string) {
  return shelfThemes[hashText(key) % shelfThemes.length];
}

function relativeUpdatedAt(value: string | null) {
  if (!value) return "未记录更新时间";
  const ts = Date.parse(value);
  if (Number.isNaN(ts)) return value;
  const diff = Date.now() - ts;
  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (diff < hour) return `${Math.max(1, Math.round(diff / minute))} 分钟前`;
  if (diff < day) return `${Math.max(1, Math.round(diff / hour))} 小时前`;
  if (diff < 7 * day) return `${Math.max(1, Math.round(diff / day))} 天前`;
  return value.slice(0, 10);
}

function stageForNovel(novel: ShelfNovel) {
  if (novel.status === "failed") {
    return {
      index: novel.framework_confirmed ? 2 : 1,
      label: novel.framework_confirmed ? "续写链路待修复" : "大纲构思受阻",
      hint: novel.framework_confirmed ? "正文或记忆同步中断" : "先回到向导确认大纲",
    };
  }
  if (!novel.framework_confirmed) {
    return {
      index: 1,
      label: "框架待确认",
      hint: "建议先锁定世界观、人物与节拍",
    };
  }
  if (novel.daily_auto_chapters > 0) {
    return {
      index: 3,
      label: "自动推进中",
      hint: `当前每日自动 ${novel.daily_auto_chapters} 章`,
    };
  }
  return {
    index: 2,
    label: "手动创作中",
    hint: "适合集中修订正文、节奏与记忆",
  };
}

function NovelStageRail({
  activeIndex,
  stripe,
  hint,
  compact = false,
}: {
  activeIndex: number;
  stripe: string;
  hint?: string;
  compact?: boolean;
}) {
  return (
    <div className={`rounded-[1.4rem] border border-border/60 bg-background/58 ${compact ? "p-3.5" : "p-4"}`}>
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-semibold text-foreground">创作路径</p>
        {hint ? <span className="text-xs text-foreground/58">{hint}</span> : null}
      </div>

      <div className={`mt-3 grid gap-2 ${compact ? "grid-cols-4" : "grid-cols-4"}`}>
        {stageLabels.map((label, index) => (
          <div
            key={`${label}-${index}`}
            className={`rounded-[1rem] border px-3 py-3 ${
              index <= activeIndex
                ? "border-primary/25 bg-background/80"
                : "border-border/50 bg-background/42"
            }`}
          >
            <div
              className={`h-1.5 rounded-full ${
                index <= activeIndex ? `bg-gradient-to-r ${stripe}` : "bg-border/60"
              }`}
            />
            <p className="mt-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-foreground/55">
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
  const spotlightTheme = spotlightNovel
    ? themeForNovel(`${spotlightNovel.id}${spotlightNovel.title}`)
    : shelfThemes[0];
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
      setTaskStartedOpen(true);
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
  const WORDS_PER_CHAPTER = [300, 2000, 3000, 5000];

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
        <section className="glass-panel relative overflow-hidden p-6 md:p-8">
          <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-primary/10 via-transparent to-accent/10" />
          <div className="grid gap-6 xl:grid-cols-[1.02fr_0.98fr]">
            <div className="relative space-y-5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="glass-chip border-primary/25 bg-primary/10 text-primary">
                  <Sparkles className="size-3.5" />
                  小说书架 / Story Shelf
                </span>
                <span className="glass-chip">作品态势板</span>
              </div>

              <div className="space-y-3">
                <h1 className="max-w-3xl text-3xl font-semibold tracking-[-0.03em] text-foreground md:text-5xl">
                  把书架做成
                  <span className="bg-gradient-to-r from-primary via-accent to-cyan-400 bg-clip-text text-transparent">
                    创作控制台
                  </span>
                  ，而不是文件列表。
                </h1>
                <p className="max-w-2xl text-sm leading-7 text-foreground/70 md:text-base">
                  在这里一眼看出每本书处在哪个阶段、有没有自动推进、哪本书最近最活跃。
                  进入工作台之前，先把整座书架的节奏和异常看清楚。
                </p>
              </div>

              <div className="flex flex-wrap gap-3">
                <Button asChild size="lg" className="min-w-36 font-semibold">
                  <Link to="/novels/new">
                    <Plus className="size-4" />
                    新建小说
                  </Link>
                </Button>
                <Button
                  size="lg"
                  variant="secondary"
                  onClick={() => setAiCreateOpen(true)}
                  className="font-semibold text-foreground/90"
                >
                  一键AI建书
                </Button>
                <Button asChild size="lg" variant="glass" className="font-semibold">
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
                    <p className="text-xs font-semibold uppercase tracking-[0.22em] text-foreground/55">
                      {label}
                    </p>
                    <p className="mt-2 text-2xl font-semibold tracking-tight text-foreground">
                      {value}
                    </p>
                    <p className="mt-1 text-sm leading-6 text-foreground/60">{hint}</p>
                  </div>
                ))}
              </div>
              {failedCount > 0 ? (
                <div className="status-badge border-amber-500/30 bg-amber-500/8 text-amber-700 dark:text-amber-300">
                  当前有 {failedCount} 本作品需要排障，建议优先查看焦点作品或失败任务。
                </div>
              ) : null}
            </div>

            <div className="relative">
              {spotlightNovel ? (
                <div className="signal-surface story-mesh overflow-hidden p-5 sm:p-6">
                  <div
                    className={`pointer-events-none absolute inset-0 bg-gradient-to-br ${spotlightTheme.cover}`}
                  />
                  <div className="relative z-10 flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-[0.3em] text-foreground/55">
                        焦点作品
                      </p>
                      <h2 className="mt-3 text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
                        《{spotlightNovel.title}》
                      </h2>
                    </div>
                    <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${spotlightTheme.chip}`}>
                      {spotlightStage?.label}
                    </span>
                  </div>

                  <p className="relative z-10 mt-4 max-w-2xl text-sm leading-7 text-foreground/70">
                    <span className={spotlightIntroExpanded ? "whitespace-pre-wrap" : "line-clamp-4"}>
                      {spotlightNovel.intro || "还没有简介。你可以进入工作台先补全主线、人物和核心冲突。"}
                    </span>
                  </p>
                  <button
                    type="button"
                    className="relative z-10 mt-1 text-xs font-semibold text-primary underline-offset-4 hover:underline"
                    onClick={() => setSpotlightIntroExpanded((v) => !v)}
                  >
                    {spotlightIntroExpanded ? "收起简介" : "展开全文"}
                  </button>

                  <div className="relative z-10 mt-6">
                    <NovelStageRail
                      activeIndex={spotlightStage?.index ?? 0}
                      stripe={spotlightTheme.stripe}
                      hint={spotlightStage?.hint}
                    />
                  </div>

                  <div className="relative z-10 mt-5 flex flex-wrap gap-2 text-sm text-foreground/70">
                    <span className="status-badge">
                      目标 {spotlightNovel.target_chapters} 章 · {spotlightNovel.length_tag}
                    </span>
                    <span className="status-badge">
                      {spotlightNovel.daily_auto_chapters > 0
                        ? `自动 ${spotlightNovel.daily_auto_chapters} 章 / 天`
                        : "手动推进"}
                    </span>
                    <span className="status-badge">
                      最近活动 {relativeUpdatedAt(spotlightNovel.updated_at)}
                    </span>
                  </div>

                  <div className="relative z-10 mt-5 flex flex-wrap items-center gap-3">
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
                    <div className="flex size-16 items-center justify-center rounded-3xl bg-primary/10 text-primary">
                      <BookOpen className="size-7" />
                    </div>
                    <div className="space-y-2">
                      <p className="text-xl font-semibold text-foreground">书架还没有作品</p>
                      <p className="text-sm leading-6 text-muted-foreground">
                        新建一本书后，这里会出现最近最活跃的作品和整座书架的节奏概览。
                      </p>
                    </div>
                  </CardContent>
                </Card>
              )}
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
              <p className="mt-1 text-sm font-medium text-foreground/60 dark:text-muted-foreground">
                支持按标题、简介和状态快速筛选。
              </p>
            </div>
            <div className="glass-chip font-bold text-foreground/80">
              共 {total} 本作品
            </div>
          </div>
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
                  className="mt-2 flex h-10 w-full rounded-xl border border-input bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
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
          {total === 0 ? (
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
          {total > 0 && items.length === 0 ? (
            <Card className="overflow-hidden">
              <CardContent className="flex flex-col items-center gap-3 py-14 text-center">
                <p className="text-lg font-semibold tracking-tight text-foreground">没有匹配的作品</p>
                <p className="text-sm text-muted-foreground">试试更短的关键词，或者切换状态筛选。</p>
              </CardContent>
            </Card>
          ) : null}
          <div className="grid gap-4 lg:grid-cols-2">
            {items.map((n) => {
              const theme = themeForNovel(`${n.id}${n.title}`);
              const stage = stageForNovel(n);
              const statusLabel =
                n.status === "failed"
                  ? n.framework_confirmed
                    ? "续写 / 同步失败"
                    : "建书构思失败"
                  : n.status;

              return (
                <div
                  key={n.id}
                  className={`group glass-panel-subtle overflow-hidden p-0 transition-all duration-300 hover:-translate-y-1 hover:border-primary/25 hover:shadow-[0_20px_60px_rgba(15,23,42,0.12)] ${
                    n.status === "failed" ? "border-destructive/25" : ""
                  }`}
                >
                  <div className="relative overflow-hidden border-b border-border/50 px-5 py-5">
                    <div className={`pointer-events-none absolute inset-0 bg-gradient-to-br ${theme.cover}`} />
                    <div className={`pointer-events-none absolute right-[-18%] top-[-28%] h-44 w-44 rounded-full blur-3xl ${theme.glow}`} />

                    <div className="relative z-10 flex items-start justify-between gap-4">
                      <div className="min-w-0 flex-1 space-y-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className={`rounded-full border px-3 py-1 text-[11px] font-semibold ${theme.chip}`}>
                            {n.length_tag}
                          </span>
                          <span
                            className={`rounded-full border px-3 py-1 text-[11px] font-semibold ${
                              n.status === "failed"
                                ? "border-destructive/30 bg-destructive/10 text-destructive"
                                : "border-border/70 bg-background/70 text-foreground/65"
                            }`}
                          >
                            {statusLabel}
                          </span>
                        </div>

                        <div className="space-y-2">
                          <CardTitle className="text-2xl font-semibold tracking-tight">
                            <Link
                              to={`/novels/${n.id}`}
                              className="transition-colors group-hover:text-primary"
                            >
                              {n.title}
                            </Link>
                          </CardTitle>
                          <CardDescription className="text-[15px] text-foreground/68">
                            <span
                              className={
                                expandedIntroIds[n.id] ? "whitespace-pre-wrap" : "line-clamp-3"
                              }
                            >
                              {n.intro || "还没有简介，可以先进入工作台补充世界观、人物与主线冲突。"}
                            </span>
                          </CardDescription>
                          <button
                            type="button"
                            className="text-xs font-semibold text-primary underline-offset-4 hover:underline"
                            onClick={() =>
                              setExpandedIntroIds((prev) => ({
                                ...prev,
                                [n.id]: !prev[n.id],
                              }))
                            }
                          >
                            {expandedIntroIds[n.id] ? "收起简介" : "展开全文"}
                          </button>
                        </div>
                      </div>

                      <div className="shrink-0 rounded-[1.4rem] border border-border/60 bg-background/70 px-4 py-3 text-right shadow-[0_14px_30px_rgba(15,23,42,0.08)] backdrop-blur-xl">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-foreground/50">
                          最近活动
                        </p>
                        <p className="mt-2 inline-flex items-center gap-2 text-sm font-semibold text-foreground/78">
                          <Clock3 className="size-3.5" />
                          {relativeUpdatedAt(n.updated_at)}
                        </p>
                      </div>
                    </div>
                  </div>

                  <div className="space-y-4 p-5">
                    <div className="flex flex-wrap gap-2 text-xs text-foreground/62">
                      <span className="status-badge">目标 {n.target_chapters} 章</span>
                      <span className="status-badge">
                        {n.daily_auto_chapters > 0 ? `自动 ${n.daily_auto_chapters} 章 / 天` : "手动推进"}
                      </span>
                      <span className="status-badge">{stage.label}</span>
                    </div>
                    <NovelStageRail activeIndex={stage.index} stripe={theme.stripe} hint={stage.hint} compact />

                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="flex flex-wrap gap-2">
                        <Button asChild variant="glass">
                          <Link to={`/novels/${n.id}`}>
                            {n.status === "failed" ? "查看失败详情" : "进入工作台"}
                            <ArrowRight className="size-4" />
                          </Link>
                        </Button>
                        {!n.framework_confirmed && (
                          <Button asChild variant="outline" className="font-bold">
                            <Link to={`/novels/${n.id}?wizard=1`}>修改框架</Link>
                          </Button>
                        )}
                        {n.status === "failed" && (
                          <Button
                            variant="secondary"
                            className="font-bold"
                            onClick={() => {
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
                  </div>
                </div>
              );
            })}
          </div>
          {total > 0 ? (
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="text-sm text-muted-foreground">
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
                    min={300}
                    max={10000}
                    step={1}
                    value={aiCreateChapterTargetWords}
                    onChange={(e) => setAiCreateChapterTargetWords(Number(e.target.value))}
                    className="text-foreground"
                  />
                </div>
                <div className="space-y-2">
                  <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium pt-7">
                    提示词会强力要求正文紧贴目标字数，只允许轻微浮动。当前默认规则为上下约 5%，至少 30 字、最多 150 字。
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
            <Button
              variant="outline"
              className="font-bold"
              onClick={() => setAiCreateOpen(false)}
              disabled={aiCreateBusy}
            >
              取消
            </Button>
            <Button
              className="font-bold min-w-[100px]"
              onClick={handleAiCreate}
              disabled={aiCreateBusy || !aiCreateSubject}
            >
              {aiCreateBusy ? "正在发起任务..." : "立即开始 AI 建书"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={taskStartedOpen} onOpenChange={setTaskStartedOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="text-xl font-bold flex items-center gap-2">
              <Sparkles className="size-5 text-primary" />
              任务已在后台启动
            </DialogTitle>
            <DialogDescription className="text-foreground/80 pt-2 leading-relaxed">
              AI 正在为你构思小说设定与大纲。此过程可能需要几十秒，你可以留在本页等待刷新，也可以前往「我的任务」模块查看详细进度。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button
              variant="outline"
              className="font-bold"
              onClick={() => setTaskStartedOpen(false)}
            >
              留在本页
            </Button>
            <Button
              className="font-bold"
              onClick={() => {
                setTaskStartedOpen(false);
                navigate("/tasks");
              }}
            >
              前往我的任务
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
