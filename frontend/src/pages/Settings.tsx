import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { getLlmConfig, setLlmConfig } from "@/services/novelApi";

export function SettingsPage() {
  const [provider, setProvider] = useState<"ai302" | "custom">("ai302");
  const [model, setModel] = useState<string>("");
  const [novelWebSearch, setNovelWebSearch] = useState<boolean>(false);
  const [novelGenerateWebSearch, setNovelGenerateWebSearch] = useState<boolean>(false);
  const [novelVolumePlanWebSearch, setNovelVolumePlanWebSearch] = useState<boolean>(false);
  const [novelMemoryRefreshWebSearch, setNovelMemoryRefreshWebSearch] = useState<boolean>(false);
  const [inspirationWebSearch, setInspirationWebSearch] = useState<boolean>(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    setBusy(true);
    setErr(null);
    getLlmConfig()
      .then((c) => {
        setProvider((c.provider === "custom" ? "custom" : "ai302") as any);
        setModel(c.model || "");
        setNovelWebSearch(Boolean(c.novel_web_search));
        setNovelGenerateWebSearch(Boolean(c.novel_generate_web_search));
        setNovelVolumePlanWebSearch(Boolean(c.novel_volume_plan_web_search));
        setNovelMemoryRefreshWebSearch(Boolean(c.novel_memory_refresh_web_search));
        setInspirationWebSearch(Boolean(c.novel_inspiration_web_search));
      })
      .catch((e: unknown) => {
        setErr(e instanceof Error ? e.message : "加载失败");
      })
      .finally(() => setBusy(false));
  }, []);

  async function onSave() {
    setBusy(true);
    setErr(null);
    setNotice(null);
    try {
      await setLlmConfig({
        provider,
        model,
        novel_web_search: novelWebSearch,
        novel_generate_web_search: novelGenerateWebSearch,
        novel_volume_plan_web_search: novelVolumePlanWebSearch,
        novel_memory_refresh_web_search: novelMemoryRefreshWebSearch,
        novel_inspiration_web_search: inspirationWebSearch,
      });
      setNotice("已保存。全站所有大模型调用将使用该配置。");
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="mx-auto max-w-3xl space-y-6">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">设置</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              在这里切换全局大模型配置（灵感对话、框架生成、章计划、续写、章节助手等都会同步生效）。
            </p>
          </div>
          <Button variant="ghost" size="sm" asChild>
            <Link to="/novels">返回书架</Link>
          </Button>
        </div>

        <Card className="bg-card/60">
          <CardHeader>
            <CardTitle>全局大模型</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label>Provider</Label>
              <select
                value={provider}
                onChange={(e) => setProvider((e.target.value === "custom" ? "custom" : "ai302") as any)}
                className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                disabled={busy}
              >
                <option value="ai302">302AI</option>
                <option value="custom">自建代理（OpenAI兼容）</option>
              </select>
            </div>

            <div className="space-y-2">
              <Label>模型名称（手填，可留空使用默认）</Label>
              <input
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                placeholder={
                  provider === "ai302"
                    ? "例如：doubao-seed-2-0-pro-260215 / kimi-k2.5 / glm-4.7"
                    : "例如：243-gpt-5__2025-08-07"
                }
                disabled={busy}
              />
              <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                <span>快捷填入：</span>
                <button
                  type="button"
                  className="rounded border border-border bg-muted/30 px-2 py-1 hover:bg-muted/50"
                  onClick={() => setModel("")}
                  disabled={busy}
                >
                  留空（默认）
                </button>
                <button
                  type="button"
                  className="rounded border border-border bg-muted/30 px-2 py-1 hover:bg-muted/50"
                  onClick={() => {
                    setProvider("ai302");
                    setModel("kimi-k2.5");
                  }}
                  disabled={busy}
                >
                  kimi-k2.5
                </button>
                <button
                  type="button"
                  className="rounded border border-border bg-muted/30 px-2 py-1 hover:bg-muted/50"
                  onClick={() => {
                    setProvider("ai302");
                    setModel("doubao-seed-2-0-pro-260215");
                  }}
                  disabled={busy}
                >
                  doubao-seed-2-0-pro-260215
                </button>
                <button
                  type="button"
                  className="rounded border border-border bg-muted/30 px-2 py-1 hover:bg-muted/50"
                  onClick={() => {
                    setProvider("custom");
                    setModel("243-gpt-5__2025-08-07");
                  }}
                  disabled={busy}
                >
                  243-gpt-5__2025-08-07
                </button>
              </div>
              <p className="text-[11px] text-muted-foreground">
                提示：自建代理的 Endpoint 与 API Key 需要在后端{" "}
                <code className="rounded bg-muted px-1">backend/.env</code> 中配置。
              </p>
            </div>

            <div className="space-y-2 rounded-md border border-border bg-muted/20 p-3">
              <Label className="text-sm">联网搜索开关</Label>
              <label className="flex items-center justify-between gap-3 text-sm">
                <span>小说续写（章节生成）启用 web search</span>
                <input
                  type="checkbox"
                  checked={novelGenerateWebSearch}
                  onChange={(e) => setNovelGenerateWebSearch(e.target.checked)}
                  disabled={busy}
                />
              </label>
              <label className="flex items-center justify-between gap-3 text-sm">
                <span>卷章计划生成启用 web search</span>
                <input
                  type="checkbox"
                  checked={novelVolumePlanWebSearch}
                  onChange={(e) => setNovelVolumePlanWebSearch(e.target.checked)}
                  disabled={busy}
                />
              </label>
              <label className="flex items-center justify-between gap-3 text-sm">
                <span>记忆刷新启用 web search</span>
                <input
                  type="checkbox"
                  checked={novelMemoryRefreshWebSearch}
                  onChange={(e) => setNovelMemoryRefreshWebSearch(e.target.checked)}
                  disabled={busy}
                />
              </label>
              <label className="flex items-center justify-between gap-3 text-sm">
                <span>灵感对话启用 web search</span>
                <input
                  type="checkbox"
                  checked={inspirationWebSearch}
                  onChange={(e) => setInspirationWebSearch(e.target.checked)}
                  disabled={busy}
                />
              </label>
              <label className="flex items-center justify-between gap-3 text-sm">
                <span>其他小说流程（章节助手/框架/改写）默认开关</span>
                <input
                  type="checkbox"
                  checked={novelWebSearch}
                  onChange={(e) => setNovelWebSearch(e.target.checked)}
                  disabled={busy}
                />
              </label>
            </div>

            {err ? <p className="text-sm text-destructive">{err}</p> : null}
            {notice ? <p className="text-sm text-emerald-400">{notice}</p> : null}

            <div className="flex gap-2">
              <Button type="button" disabled={busy} onClick={() => void onSave()}>
                {busy ? "保存中…" : "保存"}
              </Button>
              <Button type="button" variant="outline" disabled={busy} onClick={() => window.location.reload()}>
                重新加载
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

