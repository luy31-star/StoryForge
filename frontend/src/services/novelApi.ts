import { apiFetch } from "@/services/api";

const BASE = "/api/novels";
const LLM_BASE = "/api/llm";

const MAX_REF_BYTES = 15 * 1024 * 1024;

export function validateReferenceFile(file: File): string | null {
  if (file.size > MAX_REF_BYTES) {
    return "参考文件不能超过 15MB";
  }
  return null;
}

export async function listNovels() {
  const r = await apiFetch(BASE);
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<
    {
      id: string;
      title: string;
      intro: string;
      status: string;
      framework_confirmed: boolean;
      daily_auto_chapters: number;
      updated_at: string | null;
    }[]
  >;
}

export async function inspirationChat(
  messages: { role: "system" | "user" | "assistant"; content: string }[]
) {
  const r = await apiFetch(`${BASE}/inspiration-chat`, {
    method: "POST",
    body: JSON.stringify({ messages }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ reply: string }>;
}

export async function getLlmConfig() {
  const r = await apiFetch(`${LLM_BASE}/config`);
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{
    provider: string;
    model: string;
    novel_web_search: boolean;
    novel_generate_web_search: boolean;
    novel_volume_plan_web_search: boolean;
    novel_memory_refresh_web_search: boolean;
    novel_inspiration_web_search: boolean;
  }>;
}

export async function setLlmConfig(payload: {
  provider: string;
  model: string;
  novel_web_search?: boolean;
  novel_generate_web_search?: boolean;
  novel_volume_plan_web_search?: boolean;
  novel_memory_refresh_web_search?: boolean;
  novel_inspiration_web_search?: boolean;
}) {
  const r = await apiFetch(`${LLM_BASE}/config`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{
    provider: string;
    model: string;
    novel_web_search: boolean;
    novel_generate_web_search: boolean;
    novel_volume_plan_web_search: boolean;
    novel_memory_refresh_web_search: boolean;
    novel_inspiration_web_search: boolean;
  }>;
}

// =========================
// Volumes / Chapter Plan
// =========================

export async function generateVolumes(
  novelId: string,
  payload?: { approx_size?: number; total_chapters?: number }
) {
  const r = await apiFetch(`${BASE}/${novelId}/volumes/generate`, {
    method: "POST",
    body: JSON.stringify({
      approx_size: payload?.approx_size ?? 50,
      total_chapters: payload?.total_chapters,
    }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ status: string; count?: number; reason?: string }>;
}

export async function listVolumes(novelId: string) {
  const r = await apiFetch(`${BASE}/${novelId}/volumes`);
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<
    {
      id: string;
      volume_no: number;
      title: string;
      summary: string;
      from_chapter: number;
      to_chapter: number;
      status: string;
      chapter_plan_count: number;
    }[]
  >;
}

export async function patchVolume(
  novelId: string,
  volumeId: string,
  payload: Partial<{
    title: string;
    summary: string;
    from_chapter: number;
    to_chapter: number;
    status: string;
  }>
) {
  const r = await apiFetch(`${BASE}/${novelId}/volumes/${volumeId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ status: "ok" }>;
}

export async function generateVolumeChapterPlan(
  novelId: string,
  volumeId: string,
  payload?: { force_regen?: boolean; batch_size?: number; from_chapter?: number }
) {
  const r = await apiFetch(
    `${BASE}/${novelId}/volumes/${volumeId}/chapter-plan/generate`,
    {
      method: "POST",
      body: JSON.stringify({
        force_regen: Boolean(payload?.force_regen),
        batch_size: payload?.batch_size,
        from_chapter: payload?.from_chapter,
      }),
    }
  );
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{
    status: string;
    saved?: number;
    reason?: string;
    batch?: {
      from_chapter: number;
      to_chapter: number;
      size: number;
      requested_count?: number;
      saved_count?: number;
      partial?: boolean;
    };
    done?: boolean;
    next_from_chapter?: number | null;
    existing?: number;
    volume_title?: string;
    volume_summary?: string;
  }>;
}

export async function regenerateChapterPlan(
  novelId: string,
  volumeId: string,
  chapterNo: number,
  payload?: { instruction?: string }
) {
  const r = await apiFetch(
    `${BASE}/${novelId}/volumes/${volumeId}/chapter-plan/${chapterNo}/regenerate`,
    {
      method: "POST",
      body: JSON.stringify({ instruction: payload?.instruction }),
    }
  );
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ status: "ok"; chapter_no: number; title: string }>;
}

export async function clearVolumeChapterPlans(novelId: string, volumeId: string) {
  const r = await apiFetch(
    `${BASE}/${novelId}/volumes/${volumeId}/chapter-plan`,
    { method: "DELETE" }
  );
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ status: string; deleted?: number }>;
}

export async function listVolumeChapterPlan(novelId: string, volumeId: string) {
  const r = await apiFetch(`${BASE}/${novelId}/volumes/${volumeId}/chapter-plan`);
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<
    {
      id: string;
      chapter_no: number;
      chapter_title: string;
      beats: Record<string, unknown>;
      status: string;
    }[]
  >;
}

type StreamHandlers = {
  onThink?: (delta: string) => void;
  onText?: (delta: string) => void;
  onDone?: () => void;
  onError?: (message: string) => void;
};

async function postSSE(
  path: string,
  payload: unknown,
  handlers: StreamHandlers,
  signal?: AbortSignal
) {
  const r = await apiFetch(path, {
    method: "POST",
    body: JSON.stringify(payload),
    signal,
    headers: {
      Accept: "text/event-stream",
    },
  });
  if (!r.ok) throw new Error(await r.text());
  if (!r.body) throw new Error("流式响应不可用");

  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const parts = buf.split("\n\n");
    buf = parts.pop() ?? "";
    for (const chunk of parts) {
      const lines = chunk.split("\n");
      let evt = "message";
      let data = "";
      for (const line of lines) {
        if (line.startsWith("event:")) evt = line.slice(6).trim();
        if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (!data) continue;
      let parsed: any = {};
      try {
        parsed = JSON.parse(data);
      } catch {
        parsed = { message: data, delta: data };
      }
      if (evt === "think" && typeof parsed.delta === "string") handlers.onThink?.(parsed.delta);
      else if (evt === "text" && typeof parsed.delta === "string") handlers.onText?.(parsed.delta);
      else if (evt === "done") handlers.onDone?.();
      else if (evt === "error") handlers.onError?.(parsed.message || "流式错误");
    }
  }
}

export async function inspirationChatStream(
  messages: { role: "system" | "user" | "assistant"; content: string }[],
  handlers: StreamHandlers,
  signal?: AbortSignal
) {
  return postSSE(`${BASE}/inspiration-chat/stream`, { messages }, handlers, signal);
}

export async function chapterContextChat(
  novelId: string,
  messages: { role: "system" | "user" | "assistant"; content: string }[]
) {
  const r = await apiFetch(`${BASE}/${novelId}/chapter-chat`, {
    method: "POST",
    body: JSON.stringify({ messages }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ reply: string }>;
}

export async function chapterContextChatStream(
  novelId: string,
  messages: { role: "system" | "user" | "assistant"; content: string }[],
  handlers: StreamHandlers,
  signal?: AbortSignal,
  options?: { llm_provider?: string; llm_model?: string }
) {
  return postSSE(
    `${BASE}/${novelId}/chapter-chat/stream`,
    { messages, llm_provider: options?.llm_provider, llm_model: options?.llm_model },
    handlers,
    signal
  );
}

export async function createNovel(body: {
  title: string;
  intro?: string;
  background?: string;
  style?: string;
  target_chapters?: number;
  daily_auto_chapters?: number;
}) {
  const r = await apiFetch(BASE, {
    method: "POST",
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ id: string }>;
}

export async function getNovel(id: string) {
  const r = await apiFetch(`${BASE}/${id}`);
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<Record<string, unknown>>;
}

export async function patchNovel(id: string, body: Record<string, unknown>) {
  const r = await apiFetch(`${BASE}/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function deleteNovel(id: string) {
  const r = await apiFetch(`${BASE}/${id}`, {
    method: "DELETE",
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ status: "ok" }>;
}

export async function uploadReference(novelId: string, file: File) {
  const err = validateReferenceFile(file);
  if (err) throw new Error(err);
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch(`${BASE}/${novelId}/reference`, {
    method: "POST",
    body: fd,
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ storage_key: string; public_url: string }>;
}

export async function generateFramework(novelId: string) {
  const r = await apiFetch(`${BASE}/${novelId}/generate-framework`, {
    method: "POST",
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function confirmFramework(
  novelId: string,
  framework_markdown: string,
  framework_json: string
) {
  const r = await apiFetch(`${BASE}/${novelId}/confirm-framework`, {
    method: "POST",
    body: JSON.stringify({ framework_markdown, framework_json }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function listChapters(novelId: string) {
  const r = await apiFetch(`${BASE}/${novelId}/chapters`);
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<
    {
      id: string;
      chapter_no: number;
      title: string;
      content: string;
      pending_content: string;
      pending_revision_prompt: string;
      status: string;
      source: string;
    }[]
  >;
}

export async function generateChapters(
  novelId: string,
  count = 1,
  title_hint = "",
  options?: {
    use_cold_recall?: boolean;
    cold_recall_items?: number;
    auto_consistency_check?: boolean;
    chapter_no?: number;
  }
) {
  const r = await apiFetch(`${BASE}/${novelId}/chapters/generate`, {
    method: "POST",
    body: JSON.stringify({
      count,
      title_hint,
      use_cold_recall: Boolean(options?.use_cold_recall),
      cold_recall_items: options?.cold_recall_items ?? 5,
      auto_consistency_check: Boolean(options?.auto_consistency_check),
      chapter_no: options?.chapter_no,
    }),
  });
  if (!r.ok) {
    let detail = "";
    try {
      const data = (await r.clone().json()) as { detail?: unknown; message?: unknown };
      if (typeof data.detail === "string") detail = data.detail;
      else if (typeof data.message === "string") detail = data.message;
      else if (data.detail != null) detail = JSON.stringify(data.detail);
    } catch {
      detail = "";
    }
    if (!detail) detail = (await r.text()).trim();
    throw new Error(detail || `生成失败（HTTP ${r.status}）`);
  }
  return r.json() as Promise<{ chapter_ids: string[]; batch_id?: string }>;
}

export async function listGenerationLogs(
  novelId: string,
  params?: { batch_id?: string; level?: string; limit?: number }
) {
  const q = new URLSearchParams();
  if (params?.batch_id) q.set("batch_id", params.batch_id);
  if (params?.level) q.set("level", params.level);
  if (params?.limit) q.set("limit", String(params.limit));
  const query = q.toString();
  const r = await apiFetch(`${BASE}/${novelId}/generation-logs${query ? `?${query}` : ""}`);
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{
    latest_batch_id: string | null;
    latest_refresh_batch_id: string | null;
    refresh_status: "idle" | "queued" | "started" | "done" | "failed";
    refresh_progress: number;
    refresh_last_message: string;
    refresh_updated_at: string | null;
    refresh_started_at: string | null;
    refresh_elapsed_seconds: number | null;
    latest_refresh_success_version: number | null;
    items: {
      id: string;
      batch_id: string;
      level: string;
      event: string;
      chapter_no: number | null;
      message: string;
      meta: Record<string, unknown>;
      created_at: string | null;
    }[];
  }>;
}

export async function patchChapter(
  chapterId: string,
  body: { title?: string; content: string }
) {
  const r = await apiFetch(`${BASE}/chapters/${chapterId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ status: "ok" }>;
}

export async function deleteChapter(chapterId: string) {
  const r = await apiFetch(`${BASE}/chapters/${chapterId}`, {
    method: "DELETE",
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{
    status: "ok";
    deleted_chapter_id: string;
    deleted_chapter_no: number;
    was_approved: boolean;
    memory_refresh_status?: "queued" | "skipped" | "none";
    memory_refresh_task_id?: string | null;
    memory_refresh_batch_id?: string | null;
  }>;
}

export async function addChapterFeedback(chapterId: string, body: string) {
  const r = await apiFetch(`${BASE}/chapters/${chapterId}/feedback`, {
    method: "POST",
    body: JSON.stringify({ body }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function approveChapter(chapterId: string) {
  const r = await apiFetch(`${BASE}/chapters/${chapterId}/approve`, {
    method: "POST",
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{
    status: "ok";
    incremental_memory_status?: "applied" | "failed" | "none";
    incremental_memory_version?: number | null;
    incremental_memory_batch_id?: string | null;
    memory_refresh_status?: "queued" | "skipped" | "none";
    memory_refresh_task_id?: string | null;
    memory_refresh_batch_id?: string | null;
  }>;
}

export async function reviseChapter(chapterId: string, user_prompt: string) {
  const r = await apiFetch(`${BASE}/chapters/${chapterId}/revise`, {
    method: "POST",
    body: JSON.stringify({ user_prompt }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function applyChapterRevision(chapterId: string) {
  const r = await apiFetch(`${BASE}/chapters/${chapterId}/apply-revision`, {
    method: "POST",
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function consistencyFixChapter(chapterId: string) {
  const r = await apiFetch(`${BASE}/chapters/${chapterId}/consistency-fix`, {
    method: "POST",
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function discardChapterRevision(chapterId: string) {
  const r = await apiFetch(`${BASE}/chapters/${chapterId}/discard-revision`, {
    method: "POST",
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function getMemory(novelId: string) {
  const r = await apiFetch(`${BASE}/${novelId}/memory`);
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{
    version: number;
    payload_json: string;
    readable_zh: string;
    readable_zh_auto?: string;
    has_readable_override?: boolean;
    summary: string;
    created_at?: string | null;
  }>;
}

export type NormalizedMemoryPayload = {
  memory_version: number;
  outline: {
    main_plot: string;
    world_rules: unknown[];
    arcs: unknown[];
    themes: unknown[];
    notes: unknown[];
    timeline_archive_summary: unknown[];
  };
  skills: { name: string; detail: Record<string, unknown> }[];
  inventory: { label: string; detail: Record<string, unknown> }[];
  pets: { name: string; detail: Record<string, unknown> }[];
  characters: {
    name: string;
    role: string;
    status: string;
    traits: unknown[];
    detail: Record<string, unknown>;
  }[];
  relations: { from: string; to: string; relation: string }[];
  open_plots: string[];
  chapters: {
    chapter_no: number;
    chapter_title: string;
    key_facts: string[];
    causal_results: string[];
    open_plots_added: string[];
    open_plots_resolved: string[];
  }[];
};

export async function getMemoryNormalized(novelId: string) {
  const r = await apiFetch(`${BASE}/${novelId}/memory/normalized`);
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<
    { status: "empty"; data: null } | { status: "ok"; data: NormalizedMemoryPayload | null }
  >;
}

export async function rebuildMemoryNormalized(novelId: string) {
  const r = await apiFetch(`${BASE}/${novelId}/memory/rebuild-normalized`, {
    method: "POST",
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ status: "ok"; data: NormalizedMemoryPayload | null }>;
}

/** 保存完整 payload_json 和/或人工「中文阅读」覆盖（readable_zh_override）。 */
export async function saveMemoryPatch(
  novelId: string,
  body: { payload_json?: string; readable_zh_override?: string | null }
) {
  const r = await apiFetch(`${BASE}/${novelId}/memory/save`, {
    method: "POST",
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{
    version: number;
    payload_json: string;
    readable_zh: string;
    readable_zh_auto: string;
    has_readable_override: boolean;
  }>;
}

export async function refreshMemory(novelId: string) {
  const r = await apiFetch(`${BASE}/${novelId}/memory/refresh`, {
    method: "POST",
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<
    | {
        version: number;
        payload_json: string;
        readable_zh: string;
      }
    | {
        status: "validation_failed";
        version: number;
        payload_json: string;
        readable_zh: string;
        candidate_json: string;
        candidate_readable_zh: string;
        errors: string[];
      }
  >;
}

export async function getNovelMetrics(novelId: string) {
  const r = await apiFetch(`${BASE}/${novelId}/metrics`);
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{
    novel: {
      id: string;
      title: string;
      framework_confirmed: boolean;
      status: string;
    };
    config: {
      novel_memory_refresh_chapters: number;
      novel_chapter_summary_mode: string;
      novel_chapter_summary_tail_chars: number;
      novel_chapter_summary_head_chars: number;
      novel_consistency_check_chapter: boolean;
      novel_consistency_check_temperature: number;
    };
    summary: {
      memory_version: number;
      open_plots_count: number;
      open_plots_preview: string[];
      open_plots_editable: string[];
      canonical_timeline_count: number;
      canonical_timeline_last_chapter_no: number | null;
      canonical_timeline_last_editable: {
        key_facts: string[];
        causal_results: string[];
        open_plots_added: string[];
        open_plots_resolved: string[];
      };
      canonical_timeline_preview: string[];
      approved_count: number;
      pending_review_count: number;
      last_approved_chapter_no: number | null;
      prev_approved_chapter_no: number | null;
      is_consecutive_last_two_approved: boolean;
    };
  }>;
}

export async function manualFixMemory(
  novelId: string,
  payload: {
    open_plots: string[];
    canonical_last: {
      key_facts: string[];
      causal_results: string[];
      open_plots_added: string[];
      open_plots_resolved: string[];
    };
    notes_hint?: string;
  }
) {
  const r = await apiFetch(`${BASE}/${novelId}/memory/manual-fix`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{
    version: number;
    open_plots_count: number;
    canonical_timeline_count: number;
    canonical_timeline_last_chapter_no: number | null;
  }>;
}
