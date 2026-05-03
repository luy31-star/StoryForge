import { useState, useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { 
  ArrowLeft, Save, Sparkles, Search, Trash2, Plus, 
  BookOpen, Type, MessageSquare, Quote, AlertCircle, Loader2,
  ChevronRight, Check, X, RefreshCcw
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import {
  getWritingStyle,
  createWritingStyle,
  updateWritingStyle,
  analyzeSnippet,
  searchAuthors,
  fetchSnippets,
  WritingStyle,
  AuthorSearchResult
} from "@/services/writingStyleApi";
import { cn } from "@/lib/utils";

export function WritingStyleEditor() {
  const { id } = useParams();
  const nav = useNavigate();
  const isNew = !id || id === "new";

  const [loading, setLoading] = useState(!isNew);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [formData, setFormData] = useState<Partial<WritingStyle>>({
    name: "",
    reference_author: "",
    lexicon: { tags: [], rules: [], forbidden: [] },
    structure: { rules: [] },
    tone: { primary: [], rules: [] },
    rhetoric: { types: {}, rules: [] },
    negative_prompts: [],
    snippets: []
  });

  const [analysisText, setAnalyzeText] = useState("");
  const [authorSearch, setAuthorSearch] = useState("");

  // 手动输入临时状态
  const [newLexiconTag, setNewLexiconTag] = useState("");
  const [newLexiconRule, setNewLexiconRule] = useState("");
  const [newStructureRule, setNewStructureRule] = useState("");
  const [newTonePrimary, setNewTonePrimary] = useState("");
  const [newToneRule, setNewToneRule] = useState("");
  const [newRhetoricType, setNewRhetoricType] = useState("");
  const [newRhetoricFreq, setNewRhetoricFreq] = useState("中");
  const [newRhetoricRule, setNewRhetoricRule] = useState("");

  // AI 提取分步交互状态
  const [aiStep, setAiStep] = useState<"IDLE" | "SELECT_AUTHOR" | "SELECT_WORKS" | "EDIT_SNIPPETS">("IDLE");
  const [authorResults, setAuthorResults] = useState<AuthorSearchResult[]>([]);
  const [selectedAuthor, setSelectedAuthor] = useState<AuthorSearchResult | null>(null);
  const [selectedWorks, setSelectedWorks] = useState<string[]>([]);
  const [fetchedSnippets, setFetchedSnippets] = useState<string[]>([]);
  const [newWork, setNewWork] = useState("");

  useEffect(() => {
    if (!isNew) {
      void loadStyle();
    }
  }, [id]);

  async function loadStyle() {
    try {
      const data = await getWritingStyle(id!);
      setFormData(data);
    } catch (e) {
      setError("加载失败");
    } finally {
      setLoading(false);
    }
  }

  async function onSave() {
    if (!formData.name?.trim()) {
      setError("请填写文风名称");
      return;
    }
    setBusy(true);
    try {
      if (isNew) {
        await createWritingStyle(formData);
      } else {
        await updateWritingStyle(id!, formData);
      }
      nav("/writing-styles");
    } catch (e) {
      setError("保存失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleAnalyze() {
    if (!analysisText.trim() || analysisText.length < 50) {
      alert("请输入至少 50 字的选段进行分析");
      return;
    }
    setBusy(true);
    try {
      const result = await analyzeSnippet(analysisText);
      mergeAnalysis(result);
      if (analysisText && !formData.snippets?.includes(analysisText)) {
        setFormData(prev => ({
          ...prev,
          snippets: [...(prev.snippets || []), analysisText]
        }));
      }
      setAnalyzeText("");
    } catch (e) {
      alert("分析失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleSearchAuthor() {
    if (!authorSearch.trim()) return;
    setBusy(true);
    try {
      const results = await searchAuthors(authorSearch);
      setAuthorResults(results);
      setAiStep("SELECT_AUTHOR");
    } catch (e) {
      alert("搜索作者失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleSelectAuthor(author: AuthorSearchResult) {
    setSelectedAuthor(author);
    setSelectedWorks(author.works || []);
    setAiStep("SELECT_WORKS");
  }

  async function handleFetchSnippets() {
    if (!selectedAuthor || selectedWorks.length === 0) return;
    setBusy(true);
    try {
      const snippets = await fetchSnippets(selectedAuthor.name, selectedWorks);
      setFetchedSnippets(snippets);
      setAiStep("EDIT_SNIPPETS");
    } catch (e) {
      alert("获取片段失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleAnalyzeSnippets() {
    if (fetchedSnippets.length === 0) return;
    setBusy(true);
    try {
      const combinedText = fetchedSnippets.join("\n\n");
      const result = await analyzeSnippet(combinedText);
      mergeAnalysis(result);
      
      // 更新参考作者和片段
      setFormData(prev => ({ 
        ...prev, 
        reference_author: selectedAuthor?.name,
        snippets: Array.from(new Set([...(prev.snippets || []), ...fetchedSnippets]))
      }));
      
      // 重置 AI 提取状态
      resetAiSteps();
    } catch (e) {
      alert("分析失败");
    } finally {
      setBusy(false);
    }
  }

  function resetAiSteps() {
    setAiStep("IDLE");
    setAuthorResults([]);
    setSelectedAuthor(null);
    setSelectedWorks([]);
    setFetchedSnippets([]);
    setAuthorSearch("");
  }

  function mergeAnalysis(result: Partial<WritingStyle>) {
    setFormData(prev => ({
      ...prev,
      lexicon: {
        tags: Array.from(new Set([...(prev.lexicon?.tags || []), ...(result.lexicon?.tags || [])])),
        rules: Array.from(new Set([...(prev.lexicon?.rules || []), ...(result.lexicon?.rules || [])])),
        forbidden: Array.from(new Set([...(prev.lexicon?.forbidden || []), ...(result.lexicon?.forbidden || [])])),
      },
      structure: {
        ...prev.structure,
        ...result.structure,
        rules: Array.from(new Set([...(prev.structure?.rules || []), ...(result.structure?.rules || [])])),
      },
      tone: {
        ...prev.tone,
        ...result.tone,
        primary: Array.from(new Set([...(prev.tone?.primary || []), ...(result.tone?.primary || [])])),
        rules: Array.from(new Set([...(prev.tone?.rules || []), ...(result.tone?.rules || [])])),
      },
      rhetoric: {
        ...prev.rhetoric,
        types: { ...(prev.rhetoric?.types || {}), ...(result.rhetoric?.types || {}) },
        rules: Array.from(new Set([...(prev.rhetoric?.rules || []), ...(result.rhetoric?.rules || [])])),
      },
      negative_prompts: Array.from(new Set([...(prev.negative_prompts || []), ...(result.negative_prompts || [])])),
      snippets: Array.from(new Set([...(prev.snippets || []), ...(result.snippets || [])])),
    }));
  }

  if (loading) return (
    <div className="flex h-[60vh] items-center justify-center">
      <Loader2 className="h-8 w-8 animate-spin text-primary" />
    </div>
  );

  return (
    <div className="novel-shell">
      <div className="novel-container max-w-5xl space-y-6 pb-20">
        <header className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Button variant="ghost" size="icon" onClick={() => nav("/writing-styles")}>
              <ArrowLeft className="h-5 w-5" />
            </Button>
            <div>
              <h1 className="text-2xl font-bold tracking-tight">{isNew ? "创建新文风" : "编辑文风"}</h1>
              <p className="text-sm text-muted-foreground font-medium">通过 AI 提取和人工微调，定制专属写作气质。</p>
            </div>
          </div>
          <Button onClick={onSave} disabled={busy} className="gap-2 font-bold px-6 shadow-lg shadow-primary/20">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            保存文风
          </Button>
        </header>

        {error && (
          <div className="rounded-xl border border-destructive/20 bg-destructive/5 p-4 text-sm text-destructive flex items-center gap-3">
            <AlertCircle className="h-4 w-4" />
            {error}
          </div>
        )}

        <div className="grid gap-6 lg:grid-cols-[1fr_350px]">
          <div className="space-y-6">
            {/* 基础信息 */}
            <Card className="glass-panel-subtle">
              <CardHeader className="pb-4">
                <CardTitle className="text-lg flex items-center gap-2">
                  <Type className="h-5 w-5 text-primary" />
                  基础信息
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label className="font-bold">文风名称</Label>
                    <Input 
                      placeholder="例如：冷峻硬核风格" 
                      value={formData.name} 
                      onChange={(e: React.ChangeEvent<HTMLInputElement>) => setFormData(prev => ({ ...prev, name: e.target.value }))}
                      className="field-shell"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label className="font-bold">参考作者 (可选)</Label>
                    <Input 
                      placeholder="例如：余华" 
                      value={formData.reference_author} 
                      onChange={(e: React.ChangeEvent<HTMLInputElement>) => setFormData(prev => ({ ...prev, reference_author: e.target.value }))}
                      className="field-shell"
                    />
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* 词库与分析 */}
            <div className="grid gap-6 sm:grid-cols-2">
              <Card className="glass-panel-subtle">
                <CardHeader className="pb-3">
                  <CardTitle className="text-base flex items-center gap-2">
                    <BookOpen className="h-4 w-4 text-primary" />
                    词库特征
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="space-y-2">
                    <Label className="text-xs font-bold text-muted-foreground">词汇标签</Label>
                    <div className="flex flex-wrap gap-1.5 min-h-[32px] p-2 rounded-lg bg-muted border border-dashed">
                      {formData.lexicon?.tags?.map((t, i) => (
                        <Badge key={i} variant="secondary" className="gap-1 px-2 py-0.5 text-[10px] font-bold">
                          {t}
                          <button onClick={() => setFormData(prev => ({
                            ...prev,
                            lexicon: { ...prev.lexicon!, tags: prev.lexicon!.tags.filter((_, idx) => idx !== i) }
                          }))} className="hover:text-destructive">×</button>
                        </Badge>
                      ))}
                      {formData.lexicon?.tags?.length === 0 && <span className="text-[10px] text-muted-foreground italic">暂无标签</span>}
                    </div>
                    <div className="flex gap-1.5">
                      <Input 
                        placeholder="回车添加标签" 
                        className="h-7 text-[10px] field-shell"
                        value={newLexiconTag}
                        onChange={(e) => setNewLexiconTag(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && newLexiconTag.trim()) {
                            if (!formData.lexicon?.tags?.includes(newLexiconTag.trim())) {
                              setFormData(prev => ({
                                ...prev,
                                lexicon: { ...prev.lexicon!, tags: [...(prev.lexicon!.tags || []), newLexiconTag.trim()] }
                              }));
                            }
                            setNewLexiconTag("");
                          }
                        }}
                      />
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label className="text-xs font-bold text-muted-foreground">具体词汇要求</Label>
                    <div className="space-y-1">
                      {formData.lexicon?.rules?.map((r, i) => (
                        <div key={i} className="flex items-start gap-2 text-xs group">
                          <span className="mt-1 text-primary">•</span>
                          <span className="flex-1 leading-relaxed">{r}</span>
                          <button onClick={() => setFormData(prev => ({
                            ...prev,
                            lexicon: { ...prev.lexicon!, rules: prev.lexicon!.rules.filter((_, idx) => idx !== i) }
                          }))} className="opacity-0 group-hover:opacity-100 text-destructive text-[10px]">删除</button>
                        </div>
                      ))}
                    </div>
                    <div className="flex gap-2">
                      <Input 
                        placeholder="添加一条具体规则..." 
                        className="h-8 text-[10px] field-shell"
                        value={newLexiconRule}
                        onChange={(e) => setNewLexiconRule(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && newLexiconRule.trim()) {
                            setFormData(prev => ({
                              ...prev,
                              lexicon: { ...prev.lexicon!, rules: [...(prev.lexicon!.rules || []), newLexiconRule.trim()] }
                            }));
                            setNewLexiconRule("");
                          }
                        }}
                      />
                      <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => {
                        if (newLexiconRule.trim()) {
                          setFormData(prev => ({
                            ...prev,
                            lexicon: { ...prev.lexicon!, rules: [...(prev.lexicon!.rules || []), newLexiconRule.trim()] }
                          }));
                          setNewLexiconRule("");
                        }
                      }}>
                        <Plus className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card className="glass-panel-subtle">
                <CardHeader className="pb-3">
                  <CardTitle className="text-base flex items-center gap-2">
                    <Type className="h-4 w-4 text-primary" />
                    语句结构
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1">
                      <Label className="text-[10px] font-bold text-muted-foreground uppercase">平均字数</Label>
                      <Input 
                        type="number" 
                        value={formData.structure?.sentence_length || ""} 
                        onChange={(e: React.ChangeEvent<HTMLInputElement>) => setFormData(prev => ({ ...prev, structure: { ...prev.structure!, sentence_length: Number(e.target.value) } }))}
                        className="h-8 text-xs font-bold"
                      />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-[10px] font-bold text-muted-foreground uppercase">复杂度</Label>
                      <Input 
                        value={formData.structure?.complexity || ""} 
                        onChange={(e: React.ChangeEvent<HTMLInputElement>) => setFormData(prev => ({ ...prev, structure: { ...prev.structure!, complexity: e.target.value } }))}
                        className="h-8 text-xs font-bold"
                      />
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label className="text-xs font-bold text-muted-foreground">结构要求</Label>
                    <div className="space-y-1">
                      {formData.structure?.rules?.map((r, i) => (
                        <div key={i} className="flex items-start gap-2 text-xs group">
                          <span className="mt-1 text-primary">•</span>
                          <span className="flex-1 leading-relaxed">{r}</span>
                          <button onClick={() => setFormData(prev => ({
                            ...prev,
                            structure: { ...prev.structure!, rules: prev.structure!.rules.filter((_, idx) => idx !== i) }
                          }))} className="opacity-0 group-hover:opacity-100 text-destructive text-[10px]">删除</button>
                        </div>
                      ))}
                    </div>
                    <div className="flex gap-2">
                      <Input 
                        placeholder="添加结构要求..." 
                        className="h-8 text-[10px] field-shell"
                        value={newStructureRule}
                        onChange={(e) => setNewStructureRule(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && newStructureRule.trim()) {
                            setFormData(prev => ({
                              ...prev,
                              structure: { ...prev.structure!, rules: [...(prev.structure!.rules || []), newStructureRule.trim()] }
                            }));
                            setNewStructureRule("");
                          }
                        }}
                      />
                      <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => {
                        if (newStructureRule.trim()) {
                          setFormData(prev => ({
                            ...prev,
                            structure: { ...prev.structure!, rules: [...(prev.structure!.rules || []), newStructureRule.trim()] }
                          }));
                          setNewStructureRule("");
                        }
                      }}>
                        <Plus className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>

            <div className="grid gap-6 sm:grid-cols-2">
              <Card className="glass-panel-subtle">
                <CardHeader className="pb-3">
                  <CardTitle className="text-base flex items-center gap-2">
                    <MessageSquare className="h-4 w-4 text-primary" />
                    语气特色
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="space-y-2">
                    <Label className="text-xs font-bold text-muted-foreground">主要语气</Label>
                    <div className="flex flex-wrap gap-1.5 min-h-[32px] p-2 rounded-lg bg-muted border border-dashed">
                      {formData.tone?.primary?.map((t, i) => (
                        <Badge key={i} variant="outline" className="gap-1 px-2 py-0.5 text-[10px] font-bold border-primary/30 text-primary">
                          {t}
                          <button onClick={() => setFormData(prev => ({
                            ...prev,
                            tone: { ...prev.tone!, primary: prev.tone!.primary.filter((_, idx) => idx !== i) }
                          }))} className="hover:text-destructive">×</button>
                        </Badge>
                      ))}
                      {formData.tone?.primary?.length === 0 && <span className="text-[10px] text-muted-foreground italic">暂无语气</span>}
                    </div>
                    <div className="flex gap-1.5">
                      <Input 
                        placeholder="添加语气标签" 
                        className="h-7 text-[10px] field-shell"
                        value={newTonePrimary}
                        onChange={(e) => setNewTonePrimary(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && newTonePrimary.trim()) {
                            if (!formData.tone?.primary?.includes(newTonePrimary.trim())) {
                              setFormData(prev => ({
                                ...prev,
                                tone: { ...prev.tone!, primary: [...(prev.tone!.primary || []), newTonePrimary.trim()] }
                              }));
                            }
                            setNewTonePrimary("");
                          }
                        }}
                      />
                    </div>
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs font-bold text-muted-foreground">语气描述</Label>
                    <Textarea 
                      value={formData.tone?.description || ""} 
                      onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setFormData(prev => ({ ...prev, tone: { ...prev.tone!, description: e.target.value } }))}
                      placeholder="对整体语气的详细描述..."
                      className="text-xs leading-relaxed min-h-[80px] bg-muted"
                    />
                  </div>
                  <div className="space-y-2">
                     <Label className="text-xs font-bold text-muted-foreground">语气要求</Label>
                     <div className="space-y-1">
                       {formData.tone?.rules?.map((r, i) => (
                         <div key={i} className="flex items-start gap-2 text-xs group">
                           <span className="mt-1 text-primary">•</span>
                           <span className="flex-1 leading-relaxed">{r}</span>
                           <button onClick={() => setFormData(prev => ({
                             ...prev,
                             tone: { ...prev.tone!, rules: prev.tone!.rules.filter((_, idx) => idx !== i) }
                           }))} className="opacity-0 group-hover:opacity-100 text-destructive text-[10px]">删除</button>
                         </div>
                       ))}
                     </div>
                     <div className="flex gap-2 mt-2">
                       <Input 
                         placeholder="添加语气要求..." 
                         className="h-8 text-[10px] field-shell"
                         value={newToneRule}
                         onChange={(e) => setNewToneRule(e.target.value)}
                         onKeyDown={(e) => {
                           if (e.key === "Enter" && newToneRule.trim()) {
                             setFormData(prev => ({
                               ...prev,
                               tone: { ...prev.tone!, rules: [...(prev.tone!.rules || []), newToneRule.trim()] }
                             }));
                             setNewToneRule("");
                           }
                         }}
                       />
                       <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => {
                         if (newToneRule.trim()) {
                           setFormData(prev => ({
                             ...prev,
                             tone: { ...prev.tone!, rules: [...(prev.tone!.rules || []), newToneRule.trim()] }
                           }));
                           setNewToneRule("");
                         }
                       }}>
                         <Plus className="h-4 w-4" />
                       </Button>
                     </div>
                   </div>
                </CardContent>
              </Card>

              <Card className="glass-panel-subtle">
                <CardHeader className="pb-3">
                  <CardTitle className="text-base flex items-center gap-2">
                    <Quote className="h-4 w-4 text-primary" />
                    修辞偏好
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid grid-cols-2 gap-2">
                    {Object.entries(formData.rhetoric?.types || {}).map(([type, freq]) => (
                      <div key={type} className="flex items-center justify-between rounded bg-muted px-2 py-1 text-[10px] group">
                        <span className="font-bold">{type}</span>
                        <div className="flex items-center gap-1">
                          <span className={cn(
                            "px-1 rounded font-bold",
                            freq === "高" ? "text-orange-500 bg-orange-500/10" : 
                            freq === "中" ? "text-blue-500 bg-blue-500/10" : "text-slate-500 bg-slate-500/10"
                          )}>{freq}</span>
                          <button onClick={() => {
                            const next = { ...(formData.rhetoric?.types || {}) };
                            delete next[type];
                            setFormData(prev => ({ ...prev, rhetoric: { ...prev.rhetoric!, types: next } }));
                          }} className="opacity-0 group-hover:opacity-100 hover:text-destructive">×</button>
                        </div>
                      </div>
                    ))}
                  </div>
                  <div className="flex gap-1 items-center">
                    <Input 
                      placeholder="修辞手法" 
                      className="h-7 text-[10px] flex-1"
                      value={newRhetoricType}
                      onChange={(e) => setNewRhetoricType(e.target.value)}
                    />
                    <select 
                      className="h-7 text-[10px] rounded border bg-background px-1"
                      value={newRhetoricFreq}
                      onChange={(e) => setNewRhetoricFreq(e.target.value)}
                    >
                      <option value="高">高</option>
                      <option value="中">中</option>
                      <option value="低">低</option>
                    </select>
                    <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => {
                      if (newRhetoricType.trim()) {
                        setFormData(prev => ({
                          ...prev,
                          rhetoric: { 
                            ...prev.rhetoric!, 
                            types: { ...(prev.rhetoric?.types || {}), [newRhetoricType.trim()]: newRhetoricFreq } 
                          }
                        }));
                        setNewRhetoricType("");
                      }
                    }}>
                      <Plus className="h-3 w-3" />
                    </Button>
                  </div>
                  <div className="space-y-2">
                    <Label className="text-xs font-bold text-muted-foreground">修辞要求</Label>
                    <div className="space-y-1 text-xs">
                      {formData.rhetoric?.rules?.map((r, i) => (
                        <div key={i} className="flex items-start gap-2 group">
                          <span className="mt-1 text-primary">•</span>
                          <span className="flex-1 leading-relaxed">{r}</span>
                          <button onClick={() => setFormData(prev => ({
                            ...prev,
                            rhetoric: { ...prev.rhetoric!, rules: prev.rhetoric!.rules.filter((_, idx) => idx !== i) }
                          }))} className="opacity-0 group-hover:opacity-100 text-destructive text-[10px]">删除</button>
                        </div>
                      ))}
                    </div>
                    <div className="flex gap-2">
                      <Input 
                        placeholder="添加修辞要求..." 
                        className="h-8 text-[10px] field-shell"
                        value={newRhetoricRule}
                        onChange={(e) => setNewRhetoricRule(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && newRhetoricRule.trim()) {
                            setFormData(prev => ({
                              ...prev,
                              rhetoric: { ...prev.rhetoric!, rules: [...(prev.rhetoric!.rules || []), newRhetoricRule.trim()] }
                            }));
                            setNewRhetoricRule("");
                          }
                        }}
                      />
                      <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => {
                        if (newRhetoricRule.trim()) {
                          setFormData(prev => ({
                            ...prev,
                            rhetoric: { ...prev.rhetoric!, rules: [...(prev.rhetoric!.rules || []), newRhetoricRule.trim()] }
                          }));
                          setNewRhetoricRule("");
                        }
                      }}>
                        <Plus className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>

            {/* 负面示例 */}
            <Card className="glass-panel-subtle border-destructive/20">
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2 text-destructive">
                  <AlertCircle className="h-4 w-4" />
                  文风禁区 (Negative Prompts)
                </CardTitle>
                <CardDescription className="text-[11px] font-medium">列出在该文风下绝对禁止出现的表达方式或 AI 常见套话。</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex flex-wrap gap-2">
                  {formData.negative_prompts?.map((p, i) => (
                    <div key={i} className="flex items-center gap-2 rounded-lg bg-destructive/5 border border-destructive/10 px-3 py-1.5 text-xs text-destructive group">
                      <span>{p}</span>
                      <button onClick={() => setFormData(prev => ({
                        ...prev,
                        negative_prompts: prev.negative_prompts?.filter((_, idx) => idx !== i)
                      }))} className="opacity-50 hover:opacity-100">×</button>
                    </div>
                  ))}
                </div>
                <div className="flex gap-2">
                  <Input 
                    placeholder="添加禁止项..." 
                    className="h-9 text-xs field-shell"
                    onKeyDown={(e: React.KeyboardEvent<HTMLInputElement>) => {
                      if (e.key === "Enter") {
                        const val = (e.target as HTMLInputElement).value.trim();
                        if (val) {
                          setFormData(prev => ({ ...prev, negative_prompts: [...(prev.negative_prompts || []), val] }));
                          (e.target as HTMLInputElement).value = "";
                        }
                      }
                    }}
                  />
                </div>
              </CardContent>
            </Card>

            {/* 代表片段 */}
            <Card className="glass-panel-subtle">
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <Quote className="h-4 w-4 text-primary" />
                  代表段落 (Few-shot)
                </CardTitle>
                <CardDescription className="text-[11px] font-medium">提供 1-3 个最能代表该文风的段落，将作为 Few-shot 示例喂给 AI。</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-4">
                  {formData.snippets?.map((s, i) => (
                    <div key={i} className="relative group">
                      <Textarea 
                        value={s} 
                        onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => {
                          const next = [...(formData.snippets || [])];
                          next[i] = e.target.value;
                          setFormData(prev => ({ ...prev, snippets: next }));
                        }}
                        className="min-h-[100px] text-xs leading-relaxed bg-background/50"
                      />
                      <Button 
                        size="icon" 
                        variant="destructive" 
                        className="absolute -top-2 -right-2 h-6 w-6 rounded-full opacity-0 group-hover:opacity-100 transition-opacity"
                        onClick={() => setFormData(prev => ({
                          ...prev,
                          snippets: prev.snippets?.filter((_, idx) => idx !== i)
                        }))}
                      >
                        <Trash2 className="h-3 w-3" />
                      </Button>
                    </div>
                  ))}
                  <Button variant="outline" className="w-full border-dashed h-16 gap-2" onClick={() => setFormData(prev => ({
                    ...prev,
                    snippets: [...(prev.snippets || []), ""]
                  }))}>
                    <Plus className="h-4 w-4" />
                    添加新片段
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>

          <aside className="space-y-6">
            {/* AI 提取 */}
            <Card className="glass-panel shadow-xl shadow-primary/5 border-primary/20 sticky top-20">
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <Sparkles className="h-4 w-4 text-primary" />
                    AI 智能提取
                  </CardTitle>
                  {aiStep !== "IDLE" && (
                    <Button variant="ghost" size="icon" className="h-6 w-6" onClick={resetAiSteps}>
                      <RefreshCcw className="h-3 w-3" />
                    </Button>
                  )}
                </div>
              </CardHeader>
              <CardContent className="space-y-6">
                {aiStep === "IDLE" && (
                  <>
                    <div className="space-y-3">
                      <Label className="text-xs font-bold">联网搜索作者文风</Label>
                      <div className="flex gap-2">
                        <Input 
                          placeholder="作者名..." 
                          className="h-9 text-xs"
                          value={authorSearch}
                          onChange={(e: React.ChangeEvent<HTMLInputElement>) => setAuthorSearch(e.target.value)}
                          onKeyDown={(e: React.KeyboardEvent<HTMLInputElement>) => e.key === "Enter" && handleSearchAuthor()}
                        />
                        <Button size="sm" variant="secondary" className="h-9" onClick={handleSearchAuthor} disabled={busy || !authorSearch}>
                          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Search className="h-3.5 w-3.5" />}
                        </Button>
                      </div>
                    </div>

                    <Separator />

                    <div className="space-y-3">
                      <Label className="text-xs font-bold">从选段分析文风</Label>
                      <Textarea 
                        placeholder="在此粘贴一段具有代表性的文字（至少50字）..." 
                        className="min-h-[150px] text-xs resize-none bg-muted"
                        value={analysisText}
                        onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setAnalyzeText(e.target.value)}
                      />
                      <Button 
                        className="w-full gap-2 font-bold" 
                        onClick={handleAnalyze}
                        disabled={busy || !analysisText.trim()}
                      >
                        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                        开始 AI 分析
                      </Button>
                      <p className="text-[10px] text-center text-muted-foreground leading-relaxed">
                        AI 将自动分析词汇、句式、语气和修辞特色，并填充到左侧表单中。
                      </p>
                    </div>
                  </>
                )}

                {aiStep === "SELECT_AUTHOR" && (
                  <div className="space-y-4">
                    <Label className="text-xs font-bold">请选择目标作者</Label>
                    <div className="space-y-2 max-h-[400px] overflow-y-auto pr-2">
                      {authorResults.map((author, idx) => (
                        <div 
                          key={idx} 
                          className="p-3 rounded-lg border bg-muted hover:border-primary/50 cursor-pointer transition-colors group"
                          onClick={() => handleSelectAuthor(author)}
                        >
                          <div className="flex items-center justify-between mb-1">
                            <span className="font-bold text-sm">{author.name}</span>
                            <ChevronRight className="h-4 w-4 opacity-0 group-hover:opacity-100 transition-opacity" />
                          </div>
                          <p className="text-[10px] text-muted-foreground mb-2 line-clamp-2">{author.description}</p>
                          <div className="flex flex-wrap gap-1">
                            {author.works?.slice(0, 3).map((w, i) => (
                              <Badge key={i} variant="outline" className="text-[9px] px-1 py-0 h-4 border-muted-foreground/30">{w}</Badge>
                            ))}
                          </div>
                        </div>
                      ))}
                      <div 
                        className="p-3 rounded-lg border border-dashed hover:border-primary/50 cursor-pointer transition-colors text-center"
                        onClick={() => handleSelectAuthor({ name: authorSearch, works: [], description: "自定义作者" })}
                      >
                        <span className="text-xs font-medium text-muted-foreground">没有找到？直接分析“{authorSearch}”</span>
                      </div>
                    </div>
                  </div>
                )}

                {aiStep === "SELECT_WORKS" && selectedAuthor && (
                  <div className="space-y-4">
                    <div className="flex items-center justify-between">
                      <Label className="text-xs font-bold">选择参考作品 ({selectedAuthor.name})</Label>
                    </div>
                    <div className="space-y-2 max-h-[300px] overflow-y-auto pr-2">
                      {selectedAuthor.works?.map((work, idx) => (
                        <div 
                          key={idx} 
                          className={cn(
                            "flex items-center justify-between p-2 rounded border cursor-pointer transition-colors",
                            selectedWorks.includes(work) ? "bg-primary/5 border-primary/30" : "bg-muted border-transparent"
                          )}
                          onClick={() => {
                            if (selectedWorks.includes(work)) {
                              setSelectedWorks(prev => prev.filter(w => w !== work));
                            } else {
                              setSelectedWorks(prev => [...prev, work]);
                            }
                          }}
                        >
                          <span className="text-xs">{work}</span>
                          {selectedWorks.includes(work) ? <Check className="h-3 w-3 text-primary" /> : <div className="h-3 w-3" />}
                        </div>
                      ))}
                    </div>
                    
                    <div className="flex gap-2">
                      <Input 
                        placeholder="添加其他作品..." 
                        className="h-8 text-xs"
                        value={newWork}
                        onChange={(e) => setNewWork(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' && newWork.trim()) {
                            if (!selectedWorks.includes(newWork.trim())) {
                              setSelectedWorks(prev => [...prev, newWork.trim()]);
                              if (selectedAuthor && !selectedAuthor.works.includes(newWork.trim())) {
                                selectedAuthor.works.push(newWork.trim());
                              }
                            }
                            setNewWork("");
                          }
                        }}
                      />
                      <Button size="sm" variant="ghost" className="h-8 px-2" onClick={() => {
                        if (newWork.trim()) {
                          setSelectedWorks(prev => [...prev, newWork.trim()]);
                          setNewWork("");
                        }
                      }}>
                        <Plus className="h-3.5 w-3.5" />
                      </Button>
                    </div>

                    <Button 
                      className="w-full gap-2 font-bold" 
                      onClick={handleFetchSnippets}
                      disabled={busy || selectedWorks.length === 0}
                    >
                      {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                      获取名场面片段
                    </Button>
                  </div>
                )}

                {aiStep === "EDIT_SNIPPETS" && (
                  <div className="space-y-4">
                    <Label className="text-xs font-bold">核对提取到的片段</Label>
                    <div className="space-y-3 max-h-[500px] overflow-y-auto pr-2">
                      {fetchedSnippets.map((snippet, idx) => (
                        <div key={idx} className="relative group">
                          <Textarea 
                            value={snippet} 
                            onChange={(e) => {
                              const next = [...fetchedSnippets];
                              next[idx] = e.target.value;
                              setFetchedSnippets(next);
                            }}
                            className="text-[10px] min-h-[100px] bg-muted"
                          />
                          <Button 
                            size="icon" 
                            variant="ghost" 
                            className="absolute -top-1 -right-1 h-5 w-5 rounded-full text-destructive"
                            onClick={() => setFetchedSnippets(prev => prev.filter((_, i) => i !== idx))}
                          >
                            <X className="h-3 w-3" />
                          </Button>
                        </div>
                      ))}
                      <Button 
                        variant="outline" 
                        className="w-full border-dashed h-12 text-[10px]"
                        onClick={() => setFetchedSnippets(prev => [...prev, ""])}
                      >
                        添加片段
                      </Button>
                    </div>

                    <Button 
                      className="w-full gap-2 font-bold" 
                      onClick={handleAnalyzeSnippets}
                      disabled={busy || fetchedSnippets.filter(s => s.trim()).length === 0}
                    >
                      {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                      分析文风并填充
                    </Button>
                  </div>
                )}
              </CardContent>
            </Card>
          </aside>
        </div>
      </div>
    </div>
  );
}
