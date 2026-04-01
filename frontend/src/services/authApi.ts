import { apiFetch } from "@/services/api";
import type { AuthUser } from "@/stores/authStore";

export async function login(username: string, password: string) {
  const r = await apiFetch("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ access_token: string; token_type: string }>;
}

export async function register(username: string, password: string) {
  const r = await apiFetch("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ access_token: string; token_type: string }>;
}

export async function fetchMe(token: string) {
  const r = await apiFetch("/api/auth/me", {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<AuthUser>;
}
