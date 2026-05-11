import React from 'react';

const QB_ASSETS_MOUNT = '/static/question-bank/assets/';

/**
 * 将题库/知识点 DOCX 写入的 storage_url（绝对路径或相对路径）映射为预处理 UI 已挂载的静态路径。
 */
const mapStoragePathToQuestionBankMount = (raw) => {
  if (!raw || typeof raw !== 'string') return '';
  let u = raw.trim();
  if (u.startsWith('data:')) return u;
  if (u.startsWith('http://') || u.startsWith('https://')) return u;
  if (u.startsWith(QB_ASSETS_MOUNT) || u.startsWith('/static/question-bank/')) {
    return u.startsWith('/') ? u : `/${u}`;
  }
  if (u.startsWith('file://')) {
    u = u.replace(/^file:\/\/\/?/i, '');
  }
  const norm = u.replace(/\\/g, '/');
  const low = norm.toLowerCase();
  const marker = 'question_bank_assets/';
  const idx = low.indexOf(marker);
  if (idx !== -1) {
    const rel = norm.slice(idx + marker.length).replace(/^\/+/, '');
    return `${QB_ASSETS_MOUNT}${rel}`.replace(/\/{2,}/g, '/');
  }
  const tail = norm.match(/(document_\d+\/.+)$/i);
  if (tail) {
    return `${QB_ASSETS_MOUNT}${tail[1]}`.replace(/\/{2,}/g, '/');
  }
  return '';
};

const resolveAssetUrl = (url) => {
  if (!url || typeof url !== 'string') return '';
  const u = url.trim();
  if (u.startsWith('data:')) return u;
  if (u.startsWith('http://') || u.startsWith('https://')) return u;
  if (u.startsWith('/')) {
    const origin = typeof window !== 'undefined' ? window.location.origin : '';
    return `${origin}${u}`;
  }
  const mapped = mapStoragePathToQuestionBankMount(u);
  if (mapped && mapped.startsWith('/')) {
    const origin = typeof window !== 'undefined' ? window.location.origin : '';
    return `${origin}${mapped}`;
  }
  return u;
};


const MAX_BODY_FONT_PT = 13;
/** 段落默认字号（与 paragraphStyleFromConfig 一致，用于行高像素估算） */
const RICH_PARAGRAPH_BASE_PT = 12.75;
const RICH_PARAGRAPH_LINE_HEIGHT = 1.8;

/** CSS px：1pt ≈ 96/72 px（与 Word 导出栅格常见参照一致） */
const ptToPx = (pt) => (pt * 96) / 72;

/**
 * 行内公式图允许的最大高度（px）：与「正文字号」同量级，不用整行行高（否则 30~40px 的图会原样显示，字母比正文大一圈）。
 * 元数据 h 不大于此则保持原像素；超过则等比缩小。
 */
const inlineFormulaMaxHeightPx = () =>
  Math.round(ptToPx(RICH_PARAGRAPH_BASE_PT) * 1.22);

/** 无 Word layout_* 时 OMML 栅格：上限略放宽，避免解析区小分式被压成「几像素高」 */
const inlineFormulaMaxHeightOmmlFallbackPx = () =>
  Math.round(ptToPx(RICH_PARAGRAPH_BASE_PT) * 2.12);

/** 与后端 _OMATH_RENDER_SCALE 一致：栅格像素 → 约等于版式像素的除数 */
const OMML_RASTER_DISPLAY_DIV = 6;

/** 宽幅栅格（四格选项等）：按像素缩放，不用 em */
const WIDE_FORMULA_ASPECT = 2.05;
const WIDE_FORMULA_MIN_META_W = 240;
const PANEL_MAX_W_PX = 620;
const PANEL_MAX_H_PX = 200;

/**
 * 横向「条带」式子（如 A={x|…}, B={…} 整行导出）：宽远大于高，无分式堆叠也可很高分辨。
 * 与含分式/矩阵的「竖向占高」块区分：后者宽高比通常较小或 boxH 明显更大。
 * 此类不应走 scaleWideFormulaPanel（行内会顶到近百 px），应与正文行内 cap 一致。
 */
const FLAT_INLINE_STRIP_MIN_ASPECT = 2.72;
const FLAT_INLINE_STRIP_MAX_BOX_H_PX = 102;

const isFlatInlineFormulaStrip = (boxW, boxH) => {
  if (!(boxW > 0 && boxH > 0)) return false;
  const aspect = boxW / boxH;
  return aspect >= FLAT_INLINE_STRIP_MIN_ASPECT && boxH <= FLAT_INLINE_STRIP_MAX_BOX_H_PX;
};

/** 条带式行内公式：高度与正文 cap 对齐，略紧于「有分式」的 OMML 放宽档 */
const inlineFlatStripMaxHeightPx = () =>
  Math.round(ptToPx(RICH_PARAGRAPH_BASE_PT) * 1.18);

const textStyleFromMarks = (marks = {}) => {
  const style = {};
  if (marks.bold) style.fontWeight = 700;
  if (marks.italic) style.fontStyle = 'italic';
  if (marks.underline) style.textDecoration = 'underline';
  if (marks.subscript) style.verticalAlign = 'sub';
  if (marks.superscript) style.verticalAlign = 'super';
  if (marks.font_size_pt != null) {
    const pt = Number(marks.font_size_pt);
    if (Number.isFinite(pt)) {
      style.fontSize = `${pt > MAX_BODY_FONT_PT ? MAX_BODY_FONT_PT : pt}pt`;
    }
  }
  return style;
};

/** 系统 UI 字体常把 U+2201（∁）等画成拉丁 C；对数学区码位使用数学备用字体 */
const MATH_SYMBOL_FONT_FAMILY =
  '"Cambria Math", "STIX Two Math", "STIX Math", "Noto Sans Math", "Segoe UI Symbol", "Latin Modern Math", serif';

/** 竖线类笔画：数学字体里斜体上下文下常被画成“斜杠”，强制用等宽直立字形 */
const UPRIGHT_BAR_FONT_FAMILY = 'Consolas, "Courier New", ui-monospace, monospace';

const isMathSymbolCodePoint = (cp) =>
  cp === 0x7c // | vertical bar – must stay upright even when surrounding text is italic
  || cp === 0xff5c // ｜ fullwidth vertical line
  || (cp >= 0x2200 && cp <= 0x22ff)
  || (cp >= 0x2100 && cp <= 0x214f)
  || (cp >= 0x2300 && cp <= 0x23fe)
  || (cp >= 0x2a00 && cp <= 0x2aff)
  || (cp >= 0x1d400 && cp <= 0x1d7ff);

const splitMathFontRuns = (text) => {
  if (!text) return [{ t: '', math: false }];
  const runs = [];
  let buf = '';
  let math = null;
  for (const ch of text) {
    const cp = ch.codePointAt(0);
    const m = isMathSymbolCodePoint(cp);
    if (math === null) math = m;
    if (m !== math) {
      runs.push({ t: buf, math });
      buf = ch;
      math = m;
    } else {
      buf += ch;
    }
  }
  if (buf.length) runs.push({ t: buf, math });
  return runs;
};

const mathSymbolSpanStyle = (runText, baseStyle) => {
  const t = runText || '';
  const cp0 = t.codePointAt(0);
  const isBarOnly = t.length > 0 && [...t].length === 1 && (cp0 === 0x7c || cp0 === 0xff5c);
  return {
    ...baseStyle,
    fontFamily: isBarOnly ? UPRIGHT_BAR_FONT_FAMILY : MATH_SYMBOL_FONT_FAMILY,
    fontStyle: 'normal',
    fontSynthesis: 'none',
    textDecoration: 'none',
  };
};

const renderTextWithMathFonts = (text, baseStyle, key) => {
  const runs = splitMathFontRuns(text || '');
  if (runs.length === 1 && !runs[0].math) {
    return (
      <span key={key} style={baseStyle}>
        {text}
      </span>
    );
  }
  return (
    <span key={key}>
      {runs.map((r, i) => (
        <span
          key={`${key}-m${i}`}
          style={r.math ? mathSymbolSpanStyle(r.t, baseStyle) : baseStyle}
        >
          {r.t}
        </span>
      ))}
    </span>
  );
};

const renderPlainTextWithMathFonts = (text) =>
  splitMathFontRuns(text || '').map((r, i) => (
    <span key={i} style={r.math ? mathSymbolSpanStyle(r.t, {}) : undefined}>
      {r.t}
    </span>
  ));

const FORMULA_IMAGE_ALT = new Set(['公式', '公式图片', '[公式]', 'formula']);

const readLayoutBox = (node) => {
  const lw = typeof node.layout_width_px === 'number' ? node.layout_width_px : null;
  const lh = typeof node.layout_height_px === 'number' ? node.layout_height_px : null;
  if (lw != null && lh != null && lw > 0 && lh > 0) {
    return { lw, lh };
  }
  return null;
};

/**
 * 展示盒：有 layout_* 时与 Word 占位一致；无则退回 width/height（与历史 JSON 兼容）。
 * 宽幅条带（多图合一）单独用像素上限。非公式图仍用栏宽/视口约束。
 */
const scaleWideFormulaPanel = (w, h) => {
  let nh = Math.min(h, PANEL_MAX_H_PX);
  let nw = Math.round(w * (nh / h));
  if (nw > PANEL_MAX_W_PX) {
    nw = PANEL_MAX_W_PX;
    nh = Math.max(1, Math.round(h * (nw / w)));
  }
  return {
    width: `${nw}px`,
    height: `${nh}px`,
    maxWidth: '100%',
    objectFit: 'contain',
    margin: '0.25rem 0',
    verticalAlign: 'middle',
  };
};

const scaleInlineFormulaFromMeta = (w, h, options = {}) => {
  const maxH = typeof options.maxHeightPx === 'number' ? options.maxHeightPx : inlineFormulaMaxHeightPx();
  const base = {
    maxWidth: '100%',
    objectFit: 'contain',
    margin: '0 0.12rem',
    verticalAlign: '-0.18em',
  };
  if (h <= maxH) {
    return {
      ...base,
      width: `${w}px`,
      height: `${h}px`,
    };
  }
  const s = maxH / h;
  const nw = Math.max(1, Math.round(w * s));
  const nh = Math.max(1, Math.round(h * s));
  return {
    ...base,
    width: `${nw}px`,
    height: `${nh}px`,
  };
};

/** 无 layout_* 时：若 JSON 里 width/height 明显小于栅格，用栅格/OMML_RASTER_DISPLAY_DIV 作展示参考 */
const effectiveOmmlMetaBox = (node, w, h) => {
  const rw = typeof node.raster_width === 'number' ? node.raster_width : null;
  const rh = typeof node.raster_height === 'number' ? node.raster_height : null;
  if (rw == null || rh == null || rw <= 0 || rh <= 0) {
    return { cw: w, ch: h };
  }
  const cw0 = Math.max(1, Math.round(rw / OMML_RASTER_DISPLAY_DIV));
  const ch0 = Math.max(1, Math.round(rh / OMML_RASTER_DISPLAY_DIV));
  if (w == null || h == null || w <= 0 || h <= 0) {
    return { cw: cw0, ch: ch0 };
  }
  if (ch0 > h * 1.12 || cw0 > w * 1.12) {
    return { cw: cw0, ch: ch0 };
  }
  return { cw: w, ch: h };
};

const buildRichImageDisplay = (node) => {
  const layout = readLayoutBox(node);
  const w = typeof node.width === 'number' ? node.width : null;
  const h = typeof node.height === 'number' ? node.height : null;
  const hasMetaDims = w != null && h != null && w > 0 && h > 0;
  const isFormulaImage = Boolean(node.omml_raster) || FORMULA_IMAGE_ALT.has(node.alt_text || '');

  const imgClassFlat = 'inline-block align-middle bg-white object-contain max-w-full';
  const imgClassWrapInner = 'block max-h-full max-w-full bg-white';

  if (!isFormulaImage) {
    if (layout) {
      const { lw, lh } = layout;
      return {
        wrap: true,
        wrapStyle: {
          display: 'inline-block',
          verticalAlign: 'middle',
          lineHeight: 0,
          width: `min(100%, ${lw}px)`,
          aspectRatio: `${lw} / ${lh}`,
          height: 'auto',
          maxWidth: '100%',
          margin: '0.2rem 0',
        },
        imgClass: imgClassWrapInner,
        imgStyle: {
          width: '100%',
          height: '100%',
          objectFit: 'contain',
          maxHeight: 'min(560px, 72vh)',
        },
      };
    }
    if (!hasMetaDims) {
      return {
        wrap: false,
        imgClass: `${imgClassFlat} max-h-[min(70vh,480px)]`,
        imgStyle: { width: 'auto', height: 'auto', maxWidth: '100%' },
      };
    }
    return {
      wrap: false,
      imgClass: imgClassFlat,
      imgStyle: {
        width: `min(100%, ${Math.min(w, 720)}px)`,
        height: 'auto',
        maxWidth: '100%',
        maxHeight: `min(${h}px, 560px, 72vh)`,
        margin: '0.2rem 0',
        verticalAlign: 'middle',
      },
    };
  }

  let boxW = layout ? layout.lw : w;
  let boxH = layout ? layout.lh : h;
  if (isFormulaImage && !layout) {
    const er = effectiveOmmlMetaBox(node, w, h);
    boxW = er.cw;
    boxH = er.ch;
  }
  const hasBox = boxW != null && boxH != null && boxW > 0 && boxH > 0;

  if (!hasBox) {
    const fallbackH = inlineFormulaMaxHeightPx();
    return {
      wrap: false,
      imgClass: imgClassFlat,
      imgStyle: {
        width: 'auto',
        height: 'auto',
        maxHeight: `${fallbackH}px`,
        maxWidth: '100%',
        margin: '0 0.12rem',
        verticalAlign: '-0.18em',
      },
    };
  }

  const aspect = boxW / boxH;
  const isWideFormulaPanel =
    (aspect >= WIDE_FORMULA_ASPECT && boxW >= WIDE_FORMULA_MIN_META_W)
    || (boxW >= 300 && boxH >= 80 && aspect >= 1.82);
  const flatStrip = isFlatInlineFormulaStrip(boxW, boxH);

  if (layout) {
    if (isWideFormulaPanel) {
      if (flatStrip) {
        const scaled = scaleInlineFormulaFromMeta(boxW, boxH, {
          maxHeightPx: inlineFlatStripMaxHeightPx(),
        });
        return { wrap: false, imgClass: imgClassFlat, imgStyle: scaled };
      }
      const scaled = scaleWideFormulaPanel(boxW, boxH);
      const wrapperSized = { ...scaled };
      delete wrapperSized.objectFit;
      return {
        wrap: true,
        wrapStyle: {
          ...wrapperSized,
          display: 'inline-block',
          lineHeight: 0,
        },
        imgClass: imgClassWrapInner,
        imgStyle: {
          width: '100%',
          height: '100%',
          objectFit: 'contain',
          verticalAlign: 'middle',
        },
      };
    }
    // Word 布局行内公式：不再压到「一行半」统一高度，保留题面相邻公式的相对高矮
    return {
      wrap: true,
      wrapStyle: {
        display: 'inline-block',
        verticalAlign: '-0.18em',
        lineHeight: 0,
        width: `min(100%, ${boxW}px)`,
        aspectRatio: `${boxW} / ${boxH}`,
        height: 'auto',
        maxWidth: '100%',
        margin: '0 0.12em',
      },
      imgClass: imgClassWrapInner,
      imgStyle: {
        width: '100%',
        height: '100%',
        objectFit: 'contain',
        maxHeight: 'min(70vh, 520px)',
      },
    };
  }

  const scaled = isWideFormulaPanel
    ? (flatStrip
        ? scaleInlineFormulaFromMeta(boxW, boxH, {
            maxHeightPx: inlineFlatStripMaxHeightPx(),
          })
        : scaleWideFormulaPanel(boxW, boxH))
    : scaleInlineFormulaFromMeta(boxW, boxH, {
        maxHeightPx:
          node.omml_raster && !flatStrip
            ? inlineFormulaMaxHeightOmmlFallbackPx()
            : undefined,
      });

  return { wrap: false, imgClass: imgClassFlat, imgStyle: scaled };
};

const paragraphStyleFromConfig = (style = {}) => {
  const resolved = {
    whiteSpace: 'pre-wrap',
    lineHeight: RICH_PARAGRAPH_LINE_HEIGHT,
  };
  if (style.font_size_pt != null) {
    const pt = Number(style.font_size_pt);
    if (Number.isFinite(pt)) {
      resolved.fontSize = `${Math.min(pt, MAX_BODY_FONT_PT)}pt`;
    }
  } else {
    resolved.fontSize = `${RICH_PARAGRAPH_BASE_PT}pt`;
  }
  if (style.text_align) resolved.textAlign = style.text_align;
  if (style.first_line_indent_pt) resolved.textIndent = `${style.first_line_indent_pt}pt`;
  if (style.left_indent_pt) resolved.paddingLeft = `${style.left_indent_pt}pt`;
  if (style.right_indent_pt) resolved.paddingRight = `${style.right_indent_pt}pt`;
  if (style.space_before_pt) resolved.marginTop = `${style.space_before_pt}pt`;
  if (style.space_after_pt) resolved.marginBottom = `${style.space_after_pt}pt`;
  if (style.line_spacing) resolved.lineHeight = style.line_spacing;
  return resolved;
};

const renderInlineNode = (node, key) => {
  if (!node || typeof node !== 'object') return null;
  switch (node.type) {
    case 'text':
      return renderTextWithMathFonts(node.text, textStyleFromMarks(node.marks), key);
    case 'formula':
      return (
        <span key={key} className="font-medium text-slate-900">
          {renderTextWithMathFonts(node.text, textStyleFromMarks(node.marks), `${key}-f`)}
        </span>
      );
    case 'image': {
      const src = resolveAssetUrl(node.src || node.public_url || node.storage_url);
      const disp = buildRichImageDisplay(node);
      if (disp.wrap) {
        return (
          <span key={key} style={disp.wrapStyle}>
            <img
              src={src}
              alt={node.alt_text || '题目图片'}
              className={disp.imgClass}
              style={disp.imgStyle}
            />
          </span>
        );
      }
      return (
        <img
          key={key}
          src={src}
          alt={node.alt_text || '题目图片'}
          className={disp.imgClass}
          style={disp.imgStyle}
        />
      );
    }
    case 'line_break':
      return <br key={key} />;
    default:
      return null;
  }
};

const renderBlockNode = (node, keyPrefix = 'node') => {
  if (!node || typeof node !== 'object') return null;
  switch (node.type) {
    case 'block_group': {
      const inner = (node.blocks || [])
        .map((child, index) => renderBlockNode(child, `${keyPrefix}-block-${index}`))
        .filter(Boolean);
      if (!inner.length && node.plain_text) {
        return (
          <p key={keyPrefix} className="text-slate-800 whitespace-pre-wrap leading-8">
            {renderPlainTextWithMathFonts(node.plain_text)}
          </p>
        );
      }
      return (
        <div key={keyPrefix} className="space-y-2">
          {inner}
        </div>
      );
    }
    case 'paragraph':
      return (
        <p key={keyPrefix} className="text-slate-800" style={paragraphStyleFromConfig(node.style)}>
          {(node.children || []).map((child, index) => renderInlineNode(child, `${keyPrefix}-inline-${index}`))}
        </p>
      );
    case 'table': {
      const rows = node.rows || [];
      if (!rows.length) return null;
      const [headRow, ...bodyRows] = rows;
      const renderCellInner = (cell, rowIndex, cellIndex) => (
        <div className="min-w-[3.5rem] max-w-[min(92vw,36rem)] space-y-2 break-words">
          {(cell.blocks || []).map((block, blockIndex) =>
            renderBlockNode(block, `${keyPrefix}-cell-block-${rowIndex}-${cellIndex}-${blockIndex}`))}
        </div>
      );
      const thClass = 'border-b border-slate-200 bg-slate-50 px-3 py-2.5 text-left text-slate-800 font-semibold align-top';
      const tdClass = 'border border-slate-200 px-3 py-2 align-top text-slate-800';
      return (
        <div key={keyPrefix} className="my-3 overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
          <table className="w-full min-w-[12rem] border-collapse text-[13px] leading-relaxed">
            <thead>
              <tr>
                {(headRow.cells || []).map((cell, cellIndex) => (
                  <th key={`${keyPrefix}-h-${cellIndex}`} className={thClass} scope="col">
                    {renderCellInner(cell, 0, cellIndex)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {bodyRows.map((row, rowIndex) => (
                <tr
                  key={`${keyPrefix}-row-${rowIndex + 1}`}
                  className={rowIndex % 2 === 1 ? 'bg-slate-50/60' : 'bg-white'}
                >
                  {(row.cells || []).map((cell, cellIndex) => (
                    <td key={`${keyPrefix}-d-${rowIndex}-${cellIndex}`} className={tdClass}>
                      {renderCellInner(cell, rowIndex + 1, cellIndex)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
    default:
      return null;
  }
};

export default function QuestionRichRenderer({ payload, fallbackText, className = '' }) {
  if (!payload) {
    return fallbackText ? (
      <p className={`whitespace-pre-wrap leading-8 text-slate-800 ${className}`}>
        {renderPlainTextWithMathFonts(fallbackText)}
      </p>
    ) : null;
  }

  const rendered = renderBlockNode(payload);
  if (
    payload.type === 'block_group'
    && !(payload.blocks || []).length
    && !rendered
    && (payload.plain_text || fallbackText)
  ) {
    const text = payload.plain_text || fallbackText;
    return (
      <p className={`whitespace-pre-wrap leading-8 text-slate-800 ${className}`}>
        {renderPlainTextWithMathFonts(text)}
      </p>
    );
  }

  if (!rendered && fallbackText) {
    return (
      <p className={`whitespace-pre-wrap leading-8 text-slate-800 ${className}`}>
        {renderPlainTextWithMathFonts(fallbackText)}
      </p>
    );
  }

  return <div className={className}>{rendered}</div>;
}
