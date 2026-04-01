import { useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { mockRecharge } from "@/services/billingApi";
import { fetchMe } from "@/services/authApi";
import { useAuthStore } from "@/stores/authStore";

const PRESETS = [10, 50, 100] as const;

export function Recharge() {
  const token = useAuthStore((s) => s.token);
  const user = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function pay(cny: number) {
    if (!token) return;
    setErr(null);
    setNotice(null);
    setBusy(true);
    try {
      const out = await mockRecharge(cny);
      const me = await fetchMe(token);
      setUser(me);
      setNotice(`已模拟充值：+${out.points_added} 积分，当前余额 ${out.points_balance}`);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "充值失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="mx-auto max-w-lg space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">积分充值（模拟）</h1>
          <Button variant="ghost" size="sm" asChild>
            <Link to="/novels">返回</Link>
          </Button>
        </div>
        <Card>
          <CardHeader>
            <CardTitle>当前余额</CardTitle>
            <p className="text-3xl font-semibold tabular-nums">
              {user?.points_balance ?? 0}{" "}
              <span className="text-base font-normal text-muted-foreground">积分</span>
            </p>
            <p className="text-sm text-muted-foreground">规则：1 元人民币 = 10 积分（演示环境直接到账）</p>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-3 gap-2">
              {PRESETS.map((cny) => (
                <div key={cny} className="rounded-lg border border-border p-3 text-center">
                  <div className="text-sm text-muted-foreground">{cny} 元</div>
                  <div className="font-medium">{cny * 10} 积分</div>
                  <Button
                    className="mt-2 w-full"
                    size="sm"
                    disabled={busy}
                    onClick={() => void pay(cny)}
                  >
                    模拟支付
                  </Button>
                </div>
              ))}
            </div>
            {notice ? <p className="text-sm text-emerald-600">{notice}</p> : null}
            {err ? <p className="text-sm text-destructive">{err}</p> : null}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
