import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  adminListModelPrices,
  adminPatchModelPrice,
  adminGetDashboardStats,
  adminListUsers,
  adminGetUserTokenUsage,
  adminCreateModelPrice,
  adminDeleteModelPrice,
  type ModelPriceRow,
  type DashboardStats,
  type UserAdminOut,
  type DailyTokenUsageOut,
} from "@/services/billingApi";

export function Admin() {
  const [rows, setRows] = useState<ModelPriceRow[]>([]);
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [users, setUsers] = useState<UserAdminOut[]>([]);
  const [selectedUserUsage, setSelectedUserUsage] = useState<DailyTokenUsageOut[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [activeTab, setActiveTab] = useState("dashboard");
  const [newModel, setNewModel] = useState({
    model_id: "",
    display_name: "",
  });

  const reloadPrices = useCallback(async () => {
    const data = await adminListModelPrices();
    setRows(data);
  }, []);

  const reloadStats = useCallback(async () => {
    const data = await adminGetDashboardStats();
    setStats(data);
  }, []);

  const reloadUsers = useCallback(async () => {
    const data = await adminListUsers();
    setUsers(data);
  }, []);

  const reload = useCallback(async () => {
    setBusy(true);
    setErr(null);
    try {
      if (activeTab === "dashboard") {
        await reloadStats();
      } else if (activeTab === "users") {
        await reloadUsers();
      } else if (activeTab === "models") {
        await reloadPrices();
      }
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "加载失败");
    } finally {
      setBusy(false);
    }
  }, [activeTab, reloadStats, reloadUsers, reloadPrices]);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function toggle(row: ModelPriceRow) {
    setErr(null);
    try {
      await adminPatchModelPrice(row.id, { enabled: !row.enabled });
      await reloadPrices();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "更新失败");
    }
  }

  async function savePrice(row: ModelPriceRow, field: "prompt" | "completion", value: string) {
    const n = parseFloat(value);
    if (Number.isNaN(n) || n < 0) return;
    setErr(null);
    try {
      if (field === "prompt") {
        await adminPatchModelPrice(row.id, { prompt_price_cny_per_million_tokens: n });
      } else {
        await adminPatchModelPrice(row.id, { completion_price_cny_per_million_tokens: n });
      }
      await reloadPrices();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "保存失败");
    }
  }

  async function viewUserUsage(userId: string) {
    setErr(null);
    try {
      const data = await adminGetUserTokenUsage(userId);
      setSelectedUserUsage(data);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "加载用户使用量失败");
    }
  }

  async function handleAddModel(e: React.FormEvent) {
    e.preventDefault();
    if (!newModel.model_id) return;
    setBusy(true);
    setErr(null);
    try {
      await adminCreateModelPrice({
        model_id: newModel.model_id.trim(),
        display_name: newModel.display_name.trim() || newModel.model_id.trim(),
      });
      setNewModel({ model_id: "", display_name: "" });
      await reloadPrices();
    } catch (e: any) {
      setErr(e.message || "添加模型失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteModel(row: ModelPriceRow) {
    if (!confirm(`确定要删除模型 ${row.model_id} 吗？`)) return;
    setBusy(true);
    setErr(null);
    try {
      await adminDeleteModelPrice(row.id);
      await reloadPrices();
    } catch (e: any) {
      setErr(e.message || "删除模型失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="mx-auto max-w-4xl space-y-6">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold">管理后台</h1>
            <p className="text-sm text-muted-foreground">
              监控全局统计、用户用量以及配置模型价格。
            </p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => void reload()} disabled={busy}>
              刷新
            </Button>
            <Button variant="ghost" size="sm" asChild>
              <Link to="/novels">返回书架</Link>
            </Button>
          </div>
        </div>

        {err ? <p className="text-sm text-destructive">{err}</p> : null}

        <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
          <TabsList className="grid w-full grid-cols-3">
            <TabsTrigger value="dashboard">全局仪表盘</TabsTrigger>
            <TabsTrigger value="users">用户管理</TabsTrigger>
            <TabsTrigger value="models">模型计价</TabsTrigger>
          </TabsList>

          <TabsContent value="dashboard" className="space-y-4 pt-4">
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
              <Card>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                  <CardTitle className="text-sm font-medium">总消耗 Token</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">{stats?.total_tokens?.toLocaleString() || 0}</div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                  <CardTitle className="text-sm font-medium">总生成章节</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">{stats?.total_chapters?.toLocaleString() || 0}</div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                  <CardTitle className="text-sm font-medium">总小说数</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">{stats?.total_novels?.toLocaleString() || 0}</div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                  <CardTitle className="text-sm font-medium">总用户数</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">{stats?.total_users?.toLocaleString() || 0}</div>
                </CardContent>
              </Card>
            </div>
          </TabsContent>

          <TabsContent value="users" className="space-y-4 pt-4">
            <div className="grid gap-4 md:grid-cols-2">
              <Card>
                <CardHeader>
                  <CardTitle>用户列表</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  {users.map((u) => (
                    <div
                      key={u.id}
                      className="flex flex-col gap-2 rounded-lg border p-4 md:flex-row md:items-center md:justify-between"
                    >
                      <div className="space-y-1">
                        <div className="font-medium">{u.username}</div>
                        <div className="text-xs text-muted-foreground">ID: {u.id}</div>
                        <div className="text-xs text-muted-foreground">创建时间: {new Date(u.created_at).toLocaleString()}</div>
                      </div>
                      <div className="flex flex-col items-end gap-1">
                        <div className="text-sm font-medium">
                          Token 消耗: {u.total_tokens_used.toLocaleString()}
                        </div>
                        <div className="text-sm">剩余积分: {u.points_balance}</div>
                        <Button variant="outline" size="sm" onClick={() => void viewUserUsage(u.id)}>
                          查看每日消耗
                        </Button>
                      </div>
                    </div>
                  ))}
                  {users.length === 0 && !busy ? (
                    <p className="text-sm text-muted-foreground">暂无用户</p>
                  ) : null}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>每日 Token 消耗</CardTitle>
                </CardHeader>
                <CardContent>
                  {!selectedUserUsage ? (
                    <p className="text-sm text-muted-foreground">请在左侧选择一个用户查看</p>
                  ) : (
                    <div className="space-y-2">
                      {selectedUserUsage.map((usage) => (
                        <div key={usage.date} className="flex justify-between border-b pb-2">
                          <span className="text-sm">{usage.date}</span>
                          <span className="text-sm font-medium">{usage.total_tokens.toLocaleString()}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          </TabsContent>

          <TabsContent value="models" className="pt-4">
            <Card>
              <CardHeader>
                <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                  <CardTitle>模型列表</CardTitle>
                  <form onSubmit={handleAddModel} className="flex flex-wrap items-center gap-2">
                    <input
                      value={newModel.display_name}
                      onChange={(e) => setNewModel((p) => ({ ...p, display_name: e.target.value }))}
                      placeholder="显示名称 (可选)"
                      className="h-9 w-[140px] rounded-md border border-input bg-background px-3 text-sm"
                      disabled={busy}
                    />
                    <input
                      value={newModel.model_id}
                      onChange={(e) => setNewModel((p) => ({ ...p, model_id: e.target.value }))}
                      placeholder="模型 ID (必填)"
                      className="h-9 w-[160px] rounded-md border border-input bg-background px-3 text-sm"
                      required
                      disabled={busy}
                    />
                    <Button type="submit" size="sm" disabled={busy || !newModel.model_id}>
                      添加模型
                    </Button>
                  </form>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                {rows.length === 0 && !busy && activeTab === "models" ? (
                  <p className="text-sm text-muted-foreground">暂无记录；请在此添加模型 ID 与单价。</p>
                ) : null}
                {rows.map((r) => (
                  <div
                    key={r.id}
                    className="flex flex-col gap-3 rounded-lg border border-border/60 p-4 md:flex-row md:items-center"
                  >
                    <div className="flex-1 space-y-1">
                      <div className="font-medium">{r.display_name || r.model_id}</div>
                      <div className="font-mono text-xs text-muted-foreground">{r.model_id}</div>
                    </div>
                    <div className="flex flex-wrap items-end gap-3">
                      <div className="space-y-1">
                        <Label className="text-[10px] text-muted-foreground uppercase">输入(元/M)</Label>
                        <input
                          key={r.id + "-prompt"}
                          defaultValue={String(r.prompt_price_cny_per_million_tokens)}
                          className="h-9 w-20 rounded-md border border-input bg-background px-2 text-sm"
                          onBlur={(e) => void savePrice(r, "prompt", e.target.value)}
                        />
                      </div>
                      <div className="space-y-1">
                        <Label className="text-[10px] text-muted-foreground uppercase">输出(元/M)</Label>
                        <input
                          key={r.id + "-completion"}
                          defaultValue={String(r.completion_price_cny_per_million_tokens)}
                          className="h-9 w-20 rounded-md border border-input bg-background px-2 text-sm"
                          onBlur={(e) => void savePrice(r, "completion", e.target.value)}
                        />
                      </div>
                      <Button
                        type="button"
                        variant={r.enabled ? "secondary" : "outline"}
                        size="sm"
                        onClick={() => void toggle(r)}
                      >
                        {r.enabled ? "已启用" : "已禁用"}
                      </Button>
                      <Button
                        type="button"
                        variant="destructive"
                        size="sm"
                        onClick={() => void handleDeleteModel(r)}
                      >
                        删除
                      </Button>
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
