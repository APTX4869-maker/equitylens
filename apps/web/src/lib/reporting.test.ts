import { describe, expect, it } from "vitest";
import { cashPeriodNote } from "./reporting";

describe("cash flow period coverage", () => {
  it("preserves the period of a zero value", () => {
    expect(cashPeriodNote({ value: 0, period: "FY2026Q4" })).toBe("截至 FY2026Q4");
  });
  it("never presents a missing result target as an available-value date", () => {
    expect(cashPeriodNote({ value: null, period: "FY2026Q2" })).toBe("未覆盖");
  });
  it("explains all missing quarter inputs with user-facing metric names", () => {
    expect(cashPeriodNote({ value: null, missing_reason: "OPERATING_CASH_FLOW missing FY2026Q2; CAPITAL_EXPENDITURES null FY2026Q1" }))
      .toBe("经营现金流缺少 FY2026Q2；资本开支为空 FY2026Q1");
  });
  it("keeps Chinese reasons and gives unknown technical failures a coverage explanation", () => {
    expect(cashPeriodNote({ value: null, missing_reason: "缺少连续季度" })).toBe("缺少连续季度");
    expect(cashPeriodNote({ value: null, missing_reason: "unit mismatch: USD, EUR" })).toContain("未提供完整计算结果");
    expect(cashPeriodNote(undefined)).toBe("未覆盖");
  });
});
