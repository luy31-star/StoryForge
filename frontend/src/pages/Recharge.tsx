import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { createAlipayRechargeForm, getRechargeOrder } from "@/services/billingApi";
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
  const [searchParams] = useSearchParams();
  const [pendingOutTradeNo, setPendingOutTradeNo] = useState<string | null>(null);

  useEffect(() => {
    const outTradeNo = searchParams.get("out_trade_no");
    if (!outTradeNo) return;
    setPendingOutTradeNo(outTradeNo);
    setNotice("已从支付宝返回，正在确认到账…");
  }, [searchParams]);

  useEffect(() => {
    if (!token || !pendingOutTradeNo) return;
    let stopped = false;
    let tries = 0;
    const timer = window.setInterval(async () => {
      if (stopped) return;
      tries += 1;
      try {
        const order = await getRechargeOrder(pendingOutTradeNo);
        if (order.status === "paid") {
          const me = await fetchMe(token);
          setUser(me);
          setNotice(`充值成功：+${order.points} 积分，当前余额 ${me.points_balance}`);
          setPendingOutTradeNo(null);
          stopped = true;
          window.clearInterval(timer);
        } else if (order.status === "closed") {
          setErr("订单已关闭或未支付");
          setPendingOutTradeNo(null);
          stopped = true;
          window.clearInterval(timer);
        } else if (tries >= 45) {
          setNotice("支付结果确认中，稍后可刷新页面查看余额是否到账。");
          setPendingOutTradeNo(null);
          stopped = true;
          window.clearInterval(timer);
        }
      } catch {
        if (tries >= 10) {
          setNotice("支付结果确认中，稍后可刷新页面查看余额是否到账。");
          setPendingOutTradeNo(null);
          stopped = true;
          window.clearInterval(timer);
        }
      }
    }, 2000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [token, pendingOutTradeNo, setUser]);

  async function pay(cny: number) {
    if (!token) return;
    setErr(null);
    setNotice(null);
    setBusy(true);
    try {
      const { out_trade_no, form_html, points } = await createAlipayRechargeForm(cny);
      const w = window.open("", "_blank", "noopener,noreferrer");
      if (!w) {
        throw new Error("浏览器拦截了新窗口，请允许弹窗后重试");
      }
      w.document.open();
      w.document.write(form_html);
      w.document.close();
      setPendingOutTradeNo(out_trade_no);
      setNotice(`已发起支付：${cny} 元（+${points} 积分），请在新窗口完成支付…`);
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
          <h1 className="text-2xl font-bold">积分充值</h1>
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
            <p className="text-sm text-muted-foreground">规则：1 元人民币 = 10 积分（支付宝电脑网站支付）</p>
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
                    立即充值
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
