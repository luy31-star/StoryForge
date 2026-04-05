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
  adminAdjustUserPoints,
  adminFreezeUser,
  adminUnfreezeUser,
  adminListInviteCodes,
  adminCreateInviteCode,
  adminFreezeInviteCode,
  adminUnfreezeInviteCode,
  adminDeleteInviteCode,
  adminGetRegistrationMode,
  adminSetRegistrationMode,
  type ModelPriceRow,
  type DashboardStats,
  type UserAdminOut,
  type DailyTokenUsageOut,
  type InviteCodeRow,
} from "@/services/billingApi";

export function Admin() {
  const [rows, setRows] = useState<ModelPriceRow[]>([]);
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [users, setUsers] = useState<UserAdminOut[]>([]);
  const [selectedUserUsage, setSelectedUserUsage] = useState<DailyTokenUsageOut[] | null>(null);
  const [invites, setInvites] = useState<InviteCodeRow[]>([]);
  const [inviteOnly, setInviteOnly] = useState<boolean | null>(null);
  const [invitePage, setInvitePage] = useState(1);
  const [invitePageSize] = useState(20);
  const [inviteTotal, setInviteTotal] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [activeTab, setActiveTab] = useState("dashboard");
  const [newModel, setNewModel] = useState({
    model_id: "",
    display_name: "",
  });
  const [inviteForm, setInviteForm] = useState({ expiresInDays: "7", note: "" });

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

  const reloadInvites = useCallback(async () => {
    const [list, mode] = await Promise.all([
      adminListInviteCodes(invitePage, invitePageSize),
      adminGetRegistrationMode(),
    ]);
    setInvites(list.items);
    setInviteTotal(Number(list.total || 0));
    setInviteOnly(Boolean(mode.invite_only));
  }, [invitePage, invitePageSize]);

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
      } else if (activeTab === "invites") {
        await reloadInvites();
      }
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "加载失败");
    } finally {
      setBusy(false);
    }
  }, [activeTab, reloadStats, reloadUsers, reloadPrices, reloadInvites]);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function adjustPoints(userId: string) {
    const amount = prompt("请输入要调整的积分数（正数为增加，负数为减少）", "100");
    if (!amount) return;
    const n = parseInt(amount);
    if (isNaN(n)) return;

    const note = prompt("请输入调整备注（可选）", "管理员手动调整");
    
    setBusy(true);
    setErr(null);
    try {
      await adminAdjustUserPoints(userId, n, note || undefined);
      await reloadUsers();
      alert("调整成功");
    } catch (e: any) {
      setErr(e.message || "调整失败");
    } finally {
      setBusy(false);
    }
  }

  async function freezeUser(userId: string) {
    const reason = prompt("请输入冻结原因（可选）", "");
    setBusy(true);
    setErr(null);
    try {
      await adminFreezeUser(userId, reason || undefined);
      await reloadUsers();
    } catch (e: any) {
      setErr(e.message || "冻结失败");
    } finally {
      setBusy(false);
    }
  }

  async function unfreezeUser(userId: string) {
    setBusy(true);
    setErr(null);
    try {
      await adminUnfreezeUser(userId);
      await reloadUsers();
    } catch (e: any) {
      setErr(e.message || "解冻失败");
    } finally {
      setBusy(false);
    }
  }

  async function createInvite(e: React.FormEvent) {
    e.preventDefault();
    const days = inviteForm.expiresInDays.trim();
    const n = days ? parseInt(days) : NaN;
    const expiresInDays = Number.isNaN(n) ? undefined : n;
    setBusy(true);
    setErr(null);
    try {
      await adminCreateInviteCode(expiresInDays, inviteForm.note.trim() || undefined);
      setInviteForm({ expiresInDays: "7", note: "" });
      await reloadInvites();
    } catch (e: any) {
      setErr(e.message || "创建邀请码失败");
    } finally {
      setBusy(false);
    }
  }

  async function toggleInvite(row: InviteCodeRow) {
    setBusy(true);
    setErr(null);
    try {
      if (row.is_frozen) {
        await adminUnfreezeInviteCode(row.id);
      } else {
        await adminFreezeInviteCode(row.id);
      }
      await reloadInvites();
    } catch (e: any) {
      setErr(e.message || "更新邀请码失败");
    } finally {
      setBusy(false);
    }
  }

  async function toggleInviteOnly(next: boolean) {
    setBusy(true);
    setErr(null);
    try {
      const out = await adminSetRegistrationMode(next);
      setInviteOnly(Boolean(out.invite_only));
    } catch (e: any) {
      setErr(e.message || "更新注册策略失败");
    } finally {
      setBusy(false);
    }
  }

  async function removeInvite(row: InviteCodeRow) {
    if (!confirm(`确定要删除邀请码 ${row.code} 吗？`)) return;
    setBusy(true);
    setErr(null);
    try {
      await adminDeleteInviteCode(row.id);
      if (invites.length === 1 && invitePage > 1) {
        setInvitePage(invitePage - 1);
      }
      await reloadInvites();
    } catch (e: any) {
      setErr(e.message || "删除邀请码失败");
    } finally {
      setBusy(false);
    }
  }

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
          <TabsList className="grid w-full grid-cols-4">
            <TabsTrigger value="dashboard">全局仪表盘</TabsTrigger>
            <TabsTrigger value="users">用户管理</TabsTrigger>
            <TabsTrigger value="models">模型计价</TabsTrigger>
            <TabsTrigger value="invites">邀请码</TabsTrigger>
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
                        <div className="flex items-center gap-2">
                          <div className="font-medium">{u.username}</div>
                          {u.is_admin ? (
                            <span className="rounded-full border px-2 py-0.5 text-[11px]">admin</span>
                          ) : null}
                          {u.is_frozen ? (
                            <span className="rounded-full border border-destructive/30 bg-destructive/10 px-2 py-0.5 text-[11px] text-destructive">
                              frozen
                            </span>
                          ) : null}
                        </div>
                        <div className="text-xs text-muted-foreground">邮箱: {u.email}</div>
                        <div className="text-xs text-muted-foreground">ID: {u.id}</div>
                        <div className="text-xs text-muted-foreground">创建时间: {new Date(u.created_at).toLocaleString()}</div>
                        {u.is_frozen && u.frozen_reason ? (
                          <div className="text-xs text-destructive">冻结原因: {u.frozen_reason}</div>
                        ) : null}
                      </div>
                      <div className="flex flex-col items-end gap-1">
                        <div className="text-sm font-medium">
                          Token 消耗: {u.total_tokens_used.toLocaleString()}
                        </div>
                        <div className="text-sm">剩余积分: {u.points_balance}</div>
                        <div className="flex gap-2 mt-1">
                          <Button variant="outline" size="sm" onClick={() => void viewUserUsage(u.id)}>
                            消耗详情
                          </Button>
                          <Button variant="outline" size="sm" onClick={() => void adjustPoints(u.id)}>
                            积分调整
                          </Button>
                          {u.is_frozen ? (
                            <Button variant="outline" size="sm" onClick={() => void unfreezeUser(u.id)}>
                              解冻
                            </Button>
                          ) : (
                            <Button variant="destructive" size="sm" onClick={() => void freezeUser(u.id)}>
                              冻结
                            </Button>
                          )}
                        </div>
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

          <TabsContent value="invites" className="pt-4">
            <Card>
              <CardHeader>
                <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                  <CardTitle>邀请码管理</CardTitle>
                  <form onSubmit={createInvite} className="flex flex-wrap items-center gap-2">
                    <input
                      value={inviteForm.expiresInDays}
                      onChange={(e) => setInviteForm((p) => ({ ...p, expiresInDays: e.target.value }))}
                      placeholder="有效期天数"
                      className="h-9 w-[120px] rounded-md border border-input bg-background px-3 text-sm"
                      disabled={busy}
                    />
                    <input
                      value={inviteForm.note}
                      onChange={(e) => setInviteForm((p) => ({ ...p, note: e.target.value }))}
                      placeholder="备注(可选)"
                      className="h-9 w-[180px] rounded-md border border-input bg-background px-3 text-sm"
                      disabled={busy}
                    />
                    <Button type="submit" size="sm" disabled={busy}>
                      生成邀请码
                    </Button>
                  </form>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex items-center justify-between rounded-lg border border-border/60 bg-background/50 p-3">
                  <div className="space-y-0.5">
                    <div className="text-sm font-medium">注册策略</div>
                    <div className="text-xs text-muted-foreground">
                      开启后，只有持有管理员发放的邀请码才能注册；关闭后所有人都可注册。
                    </div>
                  </div>
                  <Button
                    variant={inviteOnly ? "secondary" : "outline"}
                    size="sm"
                    disabled={busy || inviteOnly === null}
                    onClick={() => void toggleInviteOnly(!Boolean(inviteOnly))}
                  >
                    {inviteOnly ? "邀请码注册：开启" : "邀请码注册：关闭"}
                  </Button>
                </div>
                {invites.length === 0 && !busy ? (
                  <p className="text-sm text-muted-foreground">暂无邀请码</p>
                ) : null}
                {invites.map((it) => {
                  const used = Boolean(it.used_by_user_id);
                  const exp = it.expires_at ? new Date(it.expires_at).toLocaleString() : "永不过期";
                  return (
                    <div key={it.id} className="flex flex-col gap-2 rounded-lg border border-border/60 p-4 md:flex-row md:items-center md:justify-between">
                      <div className="space-y-1">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-sm">{it.code}</span>
                          {it.is_frozen ? (
                            <span className="rounded-full border border-destructive/30 bg-destructive/10 px-2 py-0.5 text-[11px] text-destructive">
                              frozen
                            </span>
                          ) : null}
                          {used ? (
                            <span className="rounded-full border px-2 py-0.5 text-[11px]">used</span>
                          ) : (
                            <span className="rounded-full border px-2 py-0.5 text-[11px]">unused</span>
                          )}
                        </div>
                        <div className="text-xs text-muted-foreground">有效期: {exp}</div>
                        <div className="text-xs text-muted-foreground">
                          使用者: {used ? (it.used_by_username || it.used_by_user_id) : "—"}
                        </div>
                        {it.note ? <div className="text-xs text-muted-foreground">备注: {it.note}</div> : null}
                      </div>
                      <div className="flex gap-2 md:justify-end">
                        <Button variant="outline" size="sm" onClick={() => void toggleInvite(it)} disabled={busy}>
                          {it.is_frozen ? "解冻" : "冻结"}
                        </Button>
                        <Button
                          variant="destructive"
                          size="sm"
                          onClick={() => void removeInvite(it)}
                          disabled={busy || used}
                        >
                          删除
                        </Button>
                      </div>
                    </div>
                  );
                })}
                {inviteTotal > invitePageSize ? (
                  <div className="flex items-center justify-between pt-2">
                    <div className="text-xs text-muted-foreground">
                      共 {inviteTotal} 条，第 {invitePage} 页
                    </div>
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={busy || invitePage <= 1}
                        onClick={() => setInvitePage((p) => Math.max(1, p - 1))}
                      >
                        上一页
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={busy || invitePage * invitePageSize >= inviteTotal}
                        onClick={() => setInvitePage((p) => p + 1)}
                      >
                        下一页
                      </Button>
                    </div>
                  </div>
                ) : null}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
