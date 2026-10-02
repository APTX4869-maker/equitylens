import { describe, expect, test } from "vitest";

import {
  adaptivePercentRange,
  updateDraft,
  validateValuationDraft,
  type DcfInputs,
} from "./valuationDraft";

const draft: DcfInputs = {
  revenue_base: 1_000,
  revenue_growth: [0.30, 0.24, 0.18, 0.14, 0.10],
  op_margin_start: 0.60,
  op_margin_end: 0.6088,
  tax_rate: 0.17,
  da_pct: 0.03,
  capex_pct: 0.05,
  nwc_pct: 0.002,
  wacc: 0.10,
  terminal_growth: 0.025,
  terminal_roic: 0.20,
  net_cash: 100,
  shares: 10,
};

describe("adaptivePercentRange", () => {
  test("expands the standard range without clipping an issuer value", () => {
    expect(adaptivePercentRange({ min: -100, max: 20, step: 0.5 }, 30)).toEqual({
      min: -100,
      max: 30,
      step: 0.5,
    });
    expect(adaptivePercentRange({ min: 5, max: 60, step: 0.5 }, 60.88)).toEqual({
      min: 5,
      max: 61,
      step: 0.5,
    });
  });
});

test("a minus 100 percent growth edit never creates a path below minus 100 percent", () => {
  expect(updateDraft(draft, { field: "growth", percent: -100 }).revenue_growth).toEqual([
    -1,
    -1,
    -1,
    -1,
    -1,
  ]);
});

describe("validateValuationDraft", () => {
  test("reports the exact field when WACC is not above terminal growth by one point", () => {
    expect(validateValuationDraft({ ...draft, wacc: 0.03, terminal_growth: 0.025 })).toEqual({
      wacc: "WACC 必须至少高于永续增长率 1 个百分点",
    });
  });

  test("rejects a terminal growth rate that consumes all stable-period ROIC", () => {
    expect(validateValuationDraft({ ...draft, terminal_growth: 0.20, terminal_roic: 0.20 })).toEqual({
      wacc: "WACC 必须至少高于永续增长率 1 个百分点",
      roic: "永续增长率必须低于稳定期 ROIC",
    });
  });

  test("accepts the exact NVDA-style baseline without rounding or clipping", () => {
    expect(validateValuationDraft(draft)).toEqual({});
  });
});
