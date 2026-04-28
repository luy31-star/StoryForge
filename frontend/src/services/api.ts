import { useAuthStore } from "@/stores/authStore";

const base =
  typeof import.meta.env.VITE_API_BASE === "string"
    ? import.meta.env.VITE_API_BASE
    : "";

const apiTraceEnabled =
  import.meta.env.DEV || String(import.meta.env.VITE_API_TRACE || "") === "1";

type ApiFetchInit = RequestInit & {
  _retry401?: boolean;
  _skipAuthRefresh?: boolean;
};

let refreshPromise: Promise<string | null> | null = null;
const TOKEN_REFRESH_THRESHOLD_MS = 2 * 60 * 1000;

function currentToken(): string | null {
  return useAuthStore.getState().token;
}

function authHeader(token?: string | null): Record<string, string> {
  const t = token ?? currentToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

function mergeHeaders(
  initHeaders?: HeadersInit,
  token?: string | null
): Record<string, string> {
  return {
    "Content-Type": "application/json",
    ...authHeader(token),
    ...(initHeaders as Record<string, string> | undefined),
  };
}

function parseJwtExpireMs(token: string): number | null {
  try {
    const parts = token.split(".");
    if (parts.length < 2) return null;
    const normalized = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padLen = (4 - (normalized.length % 4)) % 4;
    const base64 = normalized + "=".repeat(padLen);
    const payload = JSON.parse(atob(base64)) as { exp?: number };
    if (!payload.exp) return null;
    return payload.exp * 1000;
  } catch {
    return null;
  }
}

async function refreshAccessToken(): Promise<string | null> {
  if (refreshPromise) return refreshPromise;
  const token = currentToken();
  if (!token) return null;

  refreshPromise = (async () => {
    try {
      const resp = await fetch(`${base}/api/auth/refresh`, {
        method: "POST",
        headers: mergeHeaders(undefined, token),
      });
      if (!resp.ok) {
        useAuthStore.getState().logout();
        return null;
      }
      const data = (await resp.json()) as { access_token?: string };
      const nextToken = data.access_token || null;
      if (!nextToken) {
        useAuthStore.getState().logout();
        return null;
      }
      useAuthStore.getState().setToken(nextToken);
      return nextToken;
    } catch {
      useAuthStore.getState().logout();
      return null;
    } finally {
      refreshPromise = null;
    }
  })();

  return refreshPromise;
}

async function ensureFreshToken(path: string): Promise<string | null> {
  const token = currentToken();
  if (!token) return null;
  if (path.includes("/api/auth/refresh")) return token;

  const expMs = parseJwtExpireMs(token);
  if (!expMs) return token;
  const remaining = expMs - Date.now();
  if (remaining > TOKEN_REFRESH_THRESHOLD_MS) return token;
  return refreshAccessToken();
}

export async function apiFetch(
  path: string,
  init?: ApiFetchInit
): Promise<Response> {
  const url = path.startsWith("http") ? path : `${base}${path}`;
  const method = (init?.method || "GET").toUpperCase();
  const started = performance.now();
  try {
    const freshToken =
      !init?._skipAuthRefresh && Boolean(currentToken())
        ? await ensureFreshToken(path)
        : currentToken();

    const resp = await fetch(url, {
      ...init,
      headers: mergeHeaders(init?.headers, freshToken),
    });

    const shouldTryRefresh =
      resp.status === 401 &&
      !init?._retry401 &&
      !init?._skipAuthRefresh &&
      !path.includes("/api/auth/refresh") &&
      Boolean(currentToken());

    if (shouldTryRefresh) {
      const newToken = await refreshAccessToken();
      if (newToken) {
        return apiFetch(path, {
          ...init,
          _retry401: true,
          headers: {
            ...mergeHeaders(init?.headers, newToken),
          },
        });
      }
    }

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
