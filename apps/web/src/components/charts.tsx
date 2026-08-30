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

export function seriesOption(
  labels: (string | null)[],
  values: (number | null)[],
  opts: { unit?: string; color?: string; name?: string } = {}
): echarts.EChartsOption {
  return {
    grid: GRID,
    tooltip: {
      trigger: "axis",
      valueFormatter: (v) => (opts.unit === "ratio" ? `${(Number(v) * 100).toFixed(1)}%` : String(v)),
    },
    xAxis: { type: "category", data: labels.map((l) => l ?? ""), ...AXIS },
    yAxis: { type: "value", ...AXIS },
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
