// Complete editable FCFF DCF input draft (V03/U02).
//
// One source of truth for what the user is editing. Every preview, reverse-DCF,
// and save request sends the WHOLE draft, never a partial override that the
// backend would otherwise re-merge with defaults. A response is applied and a
// run is saveable only when the applied inputs still equal the current draft.

export type DcfInputs = {
  revenue_base: number;
  revenue_growth: number[];
  op_margin_start: number;
  op_margin_end: number;
  tax_rate: number;
  da_pct: number;
  capex_pct: number;
  nwc_pct: number;
  wacc: number;
  terminal_growth: number;
  terminal_roic: number;
  net_cash: number;
  shares: number;
  share_basis_label?: string;
};

export type DraftEdit =
  | { field: "growth"; percent: number }
  | { field: "margin"; percent: number }
  | { field: "wacc"; percent: number }
  | { field: "terminal"; percent: number }
  | { field: "roic"; percent: number };

/** Build a local draft from the backend's executed inputs (default/run). */
export function draftFromInputs(inputs: DcfInputs): DcfInputs {
  return { ...inputs, revenue_growth: [...(inputs.revenue_growth ?? [])] };
}

/** Rebase a user's five editable assumptions onto newly loaded company data.
 *
 * Revenue, margins, cash, shares, and other fact-derived inputs must come from
 * the fresh default response. Only the controls the user can intentionally edit
 * survive a data refresh.
 */
export function rebaseDraftOnDefaults(defaults: DcfInputs, current: DcfInputs): DcfInputs {
  return {
    ...draftFromInputs(defaults),
    revenue_growth: [...current.revenue_growth],
    op_margin_end: current.op_margin_end,
    wacc: current.wacc,
    terminal_growth: current.terminal_growth,
    terminal_roic: current.terminal_roic,
  };
}

/** Pure synchronous edit.
 *
 * Only a growth edit rebuilds the five-year path (anchored at the user CAGR and
 * declining 0.5pp per year); editing WACC / margin / terminal leaves the current
 * path untouched (V03). Negative growth is allowed down to the backend limit of
 * -100% so the required negative-growth stress case can be run (P03).
 */
export function updateDraft(draft: DcfInputs, edit: DraftEdit): DcfInputs {
  if (edit.field === "growth") {
    const g = edit.percent / 100;
    return { ...draft, revenue_growth: [g, g - 0.005, g - 0.01, g - 0.015, g - 0.02] };
  }
  if (edit.field === "margin") return { ...draft, op_margin_end: edit.percent / 100 };
  if (edit.field === "wacc") return { ...draft, wacc: edit.percent / 100 };
  if (edit.field === "terminal") return { ...draft, terminal_growth: edit.percent / 100 };
  return { ...draft, terminal_roic: edit.percent / 100 };
}

/** Complete preview/run request body for a draft (every editable field). */
export function buildPreviewRequest(draft: DcfInputs, persist = false) {
  return {
    persist,
    assumptions: {
      revenue_base: draft.revenue_base,
      revenue_growth: [...draft.revenue_growth],
      op_margin_start: draft.op_margin_start,
      op_margin_end: draft.op_margin_end,
      tax_rate: draft.tax_rate,
      da_pct: draft.da_pct,
      capex_pct: draft.capex_pct,
      nwc_pct: draft.nwc_pct,
      wacc: draft.wacc,
      terminal_growth: draft.terminal_growth,
      terminal_roic: draft.terminal_roic,
      net_cash: draft.net_cash,
      shares: draft.shares,
      share_basis_label: draft.share_basis_label,
    },
  };
}

/** Stable canonical LOCAL identity of a draft, used only for client-side
 * save/stale gating. This is deliberately distinct from the backend's SHA-256
 * `input_fingerprint` (which the API returns and which is echoed on save). */
export function draftFingerprint(draft: DcfInputs): string {
  return JSON.stringify({
    revenue_base: draft.revenue_base,
    revenue_growth: draft.revenue_growth,
    op_margin_start: draft.op_margin_start,
    op_margin_end: draft.op_margin_end,
    tax_rate: draft.tax_rate,
    da_pct: draft.da_pct,
    capex_pct: draft.capex_pct,
    nwc_pct: draft.nwc_pct,
    wacc: draft.wacc,
    terminal_growth: draft.terminal_growth,
    terminal_roic: draft.terminal_roic,
    net_cash: draft.net_cash,
    shares: draft.shares,
  });
}
