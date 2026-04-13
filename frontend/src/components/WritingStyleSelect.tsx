import { useState, useEffect } from "react";
import { Plus, Check, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  listWritingStyles,
  WritingStyle,
} from "@/services/writingStyleApi";
import { cn } from "@/lib/utils";

interface WritingStyleSelectProps {
  value?: string;
  onChange: (id: string) => void;
  className?: string;
}

export function WritingStyleSelect({ value, onChange, className }: WritingStyleSelectProps) {
  const [styles, setStyles] = useState<WritingStyle[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (open) {
      loadStyles();
    }
  }, [open]);

  async function loadStyles() {
    setLoading(true);
    try {
      const data = await listWritingStyles();
      setStyles(data);
    } catch (e) {
      console.error("Failed to load styles", e);
    } finally {
      setLoading(false);
    }
  }

  const selectedStyle = styles.find((s) => s.id === value);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          variant="outline"
          className={cn(
            "flex h-11 w-full items-center justify-between border-border bg-background px-3 text-left font-normal hover:bg-muted/50",
            className
          )}
        >
          {selectedStyle ? (
            <span className="flex items-center gap-2">
              <span className="font-semibold text-primary">{selectedStyle.name}</span>
              {selectedStyle.reference_author && (
                <span className="text-xs text-muted-foreground">({selectedStyle.reference_author})</span>
              )}
            </span>
          ) : (
            <span className="text-muted-foreground">选择写作风格...</span>
          )}
          <Plus className="h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>选择文风</DialogTitle>
        </DialogHeader>
        <div className="mt-4 space-y-2">
          {loading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : styles.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-8 text-center">
              <p className="text-sm text-muted-foreground">还没有创建任何文风</p>
              <Button
                variant="ghost"
                className="mt-2 text-primary"
                onClick={() => window.open("/writing-styles/new", "_blank")}
              >
                前往创建
              </Button>
            </div>
          ) : (
            <div className="grid gap-2 overflow-y-auto max-h-[60vh] pr-1">
              {styles.map((s) => (
                <button
                  key={s.id}
                  onClick={() => {
                    onChange(s.id);
                    setOpen(false);
                  }}
                  className={cn(
                    "flex flex-col items-start gap-1 rounded-lg border p-3 text-left transition-all hover:bg-muted/50",
                    value === s.id ? "border-primary bg-primary/5" : "border-border"
                  )}
                >
                  <div className="flex w-full items-center justify-between">
                    <span className="font-bold">{s.name}</span>
                    {value === s.id && <Check className="h-4 w-4 text-primary" />}
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {s.lexicon.tags.slice(0, 3).map((t) => (
                      <span key={t} className="text-[10px] bg-muted px-1.5 py-0.5 rounded text-muted-foreground">
                        {t}
                      </span>
                    ))}
                    {s.reference_author && (
                      <span className="text-[10px] bg-primary/10 px-1.5 py-0.5 rounded text-primary font-medium">
                        参考: {s.reference_author}
                      </span>
                    )}
                  </div>
                  {s.tone.description && (
                    <p className="line-clamp-2 mt-1 text-[11px] text-muted-foreground leading-normal">
                      {s.tone.description}
                    </p>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="mt-4 border-t pt-4">
          <Button
            variant="outline"
            className="w-full gap-2"
            onClick={() => window.open("/writing-styles/new", "_blank")}
          >
            <Plus className="h-4 w-4" />
            创建新文风
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
