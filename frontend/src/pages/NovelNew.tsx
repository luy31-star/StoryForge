import { useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Sparkles } from "lucide-react";
import { LlmActionConfirmDialog } from "@/components/LlmActionConfirmDialog";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  createNovel,
  inspirationChatStream,
  uploadReference,
  validateReferenceFile,
} from "@/services/novelApi";

type ChatTurn = { role: "user" | "assistant"; content: string };
type LlmConfirmState = {
  title: string;
  description: string;
  confirmLabel: string;
  details: string[];
};

export function NovelNew() {
  const nav = useNavigate();
  const [title, setTitle] = useState("");
  const [intro, setIntro] = useState("");
  const [background, setBackground] = useState("");
  const [style, setStyle] = useState("");
  const [targetChapters, setTargetChapters] = useState(1500);
  const [dailyChapters, setDailyChapters] = useState(0);
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const [inspireOpen, setInspireOpen] = useState(false);
  const [inspireTurns, setInspireTurns] = useState<ChatTurn[]>([]);
  const [inspireInput, setInspireInput] = useState("");
  const [inspireBusy, setInspireBusy] = useState(false);
  const [inspireErr, setInspireErr] = useState<string | null>(null);
  const [inspireThinking, setInspireThinking] = useState("");
  const [inspireAbort, setInspireAbort] = useState<AbortController | null>(null);
  const [llmConfirm, setLlmConfirm] = useState<LlmConfirmState | null>(null);
  const [llmConfirmBusy, setLlmConfirmBusy] = useState(false);
  const llmConfirmActionRef = useRef<null | (() => Promise<void>)>(null);

  function openLlmConfirm(
    config: LlmConfirmState,
    action: () => Promise<void>
  ) {
    llmConfirmActionRef.current = action;
    setLlmConfirm(config);
  }

  function handleLlmConfirmOpenChange(open: boolean) {
    if (open || llmConfirmBusy) return;
    llmConfirmActionRef.current = null;
    setLlmConfirm(null);
  }

  async function runConfirmedLlmAction() {
    const action = llmConfirmActionRef.current;
    if (!action) return;
    setLlmConfirmBusy(true);
    try {
      await action();
      llmConfirmActionRef.current = null;
      setLlmConfirm(null);
    } finally {
      setLlmConfirmBusy(false);
    }
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    if (!title.trim()) {
      setErr("请填写书名");
      return;
    }
    setLoading(true);
    try {
      const { id } = await createNovel({
        title: title.trim(),
        intro,
        background,
        style,
        target_chapters: targetChapters,
        daily_auto_chapters: dailyChapters,
      });
      if (file) {
        const verr = validateReferenceFile(file);
        if (verr) {
          setErr(verr);
          setLoading(false);
          return;
        }
        await uploadReference(id, file);
      }
      nav(`/novels/${id}`);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "创建失败");
    } finally {
      setLoading(false);
    }
  }

  async function sendInspiration() {
    const text = inspireInput.trim();
    if (!text || inspireBusy) return;
    setInspireErr(null);
    setInspireThinking("");
    setInspireBusy(true);
    const nextUser: ChatTurn = { role: "user", content: text };
    const history = [...inspireTurns, nextUser];
    setInspireTurns([...history, { role: "assistant", content: "" }]);
    setInspireInput("");
    const controller = new AbortController();
    setInspireAbort(controller);
    try {
      const payload = history.map((t) => ({
        role: t.role,
        content: t.content,
      }));
      await inspirationChatStream(
        payload,
        {
          onThink: (delta) => setInspireThinking((prev) => prev + delta),
          onText: (delta) => {
            setInspireTurns((prev) => {
              const next = [...prev];
              for (let i = next.length - 1; i >= 0; i--) {
                if (next[i].role === "assistant") {
                  next[i] = { ...next[i], content: (next[i].content || "") + delta };
                  return next;
                }
              }
              next.push({ role: "assistant", content: delta });
              return next;
            });
          },
          onError: (message) => setInspireErr(message || "请求失败"),
          onDone: () => setInspireThinking(""),
        },
        controller.signal
      );
    } catch (e: unknown) {
      if (!(e instanceof DOMException && e.name === "AbortError")) {
        setInspireErr(e instanceof Error ? e.message : "请求失败");
      }
    } finally {
      setInspireBusy(false);
      setInspireAbort(null);
    }
  }

  function confirmSendInspiration() {
    if (!inspireInput.trim() || inspireBusy) return;
    openLlmConfirm(
      {
        title: "确认发送灵感问题？",
        description: "这会调用大模型回答你的创作问题，并把当前灵感对话历史一起带上。",
        confirmLabel: "确认发送",
        details: [
          "模型会结合当前多轮对话继续生成，问题越具体，结果通常越稳。",
          "这一步会消耗一定时间与额度，返回内容也可能直接影响你的简介、设定和文风。",
        ],
      },
      async () => {
        await sendInspiration();
      }
    );
  }

  const lastAssistant =
    [...inspireTurns].reverse().find((t) => t.role === "assistant")?.content ?? "";

  return (
    <div className="novel-shell">
      <div className="novel-container max-w-5xl space-y-6">
        <section className="glass-panel overflow-hidden p-6 md:p-8">
          <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-2xl space-y-4">
              <span className="glass-chip">
                <Sparkles className="size-3.5 text-primary" />
                创作起点
              </span>
              <div className="space-y-2">
                <h1 className="text-3xl font-semibold tracking-tight text-foreground md:text-4xl">
                  先把一本书的气质定下来，再开始长跑。
                </h1>
                <p className="text-sm leading-6 text-muted-foreground md:text-base">
                  在这里先确定书名、简介、世界设定和写作基调。你也可以先与模型聊灵感，再把结果直接带入表单。
                </p>
              </div>
              <div className="flex flex-wrap gap-3">
                <Button type="button" size="lg" onClick={() => setInspireOpen(true)}>
                  <Sparkles className="h-4 w-4" />
                  打开灵感对话
                </Button>
                <Button type="button" size="lg" variant="outline" asChild>
                  <Link to="/novels">返回书架</Link>
                </Button>
              </div>
            </div>
            <div className="grid min-w-[280px] flex-1 gap-3 sm:grid-cols-3">
              {[
                ["推荐流程", "先聊灵感"],
                ["再做什么", "补简介与设定"],
                ["最后进入", "小说工作台"],
              ].map(([label, value]) => (
                <div key={label} className="glass-panel-subtle p-4">
                  <p className="text-xs text-muted-foreground">{label}</p>
                  <p className="mt-2 text-base font-semibold tracking-tight text-foreground">
                    {value}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <div className="glass-panel-subtle p-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="space-y-1">
              <p className="font-medium text-foreground">
                与大模型对话获取创作灵感
              </p>
              <p className="text-xs leading-5 text-muted-foreground">
                使用“全局模型设置”并开启联网搜索。可多轮追问后把回复一键填入简介、背景或文风。
              </p>
            </div>
            <Button
              type="button"
              variant="glass"
              className="shrink-0 gap-2 sm:min-w-[200px]"
              onClick={() => setInspireOpen(true)}
            >
              <Sparkles className="h-4 w-4" />
              打开灵感对话
            </Button>
          </div>
        </div>

        <Dialog open={inspireOpen} onOpenChange={setInspireOpen}>
          <DialogContent className="max-h-[90vh] max-w-2xl overflow-hidden sm:max-w-2xl">
            <DialogHeader>
              <DialogTitle>创作灵感 · 联网对话</DialogTitle>
              <DialogDescription>
                使用当前“全局模型设置”，并开启
                <a
                  className="text-primary underline"
                  href="https://doc.302.ai/260112819e0"
                  target="_blank"
                  rel="noreferrer"
                >
                  联网搜索
                </a>
                。可多轮追问，再把内容填入下方表单。
              </DialogDescription>
            </DialogHeader>
            <div className="soft-scroll flex max-h-[48vh] flex-col gap-3 overflow-y-auto rounded-[1.4rem] border border-border/70 bg-muted/30 p-3 text-sm">
              {inspireTurns.length === 0 ? (
                <p className="text-muted-foreground">
                  例如：「帮我查一下 2025 年流行的无限流设定，给一个适合新人作者的梗概方向」
                </p>
              ) : null}
              {inspireTurns.map((t, i) => (
                <div
                  key={`${i}-${t.role}`}
                  className={
                    t.role === "user"
                      ? "ml-8 rounded-[1.25rem] border border-primary/20 bg-primary/10 px-3.5 py-3 shadow-sm"
                      : "mr-4 rounded-[1.25rem] border border-border/60 bg-background/80 px-3.5 py-3 shadow-sm"
                  }
                >
                  <span className="text-xs font-medium text-muted-foreground">
                    {t.role === "user" ? "你" : "助手"}
                  </span>
                  <pre className="mt-1 whitespace-pre-wrap font-sans text-xs">{t.content}</pre>
                </div>
              ))}
            </div>
            {inspireErr ? (
              <p className="text-xs text-destructive">{inspireErr}</p>
            ) : null}
            {inspireThinking ? (
              <div className="rounded-[1.25rem] border border-amber-500/40 bg-amber-500/5 p-3 text-xs">
                <p className="font-medium text-amber-700 dark:text-amber-300">Think</p>
                <pre className="mt-1 whitespace-pre-wrap font-sans text-[11px] text-amber-800 dark:text-amber-200">
                  {inspireThinking}
                </pre>
              </div>
            ) : null}
            <div className="flex gap-2">
              <textarea
                value={inspireInput}
                onChange={(e) => setInspireInput(e.target.value)}
                placeholder="输入问题…（Enter 发送，Shift+Enter 换行）"
                className="field-shell-textarea min-h-[84px] flex-1"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    confirmSendInspiration();
                  }
                }}
                disabled={inspireBusy}
              />
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                disabled={inspireBusy || !inspireInput.trim()}
                onClick={() => confirmSendInspiration()}
              >
                {inspireBusy ? "思考中…" : "发送"}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                disabled={!inspireBusy || !inspireAbort}
                onClick={() => inspireAbort?.abort()}
              >
                取消生成
              </Button>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                disabled={!lastAssistant}
                onClick={() => setIntro(lastAssistant)}
              >
                填入简介
              </Button>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                disabled={!lastAssistant}
                onClick={() => setBackground(lastAssistant)}
              >
                填入背景与设定
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={!lastAssistant}
                onClick={() => setStyle((s) => (s ? `${s}\n${lastAssistant}` : lastAssistant))}
              >
                追加到文风
              </Button>
            </div>
          </DialogContent>
        </Dialog>

        <LlmActionConfirmDialog
          open={Boolean(llmConfirm)}
          onOpenChange={handleLlmConfirmOpenChange}
          title={llmConfirm?.title ?? "确认调用大模型"}
          description={llmConfirm?.description ?? ""}
          confirmLabel={llmConfirm?.confirmLabel}
          details={llmConfirm?.details ?? []}
          busy={llmConfirmBusy}
          onConfirm={runConfirmedLlmAction}
        />

        <form onSubmit={onSubmit} className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
          <div className="glass-panel-subtle space-y-4 p-5">
            <div>
              <p className="section-heading">作品基础信息</p>
              <p className="mt-1 text-sm text-muted-foreground">
                先描述这本书是什么、讲谁、在什么世界里展开。字段不必一次写满，先把骨架立住更重要。
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="title">书名</Label>
              <Input
                id="title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                className="field-shell mt-1 h-11"
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="intro">简介</Label>
              <textarea
                id="intro"
                value={intro}
                onChange={(e) => setIntro(e.target.value)}
                className="field-shell-textarea min-h-[110px]"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="bg">背景与设定</Label>
              <textarea
                id="bg"
                value={background}
                onChange={(e) => setBackground(e.target.value)}
                className="field-shell-textarea min-h-[160px]"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="style">文风</Label>
              <Input
                id="style"
                value={style}
                onChange={(e) => setStyle(e.target.value)}
                className="field-shell mt-1 h-11"
              />
            </div>
          </div>

          <div className="space-y-4">
            <div className="glass-panel-subtle space-y-4 p-5">
              <div>
                <p className="section-heading">创作节奏</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  这部分决定作品规模和默认推进速度，后续也能在工作台再调整。
                </p>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="tc">目标章节数</Label>
                  <Input
                    id="tc"
                    type="number"
                    min={1}
                    max={20000}
                    value={targetChapters}
                    onChange={(e) => setTargetChapters(Number(e.target.value))}
                    className="field-shell mt-1 h-11"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="daily">每日自动撰写章数</Label>
                  <Input
                    id="daily"
                    type="number"
                    min={0}
                    max={20}
                    value={dailyChapters}
                    onChange={(e) => setDailyChapters(Number(e.target.value))}
                    className="field-shell mt-1 h-11"
                  />
                </div>
              </div>
              <p className="text-xs text-muted-foreground">
                `0` 表示关闭自动撰写；开启后需要 Celery Beat 正常运行。
              </p>
            </div>

            <div className="glass-panel-subtle space-y-4 p-5">
              <div>
                <p className="section-heading">参考素材</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  可上传一份 `.txt` 作为风格或设定参考，后续进入工作台后再慢慢补充。
                </p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="ref">参考 txt（可选，最大 15MB）</Label>
                <Input
                  id="ref"
                  type="file"
                  accept=".txt,text/plain"
                  className="field-shell mt-1 h-11 pt-2"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                />
                {file ? (
                  <p className="text-xs text-muted-foreground">已选择：{file.name}</p>
                ) : null}
              </div>
              {err ? (
                <div className="rounded-[1.1rem] border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                  {err}
                </div>
              ) : null}
              <div className="flex flex-wrap gap-2">
                <Button type="submit" disabled={loading}>
                  {loading ? "创建中…" : "创建小说"}
                </Button>
                <Button type="button" variant="secondary" asChild>
                  <Link to="/novels">取消</Link>
                </Button>
              </div>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
