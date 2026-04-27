/** `new Date()` → "YYYY-MM-DDTHH:mm:ss" naive-local wall clock (no tz).
 *  Matches the Eight Sleep / activity convention used elsewhere in the
 *  codebase so backend HR-slicing math lines up. */
export function toNaiveLocalIso(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  );
}

export function formatRestTimer(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}
