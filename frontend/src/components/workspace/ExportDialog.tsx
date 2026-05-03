/**
 * Export chapters dialog with copy-to-clipboard.
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
  startNo: number;
  endNo: number;
  content: string;
  busy: boolean;
  onStartNoChange: (v: number) => void;
  onEndNoChange: (v: number) => void;
  onExport: () => void;
};

export function ExportDialog({
  open,
  onOpenChange,
  startNo,
  endNo,
  content,
  busy,
  onStartNoChange,
  onEndNoChange,
  onExport,
}: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-4xl overflow-hidden flex flex-col text-foreground">
        <DialogHeader>
          <DialogTitle>全文本导出</DialogTitle>
          <DialogDescription>
            选择章节范围，一键拼接所有已审定或草稿正文，方便发布或备份。
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label>起始章号</Label>
            <Input
              type="number"
              value={startNo}
              onChange={(e) => onStartNoChange(Number(e.target.value))}
            />
          </div>
          <div className="space-y-2">
            <Label>截止章号</Label>
            <Input
              type="number"
              value={endNo}
              onChange={(e) => onEndNoChange(Number(e.target.value))}
            />
          </div>
        </div>
        <div className="flex-1 overflow-hidden flex flex-col mt-4 gap-3">
          <div className="flex items-center justify-between">
            <Label>导出内容预览</Label>
            {content && (
              <Button
                variant="outline"
                size="sm"
                className="h-7 text-xs"
                onClick={() => {
                  void navigator.clipboard.writeText(content);
                  alert("已复制到剪贴板");
                }}
              >
                复制全文本
              </Button>
            )}
          </div>
          <textarea
            value={content}
            readOnly
            placeholder={'点击"开始导出"后在此显示内容...'}

            className="field-shell-textarea flex-1 font-sans text-sm leading-relaxed"
          />
        </div>
        <DialogFooter className="mt-4">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            关闭
          </Button>
          <Button onClick={onExport} disabled={busy}>
            {busy ? "正在导出..." : "开始导出"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
