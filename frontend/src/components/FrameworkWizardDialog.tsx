import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  autoGenerateChapters,
  regenerateFramework,
  updateFrameworkCharacters,
  waitForFrameworkCharactersBatch,
  waitForFrameworkRegenerateBatch,
} from "@/services/novelApi";
import { ensureLlmReady } from "@/services/llmReady";

type CharacterRow = {
  name: string;
  role: string;
  traits: string;
};

function parseCharactersFromFrameworkJson(fwJson: string): CharacterRow[] {
  try {
    const data = JSON.parse(fwJson || "{}") as Record<string, unknown>;
    const raw = data.characters;
    if (!Array.isArray(raw)) return [];
    return raw
      .map((x) => {
        if (!x || typeof x !== "object" || Array.isArray(x)) return null;
        const o = x as Record<string, unknown>;
        return {
          name: typeof o.name === "string" ? o.name : "",
          role: typeof o.role === "string" ? o.role : "",
          traits: typeof o.traits === "string" ? o.traits : "",
        } satisfies CharacterRow;
      })
      .filter((x): x is CharacterRow => Boolean(x && x.name.trim()));
  } catch {
    return [];
  }
}

export function FrameworkWizardDialog(props: {
  novelId: string;
  open: boolean;
  onOpenChange: (next: boolean) => void;
  frameworkConfirmed: boolean;
  frameworkMarkdown: string;
  frameworkJson: string;
  onReload: () => Promise<void>;
  onConfirmFramework: () => Promise<void>;
}) {
  const [step, setStep] = useState(0);
  const [regenInstruction, setRegenInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const originalChars = useMemo(
    () => parseCharactersFromFrameworkJson(props.frameworkJson),
    [props.frameworkJson]
  );
  const [characters, setCharacters] = useState<CharacterRow[]>([]);

  useEffect(() => {
    if (!props.open) return;
    setStep(0);
    setErr(null);
    setRegenInstruction("");
    setCharacters(originalChars.length ? originalChars : []);
  }, [props.open, originalChars]);

  const warningText = props.frameworkConfirmed
    ? "你正在修改已确认的框架：确认新版本后，可能影响之前已生成的章节一致性；后续续写会以新框架为准。"
    : "当前框架处于待确认状态：你可以先迭代大纲和主角设定，再确认并开始续写。";

  async function runRegenerate() {
    const instruction = regenInstruction.trim();
    if (!instruction) {
      setErr("请先输入你希望如何修改大纲的自然语言指令");
      return;
    }
    setErr(null);
    setBusy(true);
    try {
      const r = await regenerateFramework(props.novelId, instruction);
      const bid = r.batch_id;
      if (r.status === "queued" && bid) {
        const o = await waitForFrameworkRegenerateBatch(props.novelId, bid);
        if (o === "failed") throw new Error("重生成大纲失败，请查看生成日志");
      }
      await props.onReload();
      setRegenInstruction("");
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "重生成大纲失败");
    } finally {
      setBusy(false);
    }
  }

  async function runUpdateCharacters() {
    if (!characters.length) {
      setErr("请至少保留一个人物");
      return;
    }
    const payload = characters
      .map((c) => ({
        name: c.name.trim(),
        role: c.role.trim(),
        traits: c.traits.trim(),
      }))
      .filter((c) => c.name);
    if (!payload.length) {
      setErr("人物名称不能为空");
      return;
    }
    setErr(null);
    setBusy(true);
    try {
      const r = await updateFrameworkCharacters(props.novelId, payload);
      const bid = r.batch_id;
      if (r.status === "queued" && bid) {
        const o = await waitForFrameworkCharactersBatch(props.novelId, bid);
        if (o === "failed") throw new Error("更新人物设定失败，请查看生成日志");
      }
      await props.onReload();
      setStep(2);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "更新人物设定失败");
    } finally {
      setBusy(false);
    }
  }

  async function runConfirmFramework() {
    setErr(null);
    setBusy(true);
    try {
      await props.onConfirmFramework();
      const ready = await ensureLlmReady();
      if (!ready) {
        props.onOpenChange(false);
        return;
      }
      const input = window.prompt("确认框架后，自动继续生成多少章？（填 0 表示暂不生成）", "0");
      if (input === null) {
        props.onOpenChange(false);
        return;
      }
      const n = Number(String(input).trim() || "0");
      if (!Number.isFinite(n) || n < 0 || n > 50) {
        throw new Error("请输入 0-50 的数字");
      }
      if (n > 0) {
        await autoGenerateChapters(props.novelId, n);
      }
      props.onOpenChange(false);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "确认框架失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={props.open} onOpenChange={props.onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-xl font-bold text-foreground">
            修改向导（{step + 1}/3）
          </DialogTitle>
          <DialogDescription className="text-foreground/80 dark:text-muted-foreground leading-relaxed">
            {warningText}
          </DialogDescription>
        </DialogHeader>

        {err ? (
          <div className="glass-panel-subtle flex items-center gap-2 border-destructive/30 px-4 py-3 text-sm text-destructive">
            <div className="h-1.5 w-1.5 rounded-full bg-destructive" />
            {err}
          </div>
        ) : null}

        {step === 0 ? (
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">
                大纲草案（可先浏览确认）
              </Label>
              <textarea
                value={props.frameworkMarkdown || ""}
                readOnly
                className="mt-2 min-h-[260px] w-full rounded-2xl border border-border/70 bg-background/70 p-4 font-mono text-sm text-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.35)]"
              />
            </div>
            <div className="space-y-2">
              <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">
                不满意？用自然语言让 AI 重写
              </Label>
              <Input
                value={regenInstruction}
                onChange={(e) => setRegenInstruction(e.target.value)}
                placeholder="例如：把主线冲突更强、节奏更快；把背景换成近未来；增加悬疑反转..."
                disabled={busy}
              />
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="secondary"
                  className="font-bold"
                  disabled={busy || !regenInstruction.trim()}
                  onClick={() => void runRegenerate()}
                >
                  {busy ? "重生成中…" : "让 AI 重写大纲"}
                </Button>
                <Button
                  type="button"
                  className="font-bold"
                  disabled={busy}
                  onClick={() => setStep(1)}
                >
                  大纲没问题，下一步
                </Button>
              </div>
            </div>
          </div>
        ) : null}

        {step === 1 ? (
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">
                主角/人物确认（可修改名称与性格）
              </Label>
              {characters.length ? (
                <div className="space-y-3">
                  {characters.map((c, idx) => (
                    <div
                      key={`${c.name}-${idx}`}
                      className="rounded-2xl border border-border/70 bg-background/60 p-4"
                    >
                      <div className="grid gap-3 sm:grid-cols-3">
                        <div className="space-y-1">
                          <Label className="text-xs font-semibold text-foreground/70">名称</Label>
                          <Input
                            value={c.name}
                            onChange={(e) => {
                              const v = e.target.value;
                              setCharacters((prev) => {
                                const next = [...prev];
                                next[idx] = { ...next[idx], name: v };
                                return next;
                              });
                            }}
                            disabled={busy}
                          />
                        </div>
                        <div className="space-y-1">
                          <Label className="text-xs font-semibold text-foreground/70">定位</Label>
                          <Input
                            value={c.role}
                            onChange={(e) => {
                              const v = e.target.value;
                              setCharacters((prev) => {
                                const next = [...prev];
                                next[idx] = { ...next[idx], role: v };
                                return next;
                              });
                            }}
                            disabled={busy}
                          />
                        </div>
                        <div className="space-y-1">
                          <Label className="text-xs font-semibold text-foreground/70">性格/特质</Label>
                          <Input
                            value={c.traits}
                            onChange={(e) => {
                              const v = e.target.value;
                              setCharacters((prev) => {
                                const next = [...prev];
                                next[idx] = { ...next[idx], traits: v };
                                return next;
                              });
                            }}
                            disabled={busy}
                          />
                        </div>
                      </div>
                      <div className="mt-3 flex justify-end">
                        <Button
                          type="button"
                          size="sm"
                          variant="destructive"
                          disabled={busy || characters.length <= 1}
                          onClick={() => {
                            setCharacters((prev) => prev.filter((_, i) => i !== idx));
                          }}
                        >
                          删除
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-sm text-foreground/70 dark:text-muted-foreground">
                  当前框架 JSON 未解析到 characters 列表。建议先在上一步重生成大纲，或在工作台里手动补充后再试。
                </div>
              )}
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="outline"
                  className="font-bold"
                  disabled={busy}
                  onClick={() => setStep(0)}
                >
                  上一步
                </Button>
                <Button
                  type="button"
                  className="font-bold"
                  disabled={busy || characters.length === 0}
                  onClick={() => void runUpdateCharacters()}
                >
                  {busy ? "更新中…" : "确认人物并让 AI 更新大纲"}
                </Button>
              </div>
            </div>
          </div>
        ) : null}

        {step === 2 ? (
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">
                最终确认（可返回继续修改）
              </Label>
              <textarea
                value={props.frameworkMarkdown || ""}
                readOnly
                className="mt-2 min-h-[220px] w-full rounded-2xl border border-border/70 bg-background/70 p-4 font-mono text-sm text-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.35)]"
              />
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="outline"
                className="font-bold"
                disabled={busy}
                onClick={() => setStep(0)}
              >
                再改大纲
              </Button>
              <Button
                type="button"
                variant="outline"
                className="font-bold"
                disabled={busy}
                onClick={() => setStep(1)}
              >
                再改人物
              </Button>
              <Button
                type="button"
                className="font-bold"
                disabled={busy}
                onClick={() => void runConfirmFramework()}
              >
                {busy ? "确认中…" : "确认框架"}
              </Button>
            </div>
          </div>
        ) : null}

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => props.onOpenChange(false)}
            disabled={busy}
          >
            关闭
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
