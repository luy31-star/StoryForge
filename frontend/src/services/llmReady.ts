import { getLlmConfig } from "@/services/novelApi";
import { useLlmSettingsGateStore } from "@/stores/llmSettingsGateStore";

const MSG_NO_MODEL =
  "当前没有可用的全站模型：请管理员在「管理后台 → 模型计价」中添加至少一个已启用模型。";

const MSG_NEED_SAVE =
  "请先在右上角「用户设置」中选定全站默认模型，并点击「保存配置」，再使用 AI 功能。";

/**
 * 在调用各类 AI 接口前调用：若未配置或未在设置中保存过模型，则弹出用户设置并返回 false。
 */
export async function ensureLlmReady(): Promise<boolean> {
  const request = useLlmSettingsGateStore.getState().requestOpenSettings;
  try {
    const cfg = await getLlmConfig();
    const model = (cfg.model || "").trim();
    if (!model) {
      request(MSG_NO_MODEL);
      return false;
    }
    if (cfg.has_explicit_model === false) {
      request(MSG_NEED_SAVE);
      return false;
    }
    return true;
  } catch {
    request("无法读取模型配置，请检查网络后重试。");
    return false;
  }
}
