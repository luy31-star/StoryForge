import { apiFetch } from "@/services/api";

export async function createAlipayRechargeForm(amountCny: number) {
  const r = await apiFetch("/api/billing/recharge/alipay-form", {
    method: "POST",
    body: JSON.stringify({ amount_cny: amountCny }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{
    out_trade_no: string;
    amount_cny: number;
    points: number;
    form_html: string;
  }>;
}

export async function getRechargeOrder(outTradeNo: string) {
  const r = await apiFetch(`/api/billing/recharge/orders/${encodeURIComponent(outTradeNo)}`);
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{
    out_trade_no: string;
    amount_cny: number;
    points: number;
    status: string;
    trade_status: string;
    created_at: string;
    paid_at?: string | null;
  }>;
}

export type ModelPriceRow = {
  id: string;
  model_id: string;
  price_cny_per_million_tokens: number;
  prompt_price_cny_per_million_tokens: number;
  completion_price_cny_per_million_tokens: number;
  enabled: boolean;
  display_name: string;
};

export async function listPublicModelPrices() {
  const r = await apiFetch("/api/billing/model-prices");
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<ModelPriceRow[]>;
}

export async function adminListModelPrices() {
  const r = await apiFetch("/api/admin/model-prices");
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<ModelPriceRow[]>;
}

export async function adminPatchModelPrice(
  priceId: string,
  patch: Partial<{
    price_cny_per_million_tokens: number;
    prompt_price_cny_per_million_tokens: number;
    completion_price_cny_per_million_tokens: number;
    enabled: boolean;
    display_name: string;
  }>
) {
  const r = await apiFetch(`/api/admin/model-prices/${priceId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<ModelPriceRow>;
}

export async function adminCreateModelPrice(body: {
  model_id: string;
  price_cny_per_million_tokens?: number;
  prompt_price_cny_per_million_tokens?: number;
  completion_price_cny_per_million_tokens?: number;
  enabled?: boolean;
  display_name?: string;
}) {
  const r = await apiFetch("/api/admin/model-prices", {
    method: "POST",
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<ModelPriceRow>;
}

export async function adminDeleteModelPrice(priceId: string) {
  const r = await apiFetch(`/api/admin/model-prices/${priceId}`, {
    method: "DELETE",
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export type DashboardStats = {
  total_tokens: number;
  total_chapters: number;
  total_novels: number;
  total_users: number;
};

export async function adminGetDashboardStats() {
  const r = await apiFetch("/api/admin/dashboard/stats");
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<DashboardStats>;
}

export type UserAdminOut = {
  id: string;
  username: string;
  email: string;
  created_at: string;
  points_balance: number;
  total_tokens_used: number;
  is_admin: boolean;
  is_frozen: boolean;
  frozen_reason: string;
};

export async function adminListUsers() {
  const r = await apiFetch("/api/admin/users");
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<UserAdminOut[]>;
}

export type DailyTokenUsageOut = {
  date: string;
  total_tokens: number;
};

export async function adminGetUserTokenUsage(userId: string, days = 30) {
  const r = await apiFetch(`/api/admin/users/${userId}/token-usage/daily?days=${days}`);
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<DailyTokenUsageOut[]>;
}

export async function adminAdjustUserPoints(userId: string, amount: number, note?: string) {
  const r = await apiFetch(`/api/admin/users/${userId}/adjust-points`, {
    method: "POST",
    body: JSON.stringify({ amount_points: amount, note }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ status: string; new_balance: number }>;
}

export async function adminFreezeUser(userId: string, reason?: string) {
  const r = await apiFetch(`/api/admin/users/${userId}/freeze`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ status: string; is_frozen: boolean }>;
}

export async function adminUnfreezeUser(userId: string) {
  const r = await apiFetch(`/api/admin/users/${userId}/unfreeze`, {
    method: "POST",
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ status: string; is_frozen: boolean }>;
}

export type InviteCodeRow = {
  id: string;
  code: string;
  is_frozen: boolean;
  expires_at?: string | null;
  used_at?: string | null;
  used_by_user_id?: string | null;
  used_by_username?: string | null;
  note: string;
  created_at: string;
  created_by_admin_id: string;
  created_by_admin_username?: string | null;
};

export async function adminListInviteCodes(page = 1, pageSize = 20) {
  const r = await apiFetch(`/api/admin/invite-codes?page=${page}&page_size=${pageSize}`);
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{
    items: InviteCodeRow[];
    total: number;
    page: number;
    page_size: number;
  }>;
}

export async function adminCreateInviteCode(expiresInDays?: number, note?: string) {
  const r = await apiFetch("/api/admin/invite-codes", {
    method: "POST",
    body: JSON.stringify({ expires_in_days: expiresInDays, note }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<InviteCodeRow>;
}

export async function adminFreezeInviteCode(inviteId: string) {
  const r = await apiFetch(`/api/admin/invite-codes/${inviteId}/freeze`, { method: "POST" });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ status: string; is_frozen: boolean }>;
}

export async function adminUnfreezeInviteCode(inviteId: string) {
  const r = await apiFetch(`/api/admin/invite-codes/${inviteId}/unfreeze`, { method: "POST" });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ status: string; is_frozen: boolean }>;
}

export async function adminDeleteInviteCode(inviteId: string) {
  const r = await apiFetch(`/api/admin/invite-codes/${inviteId}`, { method: "DELETE" });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function adminGetRegistrationMode() {
  const r = await apiFetch("/api/admin/registration-mode");
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ invite_only: boolean }>;
}

export async function adminSetRegistrationMode(inviteOnly: boolean) {
  const r = await apiFetch("/api/admin/registration-mode", {
    method: "POST",
    body: JSON.stringify({ invite_only: inviteOnly }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ invite_only: boolean }>;
}
