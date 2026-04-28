import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
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
  batchReplaceNames,
  generateFramework,
  regenerateFramework,
  updateFrameworkCharacters,
  waitForFrameworkCharactersBatch,
  waitForFrameworkGenerateBatch,
  waitForFrameworkRegenerateBatch,
} from "@/services/novelApi";
import { ensureLlmReady } from "@/services/llmReady";
import { Sparkles } from "lucide-react";

type CharacterRow = {
  id: string;
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
      .map((x, idx) => {
        if (!x || typeof x !== "object" || Array.isArray(x)) return null;
        const o = x as Record<string, unknown>;
        return {
          id: `char-${idx}-${Date.now()}`,
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
  baseFrameworkConfirmed: boolean;
  frameworkMarkdown: string;
  frameworkJson: string;
  status: string;
  onReload: () => Promise<void>;
  onConfirmFramework: () => Promise<void>;
  onConfirmBaseFramework: () => Promise<void>;
}) {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [regenInstruction, setRegenInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [notice, setNotice] = useState<React.ReactNode | null>(null);
  const [taskStartedOpen, setTaskStartedOpen] = useState(false);

  const originalChars = useMemo(
    () => parseCharactersFromFrameworkJson(props.frameworkJson),
    [props.frameworkJson]
  );

  const [characters, setCharacters] = useState<CharacterRow[]>([]);
  const [shouldSyncNames, setShouldSyncNames] = useState(false);

  useEffect(() => {
    if (!props.open) return;
    if (props.frameworkConfirmed) {
      setStep(2);
    } else if (props.baseFrameworkConfirmed) {
      setStep(1);
    } else {
      setStep(0);
    }
    setErr(null);
    setRegenInstruction("");
    setCharacters(originalChars.length ? originalChars : []);
  }, [props.open, originalChars, props.baseFrameworkConfirmed, props.frameworkConfirmed]);

  const warningText = props.frameworkConfirmed
    ? "你正在修改已确认的框架：确认新版本后，可能影响之前已生成的章节一致性；后续续写会以新框架为准。"
    : "当前框架处于待确认状态：请先确认大纲与人物，再关闭向导，在工作台「大纲抽屉」里生成分卷剧情。";

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
        setNotice(
          <div className="flex w-full items-center justify-between">
            <span>正在按指令重写大纲...</span>
            <Button
              variant="ghost"
              size="sm"
              className="ml-2 h-auto p-0 font-bold text-emerald-600 underline decoration-2 underline-offset-4 hover:bg-transparent dark:text-emerald-300"
              onClick={() => {
                props.onOpenChange(false);
                navigate("/tasks");
              }}
            >
              前往任务页查看进度
            </Button>
          </div>
        );
        const o = await waitForFrameworkRegenerateBatch(props.novelId, bid);
        if (o === "failed") throw new Error("重写大纲失败，请查看生成日志");
      }
      setNotice(null);
      await props.onReload();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "重写大纲失败");
    } finally {
      setBusy(false);
    }
  }

  async function runRetryInitialFramework() {
    setErr(null);
    setBusy(true);
    try {
      const r = await generateFramework(props.novelId);
      const bid = r.batch_id;
      if (r.status === "queued" && bid) {
        setNotice(
          <div className="flex w-full items-center justify-between">
            <span>正在重新生成全书大纲...</span>
            <Button
              variant="ghost"
              size="sm"
              className="ml-2 h-auto p-0 font-bold text-emerald-600 underline decoration-2 underline-offset-4 hover:bg-transparent dark:text-emerald-300"
              onClick={() => {
                props.onOpenChange(false);
                navigate("/tasks");
              }}
            >
              前往任务页查看进度
            </Button>
          </div>
        );
        const o = await waitForFrameworkGenerateBatch(props.novelId, bid);
        if (o === "failed") throw new Error("生成大纲失败，请查看生成日志");
      }
      setNotice(null);
      await props.onReload();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "重试首版大纲失败");
    } finally {
      setBusy(false);
    }
  }

  const hasCharactersChanged = useMemo(() => {
    if (originalChars.length !== characters.length) return true;
    for (let i = 0; i < originalChars.length; i++) {
      if (
        originalChars[i].name !== characters[i].name ||
        originalChars[i].role !== characters[i].role ||
        originalChars[i].traits !== characters[i].traits
      ) {
        return true;
      }
    }
    return false;
  }, [originalChars, characters]);

  const nameMapping = useMemo(() => {
    const mapping: Record<string, string> = {};
    if (!props.frameworkConfirmed) return mapping;
    for (let i = 0; i < Math.min(originalChars.length, characters.length); i++) {
      const oldName = originalChars[i].name.trim();
      const newName = characters[i].name.trim();
      if (oldName && newName && oldName !== newName) {
        mapping[oldName] = newName;
      }
    }
    return mapping;
  }, [originalChars, characters, props.frameworkConfirmed]);

  const hasNameChanges = Object.keys(nameMapping).length > 0;

  async function runUpdateCharacters() {
    if (!characters.length) {
      setErr("请至少保留一个人物");
      return;
    }

    if (!hasCharactersChanged) {
      setStep(2);
      return;
    }

    if (hasNameChanges && shouldSyncNames) {
      try {
        setBusy(true);
        await batchReplaceNames(props.novelId, nameMapping);
      } catch (e: unknown) {
        console.error("Batch replace failed:", e);
        setErr("同步正文名字失败，但将继续更新人物设定");
      } finally {
        setBusy(false);
      }
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
        setNotice(
          <div className="flex w-full items-center justify-between">
            <span>正在后台按设定更新大纲...</span>
            <Button
              variant="ghost"
              size="sm"
              className="ml-2 h-auto p-0 font-bold text-emerald-600 underline decoration-2 underline-offset-4 hover:bg-transparent dark:text-emerald-300"
              onClick={() => {
                props.onOpenChange(false);
                navigate("/tasks");
              }}
            >
              前往任务页查看进度
            </Button>
          </div>
        );
        const o = await waitForFrameworkCharactersBatch(props.novelId, bid);
        if (o === "failed") throw new Error("更新人物设定失败，请查看生成日志");
      }
      setNotice(null);
      await props.onReload();
      setStep(2);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "更新人物设定失败");
    } finally {
      setBusy(false);
    }
  }

  async function runConfirmBaseFramework() {
    setErr(null);
    setBusy(true);
    try {
      await props.onConfirmBaseFramework();
      setStep(1);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "确认基础大纲失败");
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
        setTaskStartedOpen(true);
      } else {
        props.onOpenChange(false);
      }
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "确认框架失败");
    } finally {
      setBusy(false);
    }
  }

  const stepLabels = ["大纲", "人物", "确认"];
  const totalSteps = 3;

  return (
    <>
      <Dialog open={props.open} onOpenChange={props.onOpenChange}>
        <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="text-xl font-bold text-foreground">
              修改向导（{step + 1}/{totalSteps} · {stepLabels[step]}）
            </DialogTitle>
            <DialogDescription className="leading-relaxed text-foreground/80 dark:text-muted-foreground">
              {warningText}
            </DialogDescription>
          </DialogHeader>

          {err ? (
            <div className="glass-panel-subtle flex items-center gap-2 border-destructive/30 px-4 py-3 text-sm text-destructive">
              <div className="h-1.5 w-1.5 rounded-full bg-destructive" />
              {err}
            </div>
          ) : null}

          {notice ? (
            <div className="glass-panel-subtle flex items-center gap-2 border-emerald-500/30 px-4 py-3 text-sm text-emerald-600 dark:text-emerald-300">
              <div className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
              {notice}
            </div>
          ) : null}

          {/* Step 0: 大纲修改 */}
          {step === 0 ? (
            <div className="space-y-4 py-2">
              <div className="space-y-2">
                <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">
                  大纲草案（可先浏览确认）
                </Label>
                {!props.frameworkMarkdown ? (
                  <div className="mt-2 flex min-h-[260px] w-full flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-primary/30 bg-primary/5 p-4 text-center text-sm text-primary/70">
                    {props.status === "failed" ? (
                      <>
                        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-destructive/10">
                          <div className="h-4 w-4 rounded-full bg-destructive" />
                        </div>
                        <p className="text-base font-bold text-destructive">大纲生成任务似乎失败了</p>
                        <p className="mb-2 max-w-xs text-xs opacity-60">
                          这里会重新触发首版大纲生成；如果你已经有草案，建议回到上一步用自然语言重写当前版本。
                        </p>
                        <Button
                          size="sm"
                          variant="outline"
                          className="font-bold border-destructive/30 text-destructive hover:bg-destructive/5"
                          onClick={() => void runRetryInitialFramework()}
                          disabled={busy}
                        >
                          {busy ? "重试中..." : "手动重试首版大纲"}
                        </Button>
                      </>
                    ) : (
                      <>
                        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary/10">
                          <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                        </div>
                        <p className="animate-pulse text-base font-bold">AI 正在努力构思全书大纲中...</p>
                        <p className="max-w-xs text-xs opacity-60">
                          这通常需要 15-30 秒，构思完成后此页面将自动刷新并显示内容。
                        </p>
                      </>
                    )}
                  </div>
                ) : (
                  <textarea
                    value={props.frameworkMarkdown || ""}
                    readOnly
                    className="mt-2 min-h-[260px] w-full rounded-2xl border border-border/70 bg-background/70 p-4 font-mono text-sm text-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.35)]"
                  />
                )}
              </div>
              {props.frameworkMarkdown && (
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
                  {hasNameChanges && (
                    <div className="mt-4 flex items-center gap-3 rounded-2xl border border-primary/20 bg-primary/5 p-4">
                      <input
                        type="checkbox"
                        id="sync-names"
                        className="size-4 rounded border-gray-300 text-primary focus:ring-primary"
                        checked={shouldSyncNames}
                        onChange={(e) => setShouldSyncNames(e.target.checked)}
                        disabled={busy}
                      />
                      <Label htmlFor="sync-names" className="cursor-pointer text-sm font-semibold">
                        检测到人物改名，是否同步替换已生成章节正文中的旧名字？
                      </Label>
                    </div>
                  )}
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
                      onClick={() => {
                        if (props.baseFrameworkConfirmed) {
                          setStep(1);
                        } else {
                          void runConfirmBaseFramework();
                        }
                      }}
                    >
                      {busy
                        ? "确认中…"
                        : props.baseFrameworkConfirmed
                          ? "大纲已确认，下一步"
                          : "大纲没问题，确认并下一步"}
                    </Button>
                  </div>
                </div>
              )}
            </div>
          ) : null}

          {/* Step 1: 人物修改 */}
          {step === 1 ? (
            <div className="space-y-4 py-2">
              <div className="space-y-2">
                <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">
                  主角/人物确认（可修改名称与性格）
                </Label>
                {!props.baseFrameworkConfirmed ? (
                  <div className="rounded-xl border-2 border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm font-medium text-amber-900 dark:text-amber-100">
                    请先在「大纲」一步点击「确认并下一步」，提交对全书基础大纲的确认后，才能继续核对人物。
                  </div>
                ) : null}
                {characters.length ? (
                  <div className="space-y-3">
                    {characters.map((c, idx) => (
                      <div key={c.id} className="rounded-2xl border border-border/70 bg-background/60 p-4">
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
                              disabled={busy || !props.baseFrameworkConfirmed}
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
                              disabled={busy || !props.baseFrameworkConfirmed}
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
                              disabled={busy || !props.baseFrameworkConfirmed}
                            />
                          </div>
                        </div>
                        <div className="mt-3 flex justify-end">
                          <Button
                            type="button"
                            size="sm"
                            variant="destructive"
                            disabled={busy || characters.length <= 1 || !props.baseFrameworkConfirmed}
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
                    当前未能从大纲里读出人物列表。建议先回到上一步重试首版生成，或基于当前草案重写大纲后再试。
                  </div>
                )}
                <div className="flex flex-wrap gap-2">
                  <Button type="button" variant="outline" className="font-bold" disabled={busy} onClick={() => setStep(0)}>
                    上一步
                  </Button>
                  <Button
                    type="button"
                    className="font-bold"
                    disabled={busy || characters.length === 0 || !props.baseFrameworkConfirmed}
                    onClick={() => void runUpdateCharacters()}
                  >
                    {busy ? "更新中…" : hasCharactersChanged ? "确认人物并让 AI 更新大纲" : "人物无修改，下一步"}
                  </Button>
                </div>
              </div>
            </div>
          ) : null}

          {/* Step 2: 最终确认（分卷剧情在向导外「大纲抽屉」生成） */}
          {step === 2 ? (
            <div className="space-y-4 py-2">
              {!props.baseFrameworkConfirmed ? (
                <div className="rounded-xl border-2 border-destructive/35 bg-destructive/10 px-4 py-3 text-sm font-medium text-destructive">
                  还不能确认全书框架：请返回前两步，先确认大纲，再保存人物。完成后再到本页点击「确认全书框架」。
                </div>
              ) : !props.frameworkConfirmed ? (
                <div className="rounded-xl border-2 border-primary/30 bg-primary/5 px-4 py-3 text-sm font-medium text-foreground">
                  基础大纲与人物已就绪。请先关闭本向导，在工作台顶部打开「大纲抽屉」，为需要的卷生成分卷剧情；需要时生成卷列表与章计划后，再回到此处确认全书框架以开始正式创作。
                </div>
              ) : null}
              <div className="space-y-2">
                <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">
                  最终确认（可返回继续修改）
                </Label>
                <p className="text-xs text-foreground/60 dark:text-muted-foreground">
                  以下为全书基础大纲（世界观、人物、主线）。各卷剧情在「大纲抽屉」里单独生成与维护。
                </p>
                <textarea
                  value={props.frameworkMarkdown || ""}
                  readOnly
                  className="mt-2 min-h-[220px] w-full rounded-2xl border border-border/70 bg-background/70 p-4 font-mono text-sm text-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.35)]"
                />
              </div>
              <div className="flex flex-wrap gap-2">
                <Button type="button" variant="outline" className="font-bold" disabled={busy} onClick={() => setStep(0)}>
                  再改大纲
                </Button>
                <Button type="button" variant="outline" className="font-bold" disabled={busy} onClick={() => setStep(1)}>
                  再改人物
                </Button>
                <Button
                  type="button"
                  className="font-bold"
                  disabled={busy || !props.baseFrameworkConfirmed}
                  onClick={() => void runConfirmFramework()}
                >
                  {busy ? "确认中…" : "确认全书框架"}
                </Button>
              </div>
            </div>
          ) : null}

          <DialogFooter>
            <Button variant="outline" onClick={() => props.onOpenChange(false)} disabled={busy}>
              关闭
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <TaskStartedDialog
        open={taskStartedOpen}
        onOpenChange={(v) => {
          setTaskStartedOpen(v);
          if (!v) props.onOpenChange(false);
        }}
      />
    </>
  );
}

function TaskStartedDialog(props: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const navigate = useNavigate();
  return (
    <Dialog open={props.open} onOpenChange={props.onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-xl font-bold">
            <Sparkles className="size-5 text-primary" />
            任务已在后台启动
          </DialogTitle>
          <DialogDescription className="pt-2 leading-relaxed text-foreground/80">
            AI 正在为你生成内容。此过程可能需要几十秒，你可以留在本页等待，也可以前往「我的任务」模块查看详细进度。
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="gap-2 sm:gap-0">
          <Button variant="outline" className="font-bold" onClick={() => props.onOpenChange(false)}>
            留在本页
          </Button>
          <Button
            className="font-bold"
            onClick={() => {
              props.onOpenChange(false);
              navigate("/tasks");
            }}
          >
            前往我的任务
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
