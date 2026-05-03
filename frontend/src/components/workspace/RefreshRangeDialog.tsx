/**
 * Memory refresh range selection dialog.
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

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mode: "recent" | "full" | "custom";
  onModeChange: (mode: "recent" | "full" | "custom") => void;
  fromNo: number;
  toNo: number;
  onFromNoChange: (v: number) => void;
  onToNoChange: (v: number) => void;
  busy: boolean;
  onConfirm: (opts: { is_full?: boolean; from_chapter_no?: number; to_chapter_no?: number }) => void;
};

export function RefreshRangeDialog({
  open,
  onOpenChange,
  mode,
  onModeChange,
  fromNo,
  toNo,
  onFromNoChange,
  onToNoChange,
  busy,
  onConfirm,
}: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md overflow-hidden flex flex-col text-foreground">
        <DialogHeader>
          <DialogTitle>刷新记忆范围选择</DialogTitle>
          <DialogDescription>
            请选择用于汇总记忆的已审定章节范围。
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="flex flex-col gap-2">
            <Label className="text-sm font-semibold">选择模式</Label>
            <div className="grid grid-cols-3 gap-2">
              <Button
                variant={mode === "recent" ? "default" : "outline"}
                size="sm"
                onClick={() => onModeChange("recent")}
                className="text-xs"
              >
                最近 15 章
              </Button>
              <Button
                variant={mode === "full" ? "default" : "outline"}
                size="sm"
                onClick={() => onModeChange("full")}
                className="text-xs"
              >
                全量刷新
              </Button>
              <Button
                variant={mode === "custom" ? "default" : "outline"}
                size="sm"
                onClick={() => onModeChange("custom")}
                className="text-xs"
              >
                自定义范围
              </Button>
            </div>
          </div>

          {mode === "custom" && (
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label className="text-xs">起始章号</Label>
                <Input
                  type="number"
                  value={fromNo}
                  onChange={(e) => onFromNoChange(Number(e.target.value))}
                  className="h-9"
                />
              </div>
              <div className="space-y-2">
                <Label className="text-xs">结束章号</Label>
                <Input
                  type="number"
                  value={toNo}
                  onChange={(e) => onToNoChange(Number(e.target.value))}
                  className="h-9"
                />
              </div>
            </div>
          )}

          <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-3 space-y-2">
            <div className="flex items-center gap-2 text-amber-700 dark:text-amber-400">
              <div className="h-1.5 w-1.5 rounded-full bg-amber-500" />
              <p className="text-xs font-bold text-amber-600 dark:text-amber-400">温馨提示</p>
            </div>
            <ul className="list-disc list-inside text-[11px] text-amber-700/80 dark:text-amber-400/80 space-y-1">
              <li>汇总的章节越多，AI 处理速度越慢。</li>
              <li>刷新操作会消耗较多积分（按汇总字数计费）。</li>
              <li>建议仅在产生重大剧情变更或由于逻辑偏移需要"纠偏"时进行全量刷新。</li>
            </ul>
          </div>
        </div>
        <DialogFooter className="mt-4">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button
            onClick={() => {
              const opts: { is_full?: boolean; from_chapter_no?: number; to_chapter_no?: number } = {};
              if (mode === "full") opts.is_full = true;
              else if (mode === "custom") {
                opts.from_chapter_no = fromNo;
                opts.to_chapter_no = toNo;
              }
              onConfirm(opts);
            }}
            disabled={busy}
          >
            开始刷新
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
