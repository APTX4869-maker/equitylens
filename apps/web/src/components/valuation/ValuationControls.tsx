"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";

import {
  adaptivePercentRange,
  type DcfInputs,
  type DraftEdit,
  type ValuationDraftErrors,
} from "@/lib/valuationDraft";

type Field = DraftEdit["field"];

const CONTROL_CONFIG: Record<Field, {
  label: string;
  baseRange: { min: number; max: number; step: number };
  decimals: number;
}> = {
  growth: {
    label: "首年收入增速（路径逐年递减）",
    baseRange: { min: -100, max: 20, step: 0.5 },
    decimals: 2,
  },
  margin: {
    label: "第5年营业利润率",
    baseRange: { min: 5, max: 60, step: 0.5 },
    decimals: 2,
  },
  wacc: {
    label: "WACC 折现率",
    baseRange: { min: 4, max: 15, step: 0.25 },
    decimals: 2,
  },
  terminal: {
    label: "永续增长率",
    baseRange: { min: 0.5, max: 4, step: 0.25 },
    decimals: 2,
  },
  roic: {
    label: "稳定期增量资本回报率",
    baseRange: { min: 8, max: 40, step: 1 },
    decimals: 2,
  },
};

const FIELDS: Field[] = ["growth", "margin", "wacc", "terminal", "roic"];

function percentages(draft: DcfInputs): Record<Field, number> {
  return {
    growth: draft.revenue_growth[0] * 100,
    margin: draft.op_margin_end * 100,
    wacc: draft.wacc * 100,
    terminal: draft.terminal_growth * 100,
    roic: draft.terminal_roic * 100,
  };
}

function displayNumber(value: number, decimals: number): string {
  void decimals;
  return Number(value.toPrecision(15)).toString();
}

export function ValuationControls({
  draft,
  disabled,
  errors,
  notes,
  onEdit,
  onRawValidityChange,
}: {
  draft: DcfInputs;
  disabled?: boolean;
  errors: ValuationDraftErrors;
  notes: Partial<Record<Field, ReactNode>>;
  onEdit: (edit: DraftEdit) => void;
  onRawValidityChange: (field: Field, message: string | null) => void;
}) {
  const values = useMemo(() => percentages(draft), [draft]);
  const [rawValues, setRawValues] = useState<Record<Field, string>>(() =>
    Object.fromEntries(
      FIELDS.map((field) => [
        field,
        displayNumber(values[field], CONTROL_CONFIG[field].decimals),
      ])
    ) as Record<Field, string>
  );

  useEffect(() => {
    // The backend can replace the complete draft after recalculation or copy/edit.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setRawValues(Object.fromEntries(
      FIELDS.map((field) => [
        field,
        displayNumber(values[field], CONTROL_CONFIG[field].decimals),
      ])
    ) as Record<Field, string>);
  }, [values]);

  const editExact = (field: Field, raw: string) => {
    setRawValues((current) => ({ ...current, [field]: raw }));
    if (raw.trim() === "" || !Number.isFinite(Number(raw))) {
      onRawValidityChange(field, "请输入有效数字");
      return;
    }
    onRawValidityChange(field, null);
    onEdit({ field, percent: Number(raw) } as DraftEdit);
  };

  const editSlider = (field: Field, value: number) => {
    setRawValues((current) => ({
      ...current,
      [field]: displayNumber(value, CONTROL_CONFIG[field].decimals),
    }));
    onRawValidityChange(field, null);
    onEdit({ field, percent: value } as DraftEdit);
  };

  return (
    <div className="dcf-sliders" data-testid="valuation-controls">
      {FIELDS.map((field) => {
        const config = CONTROL_CONFIG[field];
        const range = adaptivePercentRange(config.baseRange, values[field]);
        const error = errors[field];
        return (
          <div className="dcf-control" key={field} data-invalid={error ? "true" : "false"}>
            <label htmlFor={`${field}-slider`}>{config.label}</label>
            <div className="dcf-control-inputs">
              <input
                id={`${field}-slider`}
                data-testid={`valuation-slider-${field}`}
                type="range"
                min={range.min}
                max={range.max}
                step={range.step}
                value={values[field]}
                disabled={disabled}
                onChange={(event) => editSlider(field, Number(event.target.value))}
              />
              <div className="dcf-exact-input">
                <input
                  type="number"
                  inputMode="decimal"
                  step="any"
                  aria-label={`${config.label}精确值`}
                  data-testid={`valuation-input-${field}`}
                  value={rawValues[field]}
                  disabled={disabled}
                  aria-invalid={error ? "true" : "false"}
                  onChange={(event) => editExact(field, event.target.value)}
                />
                <span>%</span>
              </div>
            </div>
            <output htmlFor={`${field}-slider`}>{values[field].toFixed(config.decimals)}%</output>
            {error ? <div className="dcf-control-error" role="alert">{error}</div> : null}
            {notes[field]}
          </div>
        );
      })}
    </div>
  );
}
