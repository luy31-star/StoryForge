import { Link } from "react-router-dom";
import { ArrowRight, BookMarked, Brain, GitBranch } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/stores/authStore";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export function Landing() {
  const user = useAuthStore((s) => s.user);

  return (
    <div className="min-h-screen bg-gradient-to-b from-background via-background to-muted/30">
      <div className="mx-auto max-w-4xl px-6 py-16 space-y-12">
        <header className="space-y-4 text-center">
          <p className="text-sm font-medium uppercase tracking-widest text-primary/90">
            StoryForge
          </p>
          <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">
            让你的长篇剧情<span className="text-primary">不再跑偏</span>
          </h1>
          <p className="mx-auto max-w-2xl text-lg text-muted-foreground">
            面向连载创作的 AI 小说工作台：热/冷双层记忆、弧光节奏与章计划对齐，
            把「设定—伏笔—节拍」锁进同一条叙事轨道。
          </p>
          <div className="flex flex-wrap items-center justify-center gap-3 pt-2">
            <Button size="lg" asChild>
              <Link to="/novels">
                进入书架
                <ArrowRight className="ml-2 size-4" />
              </Link>
            </Button>
            {!user && (
              <Button size="lg" variant="outline" asChild>
                <Link to="/login">登录</Link>
              </Button>
            )}
          </div>
        </header>

        <div className="grid gap-6 md:grid-cols-3">
          <Card className="border-border/60 bg-card/70 backdrop-blur">
            <CardHeader>
              <Brain className="size-8 text-primary" />
              <CardTitle>热 / 冷记忆</CardTitle>
              <CardDescription>
                近期时间线与开放伏笔常驻「热层」，冷层按需召回，降低 token 噪声又保留可追溯性。
              </CardDescription>
            </CardHeader>
          </Card>
          <Card className="border-border/60 bg-card/70 backdrop-blur">
            <CardHeader>
              <GitBranch className="size-8 text-accent" />
              <CardTitle>弧光节奏</CardTitle>
              <CardDescription>
                框架 JSON 与分卷章计划对齐「下一章节拍」，减少跨弧快进与设定漂移。
              </CardDescription>
            </CardHeader>
          </Card>
          <Card className="border-border/60 bg-card/70 backdrop-blur">
            <CardHeader>
              <BookMarked className="size-8 text-primary" />
              <CardTitle>创作闭环</CardTitle>
              <CardDescription>
                生成 → 修订 → 审定 → 记忆增量；积分按用量透明结算，可按模型配置单价。
              </CardDescription>
            </CardHeader>
            <CardContent className="pt-0">
              <Button variant="secondary" className="w-full" asChild>
                <Link to="/novels">开始创作</Link>
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
