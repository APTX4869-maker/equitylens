"use client";

import type { CompanyInfo } from "@/lib/types";

export type TabKey =
  | "overview"
  | "business"
  | "financials"
  | "moat"
  | "management"
  | "valuation"
  | "risks"
  | "ai";

export const TABS: { key: TabKey; icon: string; label: string }[] = [
  { key: "overview", icon: "⌂", label: "公司总览" },
  { key: "business", icon: "◔", label: "业务构成" },
  { key: "financials", icon: "⌁", label: "财务分析" },
  { key: "moat", icon: "◇", label: "护城河" },
  { key: "management", icon: "♙", label: "管理层" },
  { key: "valuation", icon: "◎", label: "估值" },
  { key: "risks", icon: "△", label: "风险" },
  { key: "ai", icon: "✦", label: "AI研究助手" },
];

export const COMPANIES = ["AAPL", "MSFT"] as const;

export function Sidebar({
  company,
  tab,
  onCompany,
  onTab,
}: {
  company: string;
  tab: TabKey;
  onCompany: (c: string) => void;
  onTab: (t: TabKey) => void;
}) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">E</div>
        <span>EquityLens</span>
      </div>
      <div className="side-label">研究公司</div>
      {COMPANIES.map((c) => (
        <button
          key={c}
          className={`company-btn ${company === c ? "active" : ""}`}
          onClick={() => onCompany(c)}
        >
          <div className="ticker-box">{c}</div>
          <div className="company-meta">
            <strong>{c === "AAPL" ? "Apple" : "Microsoft"}</strong>
            <span>{c === "AAPL" ? "消费电子 · 科技" : "软件 · 云计算"}</span>
          </div>
        </button>
      ))}
      <div className="side-label">研究空间</div>
      {TABS.map((t) => (
        <button
          key={t.key}
          className={`side-btn ${tab === t.key ? "active" : ""}`}
          onClick={() => onTab(t.key)}
        >
          <span className="icon">{t.icon}</span>
          <span>{t.label}</span>
        </button>
      ))}
      <div className="side-footer">
        真实财务数据来自 SEC EDGAR；未接入模块（护城河/管理层/估值/风险/AI）显示 V3 原型模拟数据并已标注。不构成投资建议。
      </div>
    </aside>
  );
}

export function Topbar({
  mode,
  onMode,
  realData,
}: {
  mode: "beginner" | "pro";
  onMode: (m: "beginner" | "pro") => void;
  realData: boolean;
}) {
  return (
    <div className="topbar">
      <div className="searchbox">
        ⌕ <input aria-label="search" placeholder="搜索公司、Ticker（当前支持 AAPL / MSFT）" readOnly />
      </div>
      <div className="top-actions">
        <div className="mode-switch">
          <button className={mode === "beginner" ? "active" : ""} onClick={() => onMode("beginner")}>
            初学者模式
          </button>
          <button className={mode === "pro" ? "active" : ""} onClick={() => onMode("pro")}>
            专业模式
          </button>
        </div>
        <div className={`demo-badge ${realData ? "real" : ""}`}>
          {realData ? "● SEC 真实数据" : "● 模拟数据"}
        </div>
      </div>
    </div>
  );
}

export function Hero({ company }: { company: CompanyInfo | null }) {
  return (
    <div className="hero">
      <div>
        <div className="eyebrow">{company?.sic_description ?? "US Equity"}</div>
        <h1>
          <span>{company?.name ?? company?.ticker ?? "…"}</span>{" "}
          <span className="ticker">{company?.ticker}</span>
        </h1>
        <div className="company-line">
          <span>{company?.exchange ?? ""}</span>
          <span>·</span>
          <span className="pill neutral">行情未配置（V0.1）</span>
          <span className="pill blue">高质量公司研究</span>
        </div>
      </div>
    </div>
  );
}
