/**
 * Hook for chapter context chat with streaming.
 */
import { useCallback, useRef } from "react";
import { chapterContextChatStream } from "@/services/novelApi";
import { useNovelWorkspaceStore } from "@/stores/novelWorkspaceStore";

const chapterQuickPrompts = [
  {
    label: "查设定冲突",
    prompt: "请检查目前已审定章节与框架设定是否有冲突，按「严重/中等/轻微」列出问题与修复建议。",
  },
  {
    label: "下一章建议",
    prompt: "请给出下一章（只出一个方案）的剧情推进建议：目标、冲突、转折、结尾钩子。",
  },
  {
    label: "伏笔回收优先级",
    prompt: "请列出当前最该优先回收的 3 条伏笔（含全书待收束线），并说明各自最佳回收章节窗口。",
  },
  {
    label: "人物动机体检",
    prompt: "请评估主角与关键配角的人物动机是否连贯，指出薄弱点并给出最小改写建议。",
  },
  {
    label: "三章节奏编排",
    prompt: "请给出接下来 3 章的节奏编排（每章一句目标 + 一句冲突 + 一句收束）。",
  },
] as const;

export function useChapterChat(novelId: string) {
  const setChapterChat = useNovelWorkspaceStore((s) => s.setChapterChat);
  const abortRef = useRef<AbortController | null>(null);

  const open = useCallback(() => {
    setChapterChat({ open: true, turns: [], input: "", err: null, thinking: "" });
  }, [setChapterChat]);

  const close = useCallback(() => {
    abortRef.current?.abort();
    setChapterChat({ open: false, turns: [], input: "", busy: false, err: null, thinking: "", abort: null });
  }, [setChapterChat]);

  const send = useCallback(
    async (message: string) => {
      if (!message.trim()) return;
      const state = useNovelWorkspaceStore.getState().chapterChat;
      const newTurns = [...state.turns, { role: "user" as const, content: message }];
      setChapterChat({ turns: newTurns, input: "", busy: true, err: null, thinking: "" });

      const controller = new AbortController();
      abortRef.current = controller;
      setChapterChat({ abort: controller });

      let assistantContent = "";
      try {
        await chapterContextChatStream(
          novelId,
          newTurns.map((t) => ({ role: t.role, content: t.content })),
          {
            onThink: (text) => setChapterChat({ thinking: text }),
            onText: (text) => {
              assistantContent += text;
              setChapterChat({
                turns: [...newTurns, { role: "assistant", content: assistantContent }],
              });
            },
            onDone: () => {
              setChapterChat({ busy: false, thinking: "" });
            },
            onError: (err) => {
              setChapterChat({ busy: false, err: String(err), thinking: "" });
            },
          },
          controller.signal
        );
      } catch (e) {
        if (!controller.signal.aborted) {
          setChapterChat({ busy: false, err: e instanceof Error ? e.message : "发送失败", thinking: "" });
        }
      }
    },
    [novelId, setChapterChat]
  );

  const sendQuickPrompt = useCallback(
    (index: number) => {
      const prompt = chapterQuickPrompts[index]?.prompt;
      if (prompt) void send(prompt);
    },
    [send]
  );

  return { open, close, send, sendQuickPrompt, chapterQuickPrompts };
}
