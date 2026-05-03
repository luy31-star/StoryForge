import { AlertTriangle, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

type LlmActionConfirmDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string | React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  details?: string[];
  busy?: boolean;
  extraContent?: React.ReactNode;
  onConfirm: () => void | Promise<void>;
};

export function LlmActionConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = "确认调用大模型",
  cancelLabel = "暂不执行",
  details = [],
  busy = false,
  extraContent,
  onConfirm,
}: LlmActionConfirmDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <div className="mb-2 flex items-center gap-2 text-amber-500">
            <div className="flex h-9 w-9 items-center justify-center rounded-2xl border border-amber-500/30 bg-amber-500/10">
              <Sparkles className="h-4 w-4" />
            </div>
            <span className="text-xs font-medium uppercase tracking-[0.18em]">
              LLM 二次确认
            </span>
          </div>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription className="leading-6">
            {description}
          </DialogDescription>
        </DialogHeader>

        {details.length > 0 ? (
          <div className="rounded-lg border border-border bg-muted p-4">
            <div className="mb-2 flex items-center gap-2 text-xs font-medium text-foreground">
              <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />
              执行前提示
            </div>
            <div className="space-y-1.5 text-sm text-muted-foreground">
              {details.map((item, idx) => (
                <p key={`${item}-${idx}`}>- {item}</p>
              ))}
            </div>
          </div>
        ) : null}

        {extraContent}

        <DialogFooter className="gap-2 sm:gap-2">
          <Button
            type="button"
            variant="outline"
            disabled={busy}
            onClick={() => onOpenChange(false)}
          >
            {cancelLabel}
          </Button>
          <Button type="button" disabled={busy} onClick={() => void onConfirm()}>
            {busy ? "处理中…" : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
