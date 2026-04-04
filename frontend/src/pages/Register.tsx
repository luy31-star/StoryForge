import { useState, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { fetchMe, register as registerApi, sendOtp } from "@/services/authApi";
import { useAuthStore } from "@/stores/authStore";

export function Register() {
  const nav = useNavigate();
  const setAuth = useAuthStore((s) => s.setAuth);
  const [email, setEmail] = useState("");
  const [otp, setOtp] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [otpBusy, setOtpBusy] = useState(false);
  const [countdown, setCountdown] = useState(0);

  useEffect(() => {
    if (countdown > 0) {
      const timer = setTimeout(() => setCountdown(countdown - 1), 1000);
      return () => clearTimeout(timer);
    }
  }, [countdown]);

  async function onSendOtp() {
    if (!email || !email.includes("@")) {
      setErr("请输入有效的邮箱地址");
      return;
    }
    setErr(null);
    setOtpBusy(true);
    try {
      await sendOtp(email.trim());
      setCountdown(60);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "发送验证码失败");
    } finally {
      setOtpBusy(false);
    }
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      const { access_token } = await registerApi(email.trim(), otp.trim(), password);
      const me = await fetchMe(access_token);
      setAuth(access_token, me);
      nav("/novels", { replace: true });
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "注册失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-6">
      <Card className="w-full max-w-md border-border/60 bg-card/80">
        <CardHeader>
          <CardTitle className="text-2xl">注册 StoryForge</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">电子邮箱</label>
              <input
                type="email"
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                required
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">验证码</label>
              <div className="flex gap-2">
                <input
                  className="h-10 flex-1 rounded-md border border-input bg-background px-3 text-sm"
                  value={otp}
                  onChange={(e) => setOtp(e.target.value)}
                  placeholder="6 位数字"
                  maxLength={6}
                  required
                />
                <Button
                  type="button"
                  variant="outline"
                  className="w-32"
                  onClick={onSendOtp}
                  disabled={otpBusy || countdown > 0}
                >
                  {countdown > 0 ? `${countdown}s` : "获取验证码"}
                </Button>
              </div>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">设置密码（至少 6 位）</label>
              <input
                type="password"
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
                minLength={6}
                required
              />
            </div>
            {err ? (
              <p className="text-sm text-destructive whitespace-pre-wrap">{err}</p>
            ) : null}
            <Button type="submit" className="w-full" disabled={busy}>
              {busy ? "提交中…" : "注册并登录"}
            </Button>
            <p className="text-center text-sm text-muted-foreground">
              已有账号？{" "}
              <Link to="/login" className="text-primary underline">
                登录
              </Link>
            </p>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
