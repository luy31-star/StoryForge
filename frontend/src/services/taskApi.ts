import { apiFetch } from "@/services/api";

export type UserTaskRow = {
  id: string;
  kind: string;
  status: string;
  title: string;
  batch_id: string | null;
  celery_task_id: string | null;
  novel_id: string | null;
  volume_id: string | null;
  progress: number;
  last_message: string;
  created_at: string | null;
  updated_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  cancel_requested_at: string | null;
  latest_log: {
    event: string;
    message: string;
    level: string;
    chapter_no: number | null;
    meta: Record<string, unknown>;
    created_at: string | null;
  } | null;
};

const BASE = "/api/tasks";

export async function listMyTasks(limit = 50, offset = 0) {
  const q = new URLSearchParams();
  q.set("limit", String(limit));
  q.set("offset", String(offset));
  const r = await apiFetch(`${BASE}?${q.toString()}`);
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{
    items: UserTaskRow[];
    total: number;
    limit: number;
    offset: number;
  }>;
}

export async function deleteTask(taskId: string) {
  const r = await apiFetch(`${BASE}/${taskId}`, { method: "DELETE" });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ status: string; task_id: string }>;
}

export async function cancelTask(taskId: string) {
  const r = await apiFetch(`${BASE}/${taskId}/cancel`, { method: "POST" });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ status: string; task_id: string; task_status: string }>;
}

