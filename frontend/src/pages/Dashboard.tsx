import { Link } from "react-router-dom";
import { ArrowRight, BookOpen, Workflow } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export function Dashboard() {
  return (
    <div className="min-h-screen bg-background p-8">
      <div className="mx-auto max-w-3xl space-y-8">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">VocalFlow Studio</h1>
          <p className="mt-2 text-muted-foreground">
            AI 创作平台：虚拟人歌唱工作流 + 小说创作（书架、框架确认、记忆与每日自动章节）。
          </p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Card>
            <CardHeader>
              <Workflow className="size-8 text-primary" />
              <CardTitle>工作流编辑器</CardTitle>
              <CardDescription>
                拖拽节点、连接边线、加载内置 Gemini + SeeDance 模板。
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Button asChild>
                <Link to="/editor">
                  进入编辑器
                  <ArrowRight className="size-4" />
                </Link>
              </Button>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <BookOpen className="size-8 text-accent" />
              <CardTitle>小说创作</CardTitle>
              <CardDescription>
                书架、参考 txt（≤15MB）、302 Chat（glm-4.7 + 联网）生成框架与章节；
                每日自动章数 + 人工反馈与审定。
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Button variant="secondary" asChild>
                <Link to="/novels">
                  进入书架
                  <ArrowRight className="size-4" />
                </Link>
              </Button>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>项目管理</CardTitle>
              <CardDescription>
                工作流与媒体的持久化将对接后端 API（Phase 1 为占位界面）。
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Button variant="outline" asChild>
                <Link to="/projects">打开项目</Link>
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
