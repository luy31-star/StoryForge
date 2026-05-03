/**
 * Shared workspace utility functions.
 * Consolidates duplicated helpers from NovelWorkspace, NovelMetrics, etc.
 */

/** Clamp a number to [0, 1]. */
export function clamp01(value: number): number {
  if (Number.isNaN(value)) return 0;
  return Math.max(0, Math.min(1, value));
}

/** Truncate text to max length with ellipsis. */
export function shortenText(value: string, max = 88): string {
  const trimmed = value.trim();
  if (trimmed.length <= max) return trimmed;
  return `${trimmed.slice(0, max - 1)}…`;
}

/** Safe JSON.stringify with fallback. */
export function safeJsonStringify(data: unknown): string {
  try {
    return JSON.stringify(data, null, 2);
  } catch {
    return String(data);
  }
}

/** Calculate total pages from item count and page size. */
export function totalPages(n: number, pageSize: number): number {
  return Math.max(1, Math.ceil(Math.max(0, n) / pageSize));
}

/** Slice a page from an array. */
export function slicePage<T>(items: T[], page: number, pageSize: number): T[] {
  const start = page * pageSize;
  return items.slice(start, start + pageSize);
}

/** Convert string array to editor text (newline-joined). */
export function linesToEditorText(items: string[]): string {
  return items.join("\n");
}

/** Convert editor text to string array (split by newline, trim, filter empty). */
export function editorTextToLines(value: string): string[] {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

/** Extract changed types from a memory diff summary. */
export function diffChangedTypes(diff?: { summary?: { changed_types?: unknown } } | null): string[] {
  const list = diff?.summary?.changed_types;
  return Array.isArray(list) ? list.map((item) => String(item)) : [];
}

/** Extract change count from a memory diff summary. */
export function diffChangeCount(diff?: { summary?: { change_count?: unknown } } | null): number {
  return Number(diff?.summary?.change_count ?? 0) || 0;
}

/** Extract chapter numbers from a memory diff summary. */
export function diffChapterNos(diff?: { summary?: { chapter_nos?: unknown } } | null): number[] {
  const list = diff?.summary?.chapter_nos;
  return Array.isArray(list)
    ? list.map((item) => Number(item)).filter((item) => Number.isFinite(item) && item > 0)
    : [];
}

/** Normalize a string or string[] field to a string array. */
export function stringListField(v: string | string[] | undefined): string[] {
  if (v == null) return [];
  if (Array.isArray(v))
    return v.map((x) => String(x).trim()).filter(Boolean);
  return String(v).trim() ? [String(v).trim()] : [];
}
