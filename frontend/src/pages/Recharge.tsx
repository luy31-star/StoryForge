import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowRight, CheckCircle2, Loader2, ShieldCheck, Sparkles, Wallet } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  createAlipayRechargeForm,
  getRechargeConfig,
  refreshRechargeOrder,
  type RechargeConfig,
  type RechargePackage,
} from "@/services/billingApi";
import { refreshMeSilently } from "@/services/userSync";
import { useAuthStore } from "@/stores/authStore";

type OrderStatus = {
  out_trade_no: string;
  amount_cny: number;
  points: number;
  status: string;
  trade_status: string;
  created_at: string;
  paid_at?: string | null;
};

const STATUS_COPY: Record<
  string,
  {
    label: string;
    tone: "default" | "secondary" | "destructive" | "outline";
    description: string;
  }
> = {
  paid: {
    label: "已到账",
    tone: "default",
    description: "支付宝已确认收款，积分已发放到当前账号。",
  },
  pending: {
    label: "支付处理中",
    tone: "secondary",
    description: "正在等待支付宝异步通知或主动查单结果，请稍候。",
  },
  created: {
    label: "待支付",
    tone: "outline",
    description: "订单已创建，尚未完成付款。",
  },
  closed: {
    label: "已关闭",
    tone: "destructive",
    description: "订单已关闭，如需充值请重新发起支付。",
  },
};

function launchAlipayForm(formHtml: string) {
  document.open();
  document.write(formHtml);
  document.close();
}

function formatPrice(amountCny: number) {
  return `¥${amountCny}`;
}

function formatPoints(points: number) {
  return `${points} 积分`;
}

function statusMeta(status: string) {
  return (
    STATUS_COPY[status] || {
      label: status || "处理中",
      tone: "outline" as const,
      description: "订单状态已更新，请稍后刷新。",
    }
  );
}

export function Recharge() {
  const user = useAuthStore((s) => s.user);
  const [searchParams, setSearchParams] = useSearchParams();

  const [config, setConfig] = useState<RechargeConfig | null>(null);
  const [selectedPackageId, setSelectedPackageId] = useState<string>("");
  const [customPoints, setCustomPoints] = useState<string>("");
  const [mode, setMode] = useState<"package" | "custom">("package");
  const [submitting, setSubmitting] = useState(false);
  const [loadingConfig, setLoadingConfig] = useState(true);
  const [configError, setConfigError] = useState<string>("");
  const [submitError, setSubmitError] = useState<string>("");
  const [order, setOrder] = useState<OrderStatus | null>(null);
  const [orderMessage, setOrderMessage] = useState<string>("");
  const [checkingOrder, setCheckingOrder] = useState(false);

  const currentOrderNo = searchParams.get("sf_order") || "";

  useEffect(() => {
    let cancelled = false;
    setLoadingConfig(true);
    getRechargeConfig()
      .then((data) => {
        if (cancelled) return;
        setConfig(data);
        setSelectedPackageId((prev) => prev || data.packages[0]?.id || "");
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : "充值配置加载失败";
        setConfigError(message);
      })
      .finally(() => {
        if (!cancelled) setLoadingConfig(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!currentOrderNo) return;
    let cancelled = false;
    let timer: number | undefined;
    let attempts = 0;

    const poll = async () => {
      setCheckingOrder(true);
      try {
        const nextOrder = await refreshRechargeOrder(currentOrderNo);
        if (cancelled) return;
        setOrder(nextOrder);
        const meta = statusMeta(nextOrder.status);
        setOrderMessage(meta.description);
        if (nextOrder.status === "paid") {
          await refreshMeSilently();
          const nextParams = new URLSearchParams(window.location.search);
          nextParams.delete("sf_order");
          setSearchParams(nextParams, { replace: true });
          return;
        }
        if ((nextOrder.status === "created" || nextOrder.status === "pending") && attempts < 9) {
          attempts += 1;
          timer = window.setTimeout(poll, 2500);
          return;
        }
      } catch (error: unknown) {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : "订单查询失败";
        setOrderMessage(message);
      } finally {
        if (!cancelled) setCheckingOrder(false);
      }
    };

    poll();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [currentOrderNo, setSearchParams]);

  const selectedPackage = useMemo<RechargePackage | null>(() => {
    if (!config) return null;
    return config.packages.find((item) => item.id === selectedPackageId) || null;
  }, [config, selectedPackageId]);

  const customPointsNumber = Number(customPoints || 0);

  const customAmountPreview = useMemo(() => {
    if (!config || Number.isNaN(customPointsNumber) || customPointsNumber <= 0) return null;
    if (customPointsNumber % config.custom_points_step !== 0) return null;
    return customPointsNumber / config.base_points_per_cny;
  }, [config, customPointsNumber]);

  const summary = useMemo(() => {
    if (!config) return null;
    if (mode === "package") {
      if (!selectedPackage) return null;
      return {
        points: selectedPackage.points,
        amount_cny: selectedPackage.amount_cny,
        title: `${selectedPackage.title} · ${selectedPackage.badge}`,
      };
    }

    if (!customAmountPreview || customPointsNumber < config.min_custom_points) return null;
    return {
      points: customPointsNumber,
      amount_cny: customAmountPreview,
      title: "自定义充值",
    };
  }, [config, customAmountPreview, customPointsNumber, mode, selectedPackage]);

  const handleSubmit = async () => {
    if (!config) return;
    setSubmitError("");

    try {
      setSubmitting(true);
      if (mode === "package") {
        if (!selectedPackageId) {
          throw new Error("请选择充值套餐");
        }
        const created = await createAlipayRechargeForm({ package_id: selectedPackageId });
        launchAlipayForm(created.form_html);
        return;
      }

      if (!customPoints.trim()) {
        throw new Error("请输入自定义积分");
      }
      if (!Number.isFinite(customPointsNumber)) {
        throw new Error("自定义积分格式不正确");
      }
      if (customPointsNumber < config.min_custom_points) {
        throw new Error(`自定义充值最少 ${config.min_custom_points} 积分`);
      }
      if (customPointsNumber % config.custom_points_step !== 0) {
        throw new Error(`自定义积分需按 ${config.custom_points_step} 积分递增`);
      }

      const created = await createAlipayRechargeForm({ custom_points: customPointsNumber });
      launchAlipayForm(created.form_html);
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : "创建充值订单失败";
      setSubmitError(message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-background px-4 py-6 md:px-8">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
        <section className="signal-surface story-mesh story-shimmer overflow-hidden px-6 py-7 md:px-8">
          <div className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
            <div className="space-y-3">
              <Badge variant="secondary" className="w-fit gap-2 rounded-full px-3 py-1 text-[11px] uppercase tracking-[0.18em]">
                <Sparkles className="h-3.5 w-3.5" />
                支付宝电脑支付
              </Badge>
              <div>
                <h1 className="text-3xl font-semibold tracking-tight text-foreground md:text-4xl">购买积分</h1>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground md:text-base">
                  直接跳转支付宝付款，充值成功后积分自动发放到当前登录账号。
                </p>
              </div>
            </div>
            <div className="grid gap-3 md:min-w-[290px]">
              <div className="rounded-[1.4rem] border border-white/20 bg-white/70 px-5 py-4 shadow-[0_16px_40px_rgba(15,23,42,0.08)] backdrop-blur-xl dark:bg-white/[0.06]">
                <div className="text-xs uppercase tracking-[0.22em] text-muted-foreground">当前余额</div>
                <div className="mt-2 flex items-end gap-2">
                  <span className="text-4xl font-semibold tabular-nums text-foreground">
                    {user?.points_balance ?? 0}
                  </span>
                  <span className="pb-1 text-sm text-muted-foreground">积分</span>
                </div>
              </div>
              <Button variant="ghost" size="sm" asChild>
                <Link to="/novels">返回工作台</Link>
              </Button>
            </div>
          </div>
        </section>

        <div className="grid gap-6 xl:grid-cols-[1.45fr_0.9fr]">
          <Card className="overflow-hidden">
            <CardHeader className="border-b border-border/60">
              <CardTitle>选择充值方案</CardTitle>
              <CardDescription>
                固定套餐直接下单，自定义充值最低 {config?.min_custom_points ?? 50} 积分。
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6 p-5">
              <div className="grid gap-3 md:grid-cols-3">
                {(loadingConfig ? [] : config?.packages || []).map((pkg) => {
                  const active = mode === "package" && selectedPackageId === pkg.id;
                  return (
                    <button
                      key={pkg.id}
                      type="button"
                      onClick={() => {
                        setMode("package");
                        setSelectedPackageId(pkg.id);
                      }}
                      className={`list-card text-left ${active ? "border-primary/50 bg-primary/[0.08] shadow-[0_18px_42px_rgba(59,130,246,0.14)]" : ""} p-4`}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <Badge variant={active ? "default" : "outline"} className="rounded-full px-2.5 py-1">
                          {pkg.badge || "套餐"}
                        </Badge>
                        <div className="text-sm font-semibold text-foreground">{formatPrice(pkg.amount_cny)}</div>
                      </div>
                      <div className="mt-4 text-2xl font-semibold tracking-tight text-foreground">{pkg.points}</div>
                      <div className="mt-1 text-sm text-muted-foreground">积分</div>
                      <div className="mt-4 text-sm font-medium text-foreground">{pkg.title}</div>
                      <div className="mt-1 text-xs leading-5 text-muted-foreground">{pkg.description}</div>
                    </button>
                  );
                })}
              </div>

              <div className="rounded-[1.5rem] border border-border/70 bg-background/60 p-5 shadow-[inset_0_1px_0_rgba(255,255,255,0.3)]">
                <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                  <div>
                    <div className="text-base font-semibold text-foreground">自定义积分</div>
                    <div className="mt-1 text-sm text-muted-foreground">
                      最低 {config?.min_custom_points ?? 50} 积分，按 {config?.custom_points_step ?? 10} 积分步进，基础单价{" "}
                      {config?.base_points_per_cny ?? 10} 积分 / 元。
                    </div>
                  </div>
                  <Button
                    type="button"
                    variant={mode === "custom" ? "default" : "outline"}
                    onClick={() => setMode("custom")}
                  >
                    使用自定义充值
                  </Button>
                </div>

                <div className="mt-4 grid gap-3 md:grid-cols-[1fr_auto]">
                  <Input
                    inputMode="numeric"
                    placeholder={`至少 ${config?.min_custom_points ?? 50} 积分`}
                    value={customPoints}
                    onChange={(e) => {
                      setMode("custom");
                      setCustomPoints(e.target.value.replace(/[^\d]/g, ""));
                    }}
                    className="h-12 rounded-2xl border-border/70 bg-background/80 px-4 text-base"
                  />
                  <div className="flex items-center rounded-2xl border border-border/70 bg-secondary/40 px-4 text-sm text-muted-foreground">
                    {customAmountPreview ? `应付 ${formatPrice(customAmountPreview)}` : "输入后自动换算"}
                  </div>
                </div>
              </div>

              {submitError ? (
                <div className="rounded-2xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
                  {submitError}
                </div>
              ) : null}

              {configError ? (
                <div className="rounded-2xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
                  {configError}
                </div>
              ) : null}

              <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div className="text-sm text-muted-foreground">
                  点击“去支付宝支付”后会离开当前页，支付完成会自动返回此页面并刷新状态。
                </div>
                <Button
                  type="button"
                  size="lg"
                  disabled={loadingConfig || submitting || !!configError}
                  onClick={handleSubmit}
                >
                  {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wallet className="h-4 w-4" />}
                  去支付宝支付
                </Button>
              </div>
            </CardContent>
          </Card>

          <div className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>本次订单摘要</CardTitle>
                <CardDescription>下单前确认积分和金额。</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="rounded-[1.4rem] border border-border/70 bg-background/55 p-4">
                  <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">充值方案</div>
                  <div className="mt-2 text-lg font-semibold text-foreground">{summary?.title || "请选择方案"}</div>
                  <div className="mt-4 flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">到账积分</span>
                    <span className="font-semibold text-foreground">{summary ? formatPoints(summary.points) : "--"}</span>
                  </div>
                  <div className="mt-2 flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">支付金额</span>
                    <span className="font-semibold text-foreground">
                      {summary ? formatPrice(summary.amount_cny) : "--"}
                    </span>
                  </div>
                </div>
                <div className="rounded-[1.4rem] border border-border/70 bg-secondary/35 p-4 text-sm text-muted-foreground">
                  固定套餐直接享受优惠，自定义充值按基础单价换算。支付成功后积分只会记入当前登录账户。
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>支付状态</CardTitle>
                <CardDescription>从支付宝返回后，这里会自动展示订单结果。</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {order ? (
                  <>
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="text-sm text-muted-foreground">订单号</div>
                        <div className="mt-1 break-all text-sm font-medium text-foreground">{order.out_trade_no}</div>
                      </div>
                      <Badge variant={statusMeta(order.status).tone}>{statusMeta(order.status).label}</Badge>
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <div className="rounded-2xl border border-border/70 bg-background/55 p-4">
                        <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">订单金额</div>
                        <div className="mt-2 text-2xl font-semibold text-foreground">{formatPrice(order.amount_cny)}</div>
                      </div>
                      <div className="rounded-2xl border border-border/70 bg-background/55 p-4">
                        <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">订单积分</div>
                        <div className="mt-2 text-2xl font-semibold text-foreground">{order.points}</div>
                      </div>
                    </div>
                    <div className="rounded-2xl border border-border/70 bg-secondary/35 px-4 py-3 text-sm text-muted-foreground">
                      {orderMessage || statusMeta(order.status).description}
                    </div>
                    <div className="flex gap-3">
                      <Button
                        type="button"
                        variant="outline"
                        disabled={checkingOrder}
                        onClick={async () => {
                          if (!order.out_trade_no) return;
                          setCheckingOrder(true);
                          try {
                            const nextOrder = await refreshRechargeOrder(order.out_trade_no);
                            setOrder(nextOrder);
                            setOrderMessage(statusMeta(nextOrder.status).description);
                            if (nextOrder.status === "paid") {
                              await refreshMeSilently();
                            }
                          } catch (error: unknown) {
                            const message = error instanceof Error ? error.message : "订单查询失败";
                            setOrderMessage(message);
                          } finally {
                            setCheckingOrder(false);
                          }
                        }}
                      >
                        {checkingOrder ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                        刷新状态
                      </Button>
                    </div>
                  </>
                ) : (
                  <div className="rounded-[1.4rem] border border-dashed border-border/80 bg-background/45 p-5 text-sm leading-6 text-muted-foreground">
                    还没有待查询的订单。完成支付宝付款后，会自动回到当前页面并带上订单号进行状态查询。
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>安全说明</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm text-muted-foreground">
                <div className="flex items-start gap-3 rounded-2xl border border-border/70 bg-background/55 p-4">
                  <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                  <span>积分到账以支付宝异步通知和服务端查单结果为准，不依赖前端本地状态。</span>
                </div>
                <div className="flex items-start gap-3 rounded-2xl border border-border/70 bg-background/55 p-4">
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                  <span>支付完成后如果结果未立即刷新，停留当前页数秒或点击“刷新状态”即可。</span>
                </div>
                <div className="flex items-start gap-3 rounded-2xl border border-border/70 bg-background/55 p-4">
                  <ArrowRight className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                  <span>支付宝配置中的异步通知地址必须指向后端公网地址，授权回调地址需能回到前端 `/recharge` 页面。</span>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}
