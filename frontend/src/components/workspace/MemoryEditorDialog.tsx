/**
 * Memory editor dialog for creating/editing/deleting structured memory entities.
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
import { Textarea } from "@/components/ui/textarea";

type MemoryEditorState = {
  kind: "character" | "relation" | "skill" | "item";
  mode: "create" | "edit" | "delete";
  title: string;
  subtitle: string;
  confirmLabel: string;
  name: string;
  role: string;
  status: string;
  traits: string;
  from: string;
  to: string;
  relation: string;
  label: string;
  owner: string;
  description: string;
  influence: string;
  isActive: boolean;
};

type Props = {
  editor: MemoryEditorState | null;
  onChange: (partial: Partial<MemoryEditorState>) => void;
  busy: boolean;
  onClose: () => void;
  onSubmit: () => void;
  onOpenChange?: (open: boolean) => void;
};

export function MemoryEditorDialog({ editor, onChange, busy, onClose, onSubmit, onOpenChange }: Props) {
  return (
    <Dialog open={Boolean(editor)} onOpenChange={onOpenChange ?? ((open) => !open && onClose())}>
      <DialogContent className="max-h-[85vh] max-w-xl overflow-y-auto text-foreground">
        <DialogHeader>
          <DialogTitle>{editor?.title || "结构化记忆编辑"}</DialogTitle>
          <DialogDescription>{editor?.subtitle || "编辑结构化记忆。"}</DialogDescription>
        </DialogHeader>
        {editor ? (
          editor.mode === "delete" ? (
            <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-4 text-sm leading-6 text-foreground/75">
              {editor.kind === "character"
                ? `将人物「${editor.name}」标记为退场。`
                : editor.kind === "relation"
                  ? `将关系「${editor.from} → ${editor.to}」标记为失效。`
                  : editor.kind === "skill"
                    ? `删除技能「${editor.name}」。`
                    : `删除物品「${editor.label}」。`}
            </div>
          ) : (
            <div className="space-y-4 py-2">
              {editor.kind === "character" ? (
                <>
                  <div className="space-y-2">
                    <Label>人物主名</Label>
                    <Input value={editor.name} onChange={(e) => onChange({ name: e.target.value })} />
                  </div>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <div className="space-y-2">
                      <Label>人物角色</Label>
                      <Input value={editor.role} onChange={(e) => onChange({ role: e.target.value })} />
                    </div>
                    <div className="space-y-2">
                      <Label>人物状态</Label>
                      <Input value={editor.status} onChange={(e) => onChange({ status: e.target.value })} />
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label>人物特征</Label>
                    <Textarea value={editor.traits} onChange={(e) => onChange({ traits: e.target.value })} placeholder="可用逗号或换行分隔" />
                  </div>
                </>
              ) : null}
              {editor.kind === "relation" ? (
                <>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <div className="space-y-2">
                      <Label>起点人物</Label>
                      <Input value={editor.from} onChange={(e) => onChange({ from: e.target.value })} />
                    </div>
                    <div className="space-y-2">
                      <Label>终点人物</Label>
                      <Input value={editor.to} onChange={(e) => onChange({ to: e.target.value })} />
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label>关系描述</Label>
                    <Textarea value={editor.relation} onChange={(e) => onChange({ relation: e.target.value })} />
                  </div>
                </>
              ) : null}
              {editor.kind === "skill" ? (
                <>
                  <div className="space-y-2">
                    <Label>技能名称</Label>
                    <Input value={editor.name} onChange={(e) => onChange({ name: e.target.value })} />
                  </div>
                  <div className="space-y-2">
                    <Label>技能描述</Label>
                    <Textarea value={editor.description} onChange={(e) => onChange({ description: e.target.value })} />
                  </div>
                </>
              ) : null}
              {editor.kind === "item" ? (
                <>
                  <div className="space-y-2">
                    <Label>物品名称</Label>
                    <Input value={editor.label} onChange={(e) => onChange({ label: e.target.value })} />
                  </div>
                  <div className="space-y-2">
                    <Label>持有人</Label>
                    <Input value={editor.owner} onChange={(e) => onChange({ owner: e.target.value })} />
                  </div>
                  <div className="space-y-2">
                    <Label>物品描述</Label>
                    <Textarea value={editor.description} onChange={(e) => onChange({ description: e.target.value })} />
                  </div>
                </>
              ) : null}
              {editor.kind !== "relation" ? (
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label>影响力</Label>
                    <Input type="number" min={0} max={100} value={editor.influence} onChange={(e) => onChange({ influence: e.target.value })} />
                  </div>
                  <div className="space-y-2">
                    <Label>当前状态</Label>
                    <div className="flex gap-2">
                      <Button type="button" size="sm" variant={editor.isActive ? "default" : "outline"} onClick={() => onChange({ isActive: true })}>活跃</Button>
                      <Button type="button" size="sm" variant={!editor.isActive ? "default" : "outline"} onClick={() => onChange({ isActive: false })}>非活跃</Button>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="space-y-2">
                  <Label>关系状态</Label>
                  <div className="flex gap-2">
                    <Button type="button" size="sm" variant={editor.isActive ? "default" : "outline"} onClick={() => onChange({ isActive: true })}>生效</Button>
                    <Button type="button" size="sm" variant={!editor.isActive ? "default" : "outline"} onClick={() => onChange({ isActive: false })}>失效</Button>
                  </div>
                </div>
              )}
            </div>
          )
        ) : null}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose} disabled={busy}>
            取消
          </Button>
          <Button type="button" onClick={onSubmit} disabled={busy}>
            {busy ? "处理中..." : editor?.confirmLabel || "确认"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
