/**
 * Chapter content editor: title, body, revision, approval.
 * All stats/controls removed — toolbar handles those.
 */
import { Button } from "@/components/ui/button";
import { NovelIntelPanel } from "@/components/NovelIntelPanel";
import {
  type ChapterJudgeLatest,
  type MemoryUpdateRun,
  type NovelRetrievalLogItem,
  type NovelWorkflowLatest,
} from "@/services/novelApi";

type ChapterItem = {
  id: string;
  chapter_no: number;
  title: string;
  content: string;
  pending_content: string;
  status: string;
  source: string;
};

type Props = {
  selectedChapter: ChapterItem | null;
  selectedChapterWordCount: number;
  busy: boolean;
  editTitle: string;
  onEditTitleChange: (v: string) => void;
  editContent: string;
  onEditContentChange: (v: string) => void;
  fbDraft: Record<string, string>;
  onFbDraftChange: (updater: (d: Record<string, string>) => Record<string, string>) => void;
  revisePrompt: Record<string, string>;
  onRevisePromptChange: (updater: (d: Record<string, string>) => Record<string, string>) => void;
  latestWorkflow: NovelWorkflowLatest | null;
  chapterJudge: ChapterJudgeLatest | null;
  retrievalLogs: NovelRetrievalLogItem[];
  memoryUpdateRuns: MemoryUpdateRun[];
  coreEvaluation: {
    rubric?: { phases?: { id: string; name: string; metrics: string[] }[]; notes?: string };
    observed?: Record<string, unknown>;
  } | null;
  intelWorkflowLoading: boolean;
  intelJudgeLoading: boolean;
  intelRetrievalLoading: boolean;
  onOpenChapterChat: () => void;
  onSaveChapter: () => void;
  onFormatChapter: () => void;
  onDeleteChapter: () => void;
  onApplyRevision: () => void;
  onDiscardRevision: () => void;
  onConsistencyFix: () => void;
  onPolishChapter: () => void;
  onRecordFeedback: () => void;
  onApproveChapter: () => void;
  onRetryMemory: () => void;
  onReviseChapter: (chapterId: string, prompt: string) => void;
};

export function ChapterContentSection({
  selectedChapter,
  selectedChapterWordCount,
  busy,
  editTitle,
  onEditTitleChange,
  editContent,
  onEditContentChange,
  fbDraft,
  onFbDraftChange,
  revisePrompt,
  onRevisePromptChange,
  latestWorkflow,
  chapterJudge,
  retrievalLogs,
  memoryUpdateRuns,
  coreEvaluation,
  intelWorkflowLoading,
  intelJudgeLoading,
  intelRetrievalLoading,
  onOpenChapterChat,
  onSaveChapter,
  onFormatChapter,
  onDeleteChapter,
  onApplyRevision,
  onDiscardRevision,
  onConsistencyFix,
  onPolishChapter,
  onRecordFeedback,
  onApproveChapter,
  onRetryMemory,
  onReviseChapter,
}: Props) {
  if (!selectedChapter) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <p className="text-sm text-foreground/50 italic font-medium">请在左侧栏选择一章。</p>
      </div>
    );
  }

  return (
    <div className="space-y-4 p-4 md:p-5">
      {/* chapter header — compact inline */}
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-bold text-foreground">第{selectedChapter.chapter_no}章</span>
        <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-bold text-foreground/60">
          {selectedChapter.status}
        </span>
        <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-bold text-foreground/60">
          {selectedChapter.source}
        </span>
        <span className="ml-auto text-xs text-foreground/50 font-medium">
          {selectedChapterWordCount} 字
        </span>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="h-7 text-xs font-bold text-foreground/60"
          onClick={onOpenChapterChat}
        >
          章节助手
        </Button>
      </div>

      {/* intel panel */}
      <NovelIntelPanel
        selectedChapter={{
          chapter_no: selectedChapter.chapter_no,
          title: selectedChapter.title,
        }}
        workflow={latestWorkflow}
        judge={chapterJudge}
        retrievalLogs={retrievalLogs}
        memoryRuns={memoryUpdateRuns}
        evaluation={coreEvaluation}
        workflowLoading={intelWorkflowLoading}
        judgeLoading={intelJudgeLoading}
        retrievalLoading={intelRetrievalLoading}
      />

      {/* pending revision banner */}
      {selectedChapter.pending_content ? (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3">
          <p className="mb-1 text-xs font-bold text-amber-800 dark:text-amber-200">
            待确认修订稿
          </p>
          <pre className="mb-2 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg border border-amber-500/20 bg-background/50 p-2 text-xs text-foreground font-medium leading-relaxed">
            {selectedChapter.pending_content}
          </pre>
          <div className="flex flex-wrap gap-2">
            <Button type="button" size="sm" className="font-bold" disabled={busy} onClick={onApplyRevision}>
              确认覆盖
            </Button>
            <Button type="button" size="sm" variant="outline" className="font-bold" disabled={busy} onClick={onDiscardRevision}>
              放弃
            </Button>
          </div>
        </div>
      ) : null}

      {/* title + body editor */}
      <div className="space-y-3">
        <input
          value={editTitle}
          onChange={(e) => onEditTitleChange(e.target.value)}
          className="field-shell w-full text-foreground font-bold"
          placeholder="章节标题"
        />
        <textarea
          value={editContent}
          onChange={(e) => onEditContentChange(e.target.value)}
          className="field-shell-textarea min-h-[min(55dvh,520px)] text-foreground text-sm font-medium leading-relaxed"
          placeholder="正文内容…"
        />
        <div className="flex flex-wrap gap-2">
          <Button type="button" size="sm" variant="secondary" className="font-bold" disabled={busy || !editContent.trim()} onClick={onFormatChapter}>
            格式化
          </Button>
          <Button type="button" size="sm" className="font-bold" disabled={busy || !editContent.trim()} onClick={onSaveChapter}>
            保存
          </Button>
          <Button type="button" size="sm" variant="outline" className="text-destructive font-bold hover:border-destructive/40 hover:bg-destructive/10" disabled={busy} onClick={onDeleteChapter}>
            删除
          </Button>
        </div>
      </div>

      {/* revision + approval controls */}
      <div className="grid gap-3 xl:grid-cols-[1.1fr_0.9fr]">
        <div className="rounded-lg border border-border bg-muted/30 space-y-3 p-3">
          <p className="text-xs font-bold text-foreground/70">修订与审定</p>
          <div className="space-y-2">
            <textarea
              value={fbDraft[selectedChapter.id] ?? ""}
              onChange={(e) => onFbDraftChange((d) => ({ ...d, [selectedChapter.id]: e.target.value }))}
              className="field-shell-textarea min-h-[80px] text-sm text-foreground font-medium"
              placeholder="改进意见（可多条）…"
            />
            <div className="flex flex-wrap gap-1.5">
              <Button type="button" size="sm" variant="secondary" className="text-xs font-bold" disabled={busy || !selectedChapter.content?.trim()} onClick={onConsistencyFix}>
                一致性修订
              </Button>
              <Button type="button" size="sm" variant="secondary" className="text-xs font-bold" disabled={busy || !(selectedChapter.content || selectedChapter.pending_content)?.trim()} onClick={onPolishChapter}>
                去AI味
              </Button>
              <Button type="button" size="sm" variant="secondary" className="text-xs font-bold" disabled={busy || !fbDraft[selectedChapter.id]?.trim()} onClick={onRecordFeedback}>
                记录反馈
              </Button>
              <Button type="button" size="sm" className="text-xs font-bold" disabled={busy} onClick={onApproveChapter}>
                审定
              </Button>
              <Button type="button" size="sm" variant="outline" className="text-xs font-semibold" disabled={busy || !selectedChapter.content?.trim()} onClick={onRetryMemory}>
                重试记忆
              </Button>
            </div>
          </div>
        </div>

        <div className="rounded-lg border border-border bg-muted/30 space-y-3 p-3">
          <p className="text-xs font-bold text-foreground/70">按指令改稿</p>
          <textarea
            value={revisePrompt[selectedChapter.id] ?? ""}
            onChange={(e) => onRevisePromptChange((d) => ({ ...d, [selectedChapter.id]: e.target.value }))}
            className="field-shell-textarea min-h-[120px] text-sm text-foreground font-medium"
            placeholder="例如：加强对话张力、压缩环境描写…"
          />
          <Button
            type="button"
            size="sm"
            variant="secondary"
            className="text-xs font-bold"
            disabled={busy || !(revisePrompt[selectedChapter.id]?.trim())}
            onClick={() => onReviseChapter(selectedChapter.id, revisePrompt[selectedChapter.id] ?? "")}
          >
            生成修订稿
          </Button>
        </div>
      </div>
    </div>
  );
}
