"use client";

export type RefreshProgressPhase = "pending" | "running" | "success" | "error";

export type RefreshProgressItem = {
  phase: RefreshProgressPhase;
  changed?: boolean;
  checkedAt?: string | null;
  reason?: string | null;
  retryable?: boolean;
};

type FreshnessItem = { key: string; as_of: string | null };

const ORDER = ["financials", "segments", "management", "quotes"] as const;
export const REFRESH_MODULE_LABELS: Record<(typeof ORDER)[number], string> = {
  financials: "财务",
  segments: "分部",
  management: "治理",
  quotes: "行情",
};
const FRESHNESS_KEYS: Record<(typeof ORDER)[number], string> = {
  financials: "sec_financials",
  segments: "segments",
  management: "management",
  quotes: "market_quote",
};

function checkedAt(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(0, 19).replace("T", " ");
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

export function RefreshProgress({
  items,
  freshness,
}: {
  items: Record<string, RefreshProgressItem>;
  freshness: FreshnessItem[];
}) {
  const visible = ORDER.filter((key) => items[key]);
  if (!visible.length) return null;

  const successful = visible.filter((key) => items[key].phase === "success").length;
  const percent = Math.round((successful / visible.length) * 100);
  const byKey = new Map(freshness.map((item) => [item.key, item]));

  return (
    <section className="refresh-progress" data-testid="refresh-progress" aria-label="数据刷新进度">
      <div className="refresh-progress-head">
        <div>
          <strong>数据刷新进度</strong>
          <span>{successful} / {visible.length} 完成</span>
        </div>
        <span>{percent}%</span>
      </div>
      <div
        className="refresh-progress-bar"
        role="progressbar"
        aria-label="数据刷新完成比例"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
      >
        <span className="refresh-progress-success" style={{ width: `${percent}%` }} />
      </div>
      <div className="refresh-progress-modules">
        {visible.map((key) => {
          const item = items[key];
          const dataDate = byKey.get(FRESHNESS_KEYS[key])?.as_of?.slice(0, 10) ?? "未同步";
          const status = item.phase === "pending"
            ? "等待"
            : item.phase === "running"
              ? "进行中"
              : item.phase === "error"
                ? "失败"
                : item.changed
                  ? "已更新"
                  : "检查成功，暂无更新";
          return (
            <article
              key={key}
              className={`refresh-module refresh-module-${item.phase}`}
              data-testid={`refresh-module-${key}`}
            >
              <div>
                <strong>{REFRESH_MODULE_LABELS[key]}</strong>
                <span className="refresh-module-status">{status}</span>
              </div>
              <p>数据日期 {dataDate}</p>
              <p>本次检查 {checkedAt(item.checkedAt)}</p>
              {item.reason ? <p className="refresh-module-error">{item.reason}</p> : null}
            </article>
          );
        })}
      </div>
    </section>
  );
}
