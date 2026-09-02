/* eslint-disable @typescript-eslint/no-explicit-any */
"use client";

import { useState } from "react";
import { demoData } from "@/lib/demo";
import { Card, Pill, ExplainNote } from "@/components/ui";

const DEMO_LABEL = "V3 原型模拟数据 · 未接入真实管线";

function DemoBanner({ title }: { title: string }) {
  return (
    <div className="demo-banner">
      <strong>⚠ {title}</strong> — 本页为 {DEMO_LABEL}。页面顶部的总览与财务分析已使用 SEC 真实数据。
    </div>
  );
}

export function MoatSection({ ticker }: { ticker: string }) {
  const c = demoData[ticker];
  const [open, setOpen] = useState(0);
  return (
    <>
      <DemoBanner title="护城河" />
      <div className="section-head">
        <div>
          <h2>护城河分析</h2>
          <div className="card-sub">不是让 AI 随便打分：每一个结论都要求证据、反面证据和置信度。</div>
        </div>
        <Pill tone="good">护城河 {c.scores["护城河"]}/100（Demo）</Pill>
      </div>
      <div className="grid grid-2">
        <div>
          {c.moat.map((m: any, i: number) => (
            <div key={m.name} className={`moat-item ${open === i ? "open" : ""}`}>
              <button className="moat-head" onClick={() => setOpen(open === i ? -1 : i)}>
                <div>
                  <div className="moat-title">{m.name}</div>
                  <div className="moat-desc">{m.desc}</div>
                </div>
                <div className="stars">{"★".repeat(m.score)}{"☆".repeat(5 - m.score)}</div>
                <div className="chev">⌄</div>
              </button>
              <div className="moat-body">
                <div className="evidence-grid">
                  <div className="evidence-box"><h4>支持证据</h4><ul>{m.evidence.map((x: any) => <li key={x}>{x}</li>)}</ul></div>
                  <div className="evidence-box"><h4>反面证据</h4><ul>{m.counter.map((x: any) => <li key={x}>{x}</li>)}</ul></div>
                </div>
                <div className="confidence">AI 置信度：<strong>{m.confidence}</strong> · 模拟数据</div>
              </div>
            </div>
          ))}
        </div>
        <Card className="card-pad">
          <div className="card-title">为什么这样设计？</div>
          <div className="card-sub">避免“苹果品牌很强，所以护城河 5 星”这种没有研究价值的 AI 套话。</div>
          <ExplainNote num="①" title="先定义护城河类型">转换成本、网络效应、品牌、成本优势、规模优势等。</ExplainNote>
          <ExplainNote num="②" title="必须同时看反面证据">研究不是证明自己是对的，而是主动寻找可能推翻观点的信息。</ExplainNote>
          <ExplainNote num="③" title="最终要落到财务结果">真正的护城河最终通常会体现在定价权、利润率、客户留存或 ROIC 上。</ExplainNote>
        </Card>
      </div>
    </>
  );
}

