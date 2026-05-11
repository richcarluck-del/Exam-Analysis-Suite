import React, { useEffect, useMemo, useState } from 'react';
import { Printer, RefreshCw, FileText, Image as ImageIcon } from 'lucide-react';
import QuestionRichRenderer from './QuestionRichRenderer';

const resolveApiOrigin = () => {
  if (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_BASE_URL) {
    return String(import.meta.env.VITE_API_BASE_URL).replace(/\/$/, '');
  }
  if (typeof window !== 'undefined' && window.location?.origin) {
    return window.location.origin;
  }
  return 'http://localhost:8000';
};

const ROLE_LABELS = {
  answer: '答案',
  analysis: '解析',
  solution: '解法',
  comment: '点评',
  knowledge: '考点',
  topic: '专题',
};

const resolveAssetUrl = (url) => {
  if (!url) return '';
  if (url.startsWith('http://') || url.startsWith('https://')) return url;
  if (url.startsWith('/')) return `${resolveApiOrigin()}${url}`;
  return url;
};

const buildFallbackBlocks = (question) => {
  const blocks = [];
  let fallbackId = -1;
  const pushBlock = (block_role, text_content) => {
    if (!text_content || !String(text_content).trim()) return;
    blocks.push({
      id: fallbackId--,
      block_order: blocks.length,
      block_role,
      content_format: 'plain_text',
      text_content,
      rich_content_json: {
        type: 'text',
        text: text_content,
      },
      is_primary: block_role === 'stem',
    });
  };
  pushBlock('stem', question?.stem_plain_text || question?.stem_text || question?.text);
  pushBlock('answer', question?.answer_text);
  pushBlock('analysis', question?.analysis_text);
  pushBlock('solution', question?.solution_text || question?.solution_summary);
  pushBlock('comment', question?.comment_text);
  return blocks;
};

const SectionBlock = ({ block, optionTextMap }) => {
  const optionKey = block?.rich_content_json?.option_key;
  const explicitLabel = block?.rich_content_json?.display_label;
  const label = explicitLabel || (block.block_role === 'option' ? optionKey : ROLE_LABELS[block.block_role]);
  const fallbackText = block.block_role === 'option' && optionKey ? optionTextMap[optionKey] || block.text_content : block.text_content;

  return (
    <div className="space-y-2">
      {label ? <div className="text-sm font-semibold text-slate-500">{label}</div> : null}
      <QuestionRichRenderer payload={block.rich_content_json} fallbackText={fallbackText} />
    </div>
  );
};

const OptionInlineBlock = ({ block, optionTextMap }) => {
  const optionKey = block?.rich_content_json?.option_key;
  const fallbackText = optionKey ? optionTextMap[optionKey] || block.text_content : block.text_content;

  return (
    <div className="inline-flex max-w-full min-w-0 flex-nowrap items-baseline gap-2 text-slate-800">
      {optionKey ? <span className="shrink-0 font-normal text-slate-800">{optionKey}.</span> : null}
      <div className="min-w-0">
        <QuestionRichRenderer payload={block.rich_content_json} fallbackText={fallbackText} className="min-w-0" />
      </div>
    </div>
  );
};

const QuestionCard = ({ question }) => {
  const optionTextMap = useMemo(
    () => Object.fromEntries((question.options || []).map((option) => [option.option_key, option.option_text])),
    [question.options],
  );

  const blocks = (question.blocks && question.blocks.length ? question.blocks : buildFallbackBlocks(question)) || [];
  const stemBlocks = blocks.filter((block) => block.block_role === 'stem');
  const optionGroupBlock = blocks.find((block) => block.block_role === 'options');
  const optionBlocks = blocks.filter((block) => block.block_role === 'option');
  const hasTableOptionText = Object.keys(optionTextMap).some((k) => (optionTextMap[k] || '').trim());
  const auxiliaryBlocks = blocks.filter((block) => !['stem', 'options', 'option'].includes(block.block_role));
  const headerAssets = (question.assets || []).filter((asset) => asset.asset_role === 'question_inline_image');

  return (

    <section className="print-question-card rounded-2xl border border-slate-200 bg-white p-6 shadow-sm space-y-5">
      <div className="flex items-start justify-between gap-4 border-b border-slate-100 pb-4">
        <div>
          <div className="text-sm font-semibold text-slate-500">第 {question.question_no || question.display_order || question.question_item_id} 题</div>
          <div className="mt-1 text-xs text-slate-400">
            题型：{question.question_type || 'unknown'}
            {question.has_formula ? ' · 含公式' : ''}
            {question.has_figure ? ' · 含图片' : ''}
          </div>
        </div>
        <div className="text-right text-xs text-slate-400">
          <div>question_item_id = {question.question_item_id}</div>
          <div>display_order = {question.display_order ?? '—'}</div>
        </div>
      </div>

      <div className="space-y-4">
        {stemBlocks.map((block) => (
          <SectionBlock key={block.id} block={block} optionTextMap={optionTextMap} />
        ))}

        {optionBlocks.length ? (
          <div className="flex flex-wrap items-baseline gap-x-10 gap-y-2">
            {optionBlocks.map((block) => (
              <OptionInlineBlock key={block.id} block={block} optionTextMap={optionTextMap} />
            ))}
          </div>
        ) : hasTableOptionText ? (
          <div className="flex flex-wrap items-baseline gap-x-10 gap-y-2">
            {Object.entries(optionTextMap).map(([key, text]) => (
              <div key={key} className="inline-flex max-w-full min-w-0 flex-nowrap items-baseline gap-2 text-slate-800">
                <span className="shrink-0 font-normal">{key}.</span>
                <span className="min-w-0 whitespace-pre-wrap leading-8">{text || '—'}</span>
              </div>
            ))}
          </div>
        ) : optionGroupBlock ? (
          <QuestionRichRenderer payload={optionGroupBlock.rich_content_json} fallbackText={optionGroupBlock.text_content} />
        ) : null}

        {auxiliaryBlocks.map((block) => (
          <SectionBlock key={block.id} block={block} optionTextMap={optionTextMap} />
        ))}
      </div>


      {headerAssets.length ? (
        <div className="rounded-xl border border-slate-100 bg-slate-50 px-4 py-3">
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-600">
            <ImageIcon size={16} /> 题目内联图片资源
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            {headerAssets.map((asset) => (
              <div key={asset.id} className="rounded-lg border border-slate-200 bg-white p-3">
                <img
                  src={resolveAssetUrl(asset.public_url || asset.storage_url)}
                  alt={asset.caption_text || '题目图片资源'}
                  className="mx-auto"
                  style={{
                    display: 'block',
                    maxWidth: 'min(100%, 400px)',
                    maxHeight: '200px',
                    width: 'auto',
                    height: 'auto',
                    objectFit: 'contain',
                  }}
                />
                <div className="mt-2 text-xs text-slate-500 break-all">asset_id={asset.id}</div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
};

export default function QuestionPaperPreviewPage() {
  const [sourceDocumentIdInput, setSourceDocumentIdInput] = useState('1');

  const [paperDetail, setPaperDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const loadPaper = async (targetSourceDocumentId) => {
    if (!targetSourceDocumentId) return;
    setLoading(true);
    setError('');
    try {
      const response = await fetch(`${resolveApiOrigin()}/api/question-bank/documents/${targetSourceDocumentId}/paper`);

      if (!response.ok) {
        throw new Error(`加载失败: ${response.status}`);
      }
      const data = await response.json();
      setPaperDetail(data);
    } catch (err) {
      setPaperDetail(null);
      setError(err.message || '加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadPaper(sourceDocumentIdInput);
  }, []);


  return (
    <div className="print-paper-shell min-h-screen bg-slate-50 px-4 py-8 md:px-8">
      <div className="mx-auto max-w-6xl space-y-6">
        <div className="print-hidden rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <div className="flex items-center gap-2 text-slate-900">
                <FileText size={20} />
                <h1 className="text-xl font-semibold">题库试卷保真预览</h1>
              </div>
              <p className="mt-2 text-sm text-slate-500">基于题库摄入后的富结构数据进行展示，支持响应式浏览与打印。</p>
            </div>
            <div className="flex flex-col gap-3 md:flex-row md:items-center">
              <input
                type="number"
                min="1"
                value={sourceDocumentIdInput}
                onChange={(event) => setSourceDocumentIdInput(event.target.value)}

                className="rounded-xl border border-slate-300 px-4 py-2.5 text-sm outline-none transition focus:border-slate-500"
                placeholder="输入 source_document_id"

              />
              <button
                type="button"
                onClick={() => loadPaper(sourceDocumentIdInput)}

                disabled={loading}
                className="inline-flex items-center justify-center gap-2 rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-400"
              >
                <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
                {loading ? '加载中...' : '加载试卷'}
              </button>
              <button
                type="button"
                onClick={() => window.print()}
                className="inline-flex items-center justify-center gap-2 rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:border-slate-400 hover:bg-slate-50"
              >
                <Printer size={16} /> 打印 / 导出 PDF
              </button>
            </div>
          </div>
          {error ? <div className="mt-4 rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-600">{error}</div> : null}
        </div>

        {paperDetail ? (
          <div className="space-y-6">
            <div className="rounded-2xl border border-slate-200 bg-white px-6 py-5 shadow-sm">
              <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
                <div>
                  <div className="text-sm font-semibold text-slate-500">paper_id = {paperDetail.paper_id}</div>
                  <h2 className="mt-1 text-2xl font-semibold text-slate-900">{paperDetail.title || '未命名试卷'}</h2>
                  <div className="mt-2 text-sm text-slate-500">
                    {paperDetail.subject || '未知学科'} · {paperDetail.grade || '未知年级'} · 共 {paperDetail.total_questions || 0} 题
                  </div>
                </div>
                <div className="text-sm text-slate-500">
                  {paperDetail.normalized_pdf_public_url ? (
                    <a href={resolveAssetUrl(paperDetail.normalized_pdf_public_url)} target="_blank" rel="noreferrer" className="text-slate-700 underline underline-offset-4">
                      查看归一化 PDF
                    </a>
                  ) : (
                    <span>未生成归一化 PDF</span>
                  )}
                </div>
              </div>
            </div>

            <div className="space-y-6">
              {(paperDetail.questions || []).map((question) => (
                <QuestionCard key={question.question_item_id} question={question} />
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
