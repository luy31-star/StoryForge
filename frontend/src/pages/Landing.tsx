import { Link } from "react-router-dom";
import {
  ArrowRight,
} from "lucide-react";
import { Button } from "@/components/ui/button";

function LandingSignalBoard() {
  return (
    <div className="group relative flex h-full w-full flex-col p-6 sm:p-8">
      <div className="flex flex-col justify-between gap-1 text-[10px] font-bold uppercase tracking-[0.24em] text-foreground/45 sm:flex-row sm:items-center">
        <span>StoryForge / Narrative Engine</span>
        <span className="opacity-45">Hot Memory / Arc Rail / Recall</span>
      </div>

      <div className="relative mt-5 min-h-[380px] sm:min-h-[430px]">
        <svg
          viewBox="0 0 640 320"
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
          <circle cx="304" cy="160" r="100" fill="url(#landing-glow)" opacity="0.72" />
          <path
            d="M86 90C158 60 220 44 282 72C346 100 390 194 454 216C507 234 554 202 596 162"
            fill="none"
            stroke="url(#landing-flow)"
            strokeWidth="4"
            strokeLinecap="round"
            opacity="0.95"
          />
          <path
            d="M98 240C166 268 236 274 292 232C360 188 386 112 460 86C516 66 562 88 604 148"
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
                cy={idx % 2 === 0 ? 90 : 240}
                r={idx === 2 ? 10 : 7}
                fill="hsl(var(--background))"
                stroke="url(#landing-flow)"
                strokeWidth="3"
              />
            </g>
          ))}
        </svg>

        <div className="absolute left-[1%] top-4 hidden w-[36%] max-w-[190px] rounded-[1.2rem] border border-primary/18 bg-background/90 p-3 shadow-lg backdrop-blur-xl sm:block">
          <div className="flex items-center justify-between gap-2">
            <span className="rounded-full border border-primary/25 bg-primary/10 px-2 py-0.5 text-[9px] font-bold text-primary">
              热记忆层
            </span>
            <span className="text-[9px] font-semibold text-foreground/40">L-01</span>
          </div>
          <div className="mt-3 space-y-1.5">
            {["角色状态", "进行中伏笔", "最近时间线"].map((item) => (
              <div
                key={item}
                className="flex items-center justify-between rounded-xl border border-border/40 bg-background/50 px-3 py-1.5 text-[11px]"
              >
                <span className="font-semibold text-foreground">{item}</span>
                <span className="h-1.5 w-1.5 rounded-full bg-primary" />
              </div>
            ))}
          </div>
        </div>

        <div className="absolute right-[1%] top-10 hidden w-[32%] max-w-[170px] rounded-[1.2rem] border border-accent/20 bg-background/90 p-3 shadow-lg backdrop-blur-xl sm:block">
          <div className="flex items-center justify-between gap-2">
            <span className="rounded-full border border-accent/30 bg-accent/10 px-2 py-0.5 text-[9px] font-bold text-accent">
              冷层归档
            </span>
            <span className="text-[9px] font-semibold text-foreground/40">L-02</span>
          </div>
          <div className="mt-3 grid gap-1.5">
            {["旧设定", "长线因果", "退场实体", "世界规则"].map((item, idx) => (
              <div
                key={item}
                className="rounded-xl border border-border/30 bg-background/40 px-3 py-1.5 text-[10px] font-semibold text-foreground/60"
                style={{ opacity: 0.9 - idx * 0.12 }}
              >
                {item}
              </div>
            ))}
          </div>
        </div>

        <div className="absolute inset-x-4 bottom-4 rounded-[1.5rem] border border-slate-800/70 bg-slate-900/95 p-4 text-slate-50 shadow-2xl sm:bottom-auto sm:left-[12%] sm:right-[12%] sm:top-[44%] sm:inset-x-auto">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-[9px] font-bold uppercase tracking-[0.2em] text-slate-400">
                Arc Rail
              </p>
              <h3 className="mt-1 text-sm font-semibold tracking-tight">
                章节执行卡沿弧线推进。
              </h3>
            </div>
            <div className="rounded-full border border-slate-700 bg-slate-800 px-2 py-0.5 text-[9px] font-medium text-slate-300">
              Ready
            </div>
          </div>

          <div className="mt-3 grid gap-2 sm:grid-cols-3">
            {[
              ["Goal", "先锁目标"],
              ["Gate", "约束强度"],
              ["Hook", "回写记忆"],
            ].map(([label, description]) => (
              <div
                key={label}
                className="rounded-xl border border-slate-700 bg-slate-800/80 px-2.5 py-2"
              >
                <p className="text-[9px] font-bold uppercase tracking-[0.15em] text-cyan-300">
                  {label}
                </p>
                <p className="mt-0.5 text-[11px] leading-relaxed text-slate-300">{description}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {[
          ["热层当前推进", "bg-primary/10 text-primary border-primary/20"],
          ["轨道锁下一章", "bg-accent/10 text-accent border-accent/20"],
          ["冷层保存长线", "bg-sky-500/10 text-sky-500 border-sky-500/20"],
        ].map(([label, colors]) => (
          <span
            key={label}
            className={`rounded-full border px-3 py-1 text-[10px] font-bold ${colors}`}
          >
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}

export function Landing() {
  return (
    <div className="relative h-[calc(100vh-96px)] overflow-hidden">
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute left-[-10%] top-[-2%] h-[28rem] w-[28rem] rounded-full bg-primary/10 blur-[120px]" />
        <div className="absolute right-[-8%] top-[10%] h-[24rem] w-[24rem] rounded-full bg-accent/8 blur-[120px]" />
      </div>

      <div className="novel-container h-full pt-0">
        <section className="grid h-full gap-8 rounded-[2.2rem] border border-border/40 bg-background/40 p-5 sm:p-8 lg:grid-cols-[0.98fr_1.02fr] lg:items-center">
          <div className="flex flex-col space-y-10 py-2 sm:py-6">
            <div className="space-y-6">
              <div className="flex flex-wrap items-center gap-2">
                <span className="glass-chip border-primary/25 bg-primary/10 text-primary">
                  <span className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-primary" />
                  STORYFORGE
                </span>
                <span className="glass-chip border-border/60 bg-muted/30 text-muted-foreground uppercase">
                  AI Serialized Writing OS
                </span>
              </div>

              <div className="space-y-3">
                <p className="text-[11px] font-bold uppercase tracking-[0.32em] text-foreground/42">
                  Narrative Control Surface
                </p>
                <h1 className="text-4xl font-extrabold leading-[1.15] tracking-tighter sm:text-5xl xl:text-6xl">
                  让你的长篇剧情
                  <span className="mt-2 block bg-gradient-to-r from-primary via-accent to-sky-400 bg-clip-text text-transparent">
                    不再跑偏。
                  </span>
                </h1>
              </div>

              <p className="max-w-[480px] text-sm leading-relaxed text-foreground/72 sm:text-base">
                面向连载创作的 AI 小说工作台，把热/冷双层记忆、卷计划执行卡和章节审定闭环压进同一个界面。重点不是更花，而是更稳、更清楚。
              </p>

              <div className="flex flex-wrap items-center gap-4 pt-2">
                <Link to="/novels">
                  <Button size="lg" className="h-12 rounded-full px-10 text-sm font-bold shadow-xl shadow-primary/20">
                    进入书架
                    <ArrowRight className="ml-2 h-4 w-4" />
                  </Button>
                </Link>
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-3">
              {[
                ["热层记忆", "只保留有用信息", "角色 / 伏笔"],
                ["卷计划轨道", "先锁目标再写", "目标 / 冲突"],
                ["审定闭环", "通过后再回写", "不断线层"],
              ].map(([title, desc, items]) => (
                <div key={title} className="rounded-2xl border border-border/40 bg-background/40 p-4 transition-colors hover:border-primary/20">
                  <h4 className="text-[11px] font-bold text-foreground/90">{title}</h4>
                  <p className="mt-1.5 text-[10px] leading-relaxed text-foreground/60">{desc}</p>
                  <p className="mt-2 text-[9px] font-medium text-foreground/40">{items}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="relative overflow-hidden rounded-[1.8rem] border border-border/50 bg-background/40 shadow-inner">
            <LandingSignalBoard />
          </div>
        </section>
      </div>
    </div>
  );
}
