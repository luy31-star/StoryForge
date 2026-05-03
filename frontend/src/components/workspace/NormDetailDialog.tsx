/**
 * Dialog for viewing structured memory detail (raw JSON/text).
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

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  body: string;
};

export function NormDetailDialog({ open, onOpenChange, title, body }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto text-foreground">
        <DialogHeader>
          <DialogTitle className="text-left text-base leading-snug">
            {title}
          </DialogTitle>
          <DialogDescription className="sr-only">
            结构化记忆条目完整内容
          </DialogDescription>
        </DialogHeader>
        <pre className="soft-scroll max-h-[min(60vh,520px)] overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border bg-muted p-3 text-[11px] leading-relaxed text-muted-foreground">
          {body}
        </pre>
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
          >
            关闭
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
