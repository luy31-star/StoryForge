import { Link } from "react-router-dom";
import {
  ArrowRight,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/stores/authStore";

const signalStats = [
  { label: "热层记忆", value: "只保留当前章真正要用的信息", hint: "角色 / 伏笔 / 时间线" },
  { label: "卷计划轨道", value: "下一章先锁目标，再写正文", hint: "目标 / 冲突 / 转折" },
  { label: "审定闭环", value: "正文通过后再回写长期记忆", hint: "写完不丢线，不断层" },
] as const;

function LandingSignalBoard() {
  return (
    <div className="signal-surface story-mesh p-5 sm:p-6">
      <div className="relative z-10 flex flex-wrap items-center justify-between gap-2 text-[11px] font-semibold uppercase tracking-[0.26em] text-foreground/72">
        <span>StoryForge / Narrative Engine</span>
        <span>Hot Memory / Arc Rail / Recall</span>
      </div>

      <div className="relative mt-6 min-h-[420px] sm:min-h-[500px]">
        <svg
          viewBox="0 0 640 420"
          className="absolute inset-0 h-full w-full"
          aria-hidden="true"
        >
          <defs>
            <linearGradient id="landing-flow" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="hsl(var(--primary) / 0.95)" />
              <stop offset="48%" stopColor="hsl(var(--accent) / 0.82)" />
              <stop offset="100%" stopColor="hsl(191 100% 72% / 0.9)" />
            </linearGradient>
            <radialGradient id="landing-glow" cx="50%" cy="50%" r="60%">
              <stop offset="0%" stopColor="hsl(var(--primary) / 0.42)" />
              <stop offset="100%" stopColor="transparent" />
            </radialGradient>
          </defs>
          <circle cx="304" cy="212" r="126" fill="url(#landing-glow)" opacity="0.72" />
          <path
            d="M86 122C158 82 220 64 282 92C346 120 390 214 454 236C507 254 554 222 596 182"
            fill="none"
            stroke="url(#landing-flow)"
            strokeWidth="4"
            strokeLinecap="round"
            opacity="0.95"
          />
          <path
            d="M98 304C166 332 236 338 292 302C360 258 386 162 460 136C516 116 562 138 604 198"
            fill="none"
            stroke="url(#landing-flow)"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeDasharray="10 12"
            opacity="0.45"
          />
          {[94, 196, 312, 452, 598].map((cx, idx) => (
            <g key={cx}>
              <circle
                cx={cx}
                cy={idx % 2 === 0 ? 122 : 304}
                r={idx === 2 ? 11 : 8}
                fill="hsl(var(--background))"
                stroke="url(#landing-flow)"
                strokeWidth="3"
              />
              <circle
                cx={cx}
                cy={idx % 2 === 0 ? 122 : 304}
                r={idx === 2 ? 22 : 16}
                fill="none"
                stroke="hsl(var(--primary) / 0.14)"
              />
            </g>
          ))}
        </svg>

        <div className="absolute left-[2%] top-8 hidden w-[36%] max-w-[210px] rounded-[1.5rem] border border-primary/18 bg-background/90 p-4 shadow-[0_16px_40px_rgba(15,23,42,0.08)] backdrop-blur-xl sm:block">
          <div className="flex items-center justify-between gap-3">
            <span className="glass-chip border-primary/25 bg-primary/10 text-primary">
              热记忆层
            </span>
            <span className="text-[11px] font-semibold text-foreground/68">Layer 01</span>
          </div>
          <div className="mt-4 space-y-2">
            {["角色状态", "进行中伏笔", "最近时间线"].map((item) => (
              <div
                key={item}
                className="flex items-center justify-between rounded-2xl border border-border/60 bg-background/72 px-3 py-2 text-sm"
              >
                <span className="font-semibold text-foreground">{item}</span>
                <span className="h-2 w-2 rounded-full bg-primary story-pulse-soft" />
              </div>
            ))}
          </div>
        </div>

        <div className="absolute right-[1%] top-12 hidden w-[32%] max-w-[188px] rounded-[1.5rem] border border-accent/20 bg-background/90 p-4 shadow-[0_16px_40px_rgba(15,23,42,0.08)] backdrop-blur-xl sm:block">
          <div className="flex items-center justify-between gap-3">
            <span className="glass-chip border-accent/30 bg-accent/10 text-accent">
              冷层归档
            </span>
            <span className="text-[11px] font-semibold text-foreground/68">Layer 02</span>
          </div>
          <div className="mt-4 grid gap-2">
            {["旧设定", "长线因果", "退场实体", "世界规则"].map((item, idx) => (
              <div
                key={item}
                className="rounded-2xl border border-border/55 bg-background/68 px-3 py-2 text-xs font-semibold text-foreground/80"
                style={{ opacity: 0.95 - idx * 0.12 }}
              >
                {item}
              </div>
            ))}
          </div>
        </div>

        <div className="absolute inset-x-4 bottom-10 rounded-[1.8rem] border border-slate-800/70 bg-slate-900/92 p-5 text-slate-50 shadow-[0_24px_70px_rgba(2,6,23,0.24)] sm:bottom-auto sm:left-[20%] sm:right-[20%] sm:top-[45%] sm:inset-x-auto">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-300">
                Arc Rail
              </p>
              <h3 className="mt-2 text-xl font-semibold tracking-tight">
                章节执行卡沿着弧线推进，而不是凭感觉漂移。
              </h3>
            </div>
            <div className="rounded-full border border-slate-700 bg-slate-800 px-3 py-1 text-xs font-medium text-slate-200">
              Next Beat Ready
            </div>
          </div>

          <div className="mt-5 grid gap-3 sm:grid-cols-3">
            {[
              ["Chapter Goal", "先锁这一章的完成目标"],
              ["Conflict Gate", "冲突强度提前被约束"],
              ["Ending Hook", "章末钩子回写长线记忆"],
            ].map(([label, description]) => (
              <div
                key={label}
                className="rounded-[1.2rem] border border-slate-700 bg-slate-800/90 px-3 py-3"
              >
                <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-cyan-200">
                  {label}
                </p>
                <p className="mt-2 text-sm leading-6 text-slate-200">{description}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="relative z-10 mt-8 flex flex-wrap gap-3 text-xs sm:mt-10">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-700/70 bg-background/92 px-3 py-1.5 text-[11px] font-semibold text-foreground shadow-[0_10px_24px_rgba(15,23,42,0.08)] backdrop-blur-md dark:border-slate-700 dark:bg-slate-950/75 dark:text-slate-100">
          热层看当前推进
        </span>
        <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-700/70 bg-background/92 px-3 py-1.5 text-[11px] font-semibold text-foreground shadow-[0_10px_24px_rgba(15,23,42,0.08)] backdrop-blur-md dark:border-slate-700 dark:bg-slate-950/75 dark:text-slate-100">
          轨道锁下一章
        </span>
        <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-700/70 bg-background/92 px-3 py-1.5 text-[11px] font-semibold text-foreground shadow-[0_10px_24px_rgba(15,23,42,0.08)] backdrop-blur-md dark:border-slate-700 dark:bg-slate-950/75 dark:text-slate-100">
          冷层保存长线
        </span>
      </div>
    </div>
  );
}

export function Landing() {
  const user = useAuthStore((s) => s.user);

  return (
    <div className="relative min-h-screen overflow-hidden">
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute left-[-10%] top-[-2%] h-[28rem] w-[28rem] rounded-full bg-primary/10 blur-[120px]" />
        <div className="absolute right-[-8%] top-[10%] h-[24rem] w-[24rem] rounded-full bg-accent/8 blur-[120px]" />
      </div>

      <div className="novel-container relative px-4 py-10 sm:px-6 md:py-16">
        <section className="grid gap-10 lg:grid-cols-[1.04fr_0.96fr] lg:items-center">
          <div className="space-y-6">
            <div className="flex flex-wrap items-center gap-2">
              <span className="glass-chip border-primary/30 bg-primary/10 text-primary">
                <Sparkles className="size-3.5" />
                StoryForge
              </span>
              <span className="glass-chip">AI Serialized Writing OS</span>
            </div>

            <div className="space-y-4">
              <p className="text-sm font-semibold uppercase tracking-[0.32em] text-foreground/55">
                Narrative Control Surface
              </p>
              <h1 className="max-w-3xl text-4xl font-semibold tracking-[-0.04em] text-foreground sm:text-5xl xl:text-6xl">
                让你的长篇剧情
                <span className="bg-gradient-to-r from-primary via-accent to-cyan-400 bg-clip-text text-transparent">
                  不再跑偏
                </span>
                。
              </h1>
              <p className="max-w-2xl text-base leading-8 text-foreground/70 md:text-lg">
                面向连载创作的 AI 小说工作台，把热/冷双层记忆、卷计划执行卡和章节审定闭环压进同一个界面。
                重点不是更花，而是更稳、更清楚。
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <Button size="lg" asChild>
                <Link to="/novels">
                  进入书架
                  <ArrowRight className="ml-2 size-4" />
                </Link>
              </Button>
              {!user && (
                <Button size="lg" variant="glass" asChild>
                  <Link to="/login">登录</Link>
                </Button>
              )}
            </div>

            <div className="grid gap-2 sm:grid-cols-3">
              {signalStats.map((stat) => (
                <div key={stat.label} className="rounded-[1.3rem] border border-border/60 bg-background/58 px-4 py-3">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-foreground/52">
                    {stat.label}
                  </p>
                  <p className="mt-2 text-sm font-semibold leading-6 text-foreground">
                    {stat.value}
                  </p>
                  <p className="mt-1 text-xs leading-5 text-foreground/58">{stat.hint}</p>
                </div>
              ))}
            </div>
          </div>

          <LandingSignalBoard />
        </section>
      </div>
    </div>
  );
}
