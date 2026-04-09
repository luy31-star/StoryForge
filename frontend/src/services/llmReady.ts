import { getLlmConfig } from "@/services/novelApi";
import { useLlmSettingsGateStore } from "@/stores/llmSettingsGateStore";

const MSG_NO_MODEL =
  "当前没有可用的全站模型：请管理员在「管理后台 → 模型计价」中添加至少一个已启用模型。";

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
    return true;
  } catch {
    request("无法读取模型配置，请检查网络后重试。");
    return false;
  }
}
