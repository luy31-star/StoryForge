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
