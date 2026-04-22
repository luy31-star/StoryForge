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
  generateArcs,
  generateFramework,
  regenerateFramework,
  updateFrameworkCharacters,
  waitForArcsGenerateBatch,
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

/** 从 framework_json 解析出已有的 arcs 按卷号列表（兼容旧数据） */
function parseVolumeNosFromFrameworkJson(fwJson: string): number[] {
  try {
    const data = JSON.parse(fwJson || "{}") as Record<string, unknown>;
    const arcs = data.arcs;
    if (!Array.isArray(arcs)) return [];
    const volSet = new Set<number>();
    for (const arc of arcs) {
      if (!arc || typeof arc !== "object") continue;
      const o = arc as Record<string, unknown>;
      const volNo = o.volume_no;
      if (typeof volNo === "number" && volNo > 0) volSet.add(volNo);
    }
    return Array.from(volSet).sort((a, b) => a - b);
  } catch {
    return [];
  }
}

type VolumeOutlineRow = {
  volume_no: number;
  title: string;
  outline_json?: string;
  outline_markdown?: string;
};

/** 优先从卷表判断哪些卷已有 Arcs */
function volumeNosWithArcsFromVolumes(volumes: VolumeOutlineRow[]): number[] {
  const ns: number[] = [];
  for (const v of volumes) {
    const md = (v.outline_markdown || "").trim();
    if (md) {
      ns.push(v.volume_no);
      continue;
    }
    const raw = (v.outline_json || "").trim();
    if (!raw || raw === "{}") continue;
    try {
      const o = JSON.parse(raw) as { arcs?: unknown };
      if (Array.isArray(o.arcs) && o.arcs.length > 0) ns.push(v.volume_no);
    } catch {
      /* ignore */
    }
  }
  return ns.sort((a, b) => a - b);
}

/** 根据目标章节数计算总卷数（50章/卷） */
function calcTotalVolumes(targetChapters: number): number {
  if (!targetChapters || targetChapters <= 0) return 1;
  return Math.ceil(targetChapters / 50);
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
  targetChapters: number;
  /** 各卷 outline（与小说级大纲分离）；用于 Arcs 步骤展示与「已有卷」标记 */
  volumes?: VolumeOutlineRow[];
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

  // Arcs 相关状态
  const [arcsInstruction, setArcsInstruction] = useState("");
  const [arcsTargetVolumes, setArcsTargetVolumes] = useState<number[]>([]);

  const originalChars = useMemo(
    () => parseCharactersFromFrameworkJson(props.frameworkJson),
    [props.frameworkJson]
  );
  const existingVolumeNos = useMemo(() => {
    const rows = props.volumes ?? [];
    if (rows.length > 0) {
      return volumeNosWithArcsFromVolumes(rows);
    }
    return parseVolumeNosFromFrameworkJson(props.frameworkJson);
  }, [props.volumes, props.frameworkJson]);

  const volumeArcsPreviewMd = useMemo(() => {
    const rows = props.volumes ?? [];
    return rows
      .filter((v) => (v.outline_markdown || "").trim().length > 0)
      .sort((a, b) => a.volume_no - b.volume_no)
      .map(
        (v) =>
          `### 第${v.volume_no}卷 ${(v.title || "").trim()}\n\n${(v.outline_markdown || "").trim()}`
      )
      .join("\n\n---\n\n");
  }, [props.volumes]);
  const totalVolumes = useMemo(
    () => calcTotalVolumes(props.targetChapters),
    [props.targetChapters]
  );

  const [characters, setCharacters] = useState<CharacterRow[]>([]);
  const [shouldSyncNames, setShouldSyncNames] = useState(false);

  useEffect(() => {
    if (!props.open) return;
    // 根据确认状态决定初始步骤
    if (props.frameworkConfirmed) {
      setStep(2); // 已确认框架，直接跳到 arcs 步骤
    } else if (props.baseFrameworkConfirmed) {
      setStep(1); // base 已确认，跳到人物步骤
    } else {
      setStep(0);
    }
    setErr(null);
    setRegenInstruction("");
    setArcsInstruction("");
    setArcsTargetVolumes([]);
    setCharacters(originalChars.length ? originalChars : []);
  }, [props.open, originalChars, props.baseFrameworkConfirmed, props.frameworkConfirmed]);

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
        setNotice(
          <div className="flex items-center justify-between w-full">
            <span>正在后台重生成大纲...</span>
            <Button
              variant="ghost"
              size="sm"
              className="h-auto p-0 text-emerald-600 dark:text-emerald-300 font-bold underline decoration-2 underline-offset-4 ml-2 hover:bg-transparent"
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
        if (o === "failed") throw new Error("重生成大纲失败，请查看生成日志");
      }
      setNotice(null);
      await props.onReload();
      setRegenInstruction("");
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "重生成大纲失败");
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
          <div className="flex items-center justify-between w-full">
            <span>正在后台生成大纲框架...</span>
            <Button
              variant="ghost"
              size="sm"
              className="h-auto p-0 text-emerald-600 dark:text-emerald-300 font-bold underline decoration-2 underline-offset-4 ml-2 hover:bg-transparent"
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
      setErr(e instanceof Error ? e.message : "重新生成大纲失败");
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
          <div className="flex items-center justify-between w-full">
            <span>正在后台按设定更新大纲...</span>
            <Button
              variant="ghost"
              size="sm"
              className="h-auto p-0 text-emerald-600 dark:text-emerald-300 font-bold underline decoration-2 underline-offset-4 ml-2 hover:bg-transparent"
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

  async function runGenerateArcs() {
    if (!arcsTargetVolumes.length) {
      setErr("请至少选择一卷");
      return;
    }
    setErr(null);
    setBusy(true);
    try {
      const r = await generateArcs(props.novelId, {
        target_volume_nos: arcsTargetVolumes,
        instruction: arcsInstruction.trim(),
      });
      const bid = r.batch_id;
      if (r.status === "queued" && bid) {
        setNotice(
          <div className="flex items-center justify-between w-full">
            <span>正在生成第 {arcsTargetVolumes.join("、")} 卷的 Arcs...</span>
            <Button
              variant="ghost"
              size="sm"
              className="h-auto p-0 text-emerald-600 dark:text-emerald-300 font-bold underline decoration-2 underline-offset-4 ml-2 hover:bg-transparent"
              onClick={() => {
                props.onOpenChange(false);
                navigate("/tasks");
              }}
            >
              前往任务页查看进度
            </Button>
          </div>
        );
        const o = await waitForArcsGenerateBatch(props.novelId, bid);
        if (o === "failed") throw new Error("生成 Arcs 失败，请查看生成日志");
      }
      setNotice(null);
      await props.onReload();
      setArcsInstruction("");
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "生成 Arcs 失败");
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

  const stepLabels = ["大纲", "人物", "Arcs", "确认"];
  const totalSteps = 4;

  return (
    <>
    <Dialog open={props.open} onOpenChange={props.onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-xl font-bold text-foreground">
            修改向导（{step + 1}/{totalSteps} · {stepLabels[step]}）
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
                <div className="mt-2 flex min-h-[260px] w-full flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-primary/30 bg-primary/5 p-4 text-sm text-primary/70 text-center">
                  {props.status === "failed" ? (
                    <>
                      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-destructive/10">
                        <div className="h-4 w-4 rounded-full bg-destructive" />
                      </div>
                      <p className="font-bold text-base text-destructive">大纲生成任务似乎失败了</p>
                      <p className="text-xs opacity-60 max-w-xs mb-2">你可以尝试重新触发生成任务，或者稍后在生成日志中查看原因。</p>
                      <Button 
                        size="sm" 
                        variant="outline" 
                        className="font-bold border-destructive/30 text-destructive hover:bg-destructive/5"
                        onClick={() => void runRetryInitialFramework()}
                        disabled={busy}
                      >
                        {busy ? "重试中..." : "手动重试生成大纲"}
                      </Button>
                    </>
                  ) : (
                    <>
                      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary/10">
                        <div className="h-4 w-4 rounded-full border-2 border-primary border-t-transparent animate-spin" />
                      </div>
                      <p className="font-bold text-base animate-pulse">AI 正在努力构思全书大纲中...</p>
                      <p className="text-xs opacity-60 max-w-xs">这通常需要 15-30 秒，构思完成后此页面将自动刷新并显示内容。</p>
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
                <div className="mt-4 p-4 rounded-2xl bg-primary/5 border border-primary/20 flex items-center gap-3">
                  <input
                    type="checkbox"
                    id="sync-names"
                    className="size-4 rounded border-gray-300 text-primary focus:ring-primary"
                    checked={shouldSyncNames}
                    onChange={(e) => setShouldSyncNames(e.target.checked)}
                    disabled={busy}
                  />
                  <Label htmlFor="sync-names" className="text-sm font-semibold cursor-pointer">
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
                    {busy ? "确认中…" : props.baseFrameworkConfirmed ? "大纲已确认，下一步" : "大纲没问题，确认并下一步"}
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
              {characters.length ? (
                <div className="space-y-3">
                  {characters.map((c, idx) => (
                    <div
                      key={c.id}
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
                  {busy ? "更新中…" : hasCharactersChanged ? "确认人物并让 AI 更新大纲" : "人物无修改，下一步"}
                </Button>
              </div>
            </div>
          </div>
        ) : null}

        {/* Step 2: Arcs 修改（选卷 + 自然语言指令） */}
        {step === 2 ? (
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">
                分卷剧情大纲（Arcs）
              </Label>
              <p className="text-xs text-foreground/60 dark:text-muted-foreground">
                Arcs 按卷存储（与上方小说级设定分离）。选择要生成或覆盖的卷号，每卷约 50 章。
              </p>

              {/* 卷号选择 */}
              <div className="flex flex-wrap gap-2 mt-2">
                {Array.from({ length: totalVolumes }, (_, i) => i + 1).map((volNo) => {
                  const isExisting = existingVolumeNos.includes(volNo);
                  const isSelected = arcsTargetVolumes.includes(volNo);
                  return (
                    <button
                      key={volNo}
                      type="button"
                      className={`px-3 py-1.5 rounded-lg text-sm font-bold border transition-colors ${
                        isSelected
                          ? "bg-primary text-primary-foreground border-primary"
                          : isExisting
                            ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/30 hover:bg-emerald-500/20"
                            : "bg-background text-foreground/70 border-border/70 hover:bg-primary/10 hover:text-primary"
                      }`}
                      onClick={() => {
                        setArcsTargetVolumes((prev) =>
                          prev.includes(volNo)
                            ? prev.filter((v) => v !== volNo)
                            : [...prev, volNo].sort((a, b) => a - b)
                        );
                      }}
                      disabled={busy}
                    >
                      第{volNo}卷
                      {isExisting && " ✓"}
                    </button>
                  );
                })}
              </div>
              <p className="text-xs text-foreground/50 dark:text-muted-foreground mt-1">
                共 {totalVolumes} 卷 · 已选 {arcsTargetVolumes.length} 卷 · 
                带 ✓ 的卷已有 Arcs 数据，重新生成会覆盖
              </p>

              {/* 修改指令 */}
              <div className="space-y-1 mt-3">
                <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">
                  修改指令（可选）
                </Label>
                <Input
                  value={arcsInstruction}
                  onChange={(e) => setArcsInstruction(e.target.value)}
                  placeholder="例如：第二卷加入更多感情线；第三卷节奏加快..."
                  disabled={busy}
                />
              </div>

              {/* 已有卷级 Arcs 预览（来自各卷 outline，不是小说级大纲） */}
              <div className="mt-3 space-y-1">
                <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">
                  当前已生成的卷级 Arcs
                </Label>
                <textarea
                  value={
                    volumeArcsPreviewMd ||
                    (existingVolumeNos.length > 0
                      ? "（旧版数据：Arcs 可能仍在大纲 JSON 中，请重新生成各卷以迁移到卷存储）"
                      : "暂无。请先选择卷号并点击生成。")
                  }
                  readOnly
                  className="mt-1 min-h-[140px] w-full rounded-2xl border border-border/70 bg-background/70 p-4 font-mono text-sm text-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.35)]"
                />
              </div>

              <div className="flex flex-wrap gap-2 mt-3">
                <Button
                  type="button"
                  variant="outline"
                  className="font-bold"
                  disabled={busy}
                  onClick={() => setStep(1)}
                >
                  上一步
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  className="font-bold"
                  disabled={busy || arcsTargetVolumes.length === 0}
                  onClick={() => void runGenerateArcs()}
                >
                  {busy ? "生成中…" : `生成第 ${arcsTargetVolumes.join("、")} 卷 Arcs`}
                </Button>
                <Button
                  type="button"
                  className="font-bold"
                  disabled={busy}
                  onClick={() => setStep(3)}
                >
                  Arcs 没问题，下一步
                </Button>
              </div>
            </div>
          </div>
        ) : null}

        {/* Step 3: 最终确认 */}
        {step === 3 ? (
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">
                最终确认（可返回继续修改）
              </Label>
              <p className="text-xs text-foreground/60 dark:text-muted-foreground">
                以下为小说级「基础大纲」（世界观、人物、主线）。分卷 Arcs 不在此文本中，而在各卷的卷级概览里。
              </p>
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
                variant="outline"
                className="font-bold"
                disabled={busy}
                onClick={() => setStep(2)}
              >
                再改 Arcs
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

    <TaskStartedDialog open={taskStartedOpen} onOpenChange={(v) => {
      setTaskStartedOpen(v);
      if (!v) props.onOpenChange(false);
    }} />
    </>
  );
}

function TaskStartedDialog(props: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const navigate = useNavigate();
  return (
    <Dialog open={props.open} onOpenChange={props.onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="text-xl font-bold flex items-center gap-2">
            <Sparkles className="size-5 text-primary" />
            任务已在后台启动
          </DialogTitle>
          <DialogDescription className="text-foreground/80 pt-2 leading-relaxed">
            AI 正在为你生成内容。此过程可能需要几十秒，你可以留在本页等待，也可以前往「我的任务」模块查看详细进度。
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="gap-2 sm:gap-0">
          <Button
            variant="outline"
            className="font-bold"
            onClick={() => props.onOpenChange(false)}
          >
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
