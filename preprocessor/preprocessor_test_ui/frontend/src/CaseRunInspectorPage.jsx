import React, { useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  Collapse,
  LinearProgress,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import ImageOutlinedIcon from '@mui/icons-material/ImageOutlined';
import AdminShell from './AdminShell';
import PageSection from './PageSection';

const DEFAULT_ROOT = 'D:\\10739\\Exam-Analysis-Suite\\preprocessor\\tests\\mock_data\\case_1774869949449';

const cardSx = {
  p: 2,
  borderRadius: 3,
  border: '1px solid #eef0f3',
  backgroundColor: '#fafbfc',
  boxShadow: 'none',
};

const tableSx = {
  borderRadius: 2.5,
  boxShadow: 'none',
  border: '1px solid #eef0f3',
};

function buildThumbUrl(rootDir, rel) {
  if (!rootDir || !rel) {
    return null;
  }
  const params = new URLSearchParams();
  params.set('root', rootDir);
  params.set('rel', rel);
  return `/api/case-run-inspect/file?${params.toString()}`;
}

function CaseRunInspectorPage() {
  const [rootDir, setRootDir] = useState(DEFAULT_ROOT);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [data, setData] = useState(null);
  const [showInventory, setShowInventory] = useState(true);
  const [showManifest, setShowManifest] = useState(false);

  const load = async () => {
    setError('');
    setData(null);
    setLoading(true);
    try {
      const res = await fetch('/api/case-run-inspect/summary', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ root_dir: rootDir }),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(json.detail || res.statusText || '请求失败');
      }
      setData(json);
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  };

  const contract = data?.contract;
  const cross = data?.cross_check;
  const manifest = data?.manifest_excerpt;
  const questions = data?.questions || [];
  const missing = data?.resource_missing || {};
  const inv = data?.file_inventory || [];

  return (
    <AdminShell
      pageKey="case-run-inspect"
      title="Bundle / Run 目录检视"
      subtitle="用于人工核验 mock 或 temp run 目录是否已正确解析，并可喂入 analyzer 标准 bundle"
      breadcrumbs="统一测试控制台 / Bundle 检视"
    >
      <Stack spacing={2.5}>
        {error && (
          <Alert severity="error" onClose={() => setError('')}>
            {error}
          </Alert>
        )}

        <PageSection
          title="目录"
          description="填写 preprocessor 导出的工作根目录，须位于 preprocessor 或 preprocessor/tests/mock_data 下。示例为录制案例目录。"
        >
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems={{ md: 'flex-start' }}>
            <TextField
              label="根目录 (root_dir)"
              value={rootDir}
              onChange={(e) => setRootDir(e.target.value)}
              fullWidth
              size="small"
            />
            <Button variant="contained" onClick={load} disabled={loading || !rootDir.trim()}>
              加载
            </Button>
          </Stack>
        </PageSection>

        {loading && <LinearProgress />}

        {data && (
          <>
            <PageSection title="合同与可导入性" description="与 analyzer 导入所需 manifest + questions 一致为「可喂入」。">
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                <Chip
                  size="small"
                  color={contract?.import_ready ? 'success' : 'warning'}
                  label={contract?.import_ready ? '可导入 analyzer' : '合同不完整 / 需检查'}
                />
                <Chip size="small" variant="outlined" label={`manifest: ${contract?.has_manifest ? '有' : '无'}`} />
                <Chip size="small" variant="outlined" label={`questions: ${contract?.has_questions ? '有' : '无'}`} />
                <Chip
                  size="small"
                  variant="outlined"
                  label={`questions 为数组: ${contract?.has_questions_array ? '是' : '否'}`}
                />
                {contract?.has_metadata_legacy && <Chip size="small" color="info" label="仅 metadata 兼容" />}
              </Stack>
            </PageSection>

            {cross && (
              <PageSection title="题量交叉核对" description="与 manifest.stats、complete_units 条数是否一致。">
                <Box sx={cardSx}>
                  <Stack spacing={0.5}>
                    <Typography variant="body2">questions.json 行数: {cross.questions_file_count}</Typography>
                    <Typography variant="body2">manifest total_questions: {cross.manifest_stats_total ?? '（无）'}</Typography>
                    <Typography variant="body2">complete_units 题项数: {cross.complete_units_count ?? '（无/未读）'}</Typography>
                    <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ pt: 1 }}>
                      <Chip
                        size="small"
                        color={cross.aligns_with_manifest === true ? 'success' : cross.aligns_with_manifest === false ? 'error' : 'default'}
                        label={
                          cross.aligns_with_manifest == null
                            ? '与 manifest 未比较'
                            : `与 manifest ${cross.aligns_with_manifest ? '一致' : '不一致'}`
                        }
                      />
                      <Chip
                        size="small"
                        color={
                          cross.aligns_with_complete_units === true
                            ? 'success'
                            : cross.aligns_with_complete_units === false
                            ? 'error'
                            : 'default'
                        }
                        label={
                          cross.aligns_with_complete_units == null
                            ? '与 complete_units 未比较'
                            : `与 complete_units ${cross.aligns_with_complete_units ? '一致' : '不一致'}`
                        }
                      />
                    </Stack>
                  </Stack>
                </Box>
              </PageSection>
            )}

            {manifest && (
              <PageSection
                title="Manifest 摘要"
                description="bundle_id、学科上下文、生产环境信息。"
                actions={
                  <Button size="small" onClick={() => setShowManifest((v) => !v)}>
                    {showManifest ? '收起 JSON' : '展开 JSON'}
                  </Button>
                }
              >
                <Box sx={cardSx}>
                  <Stack spacing={0.5}>
                    <Typography variant="body2">bundle_id: {manifest.bundle_id ?? '—'}</Typography>
                    <Typography variant="body2">run_id: {manifest.run_id ?? '—'}</Typography>
                    <Typography variant="body2">status: {manifest.status ?? '—'}</Typography>
                    <Typography variant="body2">sheets: {manifest.sheet_count}</Typography>
                    <Typography variant="body2" sx={{ wordBreak: 'break-all' }}>
                      exam_context: {JSON.stringify(manifest.exam_context || {})}
                    </Typography>
                  </Stack>
                  <Collapse in={showManifest}>
                    <Box component="pre" sx={{ mt: 1, p: 1, overflow: 'auto', maxHeight: 360, fontSize: 12, bgcolor: '#fff', border: '1px solid #eee' }}>
                      {JSON.stringify(
                        { stats: manifest.stats, manifest_warnings: manifest.manifest_warnings, producer: manifest.producer },
                        null,
                        2
                      )}
                    </Box>
                  </Collapse>
                </Box>
              </PageSection>
            )}

            {data.run_summary && (
              <PageSection title="run_summary.json" description="若存在则显示 pipeline 运行摘要。">
                <Box component="pre" sx={{ ...cardSx, overflow: 'auto', maxHeight: 240, fontSize: 12, m: 0 }}>
                  {JSON.stringify(data.run_summary, null, 2)}
                </Box>
              </PageSection>
            )}

            <PageSection
              title="顶层文件"
              description="根目录下文件列表（截断前 200 项）。"
              actions={
                <Button size="small" onClick={() => setShowInventory((v) => !v)}>
                  {showInventory ? '折叠' : '展开'}
                </Button>
              }
            >
              <Collapse in={showInventory}>
                <TableContainer component={Paper} variant="outlined" sx={tableSx}>
                  <Table size="small" stickyHeader>
                    <TableHead>
                      <TableRow>
                        <TableCell>名称</TableCell>
                        <TableCell>类型</TableCell>
                        <TableCell align="right">大小 (bytes)</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {inv.map((row) => (
                        <TableRow key={row.name}>
                          <TableCell>{row.name}</TableCell>
                          <TableCell>{row.is_file ? 'file' : row.is_dir ? 'dir' : '?'}</TableCell>
                          <TableCell align="right">{row.size_bytes != null ? row.size_bytes : '—'}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              </Collapse>
            </PageSection>

            {(data.summary_warnings || []).length > 0 && (
              <Alert severity="warning">
                {(data.summary_warnings || []).map((w, i) => (
                  <div key={i}>{w}</div>
                ))}
              </Alert>
            )}

            {missing.count > 0 && (
              <Alert severity="error">
                资源文件缺失: {missing.count} 处（前 500 条见下表）。请核对路径是否被 .gitignore 或未复制到本机。
              </Alert>
            )}

            {missing.count > 0 && (
              <TableContainer component={Paper} variant="outlined" sx={tableSx}>
                <Table size="small" stickyHeader>
                  <TableHead>
                    <TableRow>
                      <TableCell>题号</TableCell>
                      <TableCell>角色</TableCell>
                      <TableCell>路径</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {(missing.items || []).slice(0, 100).map((m, i) => (
                      <TableRow key={`${i}-${m.role}`}>
                        <TableCell>{m.question_no}</TableCell>
                        <TableCell>{m.role}</TableCell>
                        <TableCell sx={{ wordBreak: 'break-all', fontSize: 12 }}>{m.path}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            )}

            <PageSection title="逐题核验" description="题干摘要、作答、关键 confidence、资源是否齐；缩略图需同源代理。">
              <TableContainer component={Paper} variant="outlined" sx={tableSx}>
                <Table size="small" stickyHeader>
                  <TableHead>
                    <TableRow>
                      <TableCell width={120}>题号</TableCell>
                      <TableCell width={88}>图</TableCell>
                      <TableCell>题干</TableCell>
                      <TableCell width={72}>作答</TableCell>
                      <TableCell width={120}>来源</TableCell>
                      <TableCell width={80}>待复核</TableCell>
                      <TableCell width={100}>资源</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {questions.map((q) => {
                      const url = buildThumbUrl(data.root_dir, q.thumb_rel);
                      return (
                        <TableRow key={q.question_no} hover>
                          <TableCell>{q.question_no}</TableCell>
                          <TableCell>
                            {url ? (
                              <Box
                                component="img"
                                src={url}
                                alt={`q${q.question_no}`}
                                sx={{ maxWidth: 80, maxHeight: 64, objectFit: 'cover', borderRadius: 1, border: '1px solid #eee' }}
                              />
                            ) : (
                              <ImageOutlinedIcon fontSize="small" color="disabled" />
                            )}
                          </TableCell>
                          <TableCell>
                            <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
                              {q.question_text_preview}
                            </Typography>
                          </TableCell>
                          <TableCell>{q.student_answer ?? '—'}</TableCell>
                          <TableCell>
                            <Typography variant="caption" display="block">
                              {q.answer_source || '—'}
                            </Typography>
                            <Typography variant="caption" color="text.secondary">
                              {q.answer_status || ''}
                            </Typography>
                          </TableCell>
                          <TableCell>
                            <Chip
                              size="small"
                              label={q.needs_manual_review ? '是' : '否'}
                              color={q.needs_manual_review ? 'warning' : 'default'}
                              variant="outlined"
                            />
                          </TableCell>
                          <TableCell>
                            <Chip
                              size="small"
                              color={q.assets_ok ? 'success' : 'error'}
                              label={q.assets_ok ? '齐' : '缺'}
                            />
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </TableContainer>
            </PageSection>
          </>
        )}

        {!data && !loading && !error && (
          <Alert severity="info">输入目录后点击「加载」；将展示 contract、题量交叉核对、每题行与资源缺失。</Alert>
        )}
      </Stack>
    </AdminShell>
  );
}

export default CaseRunInspectorPage;
