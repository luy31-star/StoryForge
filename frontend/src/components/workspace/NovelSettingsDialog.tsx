/**
 * Novel settings dialog component.
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

type NovelSettingsDraft = {
  target_chapters: number;
  daily_auto_chapters: number;
  daily_auto_time: string;
  chapter_target_words: number;
  auto_consistency_check: boolean;
  auto_plan_guard_check: boolean;
  auto_plan_guard_fix: boolean;
  auto_style_polish: boolean;
  style: string;
  writing_style_id: string;
  framework_model: string;
  plan_model: string;
  chapter_model: string;
};

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  draft: NovelSettingsDraft;
  onDraftChange: (partial: Partial<NovelSettingsDraft>) => void;
  busy: boolean;
  onSave: () => void;
  writingStyleSlot?: React.ReactNode;
};

export function NovelSettingsDialog({
  open,
  onOpenChange,
  draft,
  onDraftChange,
  busy,
  onSave,
  writingStyleSlot,
}: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-md overflow-hidden">
        <DialogHeader>
          <DialogTitle className="text-xl font-bold">小说设置</DialogTitle>
          <DialogDescription className="text-foreground/80 dark:text-muted-foreground font-medium">
            配置当前小说的总章节数和每日自动撰写计划。
          </DialogDescription>
        </DialogHeader>
        <div className="max-h-[calc(85vh-9rem)] space-y-4 overflow-y-auto py-4 pr-2">
          <div className="space-y-2">
            <Label htmlFor="target_chapters" className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">目标总章节数</Label>
            <Input
              id="target_chapters"
              type="number"
              min={1}
              max={20000}
              value={draft.target_chapters}
              onChange={(e) => onDraftChange({ target_chapters: Number(e.target.value) })}
              className="field-shell text-foreground font-bold"
            />
            <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium italic">该小说的预计总章节数。</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="daily_auto_chapters" className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">每日自动撰写章数</Label>
            <Input
              id="daily_auto_chapters"
              type="number"
              min={0}
              max={50}
              value={draft.daily_auto_chapters}
              onChange={(e) => onDraftChange({ daily_auto_chapters: Number(e.target.value) })}
              className="field-shell text-foreground font-bold"
            />
            <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium italic">设定为 0 表示不开启每日自动撰写。如果不为 0，系统将在指定时间自动在后台为你续写小说。</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="daily_auto_time" className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">每日自动撰写时间（北京时间）</Label>
            <Input
              id="daily_auto_time"
              type="time"
              value={draft.daily_auto_time}
              onChange={(e) => onDraftChange({ daily_auto_time: e.target.value })}
              className="field-shell text-foreground font-bold"
            />
            <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium italic">由后台系统自动执行。</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="chapter_target_words" className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">每章期望字数（汉字）</Label>
            <Input
              id="chapter_target_words"
              type="number"
              min={300}
              max={10000}
              step={1}
              value={draft.chapter_target_words}
              onChange={(e) => onDraftChange({ chapter_target_words: Number(e.target.value) })}
              className="field-shell text-foreground font-bold"
            />
            <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium italic">提示词会强力要求正文紧贴目标字数，只允许轻微浮动。当前默认规则为上下约 5%，至少 30 字、最多 150 字。</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="auto_consistency_check" className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">
              生成前一致性修订
            </Label>
            <label
              htmlFor="auto_consistency_check"
              className="flex cursor-pointer items-start gap-3 rounded-xl border border-border bg-muted px-3 py-3"
            >
              <input
                id="auto_consistency_check"
                type="checkbox"
                checked={draft.auto_consistency_check}
                onChange={(e) => onDraftChange({ auto_consistency_check: e.target.checked })}
                className="mt-0.5 h-4 w-4"
              />
              <div className="space-y-1">
                <p className="text-sm font-semibold text-foreground">生成正文后，追加一次一致性修订</p>
                <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium italic">
                  默认关闭。开启后会多一次 LLM 调用，速度更慢，但会先做一轮通顺性与设定衔接修订。
                </p>
              </div>
            </label>
          </div>
          <div className="space-y-2">
            <Label htmlFor="auto_plan_guard_check" className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">
              执行卡硬校验
            </Label>
            <label
              htmlFor="auto_plan_guard_check"
              className="flex cursor-pointer items-start gap-3 rounded-xl border border-border bg-muted px-3 py-3"
            >
              <input
                id="auto_plan_guard_check"
                type="checkbox"
                checked={draft.auto_plan_guard_check}
                onChange={(e) =>
                  onDraftChange({
                    auto_plan_guard_check: e.target.checked,
                    auto_plan_guard_fix: e.target.checked ? draft.auto_plan_guard_fix : false,
                  })
                }
                className="mt-0.5 h-4 w-4"
              />
              <div className="space-y-1">
                <p className="text-sm font-semibold text-foreground">生成正文初稿后，按执行卡做一次硬校验</p>
                <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium italic">
                  默认关闭。开启后会额外消耗一次 LLM 调用；若同时未开启纠偏，校验失败会直接终止当前批次。
                </p>
              </div>
            </label>
          </div>
          <div className="space-y-2">
            <Label htmlFor="auto_plan_guard_fix" className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">
              执行卡自动纠偏
            </Label>
            <label
              htmlFor="auto_plan_guard_fix"
              className="flex cursor-pointer items-start gap-3 rounded-xl border border-border bg-muted px-3 py-3"
            >
              <input
                id="auto_plan_guard_fix"
                type="checkbox"
                checked={draft.auto_plan_guard_fix}
                onChange={(e) => onDraftChange({ auto_plan_guard_fix: e.target.checked })}
                className="mt-0.5 h-4 w-4"
              />
              <div className="space-y-1">
                <p className="text-sm font-semibold text-foreground">校验不通过时，自动让 LLM 纠偏执行卡</p>
                <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium italic">
                  需先开启「执行卡硬校验」。纠偏会额外消耗 LLM 调用，但能避免因执行卡细节不合理而中断生成。
                </p>
              </div>
            </label>
          </div>
          <div className="space-y-2">
            <Label htmlFor="auto_style_polish" className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">
              文风润色
            </Label>
            <label
              htmlFor="auto_style_polish"
              className="flex cursor-pointer items-start gap-3 rounded-xl border border-border bg-muted px-3 py-3"
            >
              <input
                id="auto_style_polish"
                type="checkbox"
                checked={draft.auto_style_polish}
                onChange={(e) => onDraftChange({ auto_style_polish: e.target.checked })}
                className="mt-0.5 h-4 w-4"
              />
              <div className="space-y-1">
                <p className="text-sm font-semibold text-foreground">生成正文后，追加一次文风润色</p>
                <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium italic">
                  开启后会多一次 LLM 调用。系统会根据所选写作风格对正文做最后一轮风格打磨。
                </p>
              </div>
            </label>
          </div>
          <div className="space-y-2">
            <Label htmlFor="novel_style" className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">文风关键词</Label>
            <Input
              id="novel_style"
              value={draft.style}
              onChange={(e) => onDraftChange({ style: e.target.value })}
              className="field-shell text-foreground font-bold"
              placeholder="例如：硬核推理、轻快幽默..."
            />
            <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium italic">简单描述文风关键词，会注入所有生成环节。</p>
          </div>
          <div className="space-y-2">
            <Label className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">写作风格 (深度定制)</Label>
            {writingStyleSlot}
            <p className="text-[11px] text-foreground/60 dark:text-muted-foreground font-medium italic">
              切换深度定制的文风，系统将按新文风进行后续章节创作。
            </p>
          </div>
          <div className="grid grid-cols-3 gap-4">
            <div className="space-y-2">
              <Label htmlFor="novel_fw_model" className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">大纲模型</Label>
              <Input
                id="novel_fw_model"
                value={draft.framework_model}
                onChange={(e) => onDraftChange({ framework_model: e.target.value })}
                className="field-shell text-foreground font-bold"
                placeholder="留空用默认"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="novel_plan_model" className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">执行卡模型</Label>
              <Input
                id="novel_plan_model"
                value={draft.plan_model}
                onChange={(e) => onDraftChange({ plan_model: e.target.value })}
                className="field-shell text-foreground font-bold"
                placeholder="留空用默认"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="novel_ch_model" className="text-sm font-semibold text-foreground/90 dark:text-foreground/70">正文模型</Label>
              <Input
                id="novel_ch_model"
                value={draft.chapter_model}
                onChange={(e) => onDraftChange({ chapter_model: e.target.value })}
                className="field-shell text-foreground font-bold"
                placeholder="留空用默认"
              />
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" className="font-semibold" onClick={() => onOpenChange(false)} disabled={busy}>
            取消
          </Button>
          <Button className="font-bold" onClick={onSave} disabled={busy}>
            {busy ? "保存中..." : "保存设置"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
