/**
 * Shared date/time formatting utilities.
 * All functions use zh-CN locale with Asia/Shanghai timezone.
 */

/** Parse backend naive UTC isoformat() strings. If no timezone info, treat as UTC. */
export function parseBackendUtcIso(iso: string): Date {
  const s = iso.trim();
  if (!s) return new Date(NaN);
  if (/[zZ]$/.test(s)) return new Date(s);
  if (/[+-]\d{2}:\d{2}$/.test(s) || /[+-]\d{4}$/.test(s)) return new Date(s);
  const normalized = s.includes("T") ? s : s.replace(" ", "T");
  return new Date(`${normalized}Z`);
}

/** Format a backend UTC timestamp as a short date-time label (MM/DD HH:mm). */
export function formatDateTimeLabel(value?: string | null): string {
  if (!value) return "暂无";
  const date = parseBackendUtcIso(value);
  if (Number.isNaN(date.getTime())) return "暂无";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Asia/Shanghai",
  }).format(date);
}

/** Format a backend UTC timestamp as a full date-time string (YYYY-MM-DD HH:mm:ss GMT+8). */
export function formatDateTimeFull(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = parseBackendUtcIso(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const shifted = new Date(d.getTime() + 8 * 60 * 60 * 1000);
  const yyyy = shifted.getUTCFullYear();
  const mm = String(shifted.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(shifted.getUTCDate()).padStart(2, "0");
  const hh = String(shifted.getUTCHours()).padStart(2, "0");
  const mi = String(shifted.getUTCMinutes()).padStart(2, "0");
  const ss = String(shifted.getUTCSeconds()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}:${ss} GMT+8`;
}

/** Format a backend UTC timestamp as MM/DD HH:mm (same as formatDateTimeLabel, for NovelIntelPanel compat). */
export function formatDateTime(value?: string | null): string {
  return formatDateTimeLabel(value);
}

/** Relative time ago in Chinese (e.g., "3 分钟前"). */
export function relativeTimeAgo(value: string | null): string {
  if (!value) return "未记录更新时间";
  const ts = Date.parse(value);
  if (Number.isNaN(ts)) return value;
  const diff = Date.now() - ts;
  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (diff < hour) return `${Math.max(1, Math.round(diff / minute))} 分钟前`;
  if (diff < day) return `${Math.max(1, Math.round(diff / hour))} 小时前`;
  if (diff < 7 * day) return `${Math.max(1, Math.round(diff / day))} 天前`;
  return value.slice(0, 10);
}

/** Format a duration in seconds to a human-readable string. */
export function formatDuration(totalSeconds: number | null | undefined): string {
  if (totalSeconds == null || totalSeconds < 0) return "-";
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}
