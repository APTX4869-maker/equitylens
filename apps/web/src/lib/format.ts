/** Presentation helpers. API returns raw base units; formatting lives here. */

/** Format source-local time without shifting dates into the browser's timezone.
 * Unknown formats retain their full original text; never substitute fetch time.
 */
export function fmtQuoteTime(raw: string | null | undefined): string {
  const text = raw?.trim();
  if (!text) return "未标注";
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const english = /^(\w{3}) (\d{1,2}), (\d{4}) (\d{1,2}):(\d{2}) (AM|PM) (ET|PT|CT|MT)$/.exec(text);
  let date: string;
  let time = "";
  let zone = "";
  if (english && months.includes(english[1]) && Number(english[4]) >= 1 && Number(english[4]) <= 12) {
    date = `${english[3]}-${String(months.indexOf(english[1]) + 1).padStart(2, "0")}-${english[2].padStart(2, "0")}`;
    const hour = Number(english[4]) % 12 + (english[6] === "PM" ? 12 : 0);
    time = `${String(hour).padStart(2, "0")}:${english[5]}`;
    zone = english[7];
  } else {
    const iso = /^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)(Z|[+-]\d{2}:\d{2})?)?$/.exec(text);
    if (!iso) return `${text}（时间格式未识别）`;
    if (iso[3] && iso[3] !== "Z" && (Number(iso[3].slice(1, 3)) > 23 || Number(iso[3].slice(4, 6)) > 59)) {
      return `${text}（时间格式未识别）`;
    }
    date = iso[1];
    time = iso[2] ?? "";
    zone = iso[3] ? (iso[3] === "Z" || iso[3] === "+00:00" ? "UTC" : `UTC${iso[3]}`) : "（时区未标注）";
  }
  const parsed = new Date(`${date}T${time || "00:00:00"}Z`);
  if (Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== date) {
    return `${text}（时间格式未识别）`;
  }
  const [year, month, day] = date.split("-");
  return `${year}年${month}月${day}日${time ? ` ${time}${zone.startsWith("（") ? "" : " "}${zone}` : ""}`;
}

export function fmtMoney(value: number | null | undefined, opts: { compact?: boolean } = {}): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  if (opts.compact !== false && abs >= 1e12) return `$${(value / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `$${(value / 1e9).toFixed(value % 1e9 === 0 ? 0 : 1)}B`;
  if (abs >= 1e6) return `$${(value / 1e6).toFixed(0)}M`;
  return `$${value.toLocaleString("en-US")}`;
}

export function fmtRatio(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

export function fmtPct(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

export function signedPct(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const v = value * 100;
  return `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;
}

export function fmtNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(digits);
}

export function statusLabel(status: string | null | undefined): string {
  switch (status) {
    case "NORMALIZED":
      return "官方披露";
    case "CALCULATED":
      return "系统计算";
    case "DISCLOSED":
      return "官方披露";
    default:
      return status ?? "未知";
  }
}
