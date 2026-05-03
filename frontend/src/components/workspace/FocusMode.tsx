/**
 * Fullscreen focus mode for streaming chapter generation.
 * Two-step flow: generate chapter plan (执行卡) → generate text.
 * Uses generateVolumeChapterPlanStream + generateChapterStream SSE.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  FilePlus2,
  Save,
  Square,
  Wand2,
  ClipboardCheck,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  generateChapterStream,
  generateVolumeChapterPlanStream,
  patchChapterPlan,
  createChapter,
  type NovelVolumeListItem,
  type ChapterPlanV2Beats,
} from "@/services/novelApi";

type ChapterItem = {
  id: string;
  chapter_no: number;
  title: string;
  content: string;
  status: string;
};

type Props = {
  open: boolean;
  onExit: () => void;
  chapters: ChapterItem[];
  selectedChapterId: string;
  onSelectChapter: (id: string) => void;
  editTitle: string;
  editContent: string;
  onEditTitleChange: (v: string) => void;
  onEditContentChange: (v: string) => void;
  onSave: () => void;
  busy: boolean;
  novelId: string;
  volumes: NovelVolumeListItem[];
  onChapterCreated: (chapterId: string) => void;
  onReloadChapters: () => Promise<void>;
};

type FocusStep = "plan" | "text";

export function FocusMode({
  open,
  onExit,
  chapters,
  selectedChapterId,
  onSelectChapter,
  editTitle,
  editContent,
  onEditTitleChange,
  onEditContentChange,
  onSave,
  busy,
  novelId,
  volumes,
  onChapterCreated,
  onReloadChapters,
}: Props) {
  const [step, setStep] = useState<FocusStep>("plan");
  const [streaming, setStreaming] = useState(false);
  const [streamedText, setStreamedText] = useState("");
  const [thinking, setThinking] = useState("");
  const [thinkExpanded, setThinkExpanded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [planSaved, setPlanSaved] = useState(false);
  const [savingPlan, setSavingPlan] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const textEndRef = useRef<HTMLDivElement>(null);

  const selectedChapter = chapters.find((c) => c.id === selectedChapterId);
  const sortedChapters = [...chapters].sort((a, b) => a.chapter_no - b.chapter_no);
  const currentIdx = sortedChapters.findIndex((c) => c.id === selectedChapterId);
  const nextChapterNo = Math.max(...chapters.map((c) => c.chapter_no), 0) + 1;

  // Find which volume the current chapter belongs to; fall back to last volume
  const currentVolume = selectedChapter
    ? (volumes.find(
        (v) =>
          selectedChapter.chapter_no >= v.from_chapter &&
          selectedChapter.chapter_no <= v.to_chapter
      ) ?? (volumes.length ? volumes[volumes.length - 1] : null))
    : null;

  // auto-scroll during streaming
  useEffect(() => {
    if (streaming && textEndRef.current) {
      textEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [streamedText, streaming]);

  // cleanup on unmount
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  // reset streaming state when chapter changes
  useEffect(() => {
    setStreamedText("");
    setThinking("");
    setError(null);
    setThinkExpanded(false);
    setPlanSaved(false);
    setStep("plan");
    abortRef.current?.abort();
  }, [selectedChapterId]);

  // auto-create a new chapter when opening without selection
  useEffect(() => {
    if (!open || selectedChapterId || creating) return;
    if (chapters.length > 0) {
      const last = sortedChapters[sortedChapters.length - 1];
      if (last) onSelectChapter(last.id);
      return;
    }
    void handleCreateChapter();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const handleCreateChapter = useCallback(async () => {
    if (creating || !novelId) return;
    setCreating(true);
    try {
      const result = await createChapter(novelId, nextChapterNo, "");
      await onReloadChapters();
      onChapterCreated(result.id);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "创建章节失败");
    } finally {
      setCreating(false);
    }
  }, [creating, novelId, nextChapterNo, onReloadChapters, onChapterCreated]);

  // Step 1: Generate chapter plan
  const handleGeneratePlan = useCallback(async () => {
    if (!selectedChapter || !currentVolume || streaming) return;
    setStreaming(true);
    setStreamedText("");
    setThinking("");
    setError(null);
    setThinkExpanded(false);
    setPlanSaved(false);

    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      await generateVolumeChapterPlanStream(
        novelId,
        currentVolume.id,
        selectedChapter.chapter_no,
        {
          onThink: (delta) => {
            setThinking((prev) => prev + delta);
            setThinkExpanded(true);
          },
          onText: (delta) => {
            setStreamedText((prev) => prev + delta);
          },
          onDone: () => {
            setStreaming(false);
          },
          onError: (msg) => {
            setError(msg);
            setStreaming(false);
          },
        },
        ctrl.signal
      );
    } catch (e: unknown) {
      if ((e as Error).name !== "AbortError") {
        setError(e instanceof Error ? e.message : "章节卡生成失败");
      }
      setStreaming(false);
    }
  }, [novelId, selectedChapter, currentVolume, streaming]);

  // Save chapter plan (parse streamed JSON → PATCH)
  const handleSavePlan = useCallback(async () => {
    if (!selectedChapter || !currentVolume || !streamedText.trim()) return;
    setSavingPlan(true);
    setError(null);
    try {
      // Try to parse the streamed JSON
      let parsed: Record<string, unknown>;
      try {
        parsed = JSON.parse(streamedText);
      } catch {
        // Try to extract JSON from the text (LLM may wrap in markdown)
        const jsonMatch = streamedText.match(/\{[\s\S]*\}/);
        if (!jsonMatch) throw new Error("无法解析章节卡 JSON");
        parsed = JSON.parse(jsonMatch[0]);
      }

      // Extract beats from the response
      // The stream returns { volume_title, volume_summary, chapters: [{ chapter_no, title, beats, ... }] }
      let beats: Partial<ChapterPlanV2Beats> = {};
      let chapterTitle = "";

      if (parsed.chapters && Array.isArray(parsed.chapters) && parsed.chapters[0]) {
        const ch = parsed.chapters[0] as Record<string, unknown>;
        beats = (ch.beats || {}) as Partial<ChapterPlanV2Beats>;
        chapterTitle = (ch.title as string) || "";
      } else {
        // Direct beats format
        beats = parsed as Partial<ChapterPlanV2Beats>;
      }

      await patchChapterPlan(novelId, currentVolume.id, selectedChapter.chapter_no, {
        chapter_title: chapterTitle || undefined,
        beats,
      });

      if (chapterTitle && !editTitle) {
        onEditTitleChange(chapterTitle);
      }

      setPlanSaved(true);
      setStep("text");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "保存章节卡失败");
    } finally {
      setSavingPlan(false);
    }
  }, [novelId, currentVolume, selectedChapter, streamedText, editTitle, onEditTitleChange]);

  // Step 2: Generate text
  const handleGenerateText = useCallback(async () => {
    if (!selectedChapter || streaming) return;
    setStreaming(true);
    setStreamedText("");
    setThinking("");
    setError(null);
    setThinkExpanded(false);

    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      await generateChapterStream(
        novelId,
        selectedChapter.chapter_no,
        {
          onThink: (delta) => {
            setThinking((prev) => prev + delta);
            setThinkExpanded(true);
          },
          onText: (delta) => {
            setStreamedText((prev) => prev + delta);
          },
          onDone: () => {
            setStreaming(false);
          },
          onError: (msg) => {
            setError(msg);
            setStreaming(false);
          },
        },
        ctrl.signal
      );
    } catch (e: unknown) {
      if ((e as Error).name !== "AbortError") {
        setError(e instanceof Error ? e.message : "正文生成失败");
      }
      setStreaming(false);
    }
  }, [novelId, selectedChapter, streaming]);

  const handleAbort = useCallback(() => {
    abortRef.current?.abort();
    setStreaming(false);
  }, []);

  const handleApplyStreamed = useCallback(() => {
    if (streamedText.trim()) {
      onEditContentChange(streamedText);
      setStreamedText("");
    }
  }, [streamedText, onEditContentChange]);

  const goPrev = useCallback(() => {
    if (currentIdx > 0) onSelectChapter(sortedChapters[currentIdx - 1].id);
  }, [currentIdx, sortedChapters, onSelectChapter]);

  const goNext = useCallback(() => {
    if (currentIdx < sortedChapters.length - 1) {
      onSelectChapter(sortedChapters[currentIdx + 1].id);
    } else {
      void handleCreateChapter();
    }
  }, [currentIdx, sortedChapters, onSelectChapter, handleCreateChapter]);

  // keyboard shortcuts
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onExit();
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        onSave();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onExit, onSave]);

  if (!open) return null;

  const canGeneratePlan = !!selectedChapter && !!currentVolume && !streaming && !busy && !creating;
  const canGenerateText = !!selectedChapter && !streaming && !busy && !creating;

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-background text-foreground">
      {/* top bar */}
      <div className="flex shrink-0 items-center gap-3 border-b border-border px-4 py-2 sm:px-6">
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="gap-1.5 text-xs font-bold"
          onClick={onExit}
        >
          <ArrowLeft className="size-4" />
          退出专注
        </Button>
        <div className="mx-2 h-5 w-px bg-border" />
        <button
          type="button"
          disabled={currentIdx <= 0}
          onClick={goPrev}
          className="rounded p-1 text-foreground/50 hover:text-foreground disabled:opacity-30"
          title="上一章"
        >
          <ChevronLeft className="size-4" />
        </button>
        <span className="min-w-0 truncate text-sm font-bold">
          {selectedChapter
            ? `第${selectedChapter.chapter_no}章${editTitle ? ` ${editTitle}` : ""}`
            : creating
              ? "正在创建…"
              : "无章节"}
        </span>
        <button
          type="button"
          onClick={goNext}
          className="rounded p-1 text-foreground/50 hover:text-foreground"
          title={currentIdx < sortedChapters.length - 1 ? "下一章" : "创建新章"}
        >
          <ChevronRight className="size-4" />
        </button>
        <div className="ml-auto flex items-center gap-2">
          {selectedChapter && (
            <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-bold text-foreground/60">
              {selectedChapter.status}
            </span>
          )}
          {currentVolume && (
            <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-bold text-foreground/60">
              第{currentVolume.volume_no}卷
            </span>
          )}
          <span className="text-xs text-foreground/50">
            {(editContent || streamedText).length} 字
          </span>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-7 gap-1 text-xs font-bold"
            disabled={busy}
            onClick={onSave}
          >
            <Save className="size-3.5" />
            保存
          </Button>
        </div>
      </div>

      {/* step indicator */}
      <div className="flex shrink-0 items-center gap-1 border-b border-border/50 px-4 py-1.5 sm:px-6">
        <button
          type="button"
          onClick={() => setStep("plan")}
          className={`rounded-full px-3 py-0.5 text-[11px] font-bold transition ${
            step === "plan"
              ? "bg-primary/15 text-primary"
              : "text-foreground/40 hover:text-foreground/60"
          }`}
        >
          1. 章节卡
        </button>
        <span className="text-foreground/20">→</span>
        <button
          type="button"
          onClick={() => setStep("text")}
          className={`rounded-full px-3 py-0.5 text-[11px] font-bold transition ${
            step === "text"
              ? "bg-primary/15 text-primary"
              : "text-foreground/40 hover:text-foreground/60"
          }`}
        >
          2. 正文
        </button>
        {planSaved && (
          <span className="ml-2 text-[10px] font-bold text-emerald-600 dark:text-emerald-400">
            章节卡已保存
          </span>
        )}
      </div>

      {/* main area */}
      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        {/* left: existing content */}
        <div className="flex min-h-0 flex-1 flex-col border-b border-border lg:border-b-0 lg:border-r">
          <div className="flex shrink-0 items-center justify-between border-b border-border/40 px-4 py-1.5">
            <span className="text-[10px] font-bold uppercase tracking-wide text-foreground/40">
              正式稿
            </span>
            <input
              value={editTitle}
              onChange={(e) => onEditTitleChange(e.target.value)}
              className="h-6 w-48 border-0 bg-transparent text-xs font-bold text-foreground/70 outline-none placeholder:text-foreground/30"
              placeholder="章节标题（可选）"
            />
          </div>
          <textarea
            value={editContent}
            onChange={(e) => onEditContentChange(e.target.value)}
            className="min-h-0 flex-1 resize-none border-0 bg-transparent p-4 font-serif text-sm leading-[1.85] text-foreground outline-none sm:p-6 sm:text-base"
            placeholder="选择一章或点击 ‹ › 创建新章开始写作…"
          />
        </div>

        {/* right: streaming output */}
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="flex shrink-0 items-center justify-between border-b border-border/40 px-4 py-1.5">
            <span className="text-[10px] font-bold uppercase tracking-wide text-foreground/40">
              {step === "plan" ? "章节卡 · AI 生成" : "正文 · AI 生成"}
            </span>
            <div className="flex gap-1.5">
              {streaming ? (
                <Button
                  type="button"
                  size="sm"
                  variant="destructive"
                  className="h-7 gap-1 text-xs font-bold"
                  onClick={handleAbort}
                >
                  <Square className="size-3" />
                  停止
                </Button>
              ) : streamedText.trim() ? (
                <>
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    className="h-7 text-xs font-bold"
                    onClick={() => {
                      setStreamedText("");
                      setThinking("");
                    }}
                  >
                    清除
                  </Button>
                  {step === "plan" ? (
                    <Button
                      type="button"
                      size="sm"
                      className="h-7 gap-1 text-xs font-bold"
                      disabled={savingPlan}
                      onClick={handleSavePlan}
                    >
                      <ClipboardCheck className="size-3" />
                      {savingPlan ? "保存中…" : "保存章节卡"}
                    </Button>
                  ) : (
                    <Button
                      type="button"
                      size="sm"
                      className="h-7 gap-1 text-xs font-bold"
                      onClick={handleApplyStreamed}
                    >
                      <Wand2 className="size-3" />
                      应用到正式稿
                    </Button>
                  )}
                </>
              ) : (
                <div className="flex gap-1.5">
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    className="h-7 gap-1 text-xs font-bold"
                    disabled={!selectedChapter || busy || creating}
                    onClick={handleCreateChapter}
                  >
                    <FilePlus2 className="size-3" />
                    新章节卡
                  </Button>
                  {step === "plan" ? (
                    <Button
                      type="button"
                      size="sm"
                      className="h-7 gap-1 text-xs font-bold"
                      disabled={!canGeneratePlan}
                      onClick={handleGeneratePlan}
                      title={!currentVolume ? "无法确定所属卷" : "生成章节卡"}
                    >
                      <Wand2 className="size-3" />
                      生成章节卡
                    </Button>
                  ) : (
                    <Button
                      type="button"
                      size="sm"
                      className="h-7 gap-1 text-xs font-bold"
                      disabled={!canGenerateText}
                      onClick={handleGenerateText}
                    >
                      <Wand2 className="size-3" />
                      生成正文
                    </Button>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* thinking block */}
          {thinking ? (
            <div className="shrink-0 border-b border-border/30">
              <button
                type="button"
                className="flex w-full items-center gap-1.5 px-4 py-1.5 text-left text-[10px] font-bold text-foreground/40 hover:text-foreground/60"
                onClick={() => setThinkExpanded((v) => !v)}
              >
                <span className={`transition ${thinkExpanded ? "rotate-90" : ""}`}>
                  ›
                </span>
                思考过程 ({thinking.length} 字)
              </button>
              {thinkExpanded && (
                <pre className="max-h-40 overflow-auto whitespace-pre-wrap px-4 pb-2 font-mono text-[11px] leading-relaxed text-foreground/50">
                  {thinking}
                </pre>
              )}
            </div>
          ) : null}

          {/* streamed output */}
          <div className="soft-scroll min-h-0 flex-1 overflow-y-auto p-4 sm:p-6">
            {error ? (
              <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                {error}
              </div>
            ) : streamedText ? (
              <div className="font-serif text-sm leading-[1.85] text-foreground sm:text-base whitespace-pre-wrap">
                {streamedText}
                {streaming && (
                  <span className="inline-block h-4 w-px animate-pulse bg-primary" />
                )}
                <div ref={textEndRef} />
              </div>
            ) : (
              <div className="flex h-full items-center justify-center">
                <p className="text-sm text-foreground/40">
                  {selectedChapter
                    ? step === "plan"
                      ? "点击「生成章节卡」为本章创建执行计划"
                      : "点击「生成正文」开始 AI 流式创作"
                    : "正在准备章节…"}
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
