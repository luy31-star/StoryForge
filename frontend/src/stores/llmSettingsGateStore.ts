import { create } from "zustand";

type State = {
  gateTick: number;
  reason: string;
  /** 由 AppLayout 在关闭设置后清零，避免重复弹层 */
  requestOpenSettings: (reason?: string) => void;
};

export const useLlmSettingsGateStore = create<State>((set) => ({
  gateTick: 0,
  reason: "",
  requestOpenSettings: (reason = "请完成全站模型配置。") =>
    set((s) => ({
      gateTick: s.gateTick + 1,
      reason,
    })),
}));
