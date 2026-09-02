"use client";

import { useEffect, useRef } from "react";
import * as echarts from "echarts";

/** Thin ECharts wrapper (hand-rolled, no extra deps). */
export function EChart({
  option,
  height = 240,
  className = "",
}: {
  option: echarts.EChartsOption;
  height?: number | string;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chartRef.current = chart;
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    chartRef.current?.setOption(option, true);
  }, [option]);

  return <div ref={ref} className={className} style={{ width: "100%", height }} />;
}

const GRID = { left: 52, right: 18, top: 24, bottom: 34 };
const AXIS = {
  axisLine: { lineStyle: { color: "#d9dfe8" } },
  axisLabel: { color: "#6d7788", fontSize: 11 },
  splitLine: { lineStyle: { color: "#eef1f6" } },
};

function fmtAxis(v: number, unit?: string): string {
  if (unit === "ratio" || unit === "growth") return `${(v * 100).toFixed(1)}%`;
  if (unit === "currency") {
    const abs = Math.abs(v);
    if (abs >= 1e12) return `$${(v / 1e12).toFixed(1)}T`;
    if (abs >= 1e9) return `$${(v / 1e9).toFixed(0)}B`;
    if (abs >= 1e6) return `$${(v / 1e6).toFixed(0)}M`;
    return `$${v.toFixed(0)}`;
  }
  return String(v);
}

export function barOption(
  labels: (string | null)[],
  seriesData: { name: string; data: (number | null)[]; color?: string }[],
  opts: { unit?: string } = {}
): echarts.EChartsOption {
  return {
    grid: { left: 52, right: 18, top: 40, bottom: 34 },
    tooltip: {
      trigger: "axis",
      valueFormatter: (v) => fmtAxis(Number(v), opts.unit),
    },
    legend: { top: 4, textStyle: { fontSize: 11, color: "#6d7788" } },
    xAxis: { type: "category", data: labels.map((l) => l ?? ""), ...AXIS },
    yAxis: { type: "value", ...AXIS, axisLabel: { formatter: (v: number) => fmtAxis(v, opts.unit) } },
    series: seriesData.map((sd) => ({
      name: sd.name,
      type: "bar",
      data: sd.data,
      barMaxWidth: 26,
      itemStyle: { color: sd.color ?? "#315ca8", borderRadius: [4, 4, 0, 0] },
    })),
  };
}

export function seriesOption(
  labels: (string | null)[],
  values: (number | null)[],
  opts: { unit?: string; color?: string; name?: string } = {}
): echarts.EChartsOption {
  return {
    grid: GRID,
    tooltip: {
      trigger: "axis",
      valueFormatter: (v) => fmtAxis(Number(v), opts.unit),
    },
    xAxis: { type: "category", data: labels.map((l) => l ?? ""), ...AXIS },
    yAxis: { type: "value", ...AXIS, axisLabel: { formatter: (v: number) => fmtAxis(v, opts.unit) } },
    series: [
      {
        name: opts.name,
        type: "line",
        smooth: true,
        symbol: "circle",
        symbolSize: 6,
        data: values,
        lineStyle: { width: 2.5, color: opts.color ?? "#1e6b57" },
        itemStyle: { color: opts.color ?? "#1e6b57" },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: "rgba(30,107,87,0.18)" },
            { offset: 1, color: "rgba(30,107,87,0.01)" },
          ]),
        },
      },
    ],
  };
}
