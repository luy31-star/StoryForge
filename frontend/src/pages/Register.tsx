import { useState, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { fetchMe, getRegistrationMode, register as registerApi, sendOtp } from "@/services/authApi";
import { useAuthStore } from "@/stores/authStore";
import { Loader2 } from "lucide-react";

const USERNAME_PATTERN = /^[A-Za-z0-9]+$/;

export function Register() {
  const nav = useNavigate();
  const setAuth = useAuthStore((s) => s.setAuth);
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [otp, setOtp] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [otpBusy, setOtpBusy] = useState(false);
  const [countdown, setCountdown] = useState(0);
  const [inviteOnly, setInviteOnly] = useState(true);

  useEffect(() => {
    let cancelled = false;
    getRegistrationMode()
      .then((r) => {
        if (!cancelled) setInviteOnly(Boolean(r.invite_only));
      })
      .catch(() => {
        /* ignore */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let timer: NodeJS.Timeout;
    if (countdown > 0) {
      timer = setTimeout(() => setCountdown(countdown - 1), 1000);
    }
    return () => {
      if (timer) clearTimeout(timer);
    };
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
      const msg = e instanceof Error ? e.message : "发送验证码失败";
      setErr(msg);
    } finally {
      setOtpBusy(false);
    }
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    const normalizedUsername = username.trim();
    if (!USERNAME_PATTERN.test(normalizedUsername)) {
      setErr("用户名只允许输入英文字母和数字");
      return;
    }
    setBusy(true);
    try {
      const { access_token } = await registerApi(
        email.trim(),
        normalizedUsername,
        inviteCode.trim(),
        otp.trim(),
        password
      );
      const me = await fetchMe(access_token);
      setAuth(access_token, me);
      nav("/novels", { replace: true });
    } catch (e: unknown) {
      let msg = "注册失败，请稍后再试";
      if (e instanceof Error) {
        try {
          const detail = JSON.parse(e.message);
          if (detail.detail && Array.isArray(detail.detail)) {
            const firstErr = detail.detail[0];
            if (firstErr.type === "string_too_short" && firstErr.loc.includes("otp")) {
              msg = "验证码必须是 6 位数字哦";
            } else if (firstErr.type === "string_too_short" && firstErr.loc.includes("invite_code")) {
              msg = "请输入邀请码后再注册";
            } else if (firstErr.type === "string_too_short" && firstErr.loc.includes("password")) {
              msg = "密码长度至少需要 6 位";
            } else if (firstErr.type === "string_too_short" && firstErr.loc.includes("username")) {
              msg = "用户名至少需要 2 个字符";
            } else if (firstErr.type === "value_error" && firstErr.msg.includes("email")) {
              msg = "邮箱格式不太对，检查一下吧";
            } else {
              msg = firstErr.msg;
            }
          } else {
            msg = e.message;
          }
        } catch {
          msg = e.message;
        }
      }
      setErr(msg);
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
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                placeholder="example@163.com"
                required
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">用户名</label>
              <input
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
                value={username}
                onChange={(e) => {
                  const next = e.target.value.replace(/[^A-Za-z0-9]/g, "");
                  setUsername(next);
                }}
                autoComplete="username"
                placeholder="仅限英文和数字"
                minLength={2}
                maxLength={64}
                required
              />
              <p className="text-xs text-muted-foreground">用户名只允许英文字母和数字。</p>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">邀请码</label>
              <input
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
                value={inviteCode}
                onChange={(e) => setInviteCode(e.target.value)}
                placeholder={inviteOnly ? "请输入管理员发放的邀请码" : "可选：管理员开启邀请码时才需要"}
                minLength={4}
                maxLength={64}
                required={inviteOnly}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">验证码</label>
              <div className="flex gap-2">
                <input
                  className="h-10 flex-1 rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
                  value={otp}
                  onChange={(e) => setOtp(e.target.value)}
                  placeholder="6 位数字"
                  maxLength={6}
                  required
                />
                <Button
                  type="button"
                  variant="outline"
                  className="w-32 transition-all"
                  onClick={onSendOtp}
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
              <label className="text-sm font-medium">设置密码（至少 6 位）</label>
              <input
                type="password"
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
                minLength={6}
                placeholder="请设置您的登录密码"
                required
              />
            </div>
            {err ? (
              <div className="bg-destructive/10 border border-destructive/20 text-destructive text-xs p-3 rounded-md animate-in fade-in zoom-in duration-200">
                {err}
              </div>
            ) : null}
            <Button type="submit" className="w-full" disabled={busy || otpBusy}>
              {busy ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  提交中…
                </>
              ) : (
                "注册并登录"
              )}
            </Button>
            <p className="text-center text-sm text-muted-foreground">
              已有账号？{" "}
              <Link to="/login" className="text-primary hover:underline font-medium">
                立即登录
              </Link>
            </p>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
