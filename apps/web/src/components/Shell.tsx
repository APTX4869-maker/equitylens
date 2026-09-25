"use client";

import { useState } from "react";
import type { CompanyInfo, CompanyListItem, MarketQuote } from "@/lib/types";

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

export function Sidebar({
  companies,
  company,
  tab,
  onCompany,
  onTab,
  onAddCompany,
  onOnboardingCenter,
}: {
  companies: CompanyListItem[];
  company: string;
  tab: TabKey;
  onCompany: (c: string) => void;
  onTab: (t: TabKey) => void;
  onAddCompany: () => void;
  onOnboardingCenter: () => void;
}) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">E</div>
        <span>EquityLens</span>
      </div>
      <div className="side-label">研究公司</div>
      <div data-testid="company-list">
      {companies.map((item) => (
        <button
          key={item.security_id}
          className={`company-btn ${company === item.ticker ? "active" : ""}`}
          onClick={() => onCompany(item.ticker)}
        >
          <div className="ticker-box">{item.ticker}</div>
          <div className="company-meta">
            <strong>{item.name}</strong>
            <span>{item.exchange ?? "交易所未标注"} · {item.quality_status}</span>
          </div>
        </button>
      ))}
      </div>
      <div className="company-ops">
        <button onClick={onAddCompany}><span>＋</span>添加公司</button>
        <button onClick={onOnboardingCenter}><span>◫</span>建档中心</button>
      </div>
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
        事实来自 SEC EDGAR，计算来自确定性代码，行情为公开非授权源（研究用途）；观点均带证据与来源可溯源。不构成投资建议。
      </div>
    </aside>
  );
}

export function Topbar({
  companies,
  mode,
  onMode,
  realData,
  onCompany,
  onAddCompany,
  onOnboardingCenter,
}: {
  companies: CompanyListItem[];
  mode: "beginner" | "pro";
  onMode: (m: "beginner" | "pro") => void;
  realData: boolean;
  onCompany: (c: string) => void;
  onAddCompany: () => void;
  onOnboardingCenter: () => void;
}) {
  const [q, setQ] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const search = () => {
    const t = q.trim().toUpperCase();
    if (!t) return;
    if (companies.some((item) => item.ticker === t)) {
      onCompany(t);
      setQ("");
      setMsg(null);
    } else {
      setMsg(`研究列表中没有 ${t}，可使用“添加公司”启动建档。`);
    }
  };
  return (
    <div className="topbar">
      <div className="searchbox">
        ⌕ <input
          aria-label="search"
          placeholder="搜索已发布公司或 Ticker"
          value={q}
          onChange={(e) => { setQ(e.target.value); setMsg(null); }}
          onKeyDown={(e) => { if (e.key === "Enter") search(); }}
        />
        {msg ? <span className="tool-value" style={{ marginLeft: 8 }}>{msg}</span> : null}
      </div>
      <div className="top-actions">
        <div className="mobile-company-actions"><button onClick={onAddCompany}>＋ 添加公司</button><button onClick={onOnboardingCenter}>建档中心</button></div>
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

export function Hero({ company, market }: { company: CompanyInfo | null; market?: MarketQuote | null }) {
  const mq = market?.status === "OK" && market.quote ? market.quote : null;
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
          <span className={mq ? "pill good" : "pill neutral"}>
            {mq
              ? `行情 ${mq.provider_label} $${mq.price.toFixed(2)} · ${mq.observed_at}`
              : "行情未同步"}
          </span>
          <span className="pill blue">高质量公司研究</span>
        </div>
      </div>
    </div>
  );
}
