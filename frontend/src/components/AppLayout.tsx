import { Link, Outlet, useNavigate } from "react-router-dom";
import { LogOut, Settings, Sparkles, Wallet, User, Sun, Moon, Monitor, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/stores/authStore";
import { useEffect, useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { getLlmConfig, setLlmConfig } from "@/services/novelApi";
import { listPublicModelPrices, type ModelPriceRow } from "@/services/billingApi";

export function AppLayout() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const nav = useNavigate();
  const isAdmin = user?.is_admin;

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark" | "system">(
    (localStorage.getItem("vocalflow-theme") as "light" | "dark" | "system") || "system"
  );
  const [llmCfg, setLlmCfg] = useState<{
    provider: string;
    model: string;
    novel_web_search?: boolean;
    novel_generate_web_search?: boolean;
    novel_volume_plan_web_search?: boolean;
    novel_memory_refresh_web_search?: boolean;
    novel_inspiration_web_search?: boolean;
  } | null>(null);
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [availableModels, setAvailableModels] = useState<ModelPriceRow[]>([]);

  useEffect(() => {
    const root = window.document.documentElement;
    if (theme === "system") {
      const systemTheme = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
      root.classList.remove("light", "dark");
      root.classList.add(systemTheme);
    } else {
      root.classList.remove("light", "dark");
      root.classList.add(theme);
    }
    localStorage.setItem("vocalflow-theme", theme);
  }, [theme]);

  useEffect(() => {
    if (settingsOpen) {
      setSettingsBusy(true);
      getLlmConfig()
        .then(setLlmCfg)
        .catch(console.error)
        .finally(() => setSettingsBusy(false));

      listPublicModelPrices()
        .then(setAvailableModels)
        .catch(console.error);
    }
  }, [settingsOpen]);

  async function handleSaveSettings(payload: NonNullable<typeof llmCfg>) {
    setSettingsBusy(true);
    try {
      await setLlmConfig(payload);
    } catch (e: any) {
      console.error(e);
      alert(e.message);
    } finally {
      setSettingsBusy(false);
    }
  }

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
              <div className="flex h-9 items-center gap-2 rounded-full border border-border/40 bg-card/40 pl-3 pr-1 shadow-sm backdrop-blur-xl ml-2">
                <div className="flex items-center gap-2 border-r border-border/40 pr-3">
                  <div className="flex h-5 w-5 items-center justify-center rounded-full bg-primary/10 text-primary">
                    <User className="h-3 w-3" />
                  </div>
                  <span className="text-xs font-medium text-muted-foreground">
                    {user?.is_admin ? "管理员" : "用户"}
                  </span>
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 rounded-full text-muted-foreground hover:bg-primary/10 hover:text-primary"
                  onClick={() => setSettingsOpen(true)}
                >
                  <Settings className="h-4 w-4" />
                </Button>
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="ml-2"
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

      <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}>
        <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Settings className="h-5 w-5" />
              用户设置
            </DialogTitle>
            <DialogDescription>
              配置全局大模型参数及界面风格。
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-6 py-4">
            <section className="space-y-3">
              <Label className="text-sm font-bold uppercase tracking-wider text-muted-foreground">
                界面风格
              </Label>
              <div className="grid grid-cols-3 gap-3">
                {[
                  { id: "light", label: "浅色", icon: Sun },
                  { id: "dark", label: "深色", icon: Moon },
                  { id: "system", label: "跟随系统", icon: Monitor },
                ].map((item) => (
                  <button
                    key={item.id}
                    onClick={() => setTheme(item.id as "dark" | "light" | "system")}
                    className={`relative flex flex-col items-center justify-center gap-2 rounded-2xl border p-4 transition-all duration-300 ${
                      theme === item.id
                        ? "border-primary/35 bg-primary/8 text-primary shadow-[0_16px_36px_hsl(var(--primary)/0.12)]"
                        : "border-border/70 bg-background/40 text-muted-foreground hover:border-muted-foreground/30 hover:bg-background/60"
                    }`}
                  >
                    <item.icon className="h-5 w-5" />
                    <span className="text-xs font-medium">{item.label}</span>
                    {theme === item.id && (
                      <div className="absolute top-1 right-1">
                        <Check className="h-3 w-3" />
                      </div>
                    )}
                  </button>
                ))}
              </div>
            </section>

            <section className="space-y-4 pt-2 border-t border-border">
              <Label className="text-sm font-bold uppercase tracking-wider text-muted-foreground">
                大模型配置
              </Label>
              {!isAdmin ? (
                <p className="text-xs text-muted-foreground">
                  全局大模型与联网开关仅<strong>管理员</strong>可修改（侧边栏「全局 LLM」）。
                </p>
              ) : null}

              <div className={`grid gap-4 ${isAdmin ? 'sm:grid-cols-2' : 'sm:grid-cols-1'}`}>
                {isAdmin ? (
                  <div className="space-y-2">
                    <Label>Provider</Label>
                    <select
                      value={llmCfg?.provider || "ai302"}
                      onChange={(e) => setLlmCfg(prev => prev ? { ...prev, provider: e.target.value } : null)}
                      className="field-shell h-10 w-full"
                      disabled={settingsBusy || !isAdmin}
                    >
                      <option value="ai302">302AI</option>
                      <option value="custom">自建代理</option>
                    </select>
                  </div>
                ) : null}

                <div className="space-y-2">
                  <Label>模型名称</Label>
                  <select
                    value={llmCfg?.model || ""}
                    onChange={(e) => setLlmCfg(prev => prev ? { ...prev, model: e.target.value } : null)}
                    className="field-shell h-10 w-full"
                    disabled={settingsBusy || !isAdmin}
                  >
                    <option value="" disabled>请选择模型</option>
                    {availableModels.map(m => (
                      <option key={m.id} value={m.model_id}>
                        {m.display_name || m.model_id}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="glass-panel-subtle space-y-3 p-4">
                <Label className="text-xs font-semibold text-muted-foreground italic">联网搜索 (Web Search)</Label>
                <div className="grid gap-3 pt-1">
                  {[
                    { id: "novel_generate_web_search" as const, label: "章节续写" },
                    { id: "novel_volume_plan_web_search" as const, label: "卷章计划" },
                    { id: "novel_memory_refresh_web_search" as const, label: "记忆刷新" },
                    { id: "novel_inspiration_web_search" as const, label: "灵感对话" },
                    { id: "novel_web_search" as const, label: "其他(助手/框架)" },
                  ].map((field) => (
                    <label key={field.id} className="flex items-center justify-between group cursor-pointer">
                      <span className="text-sm group-hover:text-foreground transition-colors">{field.label}</span>
                      <input
                        type="checkbox"
                        checked={Boolean(llmCfg?.[field.id])}
                        onChange={(e) => setLlmCfg(prev => prev ? { ...prev, [field.id]: e.target.checked } : null)}
                        className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"
                        disabled={settingsBusy || !isAdmin}
                      />
                    </label>
                  ))}
                </div>
              </div>
            </section>
          </div>

          <DialogFooter className="gap-2 sm:gap-0">
            <Button
              variant="outline"
              onClick={() => setSettingsOpen(false)}
              disabled={settingsBusy}
            >
              取消
            </Button>
            <Button
              onClick={() => {
                if (!isAdmin) {
                  setSettingsOpen(false);
                  return;
                }
                if (llmCfg) {
                  handleSaveSettings(llmCfg).then(() => setSettingsOpen(false));
                } else {
                  setSettingsOpen(false);
                }
              }}
              disabled={settingsBusy}
            >
              {settingsBusy ? "保存中..." : isAdmin ? "保存配置" : "关闭"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
