import { apiFetch } from "@/services/api";
import { refreshMeSilently } from "@/services/userSync";

export async function synthesizeVoice(body: {
  text: string;
  voice_model?: string;
  settings?: Record<string, unknown>;
}): Promise<{ audio_url: string; duration?: number }> {
  const res = await apiFetch("/api/agents/voice-synthesis", {
    method: "POST",
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  void refreshMeSilently();
  return res.json() as Promise<{ audio_url: string; duration?: number }>;
}
