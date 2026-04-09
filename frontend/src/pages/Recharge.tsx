import { Link } from "react-router-dom";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuthStore } from "@/stores/authStore";
import { useMemo, useState } from "react";

export function Recharge() {
  const user = useAuthStore((s) => s.user);
  const preferredQrUrl = useMemo(() => {
    const env = import.meta.env.VITE_POINTS_QR_URL as string | undefined;
    return env || "/wechat-qr.jpeg";
  }, []);
  const [qrUrl, setQrUrl] = useState(preferredQrUrl);

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="mx-auto max-w-lg space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">积分</h1>
          <Button className={buttonVariants({ variant: "ghost", size: "sm" })} asChild>
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
            <p className="text-sm text-muted-foreground">
              充值入口并未开放；如需增加积分，请联系管理员。
            </p>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="rounded-xl border border-border/60 bg-card/40 p-4">
              <div className="text-sm font-semibold text-foreground">联系管理员 / 加入微信群</div>
              <div className="mt-3 flex items-center justify-center">
                <img
                  src={qrUrl}
                  alt="联系管理员二维码"
                  className="h-72 w-72 rounded-lg border border-border bg-white object-contain"
                  onError={() => {
                    if (qrUrl !== "/wechat-qr.svg") setQrUrl("/wechat-qr.svg");
                  }}
                />
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
