import { apiFetch } from "@/services/api";
import { refreshMeSilently } from "@/services/userSync";

/** 前端调用后端 Gemini 代理（密钥仅在后端） */
export async function chatGemini(body: {
  systemPrompt?: string;
  messages: { role: string; content: string }[];
  model?: string;
}): Promise<{ text: string }> {
  const res = await apiFetch("/api/agents/gemini-chat", {
    method: "POST",
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(t || res.statusText);
  }
  void refreshMeSilently();
  return res.json() as Promise<{ text: string }>;
}
