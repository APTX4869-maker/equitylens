import type { OverviewResponse } from "./types";

export const KPI_PERIOD_NAMES: Record<string, string> = {
  REVENUE: "营业收入", OPERATING_CASH_FLOW: "经营现金流", CAPITAL_EXPENDITURES: "资本开支",
  REVENUE_LATEST: "最近季度收入", TTM_REVENUE: "TTM 营业收入", REVENUE_GROWTH_YOY: "收入同比",
  OPERATING_MARGIN: "营业利润率", GROSS_MARGIN: "毛利率", NET_MARGIN: "净利率",
  TTM_FCF: "TTM 自由现金流", FCF_MARGIN: "FCF 率", NET_DEBT: "净现金 / 净债务",
  OPERATING_CASH_FLOW_LATEST: "最近季度经营现金流", TTM_OPERATING_CASH_FLOW: "TTM 经营现金流",
  CAPITAL_EXPENDITURES_LATEST: "最近季度资本开支", TTM_CAPITAL_EXPENDITURES: "TTM 资本开支",
};

export function reportPeriodLabel(overview: OverviewResponse | null | undefined): string {
  const report = overview?.reporting?.latest_report;
  if (!report) return "报告元数据未覆盖";
  if (!report.fiscal_year) return report.report_date;
  if (report.form_type.startsWith("10-K")) return `FY${report.fiscal_year} 年度`;
  return report.fiscal_quarter ? `FY${report.fiscal_year} Q${report.fiscal_quarter}` : report.report_date;
}

export function cashPeriodNote(item: OverviewResponse["kpis"][string] | undefined): string {
  if (item?.value != null) return `截至 ${item.period ?? "期间未覆盖"}`;
  const reason = item?.missing_reason;
  if (!reason) return "未覆盖";
  if (/[\u4e00-\u9fff]/.test(reason)) return reason;
  const gaps = [...reason.matchAll(/([A-Z_]+) (missing|null) (FY\d+Q[1-4])/g)];
  if (gaps.length) return gaps.map(([, metric, state, period]) => `${KPI_PERIOD_NAMES[metric] ?? "计算输入"}${state === "missing" ? "缺少" : "为空"} ${period}`).join("；");
  return "当前发布未提供完整计算结果；请查看报告来源。";
}
