import type { WorkflowTemplate } from "@/types/workflow";

/** 内置：Gemini + SeeDance 完整流程（与 project.md 一致） */
export const geminiSeedanceTemplate: WorkflowTemplate = {
  id: "gemini-seedance-complete",
  name: "Gemini + SeeDance 完整流程",
  description: "从歌曲翻唱到视频生成的完整 AI 工作流",
  nodes: [
    {
      id: "input-1",
      type: "audio-input",
      position: { x: 100, y: 100 },
      data: {
        title: "原歌输入",
        acceptFormats: ["mp3", "wav"],
      },
    },
    {
      id: "gemini-1",
      type: "gemini-chat",
      position: { x: 300, y: 100 },
      data: {
        title: "歌曲分析",
        systemPrompt:
          "分析输入歌曲的风格、情感、节奏，为翻唱做准备",
        autoNext: false,
      },
    },
    {
      id: "voice-1",
      type: "voice-blend",
      position: { x: 500, y: 100 },
      data: {
        title: "声音合成",
        referenceVoices: [],
        blendSettings: {
          emotion: "auto",
          style: "singing",
        },
      },
    },
    {
      id: "character-1",
      type: "character-setup",
      position: { x: 300, y: 300 },
      data: {
        title: "角色设定",
        defaultImage: null,
        sceneSettings: {
          background: "studio",
          lighting: "soft",
        },
      },
    },
    {
      id: "seedance-1",
      type: "seedance-video",
      position: { x: 700, y: 200 },
      data: {
        title: "视频生成",
        quality: "ultra",
        resolution: "1080p",
      },
    },
    {
      id: "output-1",
      type: "output",
      position: { x: 900, y: 200 },
      data: {
        title: "最终输出",
        format: "mp4",
      },
    },
  ],
  edges: [
    { id: "e1", source: "input-1", target: "gemini-1" },
    { id: "e2", source: "gemini-1", target: "voice-1" },
    { id: "e3", source: "voice-1", target: "seedance-1" },
    { id: "e4", source: "character-1", target: "seedance-1" },
    { id: "e5", source: "seedance-1", target: "output-1" },
  ],
};
