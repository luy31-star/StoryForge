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

export async function register(email: string, username: string, invite_code: string, otp: string, password: string) {
  const r = await apiFetch("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, username, invite_code, otp, password }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ access_token: string; token_type: string }>;
}

export async function refreshToken() {
  const r = await apiFetch("/api/auth/refresh", {
    method: "POST",
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ access_token: string; token_type: string }>;
}

export async function sendForgotPasswordOtp(email: string) {
  const r = await apiFetch("/api/auth/forgot-password/send-otp", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ status: string; message: string }>;
}

export async function resetPassword(email: string, otp: string, new_password: string) {
  const r = await apiFetch("/api/auth/reset-password", {
    method: "POST",
    body: JSON.stringify({ email, otp, new_password }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ status: string; message: string }>;
}

export async function getRegistrationMode() {
  const r = await apiFetch("/api/auth/registration-mode");
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ invite_only: boolean }>;
}

export async function fetchMe(token: string) {
  void token;
  const r = await apiFetch("/api/auth/me");
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<AuthUser>;
}
