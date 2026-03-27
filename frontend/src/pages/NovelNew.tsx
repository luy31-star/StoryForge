import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Sparkles } from "lucide-react";
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

  const lastAssistant =
    [...inspireTurns].reverse().find((t) => t.role === "assistant")?.content ?? "";

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="mx-auto max-w-xl space-y-6">
        <div>
          <h1 className="text-2xl font-bold">新建小说</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            本页地址为 <code className="rounded bg-muted px-1 py-0.5 text-xs">/novels/new</code>
            （从书架点「新建小说」进入）。填表前可先与模型对话找灵感。
          </p>
        </div>

        <div className="rounded-lg border border-primary/35 bg-primary/5 p-4 shadow-sm">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="space-y-1">
              <p className="font-medium text-foreground">
                与大模型对话获取创作灵感
              </p>
              <p className="text-xs text-muted-foreground">
                使用“全局模型设置”并开启联网搜索。可多轮追问后把回复一键填入简介、背景或文风。
              </p>
            </div>
            <Button
              type="button"
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
              <div className="flex max-h-[48vh] flex-col gap-2 overflow-y-auto rounded-md border border-border bg-muted/30 p-3 text-sm">
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
                        ? "ml-8 rounded-md bg-primary/10 px-3 py-2"
                        : "mr-4 rounded-md bg-background px-3 py-2"
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
                <div className="rounded-md border border-amber-500/40 bg-amber-500/5 p-2 text-xs">
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
                  className="min-h-[72px] flex-1 rounded-md border border-input bg-background px-3 py-2 text-sm"
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      void sendInspiration();
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
                  onClick={() => void sendInspiration()}
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

        <form onSubmit={onSubmit} className="space-y-4">
          <div>
            <Label htmlFor="title">书名</Label>
            <Input
              id="title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="mt-1"
              required
            />
          </div>
          <div>
            <Label htmlFor="intro">简介</Label>
            <textarea
              id="intro"
              value={intro}
              onChange={(e) => setIntro(e.target.value)}
              className="mt-1 min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            />
          </div>
          <div>
            <Label htmlFor="bg">背景与设定</Label>
            <textarea
              id="bg"
              value={background}
              onChange={(e) => setBackground(e.target.value)}
              className="mt-1 min-h-[100px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            />
          </div>
          <div>
            <Label htmlFor="style">文风</Label>
            <Input
              id="style"
              value={style}
              onChange={(e) => setStyle(e.target.value)}
              className="mt-1"
            />
          </div>
          <div>
            <Label htmlFor="tc">目标章节数</Label>
            <Input
              id="tc"
              type="number"
              min={1}
              max={20000}
              value={targetChapters}
              onChange={(e) => setTargetChapters(Number(e.target.value))}
              className="mt-1"
            />
          </div>
          <div>
            <Label htmlFor="daily">每日自动撰写章数（0=关闭，需 Celery Beat）</Label>
            <Input
              id="daily"
              type="number"
              min={0}
              max={20}
              value={dailyChapters}
              onChange={(e) => setDailyChapters(Number(e.target.value))}
              className="mt-1"
            />
          </div>
          <div>
            <Label htmlFor="ref">参考 txt（可选，最大 15MB）</Label>
            <Input
              id="ref"
              type="file"
              accept=".txt,text/plain"
              className="mt-1"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </div>
          {err ? <p className="text-sm text-destructive">{err}</p> : null}
          <div className="flex gap-2">
            <Button type="submit" disabled={loading}>
              {loading ? "创建中…" : "创建"}
            </Button>
            <Button type="button" variant="secondary" asChild>
              <Link to="/novels">取消</Link>
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
