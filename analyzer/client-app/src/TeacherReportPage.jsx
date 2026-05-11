import React, { useEffect, useMemo, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { AlertCircle, BookOpen, CheckCircle2, Loader2, Users, AlertTriangle } from 'lucide-react';
import { AnchorCoverageStrip, AnchorTypeBadge, GraphInsightPanel, MatchAnchorsPanel } from './AnchorPanels';
import ExamSessionPicker from './ExamSessionPicker';

function TeacherReportPage() {
  const location = useLocation();
  const examSessionId = useMemo(() => new URLSearchParams(location.search).get('exam_session_id'), [location.search]);
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState('');

  useEffect(() => {
    const load = async () => {
      if (!examSessionId) {
        setLoading(false);
        return;
      }
      try {
        const response = await fetch(`/api/exam-sessions/${examSessionId}/analysis/teacher-report`);
        if (!response.ok) {
          throw new Error('教师诊断台加载失败。');
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
        <p className="text-slate-600">正在生成教师诊断台...</p>
      </div>
    );
  }

  if (!examSessionId) {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center gap-4 px-4 py-12">
        <Users className="text-slate-400" size={40} />
        <h1 className="text-xl font-bold text-slate-800">教师诊断台</h1>
        <ExamSessionPicker description="本页只展示某一次已导入考试的班级/诊断数据，必须在地址栏带上考试场次 ID（exam_session_id）。" />
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

  const summary = report?.summary || {};
  const teacher = report?.class_breakdown || {};
  const weakKnowledge = teacher?.top_weak_knowledge_points || [];
  const actionPlan = report?.action_plan || [];
  const questionAnalyses = report?.question_analyses || [];

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 pb-16">
      <main className="max-w-5xl mx-auto px-4 py-8 space-y-6">
        <div className="bg-white rounded-3xl border border-slate-100 shadow-sm p-6">
          <div className="flex items-center gap-3 mb-3">
            <Users className="text-blue-600" size={22} />
            <h1 className="text-2xl font-black">教师诊断台</h1>
          </div>
          <p className="text-slate-600 text-sm">
            ExamSession #{report?.exam_session_id} · 学科 {summary.subject || '未命名科目'} ·
            题数 {summary.total_questions || 0}
          </p>
        </div>

        <div className="grid md:grid-cols-4 gap-4">
          {[
            { label: '正确题', value: summary.correct_questions || 0, icon: CheckCircle2, color: 'text-emerald-600', bg: 'bg-emerald-50' },
            { label: '错误题', value: summary.incorrect_questions || 0, icon: AlertTriangle, color: 'text-rose-600', bg: 'bg-rose-50' },
            { label: '待复核', value: summary.uncertain_questions || 0, icon: AlertCircle, color: 'text-amber-600', bg: 'bg-amber-50' },
            { label: '图谱就绪题', value: summary.graph_ready_questions || 0, icon: BookOpen, color: 'text-blue-600', bg: 'bg-blue-50' },
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
            <h2 className="text-lg font-bold mb-4">三层锚点覆盖</h2>
            <AnchorCoverageStrip
              exactRate={summary.exact_match_rate || 0}
              structuralRate={summary.structural_anchor_rate || 0}
              knowledgeRate={summary.knowledge_anchor_rate || 0}
              graphRate={(summary.graph_ready_questions || 0) / Math.max(1, summary.total_questions || 1)}
            />
          </section>
          <section className="bg-white rounded-3xl border border-slate-100 shadow-sm p-6">
            <h2 className="text-lg font-bold mb-4">锚点能力摘要</h2>
            <div className="grid grid-cols-2 gap-4">
              {[
                { label: '标准题命中率', value: `${Math.round((summary.exact_match_rate || 0) * 100)}%` },
                { label: '相似题参考率', value: `${Math.round((summary.structural_anchor_rate || 0) * 100)}%` },
                { label: '知识锚点率', value: `${Math.round((summary.knowledge_anchor_rate || 0) * 100)}%` },
                { label: '平均置信度', value: `${Math.round((summary.average_confidence || 0) * 100)}%` },
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
            <h2 className="text-lg font-bold mb-4">重点薄弱知识点</h2>
            <div className="space-y-3">
              {weakKnowledge.length ? weakKnowledge.map((item) => (
                <div key={item.knowledge_point_id} className="rounded-2xl bg-slate-50 px-4 py-3">
                  <div className="font-semibold text-slate-800">{item.canonical_name}</div>
                  <div className="text-xs text-slate-500 mt-1">
                    ID {item.knowledge_point_id} · 掌握度 {Math.round((item.accuracy || 0) * 100)}%
                  </div>
                </div>
              )) : <p className="text-sm text-slate-500">暂无薄弱知识点。</p>}
            </div>
          </section>

          <section className="bg-white rounded-3xl border border-slate-100 shadow-sm p-6">
            <h2 className="text-lg font-bold mb-4">教师行动建议</h2>
            <div className="space-y-3">
              {actionPlan.length ? actionPlan.map((item, idx) => (
                <div key={`${item.title}-${idx}`} className="rounded-2xl bg-slate-50 px-4 py-3">
                  <div className="font-semibold text-slate-800">{item.title}</div>
                  <div className="text-sm text-slate-600 mt-1">{item.description}</div>
                </div>
              )) : <p className="text-sm text-slate-500">暂无行动建议。</p>}
            </div>
          </section>
        </div>

        <section className="bg-white rounded-3xl border border-slate-100 shadow-sm p-6">
          <h2 className="text-lg font-bold mb-4">待人工复核题号</h2>
          <div className="flex flex-wrap gap-2">
            {(teacher.manual_review_question_nos || []).length
              ? teacher.manual_review_question_nos.map((qno) => (
                <span key={qno} className="px-3 py-1.5 rounded-lg bg-amber-50 text-amber-700 border border-amber-100 text-sm">
                  第 {qno} 题
                </span>
              ))
              : <span className="text-sm text-slate-500">当前无待复核题。</span>}
          </div>
        </section>

        <section className="bg-white rounded-3xl border border-slate-100 shadow-sm p-6 space-y-4">
          <h2 className="text-lg font-bold">题级锚点与 GraphRAG 视图</h2>
          <div className="space-y-4">
            {questionAnalyses.slice(0, 6).map((item) => (
              <div key={item.exam_question_id} className="rounded-2xl border border-slate-100 bg-slate-50/40 p-4 space-y-4">
                <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-3">
                  <div className="space-y-2">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-bold text-slate-400">第 {item.source_question_no} 题</span>
                      <AnchorTypeBadge type={item.match_anchor_type} />
                      {item.needs_manual_review ? <span className="text-xs px-2 py-1 rounded-full bg-amber-50 text-amber-700 border border-amber-100">需复核</span> : null}
                    </div>
                    <div className="font-semibold text-slate-800">{item.question_summary}</div>
                    {item.match_anchor_summary ? <div className="text-sm text-slate-600">{item.match_anchor_summary}</div> : null}
                  </div>
                  <div className="text-sm text-slate-500">
                    置信度 {Math.round((item.confidence || 0) * 100)}%
                  </div>
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

export default TeacherReportPage;
