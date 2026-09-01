/* eslint-disable @typescript-eslint/no-explicit-any */
"use client";

import { useState } from "react";
import { demoData, demoV3 } from "@/lib/demo";
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

export function ManagementSection({ ticker }: { ticker: string }) {
  const c = demoData[ticker];
  const m = demoV3[ticker].management;
  const a = m.allocation.mix;
  return (
    <>
      <DemoBanner title="管理层" />
      <div className="section-head">
        <div>
          <h2>管理层与公司治理</h2>
          <div className="card-sub">核心问题：战略判断是否正确、承诺是否兑现、赚到的钱是否被高质量配置。</div>
        </div>
        <Pill tone="blue">管理层 {c.scores["管理层"]}/100（Demo）</Pill>
      </div>
      <Card className="mgmt-hero">
        <div>
          <div className="score-orb" style={{ "--score": c.scores["管理层"] } as React.CSSProperties}>
            <div className="orb-inner"><strong>{c.scores["管理层"]}</strong><span>Management Quality</span></div>
          </div>
        </div>
        <div>
          <div className="card-title">管理层质量六维框架</div>
          <div className="card-sub">总分只是入口；真正有价值的是看哪一维在改善、哪一维需要继续验证。</div>
          <div className="mgmt-dimensions">
            {m.dimensions.map((d: any) => (
              <div className="mgmt-dim" key={d[0]}>
                <div className="mgmt-dim-head"><span>{d[0]}</span><strong>{d[1]}</strong></div>
                <div className="mini-track"><i style={{ width: `${d[1]}%` }} /></div>
                <p>{d[2]}</p>
              </div>
            ))}
          </div>
        </div>
      </Card>
      <Card className="card-pad" style={{ marginTop: 16 }}>
        <div className="card-title">Management Promise Tracker（模拟）</div>
        <div className="card-sub">把电话会中的可验证承诺结构化，未来季度自动回来检查。</div>
        <div className="promise-summary">
          <div className="promise-stat"><span>已兑现</span><strong>{m.promises.done}</strong></div>
          <div className="promise-stat"><span>部分兑现</span><strong>{m.promises.partial}</strong></div>
          <div className="promise-stat"><span>未兑现</span><strong>{m.promises.missed}</strong></div>
        </div>
        <table className="promise-table">
          <thead><tr><th>提出时间</th><th>管理层承诺</th><th>验证指标</th><th>验证期</th><th>状态</th></tr></thead>
          <tbody>
            {m.promises.items.map((x: any, i: number) => (
              <tr key={i}>
                <td>{x[0]}</td><td>{x[1]}</td><td>{x[2]}</td><td>{x[3]}</td>
                <td><span className={`status-dot status-${x[5]}`}>{x[4]}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <div className="grid grid-2" style={{ marginTop: 16 }}>
        <Card className="card-pad">
          <div className="card-title">Capital Allocation Quality（模拟）</div>
          <div className="allocation">
            <span className="alloc-1" style={{ width: `${a.buyback}%` }}>{a.buyback}%</span>
            <span className="alloc-2" style={{ width: `${a.dividend}%` }}>{a.dividend}%</span>
            <span className="alloc-3" style={{ width: `${a.capex}%` }}>{a.capex}%</span>
            <span className="alloc-4" style={{ width: `${a.ma}%` }}>{a.ma}%</span>
          </div>
          <div className="allocation-legend">
            <span>■ 回购 {a.buyback}%</span><span>■ 分红 {a.dividend}%</span><span>■ CapEx {a.capex}%</span><span>■ M&A {a.ma}%</span>
          </div>
          <div className="quality-kpis">
            <div className="quality-kpi"><span>5Y FCF</span><strong>{m.allocation.fcf5}</strong></div>
            <div className="quality-kpi"><span>5Y Buyback</span><strong>{m.allocation.buyback5}</strong></div>
            <div className="quality-kpi"><span>ROIC Trend</span><strong>{m.allocation.roicTrend}</strong></div>
            <div className="quality-kpi"><span>CapEx CAGR</span><strong>{m.allocation.capexCagr}</strong></div>
          </div>
          <ExplainNote num="→" title="系统判断">{m.allocation.comment}</ExplainNote>
        </Card>
        <Card className="card-pad">
          <div className="card-title">Shareholder Alignment（模拟）</div>
          <div className="card-sub">不要只看“回购了多少”，还要扣掉股权激励造成的稀释。</div>
          <div className="alignment-grid">
            {m.alignment.map((x: any) => (
              <div className="align-card" key={x[0]}><span>{x[0]}</span><strong>{x[1]}</strong><small>{x[2]}</small></div>
            ))}
          </div>
        </Card>
      </div>
    </>
  );
}

export function ValuationSection({ ticker }: { ticker: string }) {
  const v = demoV3[ticker].valuation;
  return (
    <>
      <DemoBanner title="估值" />
      <div className="section-head">
        <div>
          <h2>估值</h2>
          <div className="card-sub beginner-only">估值不是寻找一个“精确目标价”，而是回答：当前价格对应什么假设？</div>
          <div className="card-sub pro-only">FCFF DCF + 历史倍数 + 同行倍数 + Reverse DCF（模拟）</div>
        </div>
        <Pill tone="warn">{v.archetype} · Demo</Pill>
      </div>
      <Card className="valuation-snapshot" style={{ marginBottom: 16 }}>
        <div className="card-sub">Reference Value Snapshot · Demo 模拟（行情未配置，价格非实时）</div>
        <div className="value-band">
          <div><span className="card-sub">当前价格</span><div className="big-number">${v.market}</div></div>
          <div className="range-number"><span>Base DCF 参考值</span><strong>${Math.round(v.dcf.defaults.wacc * 100)} — 待行情接入</strong></div>
          <div style={{ textAlign: "right" }}><span className="card-sub">模型可信度</span><div className="big-number" style={{ fontSize: 22 }}>{v.confidence}</div></div>
        </div>
      </Card>
      <div className="grid grid-2">
        <Card className="card-pad">
          <div className="card-title">相对估值：和自己过去比（模拟）</div>
          <div className="relative-grid">
            <div className="relative-kpi"><span>Current P/E</span><strong>{v.relative.pe}×</strong></div>
            <div className="relative-kpi"><span>P/FCF</span><strong>{v.relative.pfcf}×</strong></div>
            <div className="relative-kpi"><span>FCF Yield</span><strong>{v.relative.fcfYield}%</strong></div>
            <div className="relative-kpi"><span>10Y P/E Percentile</span><strong>{v.relative.percentile}%</strong></div>
          </div>
          <div className="range-track"><div className="range-marker" style={{ left: `${v.relative.percentile}%` }} /></div>
          <div className="range-labels"><span>25%：{v.relative.hist25}×</span><span>中位：{v.relative.histMedian}×</span><span>75%：{v.relative.hist75}×</span></div>
        </Card>
        <Card className="card-pad">
          <div className="card-title">同行估值比较（模拟）</div>
          <table className="peer-table">
            <thead><tr><th>公司</th><th>P/E</th><th>Revenue Growth</th><th>FCF Margin</th></tr></thead>
            <tbody>
              {v.relative.peers.map((p: any) => (
                <tr key={p[0]}><td>{p[0]}</td><td>{p[1]}×</td><td>{p[2]}%</td><td>{p[3]}%</td></tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
      <div className="card card-pad" style={{ marginTop: 16 }}>
        <div className="card-title">Scenario Valuation（模拟）</div>
        <div className="card-sub">不是给一个目标价，而是明确：什么经营世界对应什么价值。</div>
        <div className="scenario-grid-v3">
          {v.scenarios.map((s: any) => (
            <div className="scenario-v3" key={s[0]}>
              <h3>{s[0]} Case</h3>
              <ul>
                <li>Revenue CAGR {s[1]}%</li><li>Op Margin {s[2]}%</li><li>WACC {s[3]}%</li><li>Terminal {s[4]}%</li><li>{s[5]}</li>
              </ul>
            </div>
          ))}
        </div>
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
