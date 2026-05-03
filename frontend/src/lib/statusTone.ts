/**
 * Shared status-to-Tailwind-class mappings.
 * Consolidates tone functions from NovelWorkspace, NovelIntelPanel, NovelMetrics.
 */

/** General status tone (used in NovelIntelPanel). */
export function statusTone(status?: string): string {
  const s = (status || "").toLowerCase();
  switch (s) {
    case "done":
    case "completed":
    case "approved":
    case "success":
      return "text-emerald-500 bg-emerald-500/10 border-emerald-500/20";
    case "running":
    case "started":
    case "pending_review":
    case "queued":
    case "active":
      return "text-sky-500 bg-sky-500/10 border-sky-500/20";
    case "failed":
    case "blocked":
    case "error":
    case "critical":
    case "high":
      return "text-rose-500 bg-rose-500/10 border-rose-500/20";
    case "skipped":
    case "warning":
    case "medium":
      return "text-amber-500 bg-amber-500/10 border-amber-500/20";
    default:
      return "text-foreground/40 bg-background/60 border-border/40";
  }
}

/** Memory update run status tone. */
export function memoryRunStatusTone(status?: string): string {
  switch (status) {
    case "ok":
      return "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300";
    case "warning":
      return "border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-300";
    case "blocked":
    case "failed":
      return "border-rose-500/25 bg-rose-500/10 text-rose-700 dark:text-rose-300";
    case "running":
    case "queued":
      return "border-sky-500/25 bg-sky-500/10 text-sky-700 dark:text-sky-300";
    default:
      return "border-border/70 bg-background/60 text-foreground/60";
  }
}

/** Chapter tree sidebar left-border tone. */
export function chapterTreeTone(status: string): string {
  if (status === "approved") return "border-l-emerald-400";
  if (status === "pending_review") return "border-l-amber-400";
  if (status === "failed") return "border-l-rose-400";
  return "border-l-cyan-400";
}

/** Risk ring tone (used in NovelMetrics). */
export function ringTone(value01: number): string {
  if (value01 >= 0.75) return "text-emerald-500";
  if (value01 >= 0.45) return "text-amber-500";
  return "text-rose-500";
}

/** Score background for judge display. */
export function scoreBg(score: number): string {
  if (score >= 80) return "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400";
  if (score >= 60) return "bg-amber-500/10 text-amber-600 dark:text-amber-400";
  return "bg-rose-500/10 text-rose-600 dark:text-rose-400";
}
