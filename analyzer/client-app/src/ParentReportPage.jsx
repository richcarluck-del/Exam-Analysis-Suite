import React, { useState, useEffect, useMemo } from 'react';
import { useLocation } from 'react-router-dom';
import { 
  TrendingUp, 
  CheckCircle2, 
  XCircle, 
  AlertCircle, 
  FileText, 
  Calendar, 
  Target, 
  ChevronRight, 
  Image as ImageIcon,
  Award,
  Loader2
} from 'lucide-react';
import { 
  ResponsiveContainer, 
  Radar, 
  RadarChart, 
  PolarGrid, 
  PolarAngleAxis, 
  PolarRadiusAxis,
} from 'recharts';
import { motion, AnimatePresence } from 'framer-motion';
import { AnchorCoverageStrip, AnchorTypeBadge, GraphInsightPanel, MatchAnchorsPanel } from './AnchorPanels';
import ExamSessionPicker from './ExamSessionPicker';

const safeNumber = (value, fallback = 0) => {
  const num = Number(value);
  return Number.isFinite(num) ? num : fallback;
};

const formatDate = (isoString) => {
  if (!isoString) return '—';
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toISOString().slice(0, 10);
};

const calcPercent = (part, total) => {
  const t = safeNumber(total, 0);
  if (!t) return 0;
  return Math.round((safeNumber(part, 0) / t) * 100);
};

const mapCorrectnessToStatus = (correctness, needsManualReview) => {
  if (needsManualReview) return 'uncertain';
  if (correctness === 'correct') return 'correct';
  if (correctness === 'incorrect') return 'incorrect';
  return 'uncertain';
};

const StatusBadge = ({ status }) => {
  const configs = {
    correct: { icon: CheckCircle2, color: 'text-emerald-500', bg: 'bg-emerald-50', text: '正确' },
    incorrect: { icon: XCircle, color: 'text-rose-500', bg: 'bg-rose-50', text: '错误' },
    uncertain: { icon: AlertCircle, color: 'text-amber-500', bg: 'bg-amber-50', text: '待核实' },
  };
  const config = configs[status] || configs.uncertain;
  const Icon = config.icon;

  return (
    <div className={`flex items-center gap-1.5 px-3 py-1 rounded-full ${config.bg} ${config.color} text-sm font-medium`}>
      <Icon size={14} />
      <span>{config.text}</span>
    </div>
  );
};

const QuestionCard = ({ question }) => {
  const [isExpanded, setIsExpanded] = useState(false);

  return (
    <motion.div layout className="bg-white rounded-2xl border border-slate-100 shadow-sm hover:shadow-md transition-shadow overflow-hidden">
      <div
        className="p-5 flex items-center justify-between cursor-pointer select-none"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-4">
          <div className={`w-10 h-10 rounded-xl flex items-center justify-center font-bold text-lg ${
            question.status === 'correct' ? 'bg-emerald-100 text-emerald-600' :
            question.status === 'incorrect' ? 'bg-rose-100 text-rose-600' : 'bg-amber-100 text-amber-600'
          }`}>
            {question.questionNo}
          </div>
          <div>
            <h4 className="font-semibold text-slate-800 line-clamp-1">{question.summary}</h4>
            <div className="flex items-center gap-2 mt-2 flex-wrap">
              <AnchorTypeBadge type={question.anchorType} />
              {question.anchorSummary ? <span className="text-xs text-slate-500">{question.anchorSummary}</span> : null}
            </div>
            <div className="flex gap-2 mt-1 flex-wrap">
              {question.knowledgePoints.slice(0, 3).map(kp => (
                <span key={kp} className="text-xs px-2 py-0.5 bg-slate-100 text-slate-600 rounded">#{kp}</span>
              ))}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <StatusBadge status={question.status} />
          <motion.div animate={{ rotate: isExpanded ? 90 : 0 }} className="text-slate-400">
            <ChevronRight size={20} />
          </motion.div>
        </div>
      </div>

      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="border-t border-slate-50 bg-slate-50/30"
          >
            <div className="p-5 space-y-6">
              <div className="space-y-2">
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">题目与解析回顾</span>
                <div className="rounded-lg border border-slate-200 bg-white p-2 min-h-[150px] flex items-center justify-center relative group overflow-hidden">
                  <img
                    src={question.imageUrl}
                    alt="Question"
                    className="max-w-full rounded"
                    onError={(e) => { e.currentTarget.src = "https://via.placeholder.com/600x200?text=Image+Not+Available"; }}
                  />
                  <div className="absolute inset-0 bg-black/5 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                    <span className="bg-white/90 px-3 py-1.5 rounded-full text-xs font-bold text-slate-700 shadow-lg flex items-center gap-2">
                      <ImageIcon size={14} /> 查看大图
                    </span>
                  </div>
                </div>
                {question.imagePath && (
                  <div className="text-xs text-slate-400">图像来源: {question.imagePath}</div>
                )}
              </div>

              {(question.solutionSteps || question.llmAnswer) && (
                <div className="bg-gradient-to-r from-violet-50 to-purple-50 rounded-xl p-5 border border-violet-100 space-y-4">
                  <h5 className="flex items-center gap-2 text-sm font-bold text-violet-700">
                    <Target size={16} className="text-violet-500" />
                    AI 解题步骤与答案（模型自主推理）
                  </h5>
                  {question.solutionSteps && (
                    <div className="space-y-1">
                      <span className="text-xs font-semibold text-violet-500 uppercase tracking-wider">解题步骤</span>
                      <div className="text-sm text-slate-700 leading-relaxed whitespace-pre-wrap bg-white/70 rounded-lg p-3 border border-violet-50">
                        {question.solutionSteps}
                      </div>
                    </div>
                  )}
                  {question.llmAnswer && (
                    <div className="space-y-1">
                      <span className="text-xs font-semibold text-violet-500 uppercase tracking-wider">模型答案</span>
                      <div className="text-sm font-semibold text-slate-800 bg-white/70 rounded-lg p-3 border border-violet-50">
                        {question.llmAnswer}
                      </div>
                    </div>
                  )}
                </div>
              )}

              <div className="grid md:grid-cols-2 gap-6 pt-2">
                <div className="space-y-4">
                  <div>
                    <h5 className="flex items-center gap-2 text-sm font-bold text-slate-700 mb-2">
                      <FileText size={16} className="text-blue-500" />
                      深度解析
                    </h5>
                    <div className="text-sm text-slate-600 leading-relaxed space-y-2">
                      {question.analysis.map((item, index) => (
                        <p key={index}>• {item}</p>
                      ))}
                    </div>
                  </div>
                  {question.errorCauses.length > 0 && (
                    <div>
                      <h5 className="flex items-center gap-2 text-sm font-bold text-slate-700 mb-2">
                        <XCircle size={16} className="text-rose-500" />
                        错误点
                      </h5>
                      <div className="flex flex-wrap gap-2">
                        {question.errorCauses.map(ec => (
                          <span key={ec} className="text-xs px-2.5 py-1 bg-rose-50 text-rose-600 border border-rose-100 rounded-md">
                            {ec}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
                <div className="space-y-4">
                  <div className="bg-blue-50/50 rounded-xl p-4 border border-blue-100/50 h-full">
                    <h5 className="flex items-center gap-2 text-sm font-bold text-blue-700 mb-2">
                      <Target size={16} />
                      学习建议
                    </h5>
                    <p className="text-sm text-blue-800 leading-relaxed italic">
                      “{question.studyAdvice}”
                    </p>
                  </div>
                  {question.needsManualReview && (
                    <div className="flex items-center gap-2 text-xs text-amber-600 font-medium">
                      <AlertCircle size={12} /> 建议人工复核
                    </div>
                  )}
                </div>
              </div>

              <div className="grid lg:grid-cols-2 gap-4">
                <MatchAnchorsPanel anchors={question.matchAnchors} compact />
                <GraphInsightPanel graphPath={question.graphPath} retrievalEvidence={question.retrievalEvidence} compact />
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
};

const ParentReportPage = () => {
  const location = useLocation();
  const examSessionId = useMemo(() => new URLSearchParams(location.search).get('exam_session_id'), [location.search]);
  const [report, setReport] = useState(null);
  const [questions, setQuestions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState('');

  useEffect(() => {
    const load = async () => {
      try {
        if (examSessionId) {
          const reportRes = await fetch(`/api/exam-sessions/${examSessionId}/analysis/student-report`);
          if (!reportRes.ok) {
            throw new Error('学情报告加载失败，请先完成题目匹配与分析生成。');
          }
          const reportData = await reportRes.json();
          setReport(reportData);
          setQuestions(reportData.question_analyses || []);
        } else {
          const [reportRes, questionRes] = await Promise.all([
            fetch('/mock/analysis_report.json'),
            fetch('/mock/question_analyses.json')
          ]);
          if (!reportRes.ok || !questionRes.ok) {
            throw new Error('数据文件加载失败，请确认 mock 文件已生成。');
          }
          const reportData = await reportRes.json();
          const questionData = await questionRes.json();
          setReport(reportData);
          setQuestions(questionData.questions || []);
        }
      } catch (error) {
        setErrorMessage(error.message || '加载失败');
      } finally {
        setLoading(false);
      }
    };

    load();
  }, [examSessionId]);

  const derived = useMemo(() => {
    if (Array.isArray(report?.knowledge_profile) && report.knowledge_profile.length > 0) {
      const profile = report.knowledge_profile;
      const strengths = [...profile]
        .filter((item) => ['mastered', 'developing'].includes(item.mastery_status))
        .sort((a, b) => (b.accuracy || 0) - (a.accuracy || 0))
        .slice(0, 3)
        .map((item) => item.canonical_name);
      const weaknesses = [...profile]
        .filter((item) => ['weak', 'uncertain'].includes(item.mastery_status))
        .sort((a, b) => (a.accuracy || 0) - (b.accuracy || 0))
        .slice(0, 3)
        .map((item) => item.canonical_name);
      return {
        correctCount: report?.summary?.correct_questions || 0,
        incorrectCount: report?.summary?.incorrect_questions || 0,
        uncertainCount: report?.summary?.uncertain_questions || 0,
        strengths,
        weaknesses,
        knowledgeDistribution: profile.slice(0, 5).map((item) => ({
          subject: item.canonical_name,
          A: Math.round((item.accuracy || 0) * 100),
          full: 100,
        })),
      };
    }

    const questionList = questions || [];
    const knowledgeMap = new Map();
    let correctCount = 0;
    let incorrectCount = 0;
    let uncertainCount = 0;

    questionList.forEach((q) => {
      const correctness = q.correctness || q.vlm_result?.correctness || q.final_conclusion?.correctness || 'uncertain';
      const needsManualReview = q.needs_manual_review || q.needsManualReview || false;
      const status = mapCorrectnessToStatus(correctness, needsManualReview);

      if (status === 'correct') correctCount += 1;
      else if (status === 'incorrect') incorrectCount += 1;
      else uncertainCount += 1;

      const knowledgePoints = q.knowledge_points
        ? q.knowledge_points.map((kp) => kp.canonical_name)
        : (q.vlm_result?.knowledge_points || q.final_conclusion?.knowledge_points || []);
      knowledgePoints.forEach((kpName) => {
        if (!knowledgeMap.has(kpName)) knowledgeMap.set(kpName, { total: 0, correct: 0 });
        const entry = knowledgeMap.get(kpName);
        entry.total += 1;
        if (status === 'correct') entry.correct += 1;
      });
    });

    const knowledgeStats = Array.from(knowledgeMap.entries()).map(([name, stat]) => ({
      name,
      total: stat.total,
      accuracy: stat.total ? Math.round((stat.correct / stat.total) * 100) : 0,
    }));

    const topKnowledge = knowledgeStats.sort((a, b) => b.total - a.total).slice(0, 5);
    const strengths = [...knowledgeStats].sort((a, b) => b.accuracy - a.accuracy).slice(0, 3).map((k) => k.name);
    const weaknesses = [...knowledgeStats].sort((a, b) => a.accuracy - b.accuracy).slice(0, 3).map((k) => k.name);

    return {
      correctCount,
      incorrectCount,
      uncertainCount,
      strengths,
      weaknesses,
      knowledgeDistribution: topKnowledge.map((item) => ({ subject: item.name, A: item.accuracy, full: 100 }))
    };
  }, [questions, report]);

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center flex-col gap-4">
        <Loader2 className="animate-spin text-blue-600" size={48} />
        <p className="text-slate-500 font-medium tracking-widest">AI 正在深度解析您的试卷报告...</p>
      </div>
    );
  }

  if (errorMessage) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center flex-col gap-4">
        <AlertCircle className="text-rose-500" size={42} />
        <p className="text-slate-600 font-medium">{errorMessage}</p>
        <p className="text-xs text-slate-400">
          {examSessionId
            ? '请确认该 exam_session 已匹配题库并可生成学情分析。'
            : '请确认 `public/mock` 目录下有 `analysis_report.json` 和 `question_analyses.json`。'}
        </p>
      </div>
    );
  }

  const totalQuestions = report?.summary?.total_questions || report?.input_stats?.total_questions || questions.length;
  const manualReviewCount = report?.summary?.manual_review_questions
    || report?.input_stats?.manual_review_questions
    || questions.filter((q) => q.needs_manual_review || q.needsManualReview).length
    || (report?.manual_review_question_nos || []).length
    || 0;
  const correctnessRate = report?.summary?.correct_questions
    ? calcPercent(report.summary.correct_questions, totalQuestions)
    : calcPercent(derived.correctCount, totalQuestions);

  const examInfo = {
    title: report?.summary?.headline || report?.exam_context?.paper_id || report?.exam_context?.exam_id || `试卷分析报告${examSessionId ? ` #${examSessionId}` : ''}`,
    subject: report?.summary?.subject || report?.exam_context?.subject || '未命名科目',
    student: report?.summary?.student_id || report?.exam_context?.student_id || '学生',
    date: formatDate(report?.generated_at || report?.summary?.generated_at || new Date().toISOString()),
  };

  const questionCards = questions.map((q) => {
    const correctness = q.correctness || q.vlm_result?.correctness || q.final_conclusion?.correctness || 'uncertain';
    const status = mapCorrectnessToStatus(correctness, q.needs_manual_review || q.needsManualReview);
    const analysis = q.root_cause_hypothesis
      ? [q.root_cause_hypothesis, ...(q.graph_path?.summary ? [q.graph_path.summary] : [])]
      : (q.vlm_result?.reasoning_basis || (q.final_conclusion?.explanation ? [q.final_conclusion.explanation] : [q.preliminary_judgement || '暂无解析']));
    const studyAdvice = Array.isArray(q.study_advice)
      ? q.study_advice.join('；')
      : (q.studyAdvice || q.vlm_result?.recommended_next_action || q.final_conclusion?.study_advice || '继续保持当前的学习节奏。');

    return {
      questionNo: q.source_question_no || q.question_no,
      summary: q.question_summary || q.vlm_result?.question_summary || q.final_conclusion?.summary || q.preliminary_judgement || '题目详情',
      knowledgePoints: q.knowledge_points ? q.knowledge_points.map((kp) => kp.canonical_name) : (q.vlm_result?.knowledge_points || q.final_conclusion?.knowledge_points || []),
      errorCauses: q.error_pattern?.name ? [q.error_pattern.name] : (q.vlm_result?.suspected_error_causes || q.final_conclusion?.error_causes || []),
      studyAdvice,
      analysis,
      status,
      needsManualReview: q.needs_manual_review || q.needsManualReview || false,
      anchorType: q.match_anchor_type || q.match_anchors?.primary_anchor_type || 'unanchored',
      anchorSummary: q.match_anchor_summary || '',
      matchAnchors: q.match_anchors || null,
      graphPath: q.graph_path || null,
      retrievalEvidence: q.retrieval_evidence || [],
      imagePath: q.image_paths?.[0] || '',
      imageUrl: q.image_paths?.[0] ? `/api/images?path=${encodeURIComponent(q.image_paths[0])}` : "https://via.placeholder.com/600x200?text=Question+Image",
      solutionSteps: q.solution_steps || '',
      llmAnswer: q.llm_answer || '',
    };
  });

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 pb-20 font-sans">
      <header className="bg-white border-b border-slate-100 sticky top-0 z-50 backdrop-blur-md bg-white/80">
        <div className="max-w-4xl mx-auto px-4 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center text-white font-black text-sm">AI</div>
            <h1 className="text-lg font-bold">试卷AI分析报告</h1>
          </div>
          <div className="flex items-center gap-2 text-slate-500 text-sm">
            <Calendar size={14} />
            <span>{examInfo.date}</span>
          </div>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-4 py-8 space-y-8">
        {!examSessionId && (
          <div className="rounded-xl border border-amber-200 bg-amber-50/90 px-4 py-4 text-sm text-amber-950 space-y-3">
            <p>
              <strong>未指定考试场次时</strong>，家长报告会读取{' '}
              <code className="text-xs bg-amber-100/80 px-1 rounded">public/mock</code> 中的<strong>本地演示数据</strong>
             （历史上多为化学等示例卷），<strong>不会</strong>自动对应当前你在库里验证的数学考试。
            </p>
            <p className="text-amber-900/90 text-xs">
              要查看某次真跑结果（如数学 bundle 导入后的场次），请使用{' '}
              <code className="bg-amber-100/80 px-1 rounded">/report?exam_session_id=场次数字</code>，或从下列列表点选。
            </p>
            <ExamSessionPicker description="已导入的考试（ExamSession）列表：点选后在本页打开真实学情报告。" />
          </div>
        )}
        <div className="bg-white rounded-xl border border-slate-100 px-4 py-3 text-xs text-slate-500">
          {examSessionId
            ? `数据来源: /api/exam-sessions/${examSessionId}/analysis/student-report`
            : '数据来源: `public/mock/analysis_report.json` 与 `public/mock/question_analyses.json`'}
        </div>

        <div className="bg-white rounded-3xl p-6 shadow-sm border border-slate-100 flex flex-col md:flex-row gap-6 items-center">
          <div className="flex-1 space-y-1 text-center md:text-left">
            <h2 className="text-2xl font-black text-slate-800 tracking-tight">{examInfo.title}</h2>
            <div className="flex flex-wrap justify-center md:justify-start gap-4 text-slate-500 text-sm mt-2">
              <span className="flex items-center gap-1.5"><CheckCircle2 size={14} className="text-blue-500" /> {examInfo.student}</span>
              <span className="flex items-center gap-1.5 font-bold text-slate-700 bg-slate-100 px-2 py-0.5 rounded">{examInfo.subject}</span>
            </div>
          </div>
          <div className="text-right">
             <div className="text-5xl font-black text-blue-600">{correctnessRate}%</div>
             <div className="text-xs font-bold text-slate-400 mt-1 uppercase tracking-widest">正确率</div>
          </div>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: '正确题目', value: derived.correctCount, icon: CheckCircle2, color: 'text-emerald-600', bg: 'bg-emerald-50' },
            { label: '错误题目', value: derived.incorrectCount, icon: XCircle, color: 'text-rose-600', bg: 'bg-rose-50' },
            { label: '待复核', value: manualReviewCount, icon: AlertCircle, color: 'text-amber-600', bg: 'bg-amber-50' },
            { label: '总题数', value: totalQuestions, icon: Award, color: 'text-blue-600', bg: 'bg-blue-50' },
          ].map((stat, idx) => (
            <div key={idx} className={`rounded-2xl p-4 ${stat.bg} border border-transparent shadow-sm`}>
              <stat.icon size={18} className={stat.color} />
              <div className="text-2xl font-bold text-slate-800 mt-2">{stat.value}</div>
              <div className="text-xs font-medium text-slate-500 mt-0.5">{stat.label}</div>
            </div>
          ))}
        </div>

        <div className="grid md:grid-cols-2 gap-6">
          <div className="bg-white rounded-3xl p-6 shadow-sm border border-slate-100">
            <h3 className="text-base font-bold text-slate-800 mb-6 flex items-center gap-2">
              <Award size={18} className="text-violet-500" />
              三层锚点覆盖
            </h3>
            <AnchorCoverageStrip
              exactRate={report?.summary?.exact_match_rate || 0}
              structuralRate={report?.summary?.structural_anchor_rate || 0}
              knowledgeRate={report?.summary?.knowledge_anchor_rate || 0}
              graphRate={(report?.summary?.graph_ready_questions || 0) / Math.max(1, totalQuestions)}
            />
          </div>
          <div className="bg-white rounded-3xl p-6 shadow-sm border border-slate-100">
            <h3 className="text-base font-bold text-slate-800 mb-6 flex items-center gap-2">
              <TrendingUp size={18} className="text-indigo-500" />
              AI 与 GraphRAG 能力摘要
            </h3>
            <div className="grid grid-cols-2 gap-4">
              {[
                { label: '标准题命中率', value: `${Math.round((report?.summary?.exact_match_rate || 0) * 100)}%` },
                { label: '相似题参考率', value: `${Math.round((report?.summary?.structural_anchor_rate || 0) * 100)}%` },
                { label: '知识锚点率', value: `${Math.round((report?.summary?.knowledge_anchor_rate || 0) * 100)}%` },
                { label: '图谱就绪题', value: report?.summary?.graph_ready_questions || 0 },
              ].map((item) => (
                <div key={item.label} className="rounded-2xl bg-slate-50 px-4 py-3">
                  <div className="text-xs text-slate-500">{item.label}</div>
                  <div className="text-2xl font-bold text-slate-800 mt-1">{item.value}</div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="grid md:grid-cols-2 gap-6">
          <div className="bg-white rounded-3xl p-6 shadow-sm border border-slate-100">
            <h3 className="text-base font-bold text-slate-800 mb-6 flex items-center gap-2">
              <Target size={18} className="text-blue-500" />
              知识点掌握分布
            </h3>
            <div className="h-[250px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <RadarChart cx="50%" cy="50%" outerRadius="80%" data={derived.knowledgeDistribution}>
                  <PolarGrid stroke="#E2E8F0" />
                  <PolarAngleAxis dataKey="subject" tick={{ fontSize: 12, fill: '#64748B' }} />
                  <PolarRadiusAxis angle={30} domain={[0, 100]} tick={false} axisLine={false} />
                  <Radar name="掌握度" dataKey="A" stroke="#2563EB" strokeWidth={2} fill="#3B82F6" fillOpacity={0.5} />
                </RadarChart>
              </ResponsiveContainer>
            </div>
          </div>
          
          <div className="bg-white rounded-3xl p-6 shadow-sm border border-slate-100">
            <h3 className="text-base font-bold text-slate-800 mb-6 flex items-center gap-2">
              <TrendingUp size={18} className="text-emerald-500" />
              优劣势分析
            </h3>
            <div className="space-y-6">
              <div>
                <span className="text-xs font-bold text-emerald-600 uppercase tracking-wider block mb-3">我的优势</span>
                <div className="flex flex-wrap gap-2">
                  {(derived.strengths.length ? derived.strengths : ['待生成']).map(s => (
                    <span key={s} className="px-3 py-1.5 bg-emerald-50 text-emerald-700 text-sm rounded-lg border border-emerald-100 flex items-center gap-1.5">
                      <CheckCircle2 size={14} /> {s}
                    </span>
                  ))}
                </div>
              </div>
              <div>
                <span className="text-xs font-bold text-rose-600 uppercase tracking-wider block mb-3">薄弱环节</span>
                <div className="flex flex-wrap gap-2">
                  {(derived.weaknesses.length ? derived.weaknesses : ['待生成']).map(w => (
                    <span key={w} className="px-3 py-1.5 bg-rose-50 text-rose-700 text-sm rounded-lg border border-rose-100 flex items-center gap-1.5">
                      <XCircle size={14} /> {w}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>

        <section className="space-y-6">
          <div className="flex items-center justify-between">
            <h3 className="text-xl font-black text-slate-800 flex items-center gap-2">逐题深度分析</h3>
            <div className="flex gap-2">
               <button className="px-4 py-1.5 text-xs font-bold bg-blue-600 text-white rounded-lg shadow-lg">全部报告</button>
               <button className="px-4 py-1.5 text-xs font-bold text-slate-500 hover:text-slate-800 transition-colors">仅看错题</button>
            </div>
          </div>
          <div className="space-y-4">
            {questionCards.map((q, idx) => (
              <QuestionCard key={idx} question={q} />
            ))}
          </div>
        </section>

        <footer className="bg-slate-900 rounded-3xl p-10 text-white text-center space-y-6 relative overflow-hidden shadow-2xl">
          <div className="relative z-10 space-y-4">
             <div className="inline-block p-3 bg-blue-500/20 rounded-full mb-2">
                <Target size={32} className="text-blue-400" />
             </div>
             <h4 className="text-2xl font-black tracking-tight">AI 助学评价</h4>
             <p className="text-slate-400 text-sm max-w-lg mx-auto leading-relaxed">
               数据已从分析结果中读取。建议结合错题记录进行针对性复习与训练。
             </p>
             <button className="px-8 py-3 bg-blue-600 hover:bg-blue-500 text-white font-bold rounded-full shadow-lg transition-all transform active:scale-95">
               导出我的 PDF 错题本
             </button>
          </div>
          <div className="absolute top-0 right-0 w-64 h-64 bg-blue-600/10 rounded-full blur-3xl -mr-32 -mt-32"></div>
        </footer>

      </main>
    </div>
  );
};

export default ParentReportPage;
