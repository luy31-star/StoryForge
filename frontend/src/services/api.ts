const base =
  typeof import.meta.env.VITE_API_BASE === "string"
    ? import.meta.env.VITE_API_BASE
    : "";

const apiTraceEnabled =
  import.meta.env.DEV || String(import.meta.env.VITE_API_TRACE || "") === "1";

export async function apiFetch(
  path: string,
  init?: RequestInit
): Promise<Response> {
  const url = path.startsWith("http") ? path : `${base}${path}`;
  const method = (init?.method || "GET").toUpperCase();
  const started = performance.now();
  try {
    const resp = await fetch(url, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...init?.headers,
      },
    });
    if (apiTraceEnabled) {
      const elapsed = Math.round(performance.now() - started);
      console.info(`[apiFetch] ${method} ${url} -> ${resp.status} (${elapsed}ms)`);
    }
    return resp;
  } catch (e: unknown) {
    if (apiTraceEnabled) {
      const elapsed = Math.round(performance.now() - started);
      const msg = e instanceof Error ? e.message : String(e);
      console.error(`[apiFetch] ${method} ${url} -> ERROR (${elapsed}ms): ${msg}`);
    }
    throw e;
  }
}
