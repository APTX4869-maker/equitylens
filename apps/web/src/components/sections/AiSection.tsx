"use client";

import { useCallback, useState } from "react";
import { api } from "@/lib/api";
import { Card, Pill, ErrorBox, Spinner } from "@/components/ui";

type Claim = { claim: string; confidence: string; evidence_ids: string[] };
type AskResponse = {
  intent: string;
  supported_topics: string[];
  answer: string;
  claims: Claim[];
  metric_ids: string[];
  limitations: string[];
};

const SUGGESTIONS = [
  "公司最近的风险有哪些？",
  "利润率现在怎么样？",
  "现金流和回购情况？",
  "收入增长为什么放缓？",
  "业务构成如何？",
  "估值怎么看？",
];

export function AiSection({ ticker, onOpenSource }: { ticker: string; onOpenSource: (id: string) => void }) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<(AskResponse & { _t: string }) | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const ask = useCallback(
    async (q: string) => {
      if (!q.trim()) return;
      setLoading(true);
      setError(null);
      try {
        const d = await api.fetchJson<AskResponse>(`/api/v1/research/ask`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ticker, question: q }),
        });
        setAnswer({ ...d, _t: ticker });
      } catch (e) {
        setError(String(e));
      } finally {
        setLoading(false);
      }
    },
    [ticker]
  );

  return (
    <>
      <div className="demo-banner real">
        <strong>✓ 研究助手（规则检索）</strong> — 当前不是任意问答 AI。它只处理增长、利润率、现金流、风险、估值、业务构成和指标解释，无法支持的问题会直接说明。
      </div>
      <div className="section-head">
        <div>
          <h2>研究助手</h2>
          <div className="card-sub">问真实数据能回答的问题：增长/利润率/现金流/风险/估值/业务构成。</div>
        </div>
        <Pill tone="good">证据优先 · 规则检索</Pill>
      </div>

      <div className="ai-layout">
        <Card className="ai-questions">
          <h3>试试这些问题</h3>
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              className={`question-btn ${question === s ? "active" : ""}`}
              onClick={() => {
                setQuestion(s);
                ask(s);
              }}
            >
              {s}
            </button>
          ))}
          <div style={{ marginTop: 12 }}>
            <input
              style={{ width: "100%", padding: "10px 12px", borderRadius: 10, border: "1px solid var(--line)", fontSize: 13 }}
              placeholder="输入你的研究问题…（仅回答有真实证据的问题）"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && ask(question)}
            />
            <button className="tab-btn" style={{ marginTop: 8, width: "100%" }} disabled={loading} onClick={() => ask(question)}>
              {loading ? "检索中…" : "提问"}
            </button>
          </div>
        </Card>

        <Card className="ai-answer">
          {error ? <ErrorBox message={error} /> : null}
          {loading ? <Spinner label="正在检索真实证据…" /> : null}
          {!answer && !loading && !error ? (
            <div className="muted">选择左侧问题或输入新问题。答案中的每条结论都带证据，无法回答的会明说。</div>
          ) : null}
          {answer && !loading && answer._t === ticker ? (
            <>
              <div className="ai-kicker">RESEARCH HELPER · 规则检索</div>
              <h2 style={{ fontSize: 17 }}>{answer.answer}</h2>
              {answer.claims.map((c, i) => (
                <div className="answer-point" key={i}>
                  <div className="answer-num">{i + 1}</div>
                  <div>
                    <strong>{c.claim}</strong>
                    <span className="card-sub">
                      置信度 {c.confidence}
                      {c.evidence_ids.length ? " · " : " · 结构性说明（无数字）"}
                    </span>
                    {c.evidence_ids.map((id) => (
                      <button className="text-link" key={id} onClick={() => onOpenSource(id)}>
                        证据 {id.slice(0, 12)}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
              {answer.limitations.length ? (
                <div className="warning-box" style={{ marginTop: 12 }}>
                  <strong>限制与说明：</strong>
                  <ul style={{ margin: "4px 0 0 16px", fontSize: 11 }}>
                    {answer.limitations.map((l, i) => <li key={i}>{l}</li>)}
                  </ul>
                </div>
              ) : null}
              <div className="ai-disclaimer">
                本助手当前使用确定性规则检索。规则固定只表示同输入可复现，不保证解释或投资结论正确；数值证据可点击溯源。
              </div>
            </>
          ) : null}
        </Card>
      </div>
    </>
  );
}
