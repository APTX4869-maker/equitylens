"use client";

import type { HTMLAttributes, ReactNode } from "react";

type CardProps = HTMLAttributes<HTMLDivElement> & { children: ReactNode };

export function Card({ children, className = "", ...props }: CardProps) {
  return (
    <div className={`card ${className}`} {...props}>
      {children}
    </div>
  );
}

export function SectionHead({ title, sub, right }: { title: ReactNode; sub?: ReactNode; right?: ReactNode }) {
  return (
    <div className="section-head">
      <div>
        <h2>{title}</h2>
        {sub ? <div className="card-sub">{sub}</div> : null}
      </div>
      {right}
    </div>
  );
}

export function Pill({ tone = "blue", children }: { tone?: "blue" | "good" | "warn" | "bad" | "neutral"; children: ReactNode }) {
  const cls = tone === "good" ? "good" : tone === "warn" ? "warn" : tone === "bad" ? "bad" : tone === "neutral" ? "neutral" : "blue";
  return <span className={`pill ${cls}`}>{children}</span>;
}

export function SignalDot({ tone }: { tone: "good" | "warn" | "bad" }) {
  return <span className={`signal-dot ${tone}`} />;
}

export function Spinner({ label = "加载中…" }: { label?: string }) {
  return (
    <div className="card card-pad" style={{ textAlign: "center", color: "var(--muted)" }}>
      <div className="spinner" /> {label}
    </div>
  );
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="card card-pad" style={{ borderLeft: "3px solid var(--bad)" }}>
      <strong style={{ color: "var(--bad)" }}>数据加载失败</strong>
      <p style={{ color: "var(--muted)", fontSize: 12, marginTop: 4 }}>{message}</p>
      {onRetry ? (
        <button className="tab-btn" style={{ marginTop: 8 }} onClick={onRetry}>
          重试
        </button>
      ) : null}
    </div>
  );
}

/** Beginner-mode explainer box. */
export function ExplainNote({ num, title, children }: { num: ReactNode; title: ReactNode; children: ReactNode }) {
  return (
    <div className="beginner-note">
      <div>{num}</div>
      <div>
        <strong>{title}</strong>
        <p>{children}</p>
      </div>
    </div>
  );
}
