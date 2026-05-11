import React from 'react';
import {
  AlertCircle,
  BookOpen,
  BrainCircuit,
  CheckCircle2,
  Link2,
  Network,
  Search,
  Sparkles,
} from 'lucide-react';

const anchorMeta = {
  exact_match: {
    label: '标准题命中',
    icon: CheckCircle2,
    className: 'bg-emerald-50 text-emerald-700 border-emerald-100',
  },
  structural_match: {
    label: '相似题参考',
    icon: Sparkles,
    className: 'bg-blue-50 text-blue-700 border-blue-100',
  },
  knowledge_anchor: {
    label: '知识锚点',
    icon: BrainCircuit,
    className: 'bg-violet-50 text-violet-700 border-violet-100',
  },
  unanchored: {
    label: '未找到锚点',
    icon: AlertCircle,
    className: 'bg-slate-100 text-slate-700 border-slate-200',
  },
};

const formatPercent = (value) => `${Math.round((Number(value) || 0) * 100)}%`;

export function AnchorTypeBadge({ type = 'unanchored', className = '' }) {
  const meta = anchorMeta[type] || anchorMeta.unanchored;
  const Icon = meta.icon;
  return (
    <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full border text-xs font-semibold ${meta.className} ${className}`}>
      <Icon size={13} />
      {meta.label}
    </span>
  );
}

function AnchorQuestionCard({ title, item }) {
  if (!item) return null;
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3 space-y-1">
      <div className="flex items-center justify-between gap-3">
        <div className="text-xs font-bold text-slate-500 uppercase tracking-wider">{title}</div>
        <div className="text-xs font-semibold text-slate-700">分数 {Number(item.final_score || 0).toFixed(4)}</div>
      </div>
      <div className="text-sm font-medium text-slate-800 line-clamp-2">{item.candidate_stem || '暂无题干'}</div>
      <div className="flex flex-wrap gap-2 text-[11px] text-slate-500">
        {item.paper_id ? <span className="px-2 py-0.5 rounded bg-slate-100">Paper #{item.paper_id}</span> : null}
        {item.candidate_question_type ? <span className="px-2 py-0.5 rounded bg-slate-100">{item.candidate_question_type}</span> : null}
        {item.candidate_subject ? <span className="px-2 py-0.5 rounded bg-slate-100">{item.candidate_subject}</span> : null}
      </div>
      {item.similarity_reason ? <div className="text-xs text-slate-600">{item.similarity_reason}</div> : null}
      <div className="grid grid-cols-3 gap-2 text-[11px] text-slate-500">
        <div>语义 {Number(item.vector_score || 0).toFixed(3)}</div>
        <div>文本 {Number(item.text_score || 0).toFixed(3)}</div>
        <div>重合 {Number(item.overlap_score || 0).toFixed(3)}</div>
      </div>
    </div>
  );
}

function KnowledgeAnchorCard({ item }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3 space-y-1" key={`${item.source_type}-${item.source_id}`}>
      <div className="flex items-center justify-between gap-3">
        <div className="inline-flex items-center gap-1.5 text-xs font-semibold text-violet-700">
          <BookOpen size={12} />
          {item.title || item.source_type}
        </div>
        <div className="text-xs font-semibold text-slate-700">{Number(item.score || 0).toFixed(4)}</div>
      </div>
      <div className="text-xs text-slate-500">{item.source_type}{item.knowledge_point_id ? ` · KP ${item.knowledge_point_id}` : ''}</div>
      <div className="text-sm text-slate-700 line-clamp-3">{item.snippet || '暂无摘要'}</div>
    </div>
  );
}

export function MatchAnchorsPanel({ anchors, compact = false }) {
  const anchorPack = anchors || {};
  const diagnostics = anchorPack.diagnostics || {};
  const structuralMatches = anchorPack.structural_matches || [];
  const knowledgeAnchors = anchorPack.knowledge_anchors || [];

  return (
    <div className={`rounded-2xl border border-slate-100 bg-slate-50/70 ${compact ? 'p-4' : 'p-5'} space-y-4`}>
      <div className="flex flex-wrap items-center gap-2">
        <AnchorTypeBadge type={anchorPack.primary_anchor_type} />
        {diagnostics.exact_failure_reason ? (
          <span className="inline-flex items-center gap-1 text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded-full px-3 py-1">
            <AlertCircle size={12} />
            exact 未放行：{diagnostics.exact_failure_reason}
          </span>
        ) : null}
      </div>

      {anchorPack.exact_match ? <AnchorQuestionCard title="标准题锚点" item={anchorPack.exact_match} /> : null}

      {structuralMatches.length ? (
        <div className="space-y-2">
          <div className="inline-flex items-center gap-1.5 text-xs font-bold text-blue-700 uppercase tracking-wider">
            <Search size={12} />
            相似题参考
          </div>
          <div className="space-y-2">
            {structuralMatches.slice(0, compact ? 1 : 3).map((item, index) => (
              <AnchorQuestionCard key={`${item.question_item_id}-${index}`} title={`Structural #${index + 1}`} item={item} />
            ))}
          </div>
        </div>
      ) : null}

      {knowledgeAnchors.length ? (
        <div className="space-y-2">
          <div className="inline-flex items-center gap-1.5 text-xs font-bold text-violet-700 uppercase tracking-wider">
            <BrainCircuit size={12} />
            知识锚点
          </div>
          <div className="grid gap-2">
            {knowledgeAnchors.slice(0, compact ? 2 : 4).map((item) => (
              <KnowledgeAnchorCard key={`${item.source_type}-${item.source_id}`} item={item} />
            ))}
          </div>
        </div>
      ) : null}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
        <div className="rounded-xl bg-white border border-slate-200 p-3">
          <div className="text-slate-500">候选数</div>
          <div className="text-lg font-bold text-slate-800">{diagnostics.exact_candidate_count || 0}</div>
        </div>
        <div className="rounded-xl bg-white border border-slate-200 p-3">
          <div className="text-slate-500">相似题</div>
          <div className="text-lg font-bold text-slate-800">{diagnostics.structural_match_count || 0}</div>
        </div>
        <div className="rounded-xl bg-white border border-slate-200 p-3">
          <div className="text-slate-500">知识锚点</div>
          <div className="text-lg font-bold text-slate-800">{diagnostics.knowledge_anchor_count || 0}</div>
        </div>
        <div className="rounded-xl bg-white border border-slate-200 p-3">
          <div className="text-slate-500">Top exact</div>
          <div className="text-lg font-bold text-slate-800">{diagnostics.top_exact_score ? Number(diagnostics.top_exact_score).toFixed(3) : '—'}</div>
        </div>
      </div>
    </div>
  );
}

export function GraphInsightPanel({ graphPath, retrievalEvidence, compact = false }) {
  const evidence = retrievalEvidence || [];
  const graph = graphPath || null;
  const hasGraph = Boolean(graph && ((graph.nodes || []).length || (graph.edges || []).length));

  return (
    <div className={`rounded-2xl border border-slate-100 bg-slate-50/70 ${compact ? 'p-4' : 'p-5'} space-y-4`}>
      <div className="flex items-center gap-2">
        <Network size={16} className="text-indigo-600" />
        <h4 className="text-sm font-bold text-slate-800">GraphRAG 与证据</h4>
      </div>

      <div className="grid grid-cols-3 gap-2 text-xs">
        <div className="rounded-xl bg-white border border-slate-200 p-3">
          <div className="text-slate-500">图节点</div>
          <div className="text-lg font-bold text-slate-800">{hasGraph ? (graph.nodes || []).length : 0}</div>
        </div>
        <div className="rounded-xl bg-white border border-slate-200 p-3">
          <div className="text-slate-500">图关系</div>
          <div className="text-lg font-bold text-slate-800">{hasGraph ? (graph.edges || []).length : 0}</div>
        </div>
        <div className="rounded-xl bg-white border border-slate-200 p-3">
          <div className="text-slate-500">证据条数</div>
          <div className="text-lg font-bold text-slate-800">{evidence.length}</div>
        </div>
      </div>

      {graph?.summary ? (
        <div className="rounded-xl border border-indigo-100 bg-indigo-50 p-3 text-sm text-indigo-900">
          {graph.summary}
        </div>
      ) : (
        <div className="rounded-xl border border-slate-200 bg-white p-3 text-sm text-slate-500">
          当前题目未形成稳定图路径。
        </div>
      )}

      {evidence.length ? (
        <div className="space-y-2">
          {evidence.slice(0, compact ? 2 : 4).map((item) => (
            <div key={`${item.source_type}-${item.source_id}`} className="rounded-xl border border-slate-200 bg-white p-3">
              <div className="flex items-center justify-between gap-3">
                <div className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-700">
                  <Link2 size={12} />
                  {item.title || item.source_type}
                </div>
                <div className="text-xs text-slate-500">{Number(item.score || 0).toFixed(4)}</div>
              </div>
              <div className="text-sm text-slate-700 mt-1 line-clamp-3">{item.snippet || '暂无片段'}</div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function AnchorCoverageStrip({ exactRate, structuralRate, knowledgeRate, graphRate }) {
  const metrics = [
    { key: 'exact', label: '标准题命中', value: exactRate, className: 'bg-emerald-500' },
    { key: 'structural', label: '相似题参考', value: structuralRate, className: 'bg-blue-500' },
    { key: 'knowledge', label: '知识锚点', value: knowledgeRate, className: 'bg-violet-500' },
    { key: 'graph', label: 'GraphRAG就绪', value: graphRate, className: 'bg-indigo-500' },
  ];
  return (
    <div className="space-y-3">
      {metrics.map((item) => (
        <div key={item.key} className="space-y-1">
          <div className="flex items-center justify-between text-xs text-slate-600">
            <span>{item.label}</span>
            <span className="font-semibold">{formatPercent(item.value)}</span>
          </div>
          <div className="h-2 rounded-full bg-slate-100 overflow-hidden">
            <div className={`h-full rounded-full ${item.className}`} style={{ width: `${Math.max(0, Math.min(100, (Number(item.value) || 0) * 100))}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}
