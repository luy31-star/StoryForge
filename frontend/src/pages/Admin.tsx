import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  adminListModelPrices,
  adminPatchModelPrice,
  type ModelPriceRow,
} from "@/services/billingApi";

export function Admin() {
  const [rows, setRows] = useState<ModelPriceRow[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(() => {
    setBusy(true);
    setErr(null);
    adminListModelPrices()
      .then(setRows)
      .catch((e: Error) => setErr(e.message))
      .finally(() => setBusy(false));
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  async function toggle(row: ModelPriceRow) {
    setErr(null);
    try {
      await adminPatchModelPrice(row.id, { enabled: !row.enabled });
      await reload();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "更新失败");
    }
  }

  async function savePrice(row: ModelPriceRow, value: string) {
    const n = parseFloat(value);
    if (Number.isNaN(n) || n < 0) return;
    setErr(null);
    try {
      await adminPatchModelPrice(row.id, { price_cny_per_million_tokens: n });
      await reload();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "保存失败");
    }
  }

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="mx-auto max-w-4xl space-y-6">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold">管理后台 · 模型计价</h1>
            <p className="text-sm text-muted-foreground">
              单价单位：元 / 百万 token；用户侧按积分扣费（1 元 = 10 积分）。
            </p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => reload()} disabled={busy}>
              刷新
            </Button>
            <Button variant="ghost" size="sm" asChild>
              <Link to="/novels">返回书架</Link>
            </Button>
          </div>
        </div>

        {err ? <p className="text-sm text-destructive">{err}</p> : null}

        <Card>
          <CardHeader>
            <CardTitle>模型列表</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {rows.length === 0 && !busy ? (
              <p className="text-sm text-muted-foreground">暂无记录（启动后端后会种子默认模型）。</p>
            ) : null}
            {rows.map((r) => (
              <div
                key={r.id}
                className="flex flex-col gap-3 rounded-lg border border-border/60 p-4 md:flex-row md:items-center"
              >
                <div className="flex-1 space-y-1">
                  <div className="font-medium">{r.display_name || r.model_id}</div>
                  <div className="font-mono text-xs text-muted-foreground">{r.model_id}</div>
                </div>
                <div className="flex flex-wrap items-end gap-3">
                  <div className="space-y-1">
                    <Label className="text-xs">元/百万 token</Label>
                    <input
                      key={r.id + "-price"}
                      defaultValue={String(r.price_cny_per_million_tokens)}
                      className="h-9 w-28 rounded-md border border-input bg-background px-2 text-sm"
                      onBlur={(e) => void savePrice(r, e.target.value)}
                    />
                  </div>
                  <Button
                    type="button"
                    variant={r.enabled ? "secondary" : "outline"}
                    size="sm"
                    onClick={() => void toggle(r)}
                  >
                    {r.enabled ? "已启用" : "已禁用"}
                  </Button>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
