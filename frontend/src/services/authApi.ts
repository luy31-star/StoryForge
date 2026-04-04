import { apiFetch } from "@/services/api";
import type { AuthUser } from "@/stores/authStore";

export async function login(username_or_email: string, password: string) {
  const r = await apiFetch("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username_or_email, password }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ access_token: string; token_type: string }>;
}

export async function sendOtp(email: string) {
  const r = await apiFetch("/api/auth/send-otp", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ status: string; message: string }>;
}

export async function register(email: string, otp: string, password: string) {
  const r = await apiFetch("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, otp, password }),
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
