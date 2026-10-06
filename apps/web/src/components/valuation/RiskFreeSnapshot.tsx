type RiskFreeMeta = {
  value?: unknown;
  as_of?: unknown;
  source?: unknown;
  source_type?: unknown;
  fallback_reason?: unknown;
};

// Only the metadata belonging to this draft/run is admissible. In particular,
// never fill a historical gap from a newer top-level or live rate.
export function RiskFreeSnapshot({ meta }: { meta?: unknown }) {
  const item: RiskFreeMeta = meta && typeof meta === "object" ? meta : {};
  const rate = typeof item.value === "number" && Number.isFinite(item.value)
    ? `${(item.value * 100).toFixed(2)}%` : "利率未记录";
  const date = typeof item.as_of === "string" && item.as_of.trim() ? item.as_of : "日期未记录";
  const source = typeof item.source === "string" && item.source.trim() ? item.source : "来源未记录";
  const fallback = typeof item.fallback_reason === "string" ? item.fallback_reason.trim() : "";
  const status = fallback ? "配置回退"
    : item.source_type === "external_observation" ? "外部观察"
    : item.source_type === "config_assumption" ? "配置假设"
    : item.source_type === "user_confirmation" ? "人工确认" : "状态未记录";
  const reason = fallback === "Treasury feed unavailable; using dated config fallback."
    ? "国债数据源不可用，使用带日期的配置回退。" : fallback;
  return (
    <div data-testid="risk-free-snapshot" className="card-sub" style={{ overflowWrap: "anywhere" }}>
      <span>无风险利率 {rate} · {date} · {status}</span>
      <details>
        <summary>利率来源与说明</summary>
        <div>来源：{source}</div>
        {reason ? <div title={fallback}>回退原因：{reason}</div> : null}
        <div>这是本次研究假设中的利率组件，不是 WACC，也不代表当前实时利率。历史缺失信息不会以新利率补填。</div>
      </details>
    </div>
  );
}
