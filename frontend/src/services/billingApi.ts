import { apiFetch } from "@/services/api";

export async function mockRecharge(amountCny: number) {
  const r = await apiFetch("/api/billing/recharge", {
    method: "POST",
    body: JSON.stringify({ amount_cny: amountCny }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ points_added: number; points_balance: number }>;
}

export type ModelPriceRow = {
  id: string;
  model_id: string;
  price_cny_per_million_tokens: number;
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
  created_at: string;
  points_balance: number;
  total_tokens_used: number;
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
