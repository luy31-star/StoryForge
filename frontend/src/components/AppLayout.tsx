import { Link, Outlet, useNavigate } from "react-router-dom";
import { LogOut, Settings, Shield, User, Sun, Moon, Monitor, Check, HelpCircle, Menu } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/stores/authStore";
import { useEffect, useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { getLlmConfig, setLlmConfig } from "@/services/novelApi";
import { listPublicModelPrices, type ModelPriceRow } from "@/services/billingApi";
import { ModelPriceSelect } from "@/components/ModelPriceSelect";
import { useLlmSettingsGateStore } from "@/stores/llmSettingsGateStore";

export function AppLayout() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const nav = useNavigate();

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark" | "system">(
    (localStorage.getItem("vocalflow-theme") as "light" | "dark" | "system") || "system"
  );
  const [llmCfg, setLlmCfg] = useState<{
    provider: string;
    model: string;
    has_explicit_model?: boolean;
    novel_web_search?: boolean;
    novel_generate_web_search?: boolean;
    novel_volume_plan_web_search?: boolean;
    novel_memory_refresh_web_search?: boolean;
    novel_inspiration_web_search?: boolean;
  } | null>(null);
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [availableModels, setAvailableModels] = useState<ModelPriceRow[]>([]);
  const [settingsGateHint, setSettingsGateHint] = useState<string | null>(null);
  const gateTick = useLlmSettingsGateStore((s) => s.gateTick);
  const gateReason = useLlmSettingsGateStore((s) => s.reason);

  useEffect(() => {
    if (gateTick === 0) return;
    setSettingsGateHint(gateReason);
    setSettingsOpen(true);
  }, [gateTick, gateReason]);

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

  useEffect(() => {
    if (!settingsOpen || !settingsGateHint) return;
    const t = window.setTimeout(() => {
      document.getElementById("settings-llm-section")?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }, 80);
    return () => window.clearTimeout(t);
  }, [settingsOpen, settingsGateHint]);

  /** 后端返回的 model 若与当前计价列表不一致，对齐为列表首项（与后端 resolve 一致） */
  useEffect(() => {
    if (!settingsOpen || !llmCfg || availableModels.length === 0) return;
    const ids = new Set(availableModels.map((m) => m.model_id));
    if (!llmCfg.model || !ids.has(llmCfg.model)) {
      const first = availableModels[0].model_id;
      setLlmCfg((prev) => (prev && prev.model !== first ? { ...prev, model: first } : prev));
    }
  }, [settingsOpen, availableModels, llmCfg?.model]);

  async function handleSaveSettings(payload: NonNullable<typeof llmCfg>) {
    setSettingsBusy(true);
    try {
      const saved = await setLlmConfig(payload);
      setLlmCfg(saved);
    } catch (e: unknown) {
      console.error(e);
      alert(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSettingsBusy(false);
    }
  }

  const navItems = [
    { to: "/novels", label: "小说书架" },
    { to: "/tasks", label: "我的任务" },
    { to: "/writing-styles", label: "文风管理" },
    ...(user?.is_admin
      ? [
          { to: "/editor", label: "工作流" },
          { to: "/projects", label: "项目" },
          { to: "/admin", label: "管理后台", icon: Shield },
        ]
      : []),
  ];

  return (
    <div className="min-h-screen bg-transparent">
      <header className="sticky top-0 z-20 px-4 pt-4 md:px-6">
        <div className="novel-container">
          <div className="glass-panel-subtle px-4 py-3">
            <div className="flex items-center justify-between gap-3">
              <Link to="/" className="min-w-0 flex items-center gap-3">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-primary/12 text-primary shadow-[inset_0_1px_0_rgba(255,255,255,0.45)]">
                  <img src="/favicon.svg" className="h-5 w-5" alt="" aria-hidden="true" />
                </div>
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold tracking-tight text-foreground">
                    StoryForge
                  </p>
                  <p className="truncate text-[11px] text-muted-foreground">
                    Creative workspace
                  </p>
                </div>
              </Link>
              <div className="flex items-center gap-2 md:hidden">
                <Button variant="ghost" size="icon" onClick={() => setSettingsOpen(true)}>
                  <Settings className="h-4 w-4" />
                </Button>
                <Button variant="ghost" size="icon" onClick={() => setMobileNavOpen(true)}>
                  <Menu className="h-4 w-4" />
                </Button>
              </div>
            </div>

            <div className="mt-3 flex items-center justify-between gap-2 md:hidden">
              <div className="glass-chip min-w-0 flex-1 justify-between">
                <span className="truncate">积分</span>
                <span className="font-medium text-foreground tabular-nums">
                  {user?.points_balance ?? 0}
                </span>
              </div>
              <Button variant="glass" size="sm" asChild className="shrink-0">
                <Link to="/recharge">
                  <HelpCircle className="mr-1 size-3.5" />
                  获取积分
                </Link>
              </Button>
            </div>

            <div className="mt-3 hidden items-center gap-4 md:flex">
              <nav className="flex flex-1 flex-wrap items-center gap-1 text-sm">
                {navItems.map((item) => {
                  const Icon = item.icon;
                  return (
                    <Button key={item.to} variant="ghost" size="sm" asChild>
                      <Link to={item.to}>
                        {Icon ? <Icon className="mr-1 size-3.5" /> : null}
                        {item.label}
                      </Link>
                    </Button>
                  );
                })}
              </nav>
              <div className="flex items-center gap-2">
                <div className="glass-chip hidden lg:inline-flex">
                  积分
                  <span className="font-medium text-foreground tabular-nums">
                    {user?.points_balance ?? 0}
                  </span>
                </div>
                <Button variant="glass" size="sm" asChild>
                  <Link to="/recharge">
                    <HelpCircle className="mr-1 size-3.5" />
                    积分获取
                  </Link>
                </Button>
                <div className="ml-2 flex h-9 items-center gap-2 rounded-full border border-border/40 bg-card/40 pl-3 pr-1 shadow-sm backdrop-blur-xl">
                  <div className="flex items-center gap-2 border-r border-border/40 pr-3">
                    <div className="flex h-5 w-5 items-center justify-center rounded-full bg-primary/10 text-primary">
                      <User className="h-3 w-3" />
                    </div>
                    <span className="max-w-[100px] truncate text-xs font-semibold text-foreground/90">
                      {user?.username || (user?.is_admin ? "管理员" : "用户")}
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
        </div>
      </header>
      <Outlet />

      <Dialog open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
        <DialogContent className="left-3 right-3 top-auto bottom-3 w-auto max-w-none translate-x-0 translate-y-0 overflow-y-auto rounded-[1.8rem] p-5 md:hidden">
          <DialogHeader className="text-left">
            <DialogTitle>快捷导航</DialogTitle>
            <DialogDescription>
              在手机上把常用入口收进这里，减少顶部拥挤。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="grid gap-2">
              {navItems.map((item) => {
                const Icon = item.icon;
                return (
                  <Button key={item.to} variant="outline" className="justify-start" asChild>
                    <Link to={item.to} onClick={() => setMobileNavOpen(false)}>
                      {Icon ? <Icon className="mr-2 size-4" /> : null}
                      {item.label}
                    </Link>
                  </Button>
                );
              })}
            </div>
            <div className="glass-panel-subtle flex items-center justify-between gap-3 p-4">
              <div className="min-w-0">
                <p className="text-xs font-bold text-foreground/60">当前账号</p>
                <p className="truncate text-sm font-semibold text-foreground">
                  {user?.username || (user?.is_admin ? "管理员" : "用户")}
                </p>
              </div>
              <div className="glass-chip shrink-0">
                积分
                <span className="font-medium text-foreground tabular-nums">
                  {user?.points_balance ?? 0}
                </span>
              </div>
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              <Button
                variant="outline"
                onClick={() => {
                  setMobileNavOpen(false);
                  setSettingsOpen(true);
                }}
              >
                <Settings className="mr-2 size-4" />
                用户设置
              </Button>
              <Button
                variant="destructive"
                onClick={() => {
                  setMobileNavOpen(false);
                  logout();
                  nav("/login", { replace: true });
                }}
              >
                <LogOut className="mr-2 size-4" />
                退出登录
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog
        open={settingsOpen}
        onOpenChange={(open: boolean) => {
          setSettingsOpen(open);
          if (!open) setSettingsGateHint(null);
        }}
      >
        <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Settings className="h-5 w-5" />
              用户设置
            </DialogTitle>
            <DialogDescription className="text-foreground dark:text-muted-foreground leading-relaxed">
              配置界面风格；用户可在此调整个人偏好的模型与联网搜索设置。
            </DialogDescription>
            {settingsGateHint ? (
              <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-left text-sm font-semibold text-amber-900 dark:text-amber-100">
                {settingsGateHint}
              </p>
            ) : null}
          </DialogHeader>

          <div className="space-y-6 py-4">
            <section className="space-y-3">
              <Label className="text-sm font-bold uppercase tracking-wider text-foreground dark:text-foreground/70">
                界面风格
              </Label>
              <div className="grid gap-3 sm:grid-cols-3">
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
                        : "border-border/70 bg-background/40 text-foreground dark:text-muted-foreground hover:border-muted-foreground/30 hover:bg-background/60"
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

            <section id="settings-llm-section" className="space-y-4 pt-2 border-t border-border scroll-mt-4">
              <Label className="text-sm font-bold uppercase tracking-wider text-foreground dark:text-foreground/70">
                大模型配置
              </Label>
              <p className="text-xs text-foreground dark:text-foreground/60 font-medium">
                这里的配置仅对您当前账号生效。管理员在后台维护模型计价规则。
              </p>

              <div className="grid gap-4 sm:grid-cols-1">
                <div className="space-y-2">
                  <div className="flex items-center gap-1.5">
                    <Label className="text-foreground font-semibold">默认使用模型</Label>
                    <span title="未保存过模型时，系统默认使用最便宜的已启用模型；您也可以在此指定自己偏好的模型。" className="cursor-help">
                      <HelpCircle className="h-3.5 w-3.5 text-muted-foreground" />
                    </span>
                  </div>
                  <p className="text-[11px] text-foreground dark:text-foreground/50 font-medium">
                    计价单位为人民币/百万 token（入/出分列），扣费按积分换算。可粗略理解为 1 token ≈ 1.5 个汉字。
                  </p>
                  <ModelPriceSelect
                    value={llmCfg?.model || ""}
                    onChange={(modelId) =>
                      setLlmCfg((prev) => (prev ? { ...prev, model: modelId } : null))
                    }
                    models={availableModels}
                    disabled={settingsBusy}
                  />
                  {llmCfg?.has_explicit_model === false ? (
                    <p className="text-[11px] text-amber-700 dark:text-amber-300 font-semibold">
                      当前为未保存状态：系统会默认使用最便宜模型；点击“保存配置”后才会固定为你的选择。
                    </p>
                  ) : null}
                </div>
              </div>

              <div className="glass-panel-subtle space-y-3 p-4">
                <div className="flex items-center gap-1.5">
                  <Label className="text-xs font-bold text-foreground dark:text-foreground/70 italic">联网搜索 (Web Search)</Label>
                  <span title="开启后，大模型在生成前会先搜索互联网实时信息（302.AI 提供）。" className="cursor-help">
                    <HelpCircle className="h-3.5 w-3.5 text-muted-foreground" />
                  </span>
                </div>
                <div className="grid gap-3 pt-1">
                  {[
                    { id: "novel_generate_web_search" as const, label: "章节续写" },
                    { id: "novel_volume_plan_web_search" as const, label: "卷章计划" },
                    { id: "novel_memory_refresh_web_search" as const, label: "记忆刷新" },
                    { id: "novel_inspiration_web_search" as const, label: "灵感对话" },
                    { id: "novel_web_search" as const, label: "其他(助手/框架)" },
                  ].map((field) => (
                    <label key={field.id} className="flex items-center justify-between group cursor-pointer">
                      <span className="text-sm text-foreground group-hover:text-primary transition-colors font-semibold">{field.label}</span>
                      <input
                        type="checkbox"
                        checked={Boolean(llmCfg?.[field.id])}
                        onChange={(e) => setLlmCfg(prev => prev ? { ...prev, [field.id]: e.target.checked } : null)}
                        className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"
                        disabled={settingsBusy}
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
                if (llmCfg) {
                  handleSaveSettings(llmCfg).then(() => setSettingsOpen(false));
                } else {
                  setSettingsOpen(false);
                }
              }}
              disabled={settingsBusy}
            >
              {settingsBusy ? "保存中..." : "保存配置"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
