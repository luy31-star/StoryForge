import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export function ProjectManagement() {
  return (
    <div className="min-h-screen bg-background p-8">
      <div className="mx-auto max-w-3xl space-y-6">
        <Button variant="ghost" size="sm" asChild>
          <Link to="/">
            <ArrowLeft className="size-4" />
            返回首页
          </Link>
        </Button>
        <Card>
          <CardHeader>
            <CardTitle>项目管理</CardTitle>
            <CardDescription>
              后续将在此列出已保存的工作流项目，并支持从数据库加载到画布。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              当前为 Phase 1 占位页。后端{" "}
              <code className="rounded bg-muted px-1 py-0.5 text-xs">
                /api/workflow
              </code>{" "}
              就绪后可接入列表与创建。
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
