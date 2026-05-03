import React, { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, ArrowRight, Check, Loader2, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  drawWorldOptions,
  drawProtagonistOptions,
  drawCheatOptions,
} from "@/services/novelApi";
import { apiFetch } from "@/services/api";
import { ensureLlmReady } from "@/services/llmReady";

const BASE = "/api/novels";

// ─── 选项卡片组件 ───────────────────────────────────────────────────────────

function OptionCard({
  selected,
  onSelect,
  children,
}: {
  selected: boolean;
  onSelect: () => void;
  children: React.ReactNode;
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
      className={`w-full rounded-2xl border-2 p-4 text-left transition-all duration-200 hover:scale-[1.01] ${
        selected
          ? "border-primary bg-primary/8 shadow-[0_0_0_2px_theme(colors.primary)]"
          : "border-border bg-background hover:border-primary/40 hover:bg-primary/4"
      }`}
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <div
            className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 transition-all ${
              selected
                ? "border-primary bg-primary text-white"
                : "border-border bg-transparent"
            }`}
          >
            {selected && <Check className="size-3" />}
          </div>
        </div>
      </div>
      <div className="space-y-1">{children}</div>
    </div>
  );
}

// ─── 基础信息步骤 ─────────────────────────────────────────────────────────

const SUBJECTS = [
  "言情", "现言情感", "悬疑", "惊悚", "科幻", "游戏",
  "仙侠", "历史", "玄幻", "都市", "快穿", "成长", "校园", "职场", "家庭", "冒险",
];

const PLOTS = [
  "婚姻", "出轨", "娱乐圈", "重生", "穿越", "犯罪", "丧尸", "探险", "宫斗宅斗",
  "系统", "规则怪谈", "团宠", "先婚后爱", "追妻火葬场", "破镜重圆", "超能力/异能",
  "玄学风水", "种田", "直播", "萌宝", "鉴宝", "聊天群", "弹幕", "双向救赎",
  "替身", "强制爱", "全员恶人", "万人嫌黑化", "无限流", "读心术", "预知能力",
  "侦探推理", "全员读心", "逆袭成长", "网恋",
];

const MOODS = [
  "纯爱", "HE", "BE", "甜宠", "虐恋", "暗恋", "先虐后甜", "沙雕", "热血",
  "黑暗", "治愈", "救赎", "搞笑", "高能", "烧脑",
];

const BACKGROUNDS = [
  "都市", "校园", "古代", "仙侠", "星际", "西幻", "异世界", "现代", "民国", "未来",
];

interface BasicInfo {
  subjects: string[];
  plots: string[];
  moods: string[];
  backgrounds: string[];
  lengthType: "long" | "medium" | "short";
  targetChapters: number;
  notes: string;
}

function StepBasic({
  value,
  onChange,
}: {
  value: BasicInfo;
  onChange: (v: BasicInfo) => void;
}) {
  const LENGTH_DEFAULT_CHAPTERS: Record<BasicInfo["lengthType"], number> = {
    long: 500,
    medium: 300,
    short: 80,
  };

  function toggle(
    field: keyof Pick<BasicInfo, "subjects" | "plots" | "moods" | "backgrounds">,
    item: string,
    max: number
  ) {
    const arr = value[field];
    if (arr.includes(item)) {
      onChange({ ...value, [field]: arr.filter((x) => x !== item) });
      return;
    }
    if (max === 1) {
      // 单选项直接替换，避免“必须先取消再选择”的交互阻塞
      onChange({ ...value, [field]: [item] });
      return;
    }
    if (arr.length < max) {
      onChange({ ...value, [field]: [...arr, item] });
    }
  }

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <Label className="text-sm font-semibold">题材（必选，1项）</Label>
        <div className="flex flex-wrap gap-2">
          {SUBJECTS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => toggle("subjects", s, 1)}
              className={`rounded-full border px-3 py-1 text-sm font-medium transition-all ${
                value.subjects.includes(s)
                  ? "border-primary bg-primary/15 text-primary"
                  : "border-border bg-background text-foreground/70 hover:border-primary/50 hover:text-foreground"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-3">
        <Label className="text-sm font-semibold">
          核心情节
          <span className="ml-1 font-normal text-foreground/50">（可选，最多3项）</span>
        </Label>
        <div className="flex flex-wrap gap-2">
          {PLOTS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => toggle("plots", s, 3)}
              className={`rounded-full border px-3 py-1 text-sm font-medium transition-all ${
                value.plots.includes(s)
                  ? "border-accent bg-accent/15 text-accent"
                  : "border-border bg-background text-foreground/70 hover:border-accent/50 hover:text-foreground"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-3">
        <Label className="text-sm font-semibold">
          情绪/基调
          <span className="ml-1 font-normal text-foreground/50">（可选，最多3项）</span>
        </Label>
        <div className="flex flex-wrap gap-2">
          {MOODS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => toggle("moods", s, 3)}
              className={`rounded-full border px-3 py-1 text-sm font-medium transition-all ${
                value.moods.includes(s)
                  ? "border-cyan-500 bg-cyan-500/15 text-cyan-600 dark:text-cyan-300"
                  : "border-border bg-background text-foreground/70 hover:border-cyan-500/50 hover:text-foreground"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-3">
        <Label className="text-sm font-semibold">
          世界观背景
          <span className="ml-1 font-normal text-foreground/50">（可选，1项）</span>
        </Label>
        <div className="flex flex-wrap gap-2">
          {BACKGROUNDS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => toggle("backgrounds", s, 1)}
              className={`rounded-full border px-3 py-1 text-sm font-medium transition-all ${
                value.backgrounds.includes(s)
                  ? "border-violet-500 bg-violet-500/15 text-violet-600 dark:text-violet-300"
                  : "border-border bg-background text-foreground/70 hover:border-violet-500/50 hover:text-foreground"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label className="text-sm font-semibold">篇幅</Label>
          <div className="flex rounded-xl border border-border bg-background p-1">
            {(["long", "medium", "short"] as const).map((lt) => (
              <button
                key={lt}
                type="button"
                onClick={() =>
                  onChange({
                    ...value,
                    lengthType: lt,
                    targetChapters: LENGTH_DEFAULT_CHAPTERS[lt],
                  })
                }
                className={`flex-1 rounded-lg px-3 py-2 text-sm font-medium transition-all ${
                  value.lengthType === lt
                    ? "bg-primary/15 text-primary"
                    : "text-foreground/60 hover:text-foreground"
                }`}
              >
                {lt === "long" ? "长篇" : lt === "medium" ? "中篇" : "短篇"}
              </button>
            ))}
          </div>
        </div>
        <div className="space-y-2">
          <Label className="text-sm font-semibold">目标章节数</Label>
          <input
            type="number"
            min={1}
            max={3000}
            value={value.targetChapters}
            onChange={(e) =>
              onChange({ ...value, targetChapters: Math.max(1, parseInt(e.target.value) || 1) })
            }
            className="w-full rounded-xl border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary"
          />
        </div>
      </div>

      <div className="space-y-2">
        <Label className="text-sm font-semibold">
          创作备注
          <span className="ml-1 font-normal text-foreground/50">（可选，帮助 AI 理解你的想法）</span>
        </Label>
        <textarea
          value={value.notes}
          onChange={(e) => onChange({ ...value, notes: e.target.value })}
          placeholder="例如：想写一个关于救赎的故事，主角是一个被背叛过的杀手……"
          rows={3}
          className="w-full rounded-xl border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary placeholder:text-foreground/30"
        />
      </div>
    </div>
  );
}

// ─── 抽卡结果展示 ─────────────────────────────────────────────────────────

interface WorldOption {
  world_type: string;
  main_conflict: string;
  social_structure: string;
  cultural_features: string;
  unique_rules: string;
  visual_atmosphere: string;
}

interface ProtagonistOption {
  name: string;
  role_identity: string;
  core_desire: string;
  personality_traits: string[];
  starting_ability: string;
  backstory_hint: string;
  secret_identity: string;
}

interface CheatOption {
  cheat_name: string;
  cheat_type: string;
  power_level: string;
  core_mechanic: string;
  growth_limit: string;
  initial_benefit: string;
  hidden_twist: string;
}

function asObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((v): v is string => typeof v === "string");
}

function normalizeWorldOptions(raw: unknown): WorldOption[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => {
    const o = asObject(item);
    return {
      world_type: asString(o.world_type),
      main_conflict: asString(o.main_conflict),
      social_structure: asString(o.social_structure),
      cultural_features: asString(o.cultural_features),
      unique_rules: asString(o.unique_rules),
      visual_atmosphere: asString(o.visual_atmosphere),
    };
  }).filter((o) => o.world_type || o.main_conflict || o.social_structure).slice(0, 6);
}

function normalizeProtagonistOptions(raw: unknown): ProtagonistOption[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => {
    const o = asObject(item);
    return {
      name: asString(o.name),
      role_identity: asString(o.role_identity),
      core_desire: asString(o.core_desire),
      personality_traits: asStringArray(o.personality_traits),
      starting_ability: asString(o.starting_ability),
      backstory_hint: asString(o.backstory_hint),
      secret_identity: asString(o.secret_identity),
    };
  }).filter((o) => o.name || o.role_identity || o.core_desire).slice(0, 6);
}

function normalizeCheatOptions(raw: unknown): CheatOption[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => {
    const o = asObject(item);
    return {
      cheat_name: asString(o.cheat_name),
      cheat_type: asString(o.cheat_type),
      power_level: asString(o.power_level),
      core_mechanic: asString(o.core_mechanic),
      growth_limit: asString(o.growth_limit),
      initial_benefit: asString(o.initial_benefit),
      hidden_twist: asString(o.hidden_twist),
    };
  }).filter((o) => o.cheat_name || o.core_mechanic).slice(0, 6);
}

function WorldCard({
  option,
  selected,
  onSelect,
}: {
  option: WorldOption;
  selected: boolean;
  onSelect: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <OptionCard selected={selected} onSelect={onSelect}>
      <div className="mb-2 text-sm font-bold text-primary">{option.world_type}</div>
      <div className={`${expanded ? "space-y-2" : "line-clamp-2"} text-xs text-foreground/70`}>
        <div>
          <span className="font-semibold text-foreground/80">核心矛盾：</span>
          {option.main_conflict}
        </div>
        <div>
          <span className="font-semibold text-foreground/80">社会结构：</span>
          {option.social_structure}
        </div>
        <div>
          <span className="font-semibold text-foreground/80">文化特色：</span>
          {option.cultural_features}
        </div>
        <div>
          <span className="font-semibold text-foreground/80">特殊规则：</span>
          {option.unique_rules}
        </div>
        <div className="mt-1 flex flex-wrap gap-1">
          {(option.visual_atmosphere || "").split(/[、,]/).filter(Boolean).map((kw) => (
            <span
              key={kw}
              className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary"
            >
              {kw.trim()}
            </span>
          ))}
        </div>
      </div>
      <button
        type="button"
        className="mt-2 text-[11px] font-semibold text-primary hover:underline"
        onClick={(e) => {
          e.stopPropagation();
          setExpanded((v) => !v);
        }}
      >
        {expanded ? "收起详情" : "展开详情"}
      </button>
    </OptionCard>
  );
}

function ProtagonistCard({
  option,
  selected,
  onSelect,
}: {
  option: ProtagonistOption;
  selected: boolean;
  onSelect: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <OptionCard selected={selected} onSelect={onSelect}>
      <div className="mb-1 flex items-center gap-2">
        <span className="text-base font-bold text-foreground">{option.name}</span>
        <span className="rounded-full bg-accent/15 px-2 py-0.5 text-[10px] font-medium text-accent">
          {option.role_identity}
        </span>
      </div>
      <div className="mb-1 text-xs font-medium text-primary">欲望：{option.core_desire}</div>
      <div className="mb-2 flex flex-wrap gap-1">
        {option.personality_traits.map((t) => (
          <span
            key={t}
            className="rounded-full bg-violet-500/12 px-2 py-0.5 text-[10px] text-violet-600 dark:text-violet-300"
          >
            {t}
          </span>
        ))}
      </div>
      <div className={`${expanded ? "space-y-1" : "line-clamp-2"} text-xs text-foreground/60`}>
        <div>
          <span className="font-semibold text-foreground/80">初始能力：</span>
          {option.starting_ability}
        </div>
        <div>
          <span className="font-semibold text-foreground/80">背景线索：</span>
          {option.backstory_hint}
        </div>
        {option.secret_identity && (
          <div>
            <span className="font-semibold text-foreground/80">隐藏身份：</span>
            {option.secret_identity}
          </div>
        )}
      </div>
      <button
        type="button"
        className="mt-2 text-[11px] font-semibold text-primary hover:underline"
        onClick={(e) => {
          e.stopPropagation();
          setExpanded((v) => !v);
        }}
      >
        {expanded ? "收起详情" : "展开详情"}
      </button>
    </OptionCard>
  );
}

function CheatCard({
  option,
  selected,
  onSelect,
}: {
  option: CheatOption;
  selected: boolean;
  onSelect: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const typeColors: Record<string, string> = {
    "系统": "bg-emerald-500/15 text-emerald-600 dark:text-emerald-300",
    "异能": "bg-orange-500/15 text-orange-600 dark:text-orange-300",
    "传承": "bg-purple-500/15 text-purple-600 dark:text-purple-300",
    "道具": "bg-amber-500/15 text-amber-600 dark:text-amber-300",
    "契约": "bg-red-500/15 text-red-600 dark:text-red-300",
    "知识": "bg-blue-500/15 text-blue-600 dark:text-blue-300",
    "其他": "bg-slate-500/15 text-slate-600 dark:text-slate-300",
  };
  const colorClass = typeColors[option.cheat_type] || typeColors["其他"];
  return (
    <OptionCard selected={selected} onSelect={onSelect}>
      <div className="mb-1 flex items-center gap-2">
        <span className="text-base font-bold text-foreground">{option.cheat_name}</span>
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${colorClass}`}>
          {option.cheat_type} · {option.power_level}
        </span>
      </div>
      <div className={`${expanded ? "mb-2" : "line-clamp-2"} text-xs text-foreground/60`}>
        <span className="font-semibold text-foreground/80">机制：</span>
        {option.core_mechanic}
      </div>
      <div className={`${expanded ? "space-y-1" : "line-clamp-2"} text-xs text-foreground/60`}>
        <div>
          <span className="font-semibold text-foreground/80">成长代价：</span>
          {option.growth_limit}
        </div>
        <div>
          <span className="font-semibold text-foreground/80">初始收益：</span>
          {option.initial_benefit}
        </div>
        {option.hidden_twist && (
          <div>
            <span className="font-semibold text-foreground/80">隐藏隐患：</span>
            {option.hidden_twist}
          </div>
        )}
      </div>
      <button
        type="button"
        className="mt-2 text-[11px] font-semibold text-primary hover:underline"
        onClick={(e) => {
          e.stopPropagation();
          setExpanded((v) => !v);
        }}
      >
        {expanded ? "收起详情" : "展开详情"}
      </button>
    </OptionCard>
  );
}

// ─── 确认页 ────────────────────────────────────────────────────────────────

function StepConfirm({
  basic,
  world,
  protagonist,
  cheat,
  busy,
  onLaunch,
}: {
  basic: BasicInfo;
  world: WorldOption | null;
  protagonist: ProtagonistOption | null;
  cheat: CheatOption | null;
  busy: boolean;
  onLaunch: () => void;
}) {
  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-border bg-gradient-to-br from-primary/5 to-accent/5 p-5">
        <h3 className="mb-3 font-bold text-primary">基础信息</h3>
        <div className="space-y-1 text-sm text-foreground/80">
          <div>
            <span className="font-medium text-foreground">题材：</span>
            {basic.subjects.join("、")}
          </div>
          {basic.plots.length > 0 && (
            <div>
              <span className="font-medium text-foreground">情节：</span>
              {basic.plots.join("、")}
            </div>
          )}
          {basic.moods.length > 0 && (
            <div>
              <span className="font-medium text-foreground">情绪：</span>
              {basic.moods.join("、")}
            </div>
          )}
          {basic.backgrounds.length > 0 && (
            <div>
              <span className="font-medium text-foreground">背景：</span>
              {basic.backgrounds.join("、")}
            </div>
          )}
          <div>
            <span className="font-medium text-foreground">篇幅：</span>
            {basic.lengthType === "long" ? "长篇" : basic.lengthType === "medium" ? "中篇" : "短篇"}
            {" · "}{basic.targetChapters} 章
          </div>
          {basic.notes && (
            <div>
              <span className="font-medium text-foreground">备注：</span>
              {basic.notes}
            </div>
          )}
        </div>
      </div>

      {world && (
        <div className="rounded-2xl border border-border bg-gradient-to-br from-cyan-500/5 to-transparent p-5">
          <h3 className="mb-2 font-bold text-cyan-600 dark:text-cyan-300">世界观设定</h3>
          <div className="space-y-1 text-sm text-foreground/80">
            <div className="font-medium text-foreground">{world.world_type}</div>
            <div>{world.main_conflict}</div>
            <div className="text-xs text-foreground/50">{world.social_structure}</div>
          </div>
        </div>
      )}

      {protagonist && (
        <div className="rounded-2xl border border-border bg-gradient-to-br from-accent/5 to-transparent p-5">
          <h3 className="mb-2 font-bold text-accent">主角设定</h3>
          <div className="space-y-1 text-sm text-foreground/80">
            <div className="font-medium text-foreground">
              {protagonist.name} · {protagonist.role_identity}
            </div>
            <div>欲望：{protagonist.core_desire}</div>
            <div className="text-xs text-foreground/50">{protagonist.starting_ability}</div>
          </div>
        </div>
      )}

      {cheat && (
        <div className="rounded-2xl border border-border bg-gradient-to-br from-amber-500/5 to-transparent p-5">
          <h3 className="mb-2 font-bold text-amber-600 dark:text-amber-300">金手指设定</h3>
          <div className="space-y-1 text-sm text-foreground/80">
            <div className="font-medium text-foreground">
              {cheat.cheat_name}
              <span className="ml-2 text-xs font-normal text-foreground/50">
                {cheat.cheat_type} · {cheat.power_level}
              </span>
            </div>
            <div className="text-xs text-foreground/50">{cheat.core_mechanic}</div>
          </div>
        </div>
      )}

      <Button
        size="lg"
        className="w-full gap-2 font-bold"
        onClick={onLaunch}
        disabled={busy}
      >
        {busy ? (
          <>
            <Loader2 className="size-4 animate-spin" />
            正在创建...
          </>
        ) : (
          <>
            <Sparkles className="size-4" />
            开始创作
          </>
        )}
      </Button>
    </div>
  );
}

// ─── 主组件 ───────────────────────────────────────────────────────────────

const STEP_LABELS = ["基本信息", "世界观", "主角", "金手指", "确认"];

export function AICreateWizard(props: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (novelId: string) => void;
}) {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Step 0 data
  const [basic, setBasic] = useState<BasicInfo>({
    subjects: [],
    plots: [],
    moods: [],
    backgrounds: [],
    lengthType: "long",
    targetChapters: 300,
    notes: "",
  });

  // Draw results
  const [worldOptions, setWorldOptions] = useState<WorldOption[]>([]);
  const [protagonistOptions, setProtagonistOptions] = useState<ProtagonistOption[]>([]);
  const [cheatOptions, setCheatOptions] = useState<CheatOption[]>([]);

  // Selected
  const [selectedWorld, setSelectedWorld] = useState<WorldOption | null>(null);
  const [selectedProtagonist, setSelectedProtagonist] = useState<ProtagonistOption | null>(null);
  const [selectedCheat, setSelectedCheat] = useState<CheatOption | null>(null);

  // Drawing state
  const [drawingWorld, setDrawingWorld] = useState(false);
  const [drawingProtagonist, setDrawingProtagonist] = useState(false);
  const [drawingCheat, setDrawingCheat] = useState(false);

  // Reset on open
  useEffect(() => {
    if (props.open) {
      setStep(0);
      setErr(null);
      setWorldOptions([]);
      setProtagonistOptions([]);
      setCheatOptions([]);
      setSelectedWorld(null);
      setSelectedProtagonist(null);
      setSelectedCheat(null);
      setBasic({
        subjects: [],
        plots: [],
        moods: [],
        backgrounds: [],
        lengthType: "long",
        targetChapters: 300,
        notes: "",
      });
    }
  }, [props.open]);

  // ── Draw helpers ───────────────────────────────────────────────────────

  const drawWorld = useCallback(async () => {
    if (!basic.subjects.length && !basic.plots.length && !basic.moods.length && !basic.backgrounds.length) {
      setErr("请先选择至少一个标签");
      return;
    }
    setDrawingWorld(true);
    setErr(null);
    try {
      const r = await drawWorldOptions({
        styles: [...basic.subjects, ...basic.plots, ...basic.moods],
        subjects: basic.subjects,
        backgrounds: basic.backgrounds,
        moods: basic.moods,
      });
      const opts = normalizeWorldOptions(r.options);
      if (!opts.length) throw new Error("未返回有效选项");
      setWorldOptions(opts);
      setSelectedWorld(opts[0]);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "生成世界观选项失败");
    } finally {
      setDrawingWorld(false);
    }
  }, [basic]);

  const drawProtagonist = useCallback(async () => {
    setDrawingProtagonist(true);
    setErr(null);
    try {
      const r = await drawProtagonistOptions({
        styles: [...basic.subjects, ...basic.plots],
        subjects: basic.subjects,
        protagonist_count: 1,
        selected_world: selectedWorld as Record<string, unknown> | null,
      });
      const opts = normalizeProtagonistOptions(r.options);
      if (!opts.length) throw new Error("未返回有效选项");
      setProtagonistOptions(opts);
      setSelectedProtagonist(opts[0]);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "生成主角选项失败");
    } finally {
      setDrawingProtagonist(false);
    }
  }, [basic, selectedWorld]);

  const drawCheat = useCallback(async () => {
    setDrawingCheat(true);
    setErr(null);
    try {
      const plotType = basic.plots[0] || basic.subjects[0] || "";
      const r = await drawCheatOptions({
        styles: [...basic.subjects, ...basic.plots],
        subjects: basic.subjects,
        plot_type: plotType,
        selected_world: selectedWorld as Record<string, unknown> | null,
        selected_protagonist: selectedProtagonist as Record<string, unknown> | null,
      });
      const opts = normalizeCheatOptions(r.options);
      if (!opts.length) throw new Error("未返回有效选项");
      setCheatOptions(opts);
      setSelectedCheat(opts[0]);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "生成金手指选项失败");
    } finally {
      setDrawingCheat(false);
    }
  }, [basic, selectedWorld, selectedProtagonist]);

  // ── Navigation ───────────────────────────────────────────────────────

  function canGoNext(): boolean {
    if (step === 0) return basic.subjects.length > 0;
    if (step === 1) return selectedWorld !== null;
    if (step === 2) return selectedProtagonist !== null;
    if (step === 3) return selectedCheat !== null;
    return true;
  }

  async function handleNext() {
    if (step === 0) {
      // Go to world draw step, trigger auto-draw
      setStep(1);
      await drawWorld();
    } else if (step === 1) {
      setStep(2);
      await drawProtagonist();
    } else if (step === 2) {
      setStep(3);
      await drawCheat();
    } else if (step === 3) {
      setStep(4);
    }
  }

  function handleBack() {
    if (step > 0) setStep(step - 1);
  }

  // ── Launch ─────────────────────────────────────────────────────────────

  async function handleLaunch() {
    const ready = await ensureLlmReady();
    if (!ready) return;
    setBusy(true);
    setErr(null);
    try {
      const allTags = [
        ...basic.subjects,
        ...basic.plots,
        ...basic.moods,
        ...basic.backgrounds,
      ].filter(Boolean);
      const r = await apiFetch(`${BASE}/ai-create-and-start`, {
        method: "POST",
        body: JSON.stringify({
          styles: allTags,
          subjects: basic.subjects,
          plots: basic.plots,
          moods: basic.moods,
          backgrounds: basic.backgrounds,
          target_chapters: basic.targetChapters,
          notes: basic.notes,
          length_type: basic.lengthType,
          target_generate_chapters: 0,
          selected_world: selectedWorld || null,
          selected_protagonist: selectedProtagonist || null,
          selected_cheat: selectedCheat || null,
        }),
      });
      if (!r.ok) throw new Error(await r.text());
      const data = (await r.json()) as { id?: string };
      props.onOpenChange(false);
      if (data.id) {
        props.onCreated(data.id);
      } else {
        navigate("/tasks");
      }
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "创建失败");
    } finally {
      setBusy(false);
    }
  }

  // ─── Render ───────────────────────────────────────────────────────────

  const canProceedToNext = canGoNext();
  const isLoadingDraw = drawingWorld || drawingProtagonist || drawingCheat;

  return (
    <Dialog open={props.open} onOpenChange={props.onOpenChange}>
      <DialogContent className="max-w-3xl overflow-y-auto" style={{ maxHeight: "90vh" }}>
        <DialogHeader className="pb-2">
          <div className="flex items-center justify-between">
            <DialogTitle className="text-lg font-bold">
              <span className="text-primary">✨</span> AI 一键建书
            </DialogTitle>
            {/* Step indicator */}
            <div className="flex items-center gap-1">
              {STEP_LABELS.map((label, i) => (
                <React.Fragment key={i}>
                  <div className="flex items-center gap-1">
                    <div
                      className={`flex h-6 w-6 items-center justify-center rounded-full text-[10px] font-bold transition-all ${
                        i < step
                          ? "bg-primary text-white"
                          : i === step
                          ? "border-2 border-primary text-primary"
                          : "border-2 border-border/50 text-foreground/30"
                      }`}
                    >
                      {i < step ? <Check className="size-3" /> : i + 1}
                    </div>
                    <span
                      className={`hidden text-xs font-medium sm:block ${
                        i === step ? "text-primary" : "text-foreground/30"
                      }`}
                    >
                      {label}
                    </span>
                  </div>
                  {i < STEP_LABELS.length - 1 && (
                    <div className={`mx-1 h-px w-4 ${i < step ? "bg-primary" : "bg-border/50"}`} />
                  )}
                </React.Fragment>
              ))}
            </div>
          </div>
        </DialogHeader>

        {/* Error banner */}
        {err && (
          <div className="rounded-xl border border-destructive/30 bg-destructive/8 px-4 py-2.5 text-sm text-destructive">
            {err}
          </div>
        )}

        {/* ── Step 0: Basic Info ─────────────────────────────────────── */}
        {step === 0 && (
          <div className="pb-2">
            <StepBasic value={basic} onChange={setBasic} />
          </div>
        )}

        {/* ── Step 1: World Draw ────────────────────────────────────── */}
        {step === 1 && (
          <div className="space-y-4 pb-2">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="font-bold text-foreground">世界观设定</h3>
                <p className="text-xs text-foreground/50">
                  选择题材后 AI 为你生成 6 个风格迥异的世界观，默认折叠详情，按需展开
                </p>
              </div>
              <Button
                size="sm"
                variant="outline"
                onClick={drawWorld}
                disabled={drawingWorld}
                className="gap-1.5"
              >
                {drawingWorld ? (
                  <Loader2 className="size-3 animate-spin" />
                ) : (
                  <Sparkles className="size-3" />
                )}
                重新抽卡
              </Button>
            </div>

            {drawingWorld && (
              <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-primary/30 bg-primary/5 py-12">
                <Loader2 className="size-8 animate-spin text-primary" />
                <p className="text-sm font-medium text-primary/70">AI 正在生成世界观选项...</p>
              </div>
            )}

            {!drawingWorld && worldOptions.length > 0 && (
              <div className="grid gap-3 sm:grid-cols-3">
                {worldOptions.map((opt, i) => (
                  <WorldCard
                    key={i}
                    option={opt}
                    selected={selectedWorld === opt}
                    onSelect={() => setSelectedWorld(opt)}
                  />
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Step 2: Protagonist Draw ───────────────────────────────── */}
        {step === 2 && (
          <div className="space-y-4 pb-2">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="font-bold text-foreground">主角设定</h3>
                <p className="text-xs text-foreground/50">
                  基于你的题材生成 6 个主角设定方案，默认折叠详情，按需展开
                </p>
              </div>
              <Button
                size="sm"
                variant="outline"
                onClick={drawProtagonist}
                disabled={drawingProtagonist}
                className="gap-1.5"
              >
                {drawingProtagonist ? (
                  <Loader2 className="size-3 animate-spin" />
                ) : (
                  <Sparkles className="size-3" />
                )}
                重新抽卡
              </Button>
            </div>

            {drawingProtagonist && (
              <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-accent/30 bg-accent/5 py-12">
                <Loader2 className="size-8 animate-spin text-accent" />
                <p className="text-sm font-medium text-accent/70">AI 正在生成主角选项...</p>
              </div>
            )}

            {!drawingProtagonist && protagonistOptions.length > 0 && (
              <div className="grid gap-3 sm:grid-cols-3">
                {protagonistOptions.map((opt, i) => (
                  <ProtagonistCard
                    key={i}
                    option={opt}
                    selected={selectedProtagonist === opt}
                    onSelect={() => setSelectedProtagonist(opt)}
                  />
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Step 3: Cheat Draw ────────────────────────────────────── */}
        {step === 3 && (
          <div className="space-y-4 pb-2">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="font-bold text-foreground">金手指设定</h3>
                <p className="text-xs text-foreground/50">
                  为你的主角生成 6 个独特金手指方案，默认折叠详情，按需展开
                </p>
              </div>
              <Button
                size="sm"
                variant="outline"
                onClick={drawCheat}
                disabled={drawingCheat}
                className="gap-1.5"
              >
                {drawingCheat ? (
                  <Loader2 className="size-3 animate-spin" />
                ) : (
                  <Sparkles className="size-3" />
                )}
                重新抽卡
              </Button>
            </div>

            {drawingCheat && (
              <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-amber-500/30 bg-amber-500/5 py-12">
                <Loader2 className="size-8 animate-spin text-amber-500" />
                <p className="text-sm font-medium text-amber-500/70">AI 正在生成金手指选项...</p>
              </div>
            )}

            {!drawingCheat && cheatOptions.length > 0 && (
              <div className="grid gap-3 sm:grid-cols-3">
                {cheatOptions.map((opt, i) => (
                  <CheatCard
                    key={i}
                    option={opt}
                    selected={selectedCheat === opt}
                    onSelect={() => setSelectedCheat(opt)}
                  />
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Step 4: Confirm ─────────────────────────────────────────── */}
        {step === 4 && (
          <div className="pb-2">
            <StepConfirm
              basic={basic}
              world={selectedWorld}
              protagonist={selectedProtagonist}
              cheat={selectedCheat}
              busy={busy}
              onLaunch={handleLaunch}
            />
          </div>
        )}

        {/* ── Navigation footer ──────────────────────────────────────── */}
        {step < 4 && (
          <div className="flex items-center justify-between pt-4">
            <Button
              variant="ghost"
              size="sm"
              onClick={handleBack}
              disabled={step === 0}
              className="gap-1"
            >
              <ArrowLeft className="size-3" />
              上一步
            </Button>

            {step < 3 ? (
              <Button
                size="sm"
                onClick={handleNext}
                disabled={!canProceedToNext || isLoadingDraw}
                className="gap-1"
              >
                下一步
                <ArrowRight className="size-3" />
              </Button>
            ) : (
              <Button
                size="sm"
                onClick={handleNext}
                disabled={!canProceedToNext}
                className="gap-1"
              >
                查看确认
                <ArrowRight className="size-3" />
              </Button>
            )}
          </div>
        )}

        {step === 4 && (
          <div className="flex items-center justify-between pt-2">
            <Button variant="ghost" size="sm" onClick={handleBack} className="gap-1">
              <ArrowLeft className="size-3" />
              返回修改
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
