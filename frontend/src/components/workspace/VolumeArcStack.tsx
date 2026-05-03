/**
 * Volume arc stack component for displaying volume plot arcs.
 */
import { ChevronRight } from "lucide-react";
import type { NovelVolumeListItem } from "@/services/novelApi";
import { stringListField } from "@/lib/workspaceUtils";

type VolumeArcRow = {
  title?: string;
  name?: string;
  from_chapter?: number;
  to_chapter?: number;
  summary?: string;
  description?: string;
  hook?: string;
  must_not?: string[] | string;
  progress_allowed?: string[] | string;
};

export function parseVolumeOutlineJson(
  raw?: string
): { volume_no?: number; arcs: VolumeArcRow[] } | null {
  if (!raw || raw.trim() === "" || raw === "{}") return null;
  try {
    const o = JSON.parse(raw) as { volume_no?: number; arcs?: unknown };
    if (!o || !Array.isArray(o.arcs) || o.arcs.length === 0) return null;
    return {
      volume_no: o.volume_no,
      arcs: o.arcs.filter(
        (a): a is VolumeArcRow => a != null && typeof a === "object"
      ),
    };
  } catch {
    return null;
  }
}

type Props = {
  volume: NovelVolumeListItem;
  compact?: boolean;
  roomy?: boolean;
};

export function VolumeArcStack({ volume, compact, roomy }: Props) {
  const parsed = parseVolumeOutlineJson(volume.outline_json);
  const md = (volume.outline_markdown || "").trim();

  if (parsed && parsed.arcs.length > 0) {
    return (
      <div className={compact ? "space-y-1.5" : roomy ? "space-y-3.5" : "space-y-2"}>
        {parsed.arcs.map((arc, idx) => {
          const title = (arc.title || arc.name || `第${idx + 1}段`).trim();
          const lo = arc.from_chapter;
          const hi = arc.to_chapter;
          const range = typeof lo === "number" && typeof hi === "number" ? `约第${lo}—${hi}章` : "";
          const summary = (arc.summary || arc.description || "").trim();
          const hook = (arc.hook || "").trim();
          const must = stringListField(arc.must_not);
          const allow = stringListField(arc.progress_allowed);
          return (
            <details
              key={`${volume.id}-arc-${idx}`}
              className={
                roomy
                  ? "group rounded-2xl border-2 border-border bg-card open:border-primary/30 open:shadow-sm"
                  : "group rounded-xl border border-border bg-background/50 open:border-primary/20 open:bg-muted"
              }
            >
              <summary
                className={`flex cursor-pointer list-none items-start gap-2 text-left [&::-webkit-details-marker]:hidden ${
                  roomy ? "p-4 pr-5 text-base" : "p-2.5"
                }`}
              >
                <ChevronRight
                  className={
                    roomy
                      ? "mt-0.5 size-[1.1rem] shrink-0 text-foreground/50 transition group-open:rotate-90"
                      : "mt-0.5 size-3.5 shrink-0 text-foreground/45 transition group-open:rotate-90"
                  }
                />
                <div className="min-w-0 flex-1">
                  <p className={`font-bold text-foreground ${compact ? "text-[11px] leading-snug" : roomy ? "text-base leading-snug" : "text-sm"}`}>
                    {title}
                    {range ? (
                      <span className={roomy ? "ml-2 text-sm font-normal text-foreground/50" : "ml-1.5 font-normal text-foreground/45"}>
                        {range}
                      </span>
                    ) : null}
                  </p>
                </div>
              </summary>
              <div
                className={`space-y-2 border-t border-border/40 text-foreground/85 ${
                  compact
                    ? "px-2.5 pb-2.5 pt-2 text-[10px] leading-relaxed"
                    : roomy
                      ? "space-y-3 px-4 pb-4 pt-3 text-sm leading-[1.65] sm:px-5"
                      : "px-2.5 pb-2.5 pt-2 text-xs leading-relaxed"
                }`}
              >
                {summary ? (
                  <p className={roomy ? "whitespace-pre-wrap text-[15px] text-foreground/90" : "whitespace-pre-wrap text-foreground/90"}>
                    {summary}
                  </p>
                ) : (
                  <p className="text-foreground/50">
                    （本段无剧情摘要。重新生成分卷剧情后将显示摘要与约束。）
                  </p>
                )}
                {hook ? (
                  <div className={roomy ? "rounded-xl border border-amber-500/30 bg-amber-500/10 px-3.5 py-2.5" : "rounded-lg border border-amber-500/25 bg-amber-500/10 px-2 py-1.5"}>
                    <p className="font-bold text-amber-800 dark:text-amber-200">钩子</p>
                    <p className="mt-0.5 text-foreground/90">{hook}</p>
                  </div>
                ) : null}
                {must.length > 0 ? (
                  <div className={roomy ? "rounded-xl border border-rose-500/25 bg-rose-500/10 px-3.5 py-2.5" : "rounded-lg border border-rose-500/20 bg-rose-500/5 px-2 py-1.5"}>
                    <p className="font-bold text-rose-800 dark:text-rose-200">禁止推进</p>
                    <ul className="mt-1 list-disc pl-4">
                      {must.map((x) => (<li key={x}>{x}</li>))}
                    </ul>
                  </div>
                ) : null}
                {allow.length > 0 ? (
                  <div className={roomy ? "rounded-xl border border-emerald-500/25 bg-emerald-500/10 px-3.5 py-2.5" : "rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-2 py-1.5"}>
                    <p className="font-bold text-emerald-800 dark:text-emerald-200">允许推进</p>
                    <ul className="mt-1 list-disc pl-4">
                      {allow.map((x) => (<li key={x}>{x}</li>))}
                    </ul>
                  </div>
                ) : null}
              </div>
            </details>
          );
        })}
      </div>
    );
  }

  if (md) {
    return (
      <details className="rounded-xl border border-border bg-muted open:rounded-2xl">
        <summary
          className={
            roomy
              ? "cursor-pointer list-none p-4 text-left text-sm font-bold text-foreground [&::-webkit-details-marker]:hidden"
              : "cursor-pointer list-none p-2.5 text-left text-xs font-bold text-foreground [&::-webkit-details-marker]:hidden"
          }
        >
          查看分卷剧情（仅文本，建议重新生成以带结构化约束）
        </summary>
        <pre
          className={
            roomy
              ? "max-h-[min(68dvh,800px)] overflow-auto whitespace-pre-wrap break-words p-4 font-sans text-sm leading-[1.65] text-foreground sm:p-5"
              : "max-h-[min(50vh,480px)] overflow-auto whitespace-pre-wrap break-words p-3 font-sans text-xs text-foreground sm:text-sm"
          }
        >
          {md}
        </pre>
      </details>
    );
  }

  return <p className="text-xs text-foreground/50">暂无分卷剧情。</p>;
}
