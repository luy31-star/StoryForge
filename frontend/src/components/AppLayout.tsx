import { Link, Outlet, useNavigate } from "react-router-dom";
import { LogOut, Settings, Sparkles, Wallet } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/stores/authStore";

export function AppLayout() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const nav = useNavigate();

  return (
    <div className="min-h-screen bg-transparent">
      <header className="sticky top-0 z-20 px-4 pt-4 md:px-6">
        <div className="novel-container">
          <div className="glass-panel-subtle flex flex-col gap-3 px-4 py-3 md:flex-row md:items-center md:gap-4">
            <Link to="/" className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-primary/12 text-primary shadow-[inset_0_1px_0_rgba(255,255,255,0.45)]">
                <Sparkles className="size-4" />
              </div>
              <div>
                <p className="text-sm font-semibold tracking-tight text-foreground">
                  StoryForge
                </p>
                <p className="text-[11px] text-muted-foreground">
                  Creative workspace
                </p>
              </div>
            </Link>
            <nav className="flex flex-1 flex-wrap items-center gap-1 text-sm">
            <Button variant="ghost" size="sm" asChild>
              <Link to="/novels">小说书架</Link>
            </Button>
            {user?.is_admin ? (
              <>
                <Button variant="ghost" size="sm" asChild>
                  <Link to="/editor">工作流</Link>
                </Button>
                <Button variant="ghost" size="sm" asChild>
                  <Link to="/projects">项目</Link>
                </Button>
                <Button variant="ghost" size="sm" asChild>
                  <Link to="/admin">
                    <Sparkles className="mr-1 size-3.5" />
                    管理后台
                  </Link>
                </Button>
                <Button variant="ghost" size="sm" asChild>
                  <Link to="/settings">
                    <Settings className="mr-1 size-3.5" />
                    全局 LLM
                  </Link>
                </Button>
              </>
            ) : null}
            </nav>
            <div className="flex items-center gap-2 self-end md:self-auto">
              <div className="glass-chip hidden sm:inline-flex">
                积分
                <span className="font-medium text-foreground tabular-nums">
                  {user?.points_balance ?? 0}
                </span>
              </div>
              <Button variant="glass" size="sm" asChild>
                <Link to="/recharge">
                  <Wallet className="mr-1 size-3.5" />
                  充值
                </Link>
              </Button>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => {
                  logout();
                  nav("/login", { replace: true });
                }}
              >
                <LogOut className="size-3.5" />
              </Button>
            </div>
          </div>
        </div>
      </header>
      <Outlet />
    </div>
  );
}
