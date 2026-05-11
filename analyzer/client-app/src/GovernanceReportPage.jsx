import React, { useEffect, useMemo, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { AlertCircle, BarChart3, Database, Loader2, Network, ShieldAlert } from 'lucide-react';
import { AnchorCoverageStrip, AnchorTypeBadge, GraphInsightPanel, MatchAnchorsPanel } from './AnchorPanels';
import ExamSessionPicker from './ExamSessionPicker';

function GovernanceReportPage() {
  const location = useLocation();
  const examSessionId = useMemo(() => new URLSearchParams(location.search).get('exam_session_id'), [location.search]);
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState('');

  useEffect(() => {
    const load = async () => {
      if (!examSessionId) {
        setErrorMessage('请通过 ?exam_session_id=xxx 打开治理台。');
        setLoading(false);
        return;
      }
      try {
        const response = await fetch(`/api/exam-sessions/${examSessionId}/analysis/governance-report`);
        if (!response.ok) {
          throw new Error('治理台加载失败。');
        }
        setReport(await response.json());
      } catch (error) {
        setErrorMessage(error.message || '加载失败');
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [examSessionId]);

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center flex-col gap-4">
        <Loader2 className="animate-spin text-blue-600" size={44} />
        <p className="text-slate-600">正在生成治理台...</p>
      </div>
    );
  }

  if (!examSessionId) {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center gap-4 px-4 py-12">
        <ShieldAlert className="text-slate-400" size={40} />
        <h1 className="text-xl font-bold text-slate-800">治理台</h1>
        <ExamSessionPicker description="治理与质量看板按单次考试（ExamSession）统计，请先在地址栏指定 exam_session_id。" />
      </div>
    );
  }

  if (errorMessage) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center flex-col gap-4">
        <AlertCircle className="text-rose-500" size={42} />
        <p className="text-slate-700">{errorMessage}</p>
      </div>
    );
  }

  const metrics = report?.governance_metrics || {};
  const graph = report?.graph_overview || {};
  const mistakes = report?.mistake_profile || [];
  const questionAnalyses = report?.question_analyses || [];

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 pb-16">
      <main className="max-w-5xl mx-auto px-4 py-8 space-y-6">
        <div className="bg-white rounded-3xl border border-slate-100 shadow-sm p-6">
          <div className="flex items-center gap-3 mb-3">
            <ShieldAlert className="text-indigo-600" size={22} />
            <h1 className="text-2xl font-black">教研治理台</h1>
          </div>
          <p className="text-slate-600 text-sm">
            ExamSession #{report?.exam_session_id} · 面向质量监控、图谱覆盖与人工复核治理
          </p>
        </div>

        <div className="grid md:grid-cols-4 gap-4">
          {[
            { label: '题目总数', value: metrics.question_count || 0, icon: BarChart3, color: 'text-blue-600', bg: 'bg-blue-50' },
            { label: '知识点覆盖', value: metrics.knowledge_point_coverage || 0, icon: Database, color: 'text-emerald-600', bg: 'bg-emerald-50' },
            { label: '人工复核率', value: `${Math.round((metrics.manual_review_rate || 0) * 100)}%`, icon: AlertCircle, color: 'text-amber-600', bg: 'bg-amber-50' },
            { label: '图谱就绪率', value: `${Math.round((metrics.graph_ready_rate || 0) * 100)}%`, icon: Network, color: 'text-indigo-600', bg: 'bg-indigo-50' },
          ].map((item) => (
            <div key={item.label} className={`rounded-2xl border border-transparent p-4 shadow-sm ${item.bg}`}>
              <item.icon className={item.color} size={18} />
              <div className="text-2xl font-bold mt-2">{item.value}</div>
              <div className="text-xs text-slate-500 mt-1">{item.label}</div>
            </div>
          ))}
        </div>

        <div className="grid lg:grid-cols-[1.1fr_0.9fr] gap-6">
          <section className="bg-white rounded-3xl border border-slate-100 shadow-sm p-6">
            <h2 className="text-lg font-bold mb-4">三层锚点治理分布</h2>
            <AnchorCoverageStrip
              exactRate={metrics.exact_match_rate || 0}
              structuralRate={metrics.structural_anchor_rate || 0}
              knowledgeRate={metrics.knowledge_anchor_rate || 0}
              graphRate={metrics.graph_ready_rate || 0}
            />
          </section>
          <section className="bg-white rounded-3xl border border-slate-100 shadow-sm p-6">
            <h2 className="text-lg font-bold mb-4">治理诊断摘要</h2>
            <div className="grid grid-cols-2 gap-4">
              {[
                { label: '标准题命中率', value: `${Math.round((metrics.exact_match_rate || 0) * 100)}%` },
                { label: '相似题参考率', value: `${Math.round((metrics.structural_anchor_rate || 0) * 100)}%` },
                { label: '知识锚点率', value: `${Math.round((metrics.knowledge_anchor_rate || 0) * 100)}%` },
                { label: '证据就绪率', value: `${Math.round((metrics.evidence_ready_rate || 0) * 100)}%` },
              ].map((item) => (
                <div key={item.label} className="rounded-2xl bg-slate-50 px-4 py-3">
                  <div className="text-xs text-slate-500">{item.label}</div>
                  <div className="text-2xl font-bold text-slate-800 mt-1">{item.value}</div>
                </div>
              ))}
            </div>
          </section>
        </div>

        <div className="grid lg:grid-cols-2 gap-6">
          <section className="bg-white rounded-3xl border border-slate-100 shadow-sm p-6">
            <h2 className="text-lg font-bold mb-4">图谱命中概况</h2>
            <div className="space-y-3 text-sm text-slate-700">
              <div className="flex items-center justify-between"><span>带图路径题数</span><strong>{graph.question_with_graph_paths || 0}</strong></div>
              <div className="flex items-center justify-between"><span>命中图节点</span><strong>{graph.graph_node_hits || 0}</strong></div>
              <div className="flex items-center justify-between"><span>命中图关系</span><strong>{graph.graph_edge_hits || 0}</strong></div>
              <div className="flex items-center justify-between"><span>证据就绪率</span><strong>{Math.round((metrics.evidence_ready_rate || 0) * 100)}%</strong></div>
            </div>
          </section>

          <section className="bg-white rounded-3xl border border-slate-100 shadow-sm p-6">
            <h2 className="text-lg font-bold mb-4">错因治理概览</h2>
            <div className="space-y-3">
              {mistakes.length ? mistakes.slice(0, 5).map((item) => (
                <div key={item.code} className="rounded-2xl bg-slate-50 px-4 py-3">
                  <div className="font-semibold text-slate-800">{item.name}</div>
                  <div className="text-xs text-slate-500 mt-1">
                    {item.category} · 出现 {item.count} 次 · 题号 {item.question_nos.join('、') || '—'}
                  </div>
                </div>
              )) : <p className="text-sm text-slate-500">暂无错因治理数据。</p>}
            </div>
          </section>
        </div>

        <section className="bg-white rounded-3xl border border-slate-100 shadow-sm p-6 space-y-4">
          <h2 className="text-lg font-bold">题级能力抽样</h2>
          <div className="space-y-4">
            {questionAnalyses
              .slice()
              .sort((a, b) => ((b.graph_path?.nodes?.length || 0) + (b.retrieval_evidence?.length || 0)) - ((a.graph_path?.nodes?.length || 0) + (a.retrieval_evidence?.length || 0)))
              .slice(0, 4)
              .map((item) => (
                <div key={item.exam_question_id} className="rounded-2xl border border-slate-100 bg-slate-50/40 p-4 space-y-4">
                  <div className="flex items-center justify-between gap-3 flex-wrap">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-bold text-slate-400">第 {item.source_question_no} 题</span>
                        <AnchorTypeBadge type={item.match_anchor_type} />
                      </div>
                      <div className="font-semibold text-slate-800">{item.question_summary}</div>
                    </div>
                    <div className="text-sm text-slate-500">{item.match_anchor_summary}</div>
                  </div>
                  <div className="grid lg:grid-cols-2 gap-4">
                    <MatchAnchorsPanel anchors={item.match_anchors} compact />
                    <GraphInsightPanel graphPath={item.graph_path} retrievalEvidence={item.retrieval_evidence} compact />
                  </div>
                </div>
              ))}
          </div>
        </section>
      </main>
    </div>
  );
}

export default GovernanceReportPage;
