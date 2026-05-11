import React, { useEffect, useMemo, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { AlertCircle, FileSearch, Loader2 } from 'lucide-react';
import { AnchorCoverageStrip, AnchorTypeBadge, GraphInsightPanel, MatchAnchorsPanel } from './AnchorPanels';
import ExamSessionPicker from './ExamSessionPicker';

function MatchesPage() {
  const location = useLocation();
  const examSessionId = useMemo(() => new URLSearchParams(location.search).get('exam_session_id'), [location.search]);
  const [matches, setMatches] = useState([]);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState('');

  useEffect(() => {
    const load = async () => {
      if (!examSessionId) {
        setLoading(false);
        return;
      }
      try {
        const response = await fetch(`/api/exam-sessions/${examSessionId}/matches`);
        if (!response.ok) {
          throw new Error('匹配结果加载失败。');
        }
        setMatches(await response.json());
      } catch (error) {
        setErrorMessage(error.message || '加载失败');
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [examSessionId]);

  const metrics = useMemo(() => {
    const total = matches.length || 1;
    const countBy = (type) => matches.filter((item) => (item.match_anchors || {}).primary_anchor_type === type).length;
    return {
      total: matches.length,
      exactRate: countBy('exact_match') / total,
      structuralRate: countBy('structural_match') / total,
      knowledgeRate: countBy('knowledge_anchor') / total,
      graphRate: 0,
    };
  }, [matches]);

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center flex-col gap-4">
        <Loader2 className="animate-spin text-blue-600" size={44} />
        <p className="text-slate-600">正在加载匹配锚点视图...</p>
      </div>
    );
  }

  if (!examSessionId) {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center gap-4 px-4 py-12">
        <FileSearch className="text-slate-400" size={40} />
        <h1 className="text-xl font-bold text-slate-800">三层锚点匹配</h1>
        <ExamSessionPicker description="匹配结果按单次考试（ExamSession）展示，请在地址栏指定 exam_session_id。" />
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

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 pb-16">
      <main className="max-w-6xl mx-auto px-4 py-8 space-y-6">
        <div className="bg-white rounded-3xl border border-slate-100 shadow-sm p-6">
          <div className="flex items-center gap-3 mb-3">
            <FileSearch className="text-blue-600" size={22} />
            <h1 className="text-2xl font-black">三层锚点匹配视图</h1>
          </div>
          <p className="text-slate-600 text-sm">
            ExamSession #{examSessionId} · 展示标准题命中、相似题参考、知识锚点与 exact 失败原因
          </p>
        </div>

        <div className="grid lg:grid-cols-[1.1fr_0.9fr] gap-6">
          <section className="bg-white rounded-3xl border border-slate-100 shadow-sm p-6">
            <h2 className="text-lg font-bold mb-4">锚点覆盖概览</h2>
            <AnchorCoverageStrip
              exactRate={metrics.exactRate}
              structuralRate={metrics.structuralRate}
              knowledgeRate={metrics.knowledgeRate}
              graphRate={0}
            />
          </section>
          <section className="grid grid-cols-2 gap-4">
            {[
              { label: '题目数', value: metrics.total },
              { label: '标准题命中', value: matches.filter((item) => (item.match_anchors || {}).primary_anchor_type === 'exact_match').length },
              { label: '相似题参考', value: matches.filter((item) => (item.match_anchors || {}).primary_anchor_type === 'structural_match').length },
              { label: '知识锚点', value: matches.filter((item) => (item.match_anchors || {}).primary_anchor_type === 'knowledge_anchor').length },
            ].map((item) => (
              <div key={item.label} className="bg-white rounded-3xl border border-slate-100 shadow-sm p-5">
                <div className="text-xs uppercase tracking-wider text-slate-400">{item.label}</div>
                <div className="text-3xl font-black text-slate-800 mt-2">{item.value}</div>
              </div>
            ))}
          </section>
        </div>

        <section className="space-y-4">
          {matches.map((item) => {
            const anchors = item.match_anchors || {};
            const diagnostics = anchors.diagnostics || {};
            return (
              <div key={item.exam_question_id} className="bg-white rounded-3xl border border-slate-100 shadow-sm p-6 space-y-5">
                <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-4">
                  <div className="space-y-2">
                    <div className="flex items-center gap-3 flex-wrap">
                      <span className="text-sm font-bold text-slate-400">第 {item.source_question_no} 题</span>
                      <AnchorTypeBadge type={anchors.primary_anchor_type} />
                      {item.review_status ? <span className="text-xs px-2.5 py-1 rounded-full bg-slate-100 text-slate-600">{item.review_status}</span> : null}
                    </div>
                    <h3 className="text-lg font-bold text-slate-800 max-w-3xl">{item.recognized_text || '暂无识别题干'}</h3>
                  </div>
                  <div className="text-sm text-slate-500">
                    {diagnostics.exact_failure_reason ? `exact 未放行：${diagnostics.exact_failure_reason}` : 'exact 已命中'}
                  </div>
                </div>

                <div className="grid lg:grid-cols-[1.2fr_0.8fr] gap-5">
                  <MatchAnchorsPanel anchors={anchors} />
                  <GraphInsightPanel graphPath={null} retrievalEvidence={[]} compact />
                </div>
              </div>
            );
          })}
        </section>
      </main>
    </div>
  );
}

export default MatchesPage;
