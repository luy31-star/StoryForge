import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { fetchMe, login, resetPassword, sendForgotPasswordOtp } from "@/services/authApi";
import { useAuthStore } from "@/stores/authStore";
import { Loader2 } from "lucide-react";

function parseApiError(error: unknown, fallback: string): string {
  if (!(error instanceof Error)) return fallback;
  try {
    const detail = JSON.parse(error.message);
    if (typeof detail?.detail === "string") return detail.detail;
    if (Array.isArray(detail?.detail)) return detail.detail[0]?.msg || fallback;
    return error.message || fallback;
  } catch {
    return error.message || fallback;
  }
}

export function Login() {
  const nav = useNavigate();
  const loc = useLocation() as { state?: { from?: string } };
  const setAuth = useAuthStore((s) => s.setAuth);
  const [mode, setMode] = useState<"login" | "reset">("login");
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [resetEmail, setResetEmail] = useState("");
  const [resetOtp, setResetOtp] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [otpBusy, setOtpBusy] = useState(false);
  const [countdown, setCountdown] = useState(0);

  useEffect(() => {
    if (countdown <= 0) return;
    const timer = setTimeout(() => setCountdown((v) => Math.max(0, v - 1)), 1000);
    return () => clearTimeout(timer);
  }, [countdown]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setInfo(null);
    setBusy(true);
    try {
      const { access_token } = await login(identifier.trim(), password);
      const me = await fetchMe(access_token);
      setAuth(access_token, me);
      nav(loc.state?.from || "/novels", { replace: true });
    } catch (e: unknown) {
      setErr(parseApiError(e, "登录失败，请检查账号密码"));
    } finally {
      setBusy(false);
    }
  }

  async function onSendResetOtp() {
    const email = resetEmail.trim().toLowerCase();
    if (!email || !email.includes("@")) {
      setErr("请输入有效邮箱地址");
      return;
    }
    setErr(null);
    setInfo(null);
    setOtpBusy(true);
    try {
      const res = await sendForgotPasswordOtp(email);
      setInfo(res.message || "如果邮箱已注册，验证码已发送");
      setCountdown(60);
    } catch (e: unknown) {
      setErr(parseApiError(e, "验证码发送失败，请稍后重试"));
    } finally {
      setOtpBusy(false);
    }
  }

  async function onResetPassword(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setInfo(null);
    setBusy(true);
    try {
      await resetPassword(resetEmail.trim().toLowerCase(), resetOtp.trim(), newPassword);
      setInfo("密码已重置，请使用新密码登录");
      setMode("login");
      setIdentifier(resetEmail.trim().toLowerCase());
      setPassword("");
      setResetOtp("");
      setNewPassword("");
    } catch (e: unknown) {
      setErr(parseApiError(e, "密码重置失败，请稍后重试"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-6">
      <Card className="w-full max-w-md border-border bg-card">
        <CardHeader>
          <CardTitle className="text-2xl">{mode === "login" ? "登录 StoryForge" : "找回密码"}</CardTitle>
        </CardHeader>
        <CardContent>
          {mode === "login" ? (
            <form onSubmit={onSubmit} className="space-y-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">用户名 或 邮箱</label>
                <input
                  className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                  value={identifier}
                  onChange={(e) => setIdentifier(e.target.value)}
                  placeholder="请输入用户名或注册邮箱"
                  required
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">密码</label>
                <input
                  type="password"
                  className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  required
                />
              </div>
              {err ? <p className="text-sm text-destructive whitespace-pre-wrap">{err}</p> : null}
              {info ? <p className="text-sm text-emerald-600 whitespace-pre-wrap">{info}</p> : null}
              <Button type="submit" className="w-full" disabled={busy}>
                {busy ? "登录中…" : "登录"}
              </Button>
              <button
                type="button"
                className="w-full text-sm text-primary underline"
                onClick={() => {
                  setMode("reset");
                  setErr(null);
                  setInfo(null);
                }}
              >
                忘记密码？
              </button>
              <p className="text-center text-sm text-muted-foreground">
                没有账号？{" "}
                <Link to="/register" className="text-primary underline">
                  注册
                </Link>
              </p>
            </form>
          ) : (
            <form onSubmit={onResetPassword} className="space-y-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">注册邮箱</label>
                <input
                  type="email"
                  className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                  value={resetEmail}
                  onChange={(e) => setResetEmail(e.target.value)}
                  autoComplete="email"
                  placeholder="请输入注册邮箱"
                  required
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">验证码</label>
                <div className="flex gap-2">
                  <input
                    className="h-10 flex-1 rounded-md border border-input bg-background px-3 text-sm"
                    value={resetOtp}
                    onChange={(e) => setResetOtp(e.target.value)}
                    placeholder="6 位数字"
                    maxLength={6}
                    required
                  />
                  <Button
                    type="button"
                    variant="outline"
                    className="w-32"
                    onClick={onSendResetOtp}
                    disabled={otpBusy || countdown > 0}
                  >
                    {otpBusy ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : countdown > 0 ? (
                      `${countdown}s`
                    ) : (
                      "获取验证码"
                    )}
                  </Button>
                </div>
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">新密码（至少 6 位）</label>
                <input
                  type="password"
                  className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  autoComplete="new-password"
                  minLength={6}
                  required
                />
              </div>
              {err ? <p className="text-sm text-destructive whitespace-pre-wrap">{err}</p> : null}
              {info ? <p className="text-sm text-emerald-600 whitespace-pre-wrap">{info}</p> : null}
              <Button type="submit" className="w-full" disabled={busy || otpBusy}>
                {busy ? "重置中…" : "确认重置密码"}
              </Button>
              <button
                type="button"
                className="w-full text-sm text-muted-foreground underline"
                onClick={() => {
                  setMode("login");
                  setErr(null);
                  setInfo(null);
                }}
              >
                返回登录
              </button>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
