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

export function RisksSection({ ticker }: { ticker: string }) {
  const c = demoData[ticker];
  return (
    <>
      <DemoBanner title="风险" />
      <div className="section-head">
        <div>
          <h2>风险清单</h2>
          <div className="card-sub">风险不是列得越多越专业，而是明确“什么事情发生，会让投资逻辑失效”。</div>
        </div>
        <Pill tone="warn">需持续跟踪 · Demo</Pill>
      </div>
      <div className="grid grid-2">
        <div className="risk-list">
          {c.risks.map((r: any) => (
            <div className="risk-item" key={r[2]}>
              <div className={`risk-level ${r[1]}`} style={{ background: `var(--${r[1]}-soft)`, color: `var(--${r[1]})` }}>{r[0]}</div>
              <div><h3>{r[2]}</h3><p>{r[3]}</p></div>
              <div className="risk-prob">发生概率：{r[4]}</div>
            </div>
          ))}
        </div>
        <Card className="card-pad">
          <div className="card-title">Thesis Breakers</div>
          <div className="card-sub">未来正式产品里，建议你给每家公司固定维护 3-5 个“逻辑失效条件”。</div>
          <ExplainNote num="1" title="连续两年核心业务增速显著低于行业">说明竞争力或市场空间判断可能错了。</ExplainNote>
          <ExplainNote num="2" title="ROIC 与自由现金流率持续恶化">说明增长可能是靠更多资本堆出来的。</ExplainNote>
          <ExplainNote num="3" title="护城河证据被新技术/监管削弱">定性变化最终通常会反映到财务指标。</ExplainNote>
        </Card>
      </div>
    </>
  );
}

export function AiSection({ ticker }: { ticker: string }) {
  const c = demoData[ticker];
  const keys = Object.keys(c.ai);
  const [aiKey, setAiKey] = useState(keys[0]);
  const a = c.ai[aiKey];
  return (
    <>
      <DemoBanner title="AI研究助手" />
      <div className="section-head">
        <div>
          <h2>AI研究助手</h2>
          <div className="card-sub">Demo 展示的是“AI 解释层”：数字来自数据引擎，观点必须带 Evidence。</div>
        </div>
        <Pill tone="good">Evidence-first · Demo</Pill>
      </div>
      <div className="ai-layout">
        <Card className="ai-questions">
          <h3>试试这些问题</h3>
          {keys.map((k) => (
            <button key={k} className={`question-btn ${aiKey === k ? "active" : ""}`} onClick={() => setAiKey(k)}>
              {c.ai[k].q}
            </button>
          ))}
        </Card>
        <Card className="ai-answer">
          <div className="ai-kicker">AI RESEARCHER · 模拟回答</div>
          <h2>{a.title}</h2>
          <p>真实系统会从结构化财务数据、10-K/10-Q 与电话会议中拉取证据。</p>
          {a.points.map((p: any, i: number) => (
            <div className="answer-point" key={i}>
              <div className="answer-num">{i + 1}</div>
              <div><strong>{p[0]}</strong><span>{p[1]}</span></div>
            </div>
          ))}
          <div className="sources">{a.sources.map((s: any) => <span className="source-chip" key={s}>↗ {s}</span>)}</div>
          <div className="ai-disclaimer">AI 只负责解释和组织证据；财务数字由结构化数据与确定性公式计算。</div>
        </Card>
      </div>
    </>
  );
}
