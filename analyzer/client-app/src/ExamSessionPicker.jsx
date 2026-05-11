import React, { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Loader2 } from 'lucide-react';

/**
 * 在缺少 exam_session_id 时展示：说明 + 从 GET /api/exam-sessions 拉取的场次列表（可点进当前路由）。
 */
function ExamSessionPicker({ description }) {
  const location = useLocation();
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const hint =
        '请先让 Analyzer API 在 127.0.0.1:8000 监听：`analyzer` 目录运行 `start_fastapi.ps1`，或运行预处理目录下的 `start_test_ui.bat`（会另开控制台启动 Analyzer 监听 8000）；再刷新。若改端口请编辑 `client-app/.env.development` 中的 `VITE_DEV_API_ORIGIN` 并重启 `npm run dev`。';
      try {
        const r = await fetch('/api/exam-sessions/?limit=80');
        if (!r.ok) {
          throw new Error(
            `列表请求失败 (HTTP ${r.status})。代理目标见 client-app/vite 配置；通常为 127.0.0.1:8000（analyzer）。`,
          );
        }
        const data = await r.json();
        if (!cancelled) setSessions(Array.isArray(data) ? data : []);
      } catch (e) {
        if (!cancelled) {
          const raw = typeof e?.message === 'string' ? e.message : '';
          const isNetwork =
            e instanceof TypeError ||
            /Failed to fetch|NetworkError|ECONNREFUSED|fetch failed|load failed/i.test(raw);
          setErr(
            isNetwork
              ? `无法连接后端（代理目标无服务或被拒）。 ${hint}`
              : raw || '加载失败',
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="w-full max-w-5xl mx-auto px-4 text-center">
      <p className="text-slate-600 text-sm mb-2">{description}</p>
      <p className="text-slate-500 text-xs mb-6">
        在地址栏为当前页追加参数即可，例如：
        <code className="mx-1 px-1.5 py-0.5 rounded bg-slate-200 text-slate-800 text-[11px]">
          {location.pathname}?exam_session_id=数字
        </code>
      </p>
      {loading && (
        <div className="flex justify-center items-center gap-2 text-slate-500 text-sm">
          <Loader2 className="animate-spin" size={18} />
          正在拉取考试场次…
        </div>
      )}
      {err && (
        <p className="text-rose-600 text-sm whitespace-pre-wrap text-left">
          {err}
        </p>
      )}
      {!loading && !err && (
        <div className="text-left">
          <p className="text-xs text-slate-500 mb-2">点击下方场次直接打开本页（带 exam_session_id）：</p>
          <div className="max-h-64 overflow-auto rounded-xl border border-slate-200 bg-white">
            <table className="w-full text-sm table-fixed">
              <thead className="sticky top-0 bg-slate-100 text-slate-500 text-xs uppercase">
                <tr>
                  <th className="px-3 py-2 text-left w-16">ID</th>
                  <th className="px-3 py-2 text-left w-28">学科</th>
                  <th className="px-3 py-2 text-left w-24">分析状态</th>
                  <th className="px-3 py-2 text-left w-[44rem]">Bundle 绝对路径</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {sessions.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-3 py-4 text-slate-500 text-sm text-center">
                      暂无考试场次。请先通过 bundle 导入创建 ExamSession。
                    </td>
                  </tr>
                )}
                {sessions.map((s) => (
                  <tr key={s.id}>
                    <td className="px-3 py-2">
                      <Link
                        to={{ pathname: location.pathname, search: `?exam_session_id=${s.id}` }}
                        className="font-mono text-blue-600 hover:underline"
                      >
                        #{s.id}
                      </Link>
                    </td>
                    <td className="px-3 py-2 text-slate-600">
                      {s.subject || '未设学科'}
                    </td>
                    <td className="px-3 py-2 text-slate-400 text-xs">
                      {s.analysis_status || '—'}
                    </td>
                    <td
                      className="px-3 py-2 text-slate-500 text-xs whitespace-normal break-all"
                      title={s.bundle_dir || ''}
                    >
                      {s.bundle_dir || '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

export default ExamSessionPicker;
