import { apiFetch } from "@/services/api";

export async function getSeedanceTaskStatus(taskId: string): Promise<{
  status: string;
  video_url?: string;
}> {
  const res = await apiFetch(`/api/agents/seedance-status/${encodeURIComponent(taskId)}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<{ status: string; video_url?: string }>;
}
