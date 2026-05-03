/**
 * Plan editor dialog for editing chapter execution cards.
 */
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

type PlanEditorDraft = {
  chapterNo: number | null;
  title: string;
  goal: string;
  conflict: string;
  turn: string;
  plotSummary: string;
  stagePosition: string;
  pacing: string;
  mustHappen: string;
  callbacks: string;
  allowedProgress: string;
  mustNot: string;
  reserved: string;
  endingHook: string;
  styleGuardrails: string;
};

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  draft: PlanEditorDraft;
  onChange: (partial: Partial<PlanEditorDraft>) => void;
  saving: boolean;
  onSave: () => void;
};

function Field({ label, value, onChange, placeholder, minHeight = "104px" }: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  minHeight?: string;
}) {
  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="field-shell-textarea text-sm"
        style={{ minHeight }}
        placeholder={placeholder}
      />
    </div>
  );
}

export function PlanEditorDialog({ open, onOpenChange, draft, onChange, saving, onSave }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-3xl overflow-hidden text-foreground">
        <DialogHeader>
          <DialogTitle>
            编辑执行卡
            {draft.chapterNo != null ? ` · 第${draft.chapterNo}章` : ""}
          </DialogTitle>
          <DialogDescription>
            这里修改的是当前章计划的执行卡。保存后会覆盖本章计划内容，但仍兼容旧版计划结构和正文生成链路。
          </DialogDescription>
        </DialogHeader>
        <div className="soft-scroll max-h-[62vh] space-y-4 overflow-y-auto pr-1">
          <div className="space-y-2">
            <Label>章节标题</Label>
            <Input
              value={draft.title}
              onChange={(e) => onChange({ title: e.target.value })}
              placeholder="例如：暗潮初显"
            />
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="本章目标" value={draft.goal} onChange={(v) => onChange({ goal: v })} placeholder="这一章必须完成的核心目标" />
            <Field label="核心冲突" value={draft.conflict} onChange={(v) => onChange({ conflict: v })} placeholder="这一章最主要的对抗、阻碍或张力" />
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="关键转折" value={draft.turn} onChange={(v) => onChange({ turn: v })} placeholder="本章中段或后段发生的关键变化" />
            <Field label="章末钩子" value={draft.endingHook} onChange={(v) => onChange({ endingHook: v })} placeholder="下一章必须自然承接的钩子" />
          </div>
          <Field label="剧情梗概" value={draft.plotSummary} onChange={(v) => onChange({ plotSummary: v })} placeholder="用 5-12 句写清楚本章实际会发生什么" minHeight="140px" />
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="阶段位置" value={draft.stagePosition} onChange={(v) => onChange({ stagePosition: v })} placeholder="例如：第一弧 35%，本卷仍在蓄势" minHeight="96px" />
            <Field label="节奏说明" value={draft.pacing} onChange={(v) => onChange({ pacing: v })} placeholder="说明为什么这一章不应越级推进" minHeight="96px" />
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="必须发生" value={draft.mustHappen} onChange={(v) => onChange({ mustHappen: v })} placeholder={"每行一条\n例如：主角确认账册中的异常签名"} />
            <Field label="必须承接" value={draft.callbacks} onChange={(v) => onChange({ callbacks: v })} placeholder={"每行一条\n例如：承接上一章雨夜仓库的未解释异响"} />
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="允许推进" value={draft.allowedProgress} onChange={(v) => onChange({ allowedProgress: v })} placeholder={"每行一条\n例如：只允许确认身份可疑，不允许直接揭穿"} />
            <Field label="绝对禁止" value={draft.mustNot} onChange={(v) => onChange({ mustNot: v })} placeholder={"每行一条\n例如：不能让配角知道主角真实能力"} />
          </div>
          <Field label="延后解锁" value={draft.reserved} onChange={(v) => onChange({ reserved: v })} placeholder={"每行一条，格式：条目 | 最早章节 | 原因\n例如：玉佩真名 | 18 | 需要等祠堂线揭开"} />
          <Field label="风格护栏" value={draft.styleGuardrails} onChange={(v) => onChange({ styleGuardrails: v })} placeholder={"每行一条\n例如：保持短句节奏，避免长描写"} minHeight="96px" />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>取消</Button>
          <Button onClick={onSave} disabled={saving}>
            {saving ? "保存中…" : "保存执行卡"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
