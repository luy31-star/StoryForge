/**
 * Chapter context chat dialog with streaming, thinking, abort, and quick prompts.
 */
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

type ChatTurn = { role: "user" | "assistant"; content: string };

type QuickPrompt = {
  readonly label: string;
  readonly prompt: string;
};

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  turns: ChatTurn[];
  input: string;
  onInputChange: (v: string) => void;
  busy: boolean;
  err: string | null;
  thinking: string;
  thinkExpanded: boolean;
  onThinkExpandedChange: (v: boolean) => void;
  onSend: () => void;
  onAbort: () => void;
  onClear: () => void;
  canAbort: boolean;
  quickPrompts: readonly QuickPrompt[];
  onQuickPrompt: (prompt: string) => void;
};

export function ChapterChatDialog({
  open,
  onOpenChange,
  turns,
  input,
  onInputChange,
  busy,
  err,
  thinking,
  thinkExpanded,
  onThinkExpandedChange,
  onSend,
  onAbort,
  onClear,
  canAbort,
  quickPrompts,
  onQuickPrompt,
}: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[88vh] max-w-3xl overflow-hidden text-foreground">
        <DialogHeader>
          <DialogTitle>章节助手对话</DialogTitle>
          <DialogDescription>
            自动基于已审定章节、框架与记忆回答问题，可用于续写决策和一致性检查。
          </DialogDescription>
        </DialogHeader>
        <div className="soft-scroll flex max-h-[52vh] flex-col gap-3 overflow-y-auto rounded-lg border border-border bg-muted p-3 text-sm">
          {turns.length === 0 ? (
            <p className="text-muted-foreground">
              例如："第 7 章应该先回收哪个伏笔？和主线冲突怎么排优先级？"
            </p>
          ) : null}
          {turns.map((t, i) => (
            <div
              key={`${i}-${t.role}`}
              className={
                t.role === "user"
                  ? "ml-8 rounded-lg border border-primary/20 bg-primary/10 px-3.5 py-3 shadow-sm"
                  : "mr-4 rounded-lg border border-border bg-background px-3.5 py-3 shadow-sm"
              }
            >
              <span className="text-xs font-medium text-muted-foreground">
                {t.role === "user" ? "你" : "章节助手"}
              </span>
              <pre className="mt-1 whitespace-pre-wrap font-sans text-xs">{t.content}</pre>
            </div>
          ))}
        </div>
        <div className="space-y-2">
          <p className="text-xs text-muted-foreground">快捷提问</p>
          <div className="flex flex-wrap gap-2">
            {quickPrompts.map((p) => (
              <Button
                key={p.label}
                type="button"
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={() => onQuickPrompt(p.prompt)}
                className="text-xs"
                title={p.prompt}
              >
                {p.label}
              </Button>
            ))}
          </div>
          <div className="soft-scroll max-h-20 overflow-auto rounded-2xl border border-border bg-muted px-3 py-2 text-[11px] text-muted-foreground">
            {quickPrompts.map((p) => (
              <p key={`desc-${p.label}`} className="truncate">
                <span className="font-medium">{p.label}：</span>
                {p.prompt}
              </p>
            ))}
          </div>
        </div>
        {err ? <p className="text-xs text-destructive">{err}</p> : null}
        {thinking ? (
          <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 text-xs">
            <div className="flex items-center justify-between gap-2">
              <p className="font-medium text-amber-700 dark:text-amber-300">
                Think
              </p>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="h-7 px-2 text-[11px]"
                onClick={() => onThinkExpandedChange(!thinkExpanded)}
              >
                {thinkExpanded ? "折叠" : "展开"}
              </Button>
            </div>
            <pre
              className={`mt-1 overflow-auto whitespace-pre-wrap font-sans text-[11px] text-amber-800 dark:text-amber-200 ${
                thinkExpanded ? "max-h-72" : "max-h-24"
              }`}
            >
              {thinking}
            </pre>
          </div>
        ) : null}
        <textarea
          value={input}
          onChange={(e) => onInputChange(e.target.value)}
          placeholder="输入你的问题…（Enter 发送，Shift+Enter 换行）"
          className="field-shell-textarea min-h-[104px]"
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              onSend();
            }
          }}
          disabled={busy}
        />
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            size="sm"
            disabled={busy || !input.trim()}
            onClick={onSend}
          >
            {busy ? "思考中…" : "发送"}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            disabled={!busy || !canAbort}
            onClick={onAbort}
          >
            取消生成
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={busy || turns.length === 0}
            onClick={onClear}
          >
            清空会话
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
