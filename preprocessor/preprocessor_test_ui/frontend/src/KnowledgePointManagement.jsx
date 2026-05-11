import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControl,
  FormControlLabel,
  FormGroup,
  Grid,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tabs,
  TextField,
  Typography,
} from '@mui/material';
import RefreshRoundedIcon from '@mui/icons-material/RefreshRounded';
import ManageSearchRoundedIcon from '@mui/icons-material/ManageSearchRounded';
import PlayArrowRoundedIcon from '@mui/icons-material/PlayArrowRounded';
import SyncRoundedIcon from '@mui/icons-material/SyncRounded';
import AdminShell from './AdminShell';
import PageSection from './PageSection';
import QuestionRichRenderer from './QuestionRichRenderer';
import { terminalSx } from './adminTheme';
import {
  KnowledgeGraphWorkspace,
  KnowledgeDerivativeWorkspace,
} from './KnowledgeGraphDerivativePanel';

const reviewStatusOptions = ['draft', 'pending', 'approved', 'rejected'];
const cardSx = {
  p: 2,
  borderRadius: 3,
  border: '1px solid #eef0f3',
  backgroundColor: '#fafbfc',
  minHeight: 108,
};
const tableSx = {
  borderRadius: 2.5,
  boxShadow: 'none',
  border: '1px solid #eef0f3',
};

function formatDate(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', { hour12: false });
}

/** 专题包摄入时间：按行创建时间，精确到分钟（本地时区） */
function formatIngestedAt(value) {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '—';
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function statusColor(value) {
  if (['approved', 'success'].includes(value)) return 'success';
  if (['rejected', 'failed'].includes(value)) return 'error';
  if (['pending', 'running', 'review'].includes(value)) return 'warning';
  return 'default';
}

function renderJsonSummary(value) {
  if (!value) return '-';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch (error) {
    return String(value);
  }
}

/** 某知识点出现在哪些知识块：主块 knowledge_point_id + 块锚点 llm_knowledge_points */
function blockOrdersForKnowledgePoint(knowledgePointId, blocks) {
  if (!blocks?.length || knowledgePointId == null) return [];
  const pid = Number(knowledgePointId);
  if (Number.isNaN(pid)) return [];
  const orders = new Set();
  for (const block of blocks) {
    const bo = block.block_order;
    if (bo == null) continue;
    if (Number(block.knowledge_point_id) === pid) orders.add(bo);
    const anchor = block.source_anchor_json;
    if (anchor && typeof anchor === 'object' && Array.isArray(anchor.llm_knowledge_points)) {
      for (const row of anchor.llm_knowledge_points) {
        if (row != null && Number(row.knowledge_point_id) === pid) {
          orders.add(bo);
          break;
        }
      }
    }
  }
  return Array.from(orders).sort((a, b) => a - b);
}

/** 从专题包 outline_json 中查找某题的按题桥接 LLM 审计条（与后端 question_bridge_llm_debug 对齐） */
function findQuestionBridgeLlmEntry(outlineJson, questionItemId) {
  const dbg = outlineJson && typeof outlineJson === 'object' ? outlineJson.question_bridge_llm_debug : null;
  const list = dbg && Array.isArray(dbg.raw_responses) ? dbg.raw_responses : null;
  if (!list) return null;
  const qid = Number(questionItemId);
  return list.find((r) => Number(r.question_item_id) === qid) || null;
}

function formatBlockOrders(orders) {
  if (!orders?.length) return '—';
  return orders.map((o) => `#${o}`).join('，');
}

function BlockPreviewCard({ block }) {
  const richPayload = block?.rich_content_json && typeof block.rich_content_json === 'object' && !Array.isArray(block.rich_content_json)
    ? block.rich_content_json
    : null;
  const fallbackText = block?.normalized_text || block?.raw_text || (block?.rich_content_json ? renderJsonSummary(block.rich_content_json) : '');

  return (
    <Paper sx={{ p: 1.5, borderRadius: 2, backgroundColor: '#fbfcff', boxShadow: 'none', border: '1px solid #eef0f3' }}>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} justifyContent="space-between" sx={{ mb: 1.25 }}>
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          <Chip label={block.block_role || 'block'} size="small" color="primary" variant="outlined" />
          <Chip label={block.content_format || 'unknown'} size="small" variant="outlined" />
          {block.section_path ? <Chip label={block.section_path} size="small" variant="outlined" /> : null}
        </Stack>
        <Typography variant="caption">
          页码 {block.source_page_no ?? '-'} · 顺序 {block.block_order ?? '-'}
        </Typography>
      </Stack>
      <Box sx={{ '& pre': { m: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontFamily: 'inherit' } }}>
        <QuestionRichRenderer payload={richPayload} fallbackText={fallbackText || '暂无内容'} />
      </Box>
    </Paper>
  );
}

function InfoField({ label, value }) {
  return (
    <Box>
      <Typography variant="caption" sx={{ display: 'block', mb: 0.5 }}>{label}</Typography>
      <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{value || '-'}</Typography>
    </Box>
  );
}

function KnowledgePointManagement() {
  const searchParams = useMemo(() => new URLSearchParams(window.location.search), []);
  const [activeTab, setActiveTab] = useState(searchParams.get('tab') === 'packages' ? 'packages' : 'points');
  const [overview, setOverview] = useState({ flags: {}, counts: {}, status_breakdown: {}, subjects: [], backends: {} });
  const [points, setPoints] = useState([]);
  const [packages, setPackages] = useState([]);
  const [ingestDir, setIngestDir] = useState('');
  const [ingestFiles, setIngestFiles] = useState([]);
  const [selectedIngestFiles, setSelectedIngestFiles] = useState([]);
  const [forceReingest, setForceReingest] = useState(false);
  const [ingestRunning, setIngestRunning] = useState(false);
  const [ingestTaskId, setIngestTaskId] = useState('');
  const [ingestTaskDetail, setIngestTaskDetail] = useState(null);
  const [ingestLogs, setIngestLogs] = useState('等待开始摄入…\n');
  const [lastRunDir, setLastRunDir] = useState('');
  const ingestLogRef = useRef(null);
  const ingestWsRef = useRef(null);
  const [selectedPointId, setSelectedPointId] = useState(searchParams.get('pointId') || '');
  const [selectedPackageId, setSelectedPackageId] = useState(searchParams.get('packageId') || '');
  const [pointDetail, setPointDetail] = useState(null);
  const [packageDetail, setPackageDetail] = useState(null);
  const [pointSubject, setPointSubject] = useState('');
  const [pointReviewStatus, setPointReviewStatus] = useState('');
  /** 知识点列表分页与按 ID 查询（与列表请求同步） */
  const [pointPage, setPointPage] = useState(0);
  const [pointPageSize, setPointPageSize] = useState(10);
  const [pointIdInput, setPointIdInput] = useState('');
  const [pointIdQuery, setPointIdQuery] = useState(null);
  const [pointsTotal, setPointsTotal] = useState(0);
  const [packageSubject, setPackageSubject] = useState('');
  const [packageReviewStatus, setPackageReviewStatus] = useState('');
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [syncingKey, setSyncingKey] = useState('');
  const [message, setMessage] = useState(null);
  const [refreshTick, setRefreshTick] = useState(0);
  const [deletingPointId, setDeletingPointId] = useState('');
  /** 相关题目桥接：点击行查看桥接知识点 + 按题 LLM 原始返回 */
  const [bridgeQuestionDialog, setBridgeQuestionDialog] = useState(null);
  /** 专题包右栏：详情 / 覆盖点 / 桥接 / 块预览 */
  const [packageDetailTab, setPackageDetailTab] = useState(0);

  const subjects = overview.subjects || [];
  const pointStatusBreakdown = overview.status_breakdown?.point_review_status || {};
  const packageStatusBreakdown = overview.status_breakdown?.package_review_status || {};
  const parseStatusBreakdown = overview.status_breakdown?.package_parse_status || {};

  const loadIngestFiles = async () => {
    const response = await fetch('/api/knowledge-admin/ingest/files');
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data?.detail || '加载可摄入文件失败');
    }
    const data = await response.json().catch(() => ({}));
    setIngestDir(data?.directory || '');
    setIngestFiles(Array.isArray(data?.files) ? data.files : []);
    setSelectedIngestFiles([]);
  };

  const loadIngestTask = async (taskId) => {
    if (!taskId) return null;
    const response = await fetch(`/api/knowledge-admin/ingest/tasks/${taskId}`);
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data?.detail || '加载摄入任务状态失败');
    }
    const data = await response.json().catch(() => ({}));
    setIngestTaskDetail(data);
    return data;
  };

  useEffect(() => {
    if (ingestLogRef.current) {
      ingestLogRef.current.scrollTop = ingestLogRef.current.scrollHeight;
    }
  }, [ingestLogs]);

  useEffect(() => () => {
    if (ingestWsRef.current) {
      try {
        ingestWsRef.current.close();
      } catch (e) {
        /* ignore */
      }
      ingestWsRef.current = null;
    }
  }, []);

  useEffect(() => {
    let ignore = false;

    const load = async () => {
      setLoading(true);
      try {
        const pointParams = new URLSearchParams();
        pointParams.set('limit', String(pointPageSize));
        pointParams.set('skip', String(pointPage * pointPageSize));
        if (pointSubject) pointParams.set('subject', pointSubject);
        if (pointReviewStatus) pointParams.set('review_status', pointReviewStatus);
        if (pointIdQuery != null && !Number.isNaN(pointIdQuery)) {
          pointParams.set('knowledge_point_id', String(pointIdQuery));
        }
        const packageParams = new URLSearchParams({ limit: '100' });
        if (packageSubject) packageParams.set('subject', packageSubject);
        if (packageReviewStatus) packageParams.set('review_status', packageReviewStatus);

        const [overviewRes, pointsRes, packagesRes] = await Promise.all([
          fetch('/api/knowledge-admin/overview'),
          fetch(`/api/knowledge-points/points?${pointParams.toString()}`),
          fetch(`/api/knowledge-points/packages?${packageParams.toString()}`),
        ]);

        if (!overviewRes.ok || !pointsRes.ok || !packagesRes.ok) {
          const detail = await overviewRes.text().catch(() => '');
          throw new Error(detail || '加载知识点后台数据失败');
        }

        const [overviewData, pointsData, packagesData] = await Promise.all([
          overviewRes.json(),
          pointsRes.json(),
          packagesRes.json(),
        ]);
        const totalFromHeader = pointsRes.headers.get('X-Total-Count');
        const parsedTotal = totalFromHeader != null && totalFromHeader !== '' ? parseInt(totalFromHeader, 10) : Number.NaN;

        if (ignore) return;

        const nextPoints = Array.isArray(pointsData) ? pointsData : [];
        const nextPackages = Array.isArray(packagesData) ? packagesData : [];
        setOverview(overviewData || { flags: {}, counts: {}, status_breakdown: {}, subjects: [], backends: {} });
        setPoints(nextPoints);
        setPointsTotal(Number.isFinite(parsedTotal) ? parsedTotal : nextPoints.length);
        setPackages(nextPackages);
        setSelectedPointId((prev) => (nextPoints.some((item) => String(item.id) === String(prev)) ? prev : (nextPoints[0] ? String(nextPoints[0].id) : '')));
        setSelectedPackageId((prev) => (nextPackages.some((item) => String(item.id) === String(prev)) ? prev : (nextPackages[0] ? String(nextPackages[0].id) : '')));
        setMessage(null);
      } catch (error) {
        if (!ignore) {
          setMessage({ severity: 'error', text: error.message || '加载失败' });
          setPoints([]);
          setPackages([]);
        }
      } finally {
        if (!ignore) {
          setLoading(false);
        }
      }
    };

    load();
    return () => {
      ignore = true;
    };
  }, [
    refreshTick,
    pointSubject,
    pointReviewStatus,
    pointPage,
    pointPageSize,
    pointIdQuery,
    packageSubject,
    packageReviewStatus,
  ]);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      if (activeTab !== 'ingest') return;
      try {
        await loadIngestFiles();
      } catch (error) {
        if (!cancelled) {
          setMessage({ severity: 'error', text: error.message || '加载摄入文件失败' });
        }
      }
    };

    load();
    return () => {
      cancelled = true;
    };
  }, [activeTab]);

  useEffect(() => {
    let ignore = false;

    const loadPointDetail = async () => {
      if (!selectedPointId) {
        setPointDetail(null);
        return;
      }
      setDetailLoading(true);
      try {
        const response = await fetch(`/api/knowledge-points/points/${selectedPointId}`);
        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          throw new Error(data?.detail || '加载知识点详情失败');
        }
        const data = await response.json();
        if (!ignore) {
          setPointDetail(data);
        }
      } catch (error) {
        if (!ignore) {
          setPointDetail(null);
          setMessage({ severity: 'error', text: error.message || '加载知识点详情失败' });
        }
      } finally {
        if (!ignore) {
          setDetailLoading(false);
        }
      }
    };

    loadPointDetail();
    return () => {
      ignore = true;
    };
  }, [selectedPointId]);

  useEffect(() => {
    let ignore = false;

    const loadPackageDetail = async () => {
      if (!selectedPackageId) {
        setPackageDetail(null);
        return;
      }
      setDetailLoading(true);
      try {
        const response = await fetch(`/api/knowledge-points/packages/${selectedPackageId}`);
        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          throw new Error(data?.detail || '加载专题包详情失败');
        }
        const data = await response.json();
        if (!ignore) {
          setPackageDetail(data);
        }
      } catch (error) {
        if (!ignore) {
          setPackageDetail(null);
          setMessage({ severity: 'error', text: error.message || '加载专题包详情失败' });
        }
      } finally {
        if (!ignore) {
          setDetailLoading(false);
        }
      }
    };

    loadPackageDetail();
    return () => {
      ignore = true;
    };
  }, [selectedPackageId]);

  useEffect(() => {
    setBridgeQuestionDialog(null);
  }, [selectedPackageId]);

  useEffect(() => {
    setPackageDetailTab(0);
  }, [selectedPackageId]);

  const handleSync = async (targetType, targetId) => {
    if (!targetId) return;
    const syncKey = `${targetType}:${targetId}`;
    setSyncingKey(syncKey);
    try {
      const response = await fetch(
        targetType === 'point'
          ? `/api/knowledge-points/points/${targetId}/search-index`
          : `/api/knowledge-points/packages/${targetId}/search-index`,
        { method: 'POST' },
      );
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data?.detail || '索引同步失败');
      }
      setMessage({
        severity: 'success',
        text: `${targetType === 'point' ? '知识点' : '专题包'}索引同步完成：已写入 ${data.indexed_documents ?? 0} 条检索文档。`,
      });
      setRefreshTick((prev) => prev + 1);
    } catch (error) {
      setMessage({ severity: 'error', text: error.message || '索引同步失败' });
    } finally {
      setSyncingKey('');
    }
  };

  const handleBackfillBridge = async (packageId) => {
    if (!packageId) return;
    const syncKey = `backfill:${packageId}`;
    setSyncingKey(syncKey);
    try {
      const response = await fetch(
        `/api/knowledge-points/packages/${packageId}/backfill-question-bridge`,
        { method: 'POST' },
      );
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data?.detail || '补链失败');
      }
      setMessage({
        severity: 'success',
        text:
          `补链完成：新增 ${data.new_links ?? 0} 条（其中保底 ${data.fallback_links ?? 0} 条），`
          + `覆盖题数 ${data.bridged_question_count ?? 0}/${data.material_question_count ?? 0}。`,
      });
      setRefreshTick((prev) => prev + 1);
    } catch (error) {
      setMessage({ severity: 'error', text: error.message || '补链失败' });
    } finally {
      setSyncingKey('');
    }
  };

  const pointPageSizeOptions = [10, 20, 50, 100];
  const pointListTotalPages = pointsTotal > 0 ? Math.ceil(pointsTotal / pointPageSize) : 0;
  const pointListCanPrev = pointPage > 0;
  const pointListCanNext = pointsTotal > 0 && (pointPage + 1) * pointPageSize < pointsTotal;

  const applyPointIdSearch = () => {
    const t = String(pointIdInput).trim();
    if (!t) {
      setPointIdQuery(null);
      setPointPage(0);
      return;
    }
    const n = parseInt(t, 10);
    if (!Number.isFinite(n) || n < 1) {
      setMessage({ severity: 'warning', text: '请输入有效的正整数 ID' });
      return;
    }
    setPointIdQuery(n);
    setPointPage(0);
  };

  const clearPointIdSearch = () => {
    setPointIdInput('');
    setPointIdQuery(null);
    setPointPage(0);
  };

  const handleDeleteKnowledgePoint = async (pointId) => {
    if (pointId == null || pointId === '') return;
    const idStr = String(pointId);
    if (!window.confirm(`确定删除知识点 #${idStr}？将同时移除相关关联与检索索引，此操作不可恢复。`)) {
      return;
    }
    setDeletingPointId(idStr);
    try {
      const response = await fetch(`/api/knowledge-points/points/${idStr}`, { method: 'DELETE' });
      if (response.status === 204) {
        if (String(selectedPointId) === idStr) {
          setSelectedPointId('');
          setPointDetail(null);
        }
        setMessage({ severity: 'success', text: `已删除知识点 #${idStr}` });
        setRefreshTick((n) => n + 1);
        return;
      }
      const data = await response.json().catch(() => ({}));
      const d = data?.detail;
      const msg = Array.isArray(d)
        ? d.map((x) => (x && x.msg) || String(x)).join('；')
        : d != null
          ? String(d)
          : `删除失败（HTTP ${response.status}）`;
      throw new Error(msg);
    } catch (error) {
      setMessage({ severity: 'error', text: error.message || '删除失败' });
    } finally {
      setDeletingPointId('');
    }
  };

  const renderPointWorkspace = () => (
    <Grid container spacing={2.5}>
      <Grid item xs={12} xl={4}>
        <PageSection
          title="知识点列表"
          description="支持按学科、审核状态、知识点 ID 搜索；默认每页 10 条、可翻页。点击行即可查看详情。"
        >
          <Stack spacing={2}>
            <Grid container spacing={1.5}>
              <Grid item xs={12} sm={6} xl={12}>
                <FormControl fullWidth size="small">
                  <InputLabel>学科</InputLabel>
                  <Select
                    value={pointSubject}
                    label="学科"
                    onChange={(event) => {
                      setPointPage(0);
                      setPointSubject(event.target.value);
                    }}
                  >
                    <MenuItem value="">全部学科</MenuItem>
                    {subjects.map((item) => (
                      <MenuItem key={item} value={item}>{item}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Grid>
              <Grid item xs={12} sm={6} xl={12}>
                <FormControl fullWidth size="small">
                  <InputLabel>审核状态</InputLabel>
                  <Select
                    value={pointReviewStatus}
                    label="审核状态"
                    onChange={(event) => {
                      setPointPage(0);
                      setPointReviewStatus(event.target.value);
                    }}
                  >
                    <MenuItem value="">全部状态</MenuItem>
                    {reviewStatusOptions.map((item) => (
                      <MenuItem key={item} value={item}>{item}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Grid>
            </Grid>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} alignItems={{ sm: 'center' }}>
              <TextField
                size="small"
                fullWidth
                label="知识点 ID"
                placeholder="输入数字 ID 后点击搜索"
                value={pointIdInput}
                onChange={(e) => setPointIdInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    applyPointIdSearch();
                  }
                }}
              />
              <Stack direction="row" spacing={0.5} flexShrink={0}>
                <Button size="small" variant="outlined" onClick={applyPointIdSearch}>搜索</Button>
                <Button size="small" onClick={clearPointIdSearch}>清除</Button>
              </Stack>
            </Stack>
            <TableContainer component={Paper} sx={tableSx}>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>ID</TableCell>
                    <TableCell>名称</TableCell>
                    <TableCell>状态</TableCell>
                    <TableCell align="right" width={88}>操作</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {points.map((item) => {
                    const selected = String(item.id) === String(selectedPointId);
                    return (
                      <TableRow key={item.id} hover selected={selected} onClick={() => setSelectedPointId(String(item.id))} sx={{ cursor: 'pointer' }}>
                        <TableCell>{item.id}</TableCell>
                        <TableCell>
                          <Typography variant="subtitle2" sx={{ lineHeight: 1.35 }}>{item.canonical_name}</Typography>
                        </TableCell>
                        <TableCell>
                          <Chip size="small" label={item.review_status || 'draft'} color={statusColor(item.review_status)} variant="outlined" />
                        </TableCell>
                        <TableCell align="right" onClick={(e) => e.stopPropagation()}>
                          <Button
                            size="small"
                            color="error"
                            variant="outlined"
                            disabled={deletingPointId === String(item.id) || loading}
                            onClick={() => handleDeleteKnowledgePoint(item.id)}
                          >
                            删除
                          </Button>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                  {!loading && points.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={4} align="center">暂无知识点</TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </TableContainer>
            <Stack
              direction={{ xs: 'column', sm: 'row' }}
              spacing={1}
              alignItems={{ xs: 'stretch', sm: 'center' }}
              justifyContent="space-between"
              useFlexGap
            >
              <FormControl size="small" sx={{ minWidth: 120 }}>
                <InputLabel>每页条数</InputLabel>
                <Select
                  value={pointPageSize}
                  label="每页条数"
                  onChange={(event) => {
                    setPointPage(0);
                    setPointPageSize(Number(event.target.value));
                  }}
                >
                  {pointPageSizeOptions.map((n) => (
                    <MenuItem key={n} value={n}>{n}</MenuItem>
                  ))}
                </Select>
              </FormControl>
              <Typography variant="caption" color="text.secondary" sx={{ textAlign: { xs: 'left', sm: 'center' }, flex: 1 }}>
                共 {pointsTotal} 条
                {pointsTotal > 0 && pointListTotalPages > 0
                  ? ` · 第 ${pointPage + 1} / ${pointListTotalPages} 页`
                  : null}
              </Typography>
              <Stack direction="row" spacing={0.5} justifyContent="flex-end">
                <Button
                  size="small"
                  variant="outlined"
                  disabled={!pointListCanPrev || loading}
                  onClick={() => setPointPage((p) => Math.max(0, p - 1))}
                >
                  上一页
                </Button>
                <Button
                  size="small"
                  variant="outlined"
                  disabled={!pointListCanNext || loading}
                  onClick={() => setPointPage((p) => p + 1)}
                >
                  下一页
                </Button>
              </Stack>
            </Stack>
          </Stack>
        </PageSection>
      </Grid>
      <Grid item xs={12} xl={8}>
        <PageSection
          title="知识点详情"
          description="这里直接承接第二阶段详情能力，并在第三阶段补上检索索引同步入口。"
          actions={(
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
              <Button
                size="small"
                variant="outlined"
                startIcon={<ManageSearchRoundedIcon />}
                disabled={!selectedPointId}
                onClick={() => {
                  window.location.href = `/knowledge-retrieval?knowledge_point_id=${selectedPointId}`;
                }}
              >
                去检索台
              </Button>
              <Button
                size="small"
                variant="contained"
                startIcon={syncingKey === `point:${selectedPointId}` ? <CircularProgress size={14} color="inherit" /> : <SyncRoundedIcon />}
                disabled={!selectedPointId || syncingKey === `point:${selectedPointId}`}
                onClick={() => handleSync('point', selectedPointId)}
              >
                {syncingKey === `point:${selectedPointId}` ? '同步中...' : '同步检索索引'}
              </Button>
            </Stack>
          )}
        >
          {detailLoading ? (
            <Box sx={{ py: 6, textAlign: 'center' }}><CircularProgress size={24} /></Box>
          ) : !pointDetail ? (
            <Typography variant="body2" color="text.secondary">请选择左侧知识点。</Typography>
          ) : (
            <Stack spacing={2}>
              <Paper sx={{ p: 2, borderRadius: 2.5, backgroundColor: '#fbfcff', boxShadow: 'none', border: '1px solid #eef0f3' }}>
                <Stack spacing={1.5}>
                  <Box>
                    <Typography variant="h6">{pointDetail.canonical_name}</Typography>
                    <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 1 }}>
                      <Chip size="small" label={pointDetail.subject || '未设学科'} color="primary" variant="outlined" />
                      <Chip size="small" label={pointDetail.grade_scope || '未设年级'} variant="outlined" />
                      <Chip size="small" label={pointDetail.knowledge_type || 'concept'} variant="outlined" />
                      <Chip size="small" label={pointDetail.review_status || 'draft'} color={statusColor(pointDetail.review_status)} variant="outlined" />
                    </Stack>
                  </Box>
                  <Grid container spacing={1.5}>
                    <Grid item xs={12} md={6}><InfoField label="标准摘要" value={pointDetail.canonical_summary} /></Grid>
                    <Grid item xs={12} md={6}><InfoField label="前置要求" value={pointDetail.prerequisite_summary} /></Grid>
                    <Grid item xs={12} md={6}><InfoField label="别名" value={renderJsonSummary(pointDetail.aliases_json)} /></Grid>
                    <Grid item xs={12} md={6}><InfoField label="常见混淆" value={renderJsonSummary(pointDetail.common_confusions_json)} /></Grid>
                  </Grid>
                  <Stack direction="row" spacing={1.5} flexWrap="wrap" useFlexGap>
                    <Chip label={`专题包 ${pointDetail.package_count ?? 0}`} size="small" variant="outlined" />
                    <Chip label={`内容块 ${pointDetail.block_count ?? 0}`} size="small" variant="outlined" />
                    <Chip label={`知识原子 ${pointDetail.atom_count ?? 0}`} size="small" variant="outlined" />
                    <Chip label={`题目桥接 ${pointDetail.question_link_count ?? 0}`} size="small" variant="outlined" />
                    <Chip label={`关系 ${pointDetail.relation_count ?? 0}`} size="small" variant="outlined" />
                  </Stack>
                </Stack>
              </Paper>

              <Grid container spacing={2}>
                <Grid item xs={12} lg={6}>
                  <PageSection title="关联专题包" description="展示该知识点在哪些专题包中出现。" sx={{ p: 2 }}>
                    <TableContainer component={Paper} sx={tableSx}>
                      <Table size="small">
                        <TableHead>
                          <TableRow>
                            <TableCell>专题包</TableCell>
                            <TableCell>关系</TableCell>
                            <TableCell align="right">权重</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {(pointDetail.package_links || []).slice(0, 8).map((item) => (
                            <TableRow key={item.id} hover>
                              <TableCell>{item.package_title}</TableCell>
                              <TableCell>{item.relation_type}</TableCell>
                              <TableCell align="right">{item.weight_score ?? '-'}</TableCell>
                            </TableRow>
                          ))}
                          {(!pointDetail.package_links || pointDetail.package_links.length === 0) && (
                            <TableRow><TableCell colSpan={3} align="center">暂无专题包关联</TableCell></TableRow>
                          )}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  </PageSection>
                </Grid>
                <Grid item xs={12} lg={6}>
                  <PageSection title="知识点关系" description="用于后续图谱扩召的出边基础。" sx={{ p: 2 }}>
                    <TableContainer component={Paper} sx={tableSx}>
                      <Table size="small">
                        <TableHead>
                          <TableRow>
                            <TableCell>目标知识点</TableCell>
                            <TableCell>关系</TableCell>
                            <TableCell align="right">强度</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {(pointDetail.outgoing_relations || []).slice(0, 8).map((item) => (
                            <TableRow key={item.id} hover>
                              <TableCell>{item.target_knowledge_point_name || `#${item.target_knowledge_point_id}`}</TableCell>
                              <TableCell>{item.relation_type}</TableCell>
                              <TableCell align="right">{item.strength_score ?? '-'}</TableCell>
                            </TableRow>
                          ))}
                          {(!pointDetail.outgoing_relations || pointDetail.outgoing_relations.length === 0) && (
                            <TableRow><TableCell colSpan={3} align="center">暂无知识点关系</TableCell></TableRow>
                          )}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  </PageSection>
                </Grid>
              </Grid>

              <PageSection title="知识块预览" description="保留页码、章节路径和富内容结构，便于做精准还原与检索证据核验。" sx={{ p: 2 }}>
                <Stack spacing={1.5}>
                  {(pointDetail.blocks || []).slice(0, 6).map((block) => (
                    <BlockPreviewCard key={block.id} block={block} />
                  ))}
                  {(!pointDetail.blocks || pointDetail.blocks.length === 0) && (
                    <Typography variant="body2" color="text.secondary">暂无知识块。</Typography>
                  )}
                </Stack>
              </PageSection>

              <PageSection title="题目桥接" description="第二阶段已完成的知识点到题目桥接，在这里继续作为检索证据补充展示。" sx={{ p: 2 }}>
                <TableContainer component={Paper} sx={tableSx}>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>题目 ID</TableCell>
                        <TableCell>题干摘要</TableCell>
                        <TableCell>关联类型</TableCell>
                        <TableCell align="right">相关度</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {(pointDetail.question_links || []).slice(0, 10).map((item) => (
                        <TableRow key={item.id} hover>
                          <TableCell>{item.question_item_id}</TableCell>
                          <TableCell>{item.question_stem || '-'}</TableCell>
                          <TableCell>{item.relation_type}</TableCell>
                          <TableCell align="right">{item.relevance_score ?? '-'}</TableCell>
                        </TableRow>
                      ))}
                      {(!pointDetail.question_links || pointDetail.question_links.length === 0) && (
                        <TableRow><TableCell colSpan={4} align="center">暂无题目桥接</TableCell></TableRow>
                      )}
                    </TableBody>
                  </Table>
                </TableContainer>
              </PageSection>
            </Stack>
          )}
        </PageSection>
      </Grid>
    </Grid>
  );

  const renderPackageWorkspace = () => (
    <Grid container spacing={2.5}>
      <Grid item xs={12} xl={4}>
        <PageSection title="专题包列表" description="这里承接知识专题包的查询与检索同步。">
          <Stack spacing={2}>
            <Grid container spacing={1.5}>
              <Grid item xs={12} sm={6} xl={12}>
                <FormControl fullWidth size="small">
                  <InputLabel>学科</InputLabel>
                  <Select value={packageSubject} label="学科" onChange={(event) => setPackageSubject(event.target.value)}>
                    <MenuItem value="">全部学科</MenuItem>
                    {subjects.map((item) => (
                      <MenuItem key={item} value={item}>{item}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Grid>
              <Grid item xs={12} sm={6} xl={12}>
                <FormControl fullWidth size="small">
                  <InputLabel>审核状态</InputLabel>
                  <Select value={packageReviewStatus} label="审核状态" onChange={(event) => setPackageReviewStatus(event.target.value)}>
                    <MenuItem value="">全部状态</MenuItem>
                    {reviewStatusOptions.map((item) => (
                      <MenuItem key={item} value={item}>{item}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Grid>
            </Grid>
            <TableContainer component={Paper} sx={{ ...tableSx, maxWidth: '100%', overflowX: 'auto' }}>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell sx={{ minWidth: 56 }}>ID</TableCell>
                    <TableCell sx={{ minWidth: 160 }}>标题</TableCell>
                    <TableCell sx={{ minWidth: 88 }}>解析状态</TableCell>
                    <TableCell sx={{ minWidth: 88 }}>审核状态</TableCell>
                    <TableCell sx={{ minWidth: 136, whiteSpace: 'nowrap' }}>摄入时间</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {packages.map((item) => {
                    const selected = String(item.id) === String(selectedPackageId);
                    return (
                      <TableRow key={item.id} hover selected={selected} onClick={() => setSelectedPackageId(String(item.id))} sx={{ cursor: 'pointer' }}>
                        <TableCell>{item.id}</TableCell>
                        <TableCell>
                          <Typography variant="subtitle2">{item.package_title}</Typography>
                          <Typography variant="caption">{item.subject || '-'} · {item.grade || '-'}</Typography>
                        </TableCell>
                        <TableCell>
                          <Chip size="small" label={item.parse_status || 'pending'} color={statusColor(item.parse_status)} variant="outlined" />
                        </TableCell>
                        <TableCell>
                          <Chip size="small" label={item.review_status || 'draft'} color={statusColor(item.review_status)} variant="outlined" />
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2" component="span" sx={{ fontFamily: 'ui-monospace, Consolas, monospace' }}>
                            {formatIngestedAt(item.created_at)}
                          </Typography>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                  {!loading && packages.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={5} align="center">暂无专题包</TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </TableContainer>
          </Stack>
        </PageSection>
      </Grid>
      <Grid item xs={12} xl={8}>
        <PageSection
          title="专题包"
          description="第三阶段对专题包补齐检索投影与检索入口后，这里可以直接看到包级证据基础。下方标签切换不同视图。"
          actions={(
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
              <Button
                size="small"
                variant="outlined"
                startIcon={<ManageSearchRoundedIcon />}
                disabled={!selectedPackageId}
                onClick={() => {
                  window.location.href = `/knowledge-retrieval?package_id=${selectedPackageId}`;
                }}
              >
                去检索台
              </Button>
              <Button
                size="small"
                variant="contained"
                startIcon={syncingKey === `package:${selectedPackageId}` ? <CircularProgress size={14} color="inherit" /> : <SyncRoundedIcon />}
                disabled={!selectedPackageId || syncingKey === `package:${selectedPackageId}`}
                onClick={() => handleSync('package', selectedPackageId)}
              >
                {syncingKey === `package:${selectedPackageId}` ? '同步中...' : '同步检索索引'}
              </Button>
            </Stack>
          )}
        >
          {detailLoading ? (
            <Box sx={{ py: 6, textAlign: 'center' }}><CircularProgress size={24} /></Box>
          ) : !packageDetail ? (
            <Typography variant="body2" color="text.secondary">请选择左侧专题包。</Typography>
          ) : (
            <>
              <Tabs
                value={packageDetailTab}
                onChange={(_, v) => setPackageDetailTab(v)}
                variant="scrollable"
                scrollButtons="auto"
                allowScrollButtonsMobile
                sx={{ borderBottom: 1, borderColor: 'divider' }}
              >
                <Tab label="专题包详情" />
                <Tab label="覆盖知识点" />
                <Tab label="相关题目桥接" />
                <Tab label="专题包知识块预览" />
              </Tabs>

              <Box sx={{ pt: 2 }}>
                {packageDetailTab === 0 && (
              <Paper sx={{ p: 2, borderRadius: 2.5, backgroundColor: '#fbfcff', boxShadow: 'none', border: '1px solid #eef0f3' }}>
                <Stack spacing={1.5}>
                  <Box>
                    <Typography variant="h6">{packageDetail.package_title}</Typography>
                    <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 1 }}>
                      <Chip size="small" label={packageDetail.subject || '未设学科'} color="primary" variant="outlined" />
                      <Chip size="small" label={packageDetail.grade || '未设年级'} variant="outlined" />
                      <Chip size="small" label={packageDetail.package_type || 'topic'} variant="outlined" />
                      <Chip size="small" label={packageDetail.review_status || 'draft'} color={statusColor(packageDetail.review_status)} variant="outlined" />
                      <Chip size="small" label={packageDetail.parse_status || 'pending'} color={statusColor(packageDetail.parse_status)} variant="outlined" />
                    </Stack>
                  </Box>
                  <Grid container spacing={1.5}>
                    <Grid item xs={12} md={6}><InfoField label="专题摘要" value={packageDetail.summary_text} /></Grid>
                    <Grid item xs={12} md={6}><InfoField label="大纲结构" value={renderJsonSummary(packageDetail.outline_json)} /></Grid>
                  </Grid>
                  <Stack direction="row" spacing={1.5} flexWrap="wrap" useFlexGap>
                    <Chip label={`知识点 ${packageDetail.point_count ?? 0}`} size="small" variant="outlined" />
                    <Chip label={`知识块 ${packageDetail.block_count ?? 0}`} size="small" variant="outlined" />
                    <Chip
                      label={`材料题 ${packageDetail.material_question_count ?? 0}`}
                      size="small"
                      variant="outlined"
                    />
                    <Chip
                      label={`可分析桥接 ${packageDetail.bridged_question_count ?? 0}/${packageDetail.material_question_count ?? 0}`}
                      size="small"
                      color={
                        (packageDetail.material_question_count ?? 0) > 0
                        && (packageDetail.bridged_question_count ?? 0) >= (packageDetail.material_question_count ?? 0)
                          ? 'success'
                          : 'warning'
                      }
                      variant="outlined"
                    />
                    {(packageDetail.orphan_in_material_count ?? 0) > 0 && (
                      <Chip
                        label={`缺口 ${packageDetail.orphan_in_material_count}`}
                        size="small"
                        color="warning"
                        variant="outlined"
                      />
                    )}
                    <Chip label={`相关题目 ${packageDetail.related_question_count ?? 0}`} size="small" variant="outlined" />
                    <Chip label={`来源文档 ${packageDetail.source_document_id ?? '-'}`} size="small" variant="outlined" />
                  </Stack>
                  {(packageDetail.orphan_in_material_count ?? 0) > 0 && (
                    <Alert severity="warning" sx={{ mt: 0.5 }}>
                      本专题材料卷中有 {packageDetail.orphan_in_material_count} 道题目尚未挂入本包知识点（KnowledgeQuestionLink 缺失或链向非包内点）。
                      建议「重跑专题摄入」或切换到「相关题目桥接」标签，使用「一键补链」。
                      {' '}
                      缺口题目 ID：
                      {(packageDetail.orphan_question_ids || []).slice(0, 20).join('，')}
                      {(packageDetail.orphan_question_ids || []).length > 20 ? '…' : ''}
                    </Alert>
                  )}
                </Stack>
              </Paper>
                )}

                {packageDetailTab === 1 && (
                  <Stack spacing={1.5}>
                    <Typography variant="body2" color="text.secondary">
                      展示当前专题包关联的全部知识点（与包级 KnowledgePackagePoint 一致）；知识块列由主块与块锚点 llm_knowledge_points 汇总。
                    </Typography>
                    <TableContainer
                      component={Paper}
                      sx={{ ...tableSx, maxHeight: 480, overflow: 'auto' }}
                    >
                      <Table size="small" stickyHeader>
                        <TableHead>
                          <TableRow>
                            <TableCell align="right" sx={{ minWidth: 48, width: 48 }}>序号</TableCell>
                            <TableCell sx={{ minWidth: 72 }}>包 ID</TableCell>
                            <TableCell align="right" sx={{ minWidth: 92 }}>知识点 ID</TableCell>
                            <TableCell sx={{ minWidth: 120 }}>知识块</TableCell>
                            <TableCell>知识点</TableCell>
                            <TableCell sx={{ minWidth: 88 }}>关系</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {(packageDetail.point_links || []).map((item, idx) => (
                            <TableRow key={item.id} hover>
                              <TableCell align="right">{idx + 1}</TableCell>
                              <TableCell>{item.package_id ?? packageDetail.id ?? '—'}</TableCell>
                              <TableCell align="right">
                                <Typography component="span" variant="body2" sx={{ fontFamily: 'ui-monospace, monospace' }}>
                                  {item.knowledge_point_id ?? '—'}
                                </Typography>
                              </TableCell>
                              <TableCell>
                                {formatBlockOrders(
                                  blockOrdersForKnowledgePoint(item.knowledge_point_id, packageDetail.blocks),
                                )}
                              </TableCell>
                              <TableCell>{item.knowledge_point_name}</TableCell>
                              <TableCell>{item.relation_type}</TableCell>
                            </TableRow>
                          ))}
                          {(!packageDetail.point_links || packageDetail.point_links.length === 0) && (
                            <TableRow><TableCell colSpan={6} align="center">暂无覆盖知识点</TableCell></TableRow>
                          )}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  </Stack>
                )}

                {packageDetailTab === 2 && (
                  <Stack spacing={1.5}>
                    <Stack
                      direction={{ xs: 'column', md: 'row' }}
                      spacing={1.5}
                      justifyContent="space-between"
                      alignItems={{ md: 'flex-start' }}
                    >
                      <Typography variant="body2" color="text.secondary" sx={{ flex: 1 }}>
                        {`本包内知识点与题目在库中的显式关联（KnowledgeQuestionLink）：桥接即「本题 ↔ 知识点」的显式链。桥接数=本题命中的不同知识点个数（经本包覆盖）。`
                        + ` 当前列表共 ${(packageDetail.related_questions || []).length} 道题；材料卷共 ${packageDetail.material_question_count ?? 0} 道，桥接覆盖 ${packageDetail.bridged_question_count ?? 0} 道，缺口 ${packageDetail.orphan_in_material_count ?? 0} 道。`
                        + ' 点击表格行可查看桥接到哪些知识点，以及按题 LLM 的原始返回（若本包 outline_json 中有 question_bridge_llm_debug）。'}
                      </Typography>
                      <Button
                        size="small"
                        variant="outlined"
                        disabled={!selectedPackageId || syncingKey === `backfill:${selectedPackageId}`}
                        onClick={() => handleBackfillBridge(selectedPackageId)}
                        startIcon={syncingKey === `backfill:${selectedPackageId}` ? <CircularProgress size={14} /> : <SyncRoundedIcon />}
                        sx={{ flexShrink: 0 }}
                      >
                        {syncingKey === `backfill:${selectedPackageId}` ? '补链中…' : '一键补链'}
                      </Button>
                    </Stack>
                    <TableContainer
                      component={Paper}
                      sx={{ ...tableSx, maxHeight: 480, overflow: 'auto' }}
                    >
                      <Table size="small" stickyHeader>
                        <TableHead>
                          <TableRow>
                            <TableCell align="right" sx={{ minWidth: 48, width: 48 }}>序号</TableCell>
                            <TableCell>题目 ID</TableCell>
                            <TableCell>题干摘要</TableCell>
                            <TableCell align="right">桥接数</TableCell>
                            <TableCell align="right" sx={{ minWidth: 140 }}>档位（强/中/弱）</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {(packageDetail.related_questions || []).map((item, idx) => {
                            const strong = item.strong_count ?? 0;
                            const medium = item.medium_count ?? 0;
                            const weak = item.weak_count ?? 0;
                            const fallbackOnly = strong === 0 && medium === 0 && weak > 0;
                            return (
                              <TableRow
                                key={item.question_item_id}
                                hover
                                selected={bridgeQuestionDialog?.question_item_id === item.question_item_id}
                                onClick={() => setBridgeQuestionDialog(item)}
                                sx={{ cursor: 'pointer' }}
                              >
                                <TableCell align="right">{idx + 1}</TableCell>
                                <TableCell>{item.question_item_id}</TableCell>
                                <TableCell>{item.question_stem || '-'}</TableCell>
                                <TableCell align="right">{item.bridge_count ?? 0}</TableCell>
                                <TableCell align="right">
                                  <Stack direction="row" spacing={0.5} justifyContent="flex-end">
                                    <Chip size="small" label={`强 ${strong}`} color={strong > 0 ? 'success' : 'default'} variant={strong > 0 ? 'filled' : 'outlined'} />
                                    <Chip size="small" label={`中 ${medium}`} color={medium > 0 ? 'primary' : 'default'} variant={medium > 0 ? 'filled' : 'outlined'} />
                                    <Chip size="small" label={`弱 ${weak}`} color={fallbackOnly ? 'warning' : 'default'} variant={weak > 0 ? 'filled' : 'outlined'} />
                                  </Stack>
                                </TableCell>
                              </TableRow>
                            );
                          })}
                          {(!packageDetail.related_questions || packageDetail.related_questions.length === 0) && (
                            <TableRow><TableCell colSpan={5} align="center">暂无相关题目</TableCell></TableRow>
                          )}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  </Stack>
                )}

                {packageDetailTab === 3 && (
                  <Stack spacing={1.5}>
                    <Typography variant="body2" color="text.secondary">
                      这些块会参与第三阶段的检索投影与召回。
                    </Typography>
                    {(packageDetail.blocks || []).slice(0, 6).map((block) => (
                      <BlockPreviewCard key={block.id} block={block} />
                    ))}
                    {(!packageDetail.blocks || packageDetail.blocks.length === 0) && (
                      <Typography variant="body2" color="text.secondary">暂无知识块。</Typography>
                    )}
                  </Stack>
                )}
              </Box>

              <Dialog
                open={Boolean(bridgeQuestionDialog)}
                onClose={() => setBridgeQuestionDialog(null)}
                maxWidth="md"
                fullWidth
              >
                {bridgeQuestionDialog && (
                  <>
                    <DialogTitle>
                      题目桥接详情 · ID {bridgeQuestionDialog.question_item_id}
                    </DialogTitle>
                    <DialogContent dividers>
                      <Stack spacing={2}>
                        <Box>
                          <Typography variant="subtitle2" color="text.secondary" gutterBottom>题干摘要</Typography>
                          <QuestionRichRenderer fallbackText={bridgeQuestionDialog.question_stem || '—'} />
                        </Box>
                        <Divider />
                        <Box>
                          <Typography variant="subtitle2" gutterBottom>
                            桥接到的知识点（KnowledgeQuestionLink，经本包覆盖）
                          </Typography>
                          {(bridgeQuestionDialog.matched_points || []).length > 0 ? (
                            <Table size="small" sx={{ mt: 1 }}>
                              <TableHead>
                                <TableRow>
                                  <TableCell>知识点 ID</TableCell>
                                  <TableCell>名称</TableCell>
                                  <TableCell>题侧关系</TableCell>
                                  <TableCell align="right">相关度</TableCell>
                                  <TableCell align="right">置信度</TableCell>
                                </TableRow>
                              </TableHead>
                              <TableBody>
                                {(bridgeQuestionDialog.matched_points || []).map((mp) => (
                                  <TableRow key={`${mp.knowledge_point_id}-${mp.question_relation_type}`}>
                                    <TableCell>{mp.knowledge_point_id}</TableCell>
                                    <TableCell>{mp.knowledge_point_name}</TableCell>
                                    <TableCell>{mp.question_relation_type}</TableCell>
                                    <TableCell align="right">{mp.relevance_score ?? '—'}</TableCell>
                                    <TableCell align="right">{mp.confidence ?? '—'}</TableCell>
                                  </TableRow>
                                ))}
                              </TableBody>
                            </Table>
                          ) : (
                            <Typography variant="body2" color="text.secondary">暂无匹配知识点条目。</Typography>
                          )}
                        </Box>
                        <Divider />
                        <Box>
                          <Typography variant="subtitle2" gutterBottom>
                            按题 LLM 原始返回（如有）
                          </Typography>
                          {(() => {
                            const llm = findQuestionBridgeLlmEntry(
                              packageDetail.outline_json,
                              bridgeQuestionDialog.question_item_id,
                            );
                            if (!llm) {
                              return (
                                <Typography variant="body2" color="text.secondary">
                                  未找到该题的按题 LLM 审计记录。常见于：桥接排序未使用 llm / llm_then_overlap，或该包在开启审计前摄入，需重跑专题摄入。
                                </Typography>
                              );
                            }
                            return (
                              <Stack spacing={1.5}>
                                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                                  {llm.model_name && (
                                    <Chip size="small" variant="outlined" label={`模型 ${llm.model_name}`} />
                                  )}
                                  <Chip
                                    size="small"
                                    variant="outlined"
                                    label={llm.parse_ok ? 'JSON 解析成功' : 'JSON 解析失败'}
                                    color={llm.parse_ok ? 'success' : 'warning'}
                                  />
                                  {llm.skipped_reason && (
                                    <Chip size="small" variant="outlined" color="warning" label={`原因 ${llm.skipped_reason}`} />
                                  )}
                                </Stack>
                                {Array.isArray(llm.accepted_knowledge_point_ids) && llm.accepted_knowledge_point_ids.length > 0 && (
                                  <Box>
                                    <Typography variant="caption" color="text.secondary">模型采纳的知识点 ID</Typography>
                                    <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ mt: 0.5 }}>
                                      {llm.accepted_knowledge_point_ids.map((id) => (
                                        <Chip key={id} size="small" label={String(id)} />
                                      ))}
                                    </Stack>
                                  </Box>
                                )}
                                <Paper variant="outlined" sx={{ p: 1.5, maxHeight: 320, overflow: 'auto', bgcolor: 'grey.50' }}>
                                  <Typography component="pre" variant="caption" sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', m: 0, fontFamily: 'ui-monospace, monospace' }}>
                                    {llm.response_text || '（无 response_text）'}
                                  </Typography>
                                </Paper>
                              </Stack>
                            );
                          })()}
                        </Box>
                      </Stack>
                    </DialogContent>
                    <DialogActions>
                      <Button onClick={() => setBridgeQuestionDialog(null)}>关闭</Button>
                    </DialogActions>
                  </>
                )}
              </Dialog>
            </>
          )}
        </PageSection>
      </Grid>
    </Grid>
  );

  const renderIngestWorkspace = () => {
    const taskStatus = ingestTaskDetail?.status;
    const processedFiles = ingestTaskDetail?.processed_files || ingestTaskDetail?.result?.processed || [];

    const startIngestWebSocket = () => {
      if (!selectedIngestFiles.length || ingestRunning) return;
      if (ingestWsRef.current) {
        try {
          ingestWsRef.current.close();
        } catch (e) {
          /* ignore */
        }
        ingestWsRef.current = null;
      }
      setIngestRunning(true);
      setIngestTaskDetail(null);
      setIngestTaskId('');
      setLastRunDir('');
      setIngestLogs('[SYSTEM] 正在连接 WebSocket…\n');

      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
      const socket = new WebSocket(`${proto}://${window.location.host}/ws/run-knowledge-ingest`);
      ingestWsRef.current = socket;

      socket.onopen = () => {
        socket.send(JSON.stringify({
          files: selectedIngestFiles,
          force_reingest: forceReingest,
        }));
      };

      socket.onmessage = (event) => {
        const text = typeof event.data === 'string' ? event.data : String(event.data);
        setIngestLogs((prev) => prev + text + '\n');
        if (text.includes('本次运行目录：')) {
          const parts = text.split('本次运行目录：');
          if (parts[1]) {
            setLastRunDir(parts[1].trim());
          }
        }
      };

      socket.onerror = () => {
        setIngestLogs((prev) => prev + '[SYSTEM-ERROR] WebSocket 错误。\n');
        setIngestRunning(false);
        setMessage({ severity: 'error', text: '摄入 WebSocket 连接失败' });
      };

      socket.onclose = async () => {
        ingestWsRef.current = null;
        setIngestLogs((prev) => prev + '\n[SYSTEM] WebSocket 已关闭。\n');
        setIngestRunning(false);
        setRefreshTick((t) => t + 1);
        setMessage({ severity: 'info', text: '摄入连接已关闭，请查看下方运行日志与本地 _runs 目录。' });
      };
    };

    const startIngestBackground = async () => {
      if (!selectedIngestFiles.length || ingestRunning) return;
      setIngestRunning(true);
      setIngestTaskDetail(null);
      setIngestTaskId('');
      try {
        const response = await fetch('/api/knowledge-admin/ingest', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ files: selectedIngestFiles, force_reingest: forceReingest }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(data?.detail || '启动摄入失败');
        }
        setIngestTaskId(data.task_id || '');
        setMessage({ severity: 'success', text: `已启动后台摄入任务：${data.task_id}（日志写入 analyzer/_runs/_ingest_runs/）` });

        let attempts = 0;
        while (attempts < 120) {
          const latest = await loadIngestTask(data.task_id);
          if (!latest) break;
          setIngestTaskDetail(latest);
          if (latest.run_dir) {
            setLastRunDir(latest.run_dir);
          }
          if (['success', 'failed'].includes(latest.status)) break;
          await new Promise((resolve) => setTimeout(resolve, 1500));
          attempts += 1;
        }
      } catch (error) {
        setMessage({ severity: 'error', text: error.message || '启动摄入失败' });
      } finally {
        setIngestRunning(false);
      }
    };

    return (
      <Stack spacing={2.5}>
        <PageSection
          title="专题/知识点文档摄入"
          description="从 analyzer/knowledge_points 目录选择文档执行摄入。实时日志与「内容摄入」页类似；每次运行会在后台生成 _runs/_ingest_runs/<时间戳>/run.log、manifest.json 与 assets/（PDF 会尝试导出内嵌图）。"
        >
          <Grid container spacing={2}>
            <Grid item xs={12} md={7}>
              <Paper sx={{ p: 2, borderRadius: 3, border: '1px solid #eef0f3', boxShadow: 'none' }}>
                <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between" sx={{ mb: 1.5 }}>
                  <Box>
                    <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>可摄入文档</Typography>
                    <Typography variant="caption" color="text.secondary">
                      目录：<Box component="span" sx={{ fontFamily: 'monospace' }}>{ingestDir || '未获取'}</Box>
                    </Typography>
                  </Box>
                  <Button
                    variant="outlined"
                    size="small"
                    startIcon={<RefreshRoundedIcon />}
                    onClick={async () => {
                      try {
                        await loadIngestFiles();
                        setMessage({ severity: 'success', text: '已刷新文档列表' });
                      } catch (error) {
                        setMessage({ severity: 'error', text: error.message || '刷新失败' });
                      }
                    }}
                  >
                    刷新
                  </Button>
                </Stack>

                {!ingestFiles.length ? (
                  <Alert severity="warning">未发现可摄入文档（仅支持 PDF、DOCX、TXT）。或知识点功能开关未开启。</Alert>
                ) : (
                  <FormGroup sx={{ maxHeight: 260, overflowY: 'auto', pr: 1 }}>
                    {ingestFiles.map((name) => (
                      <FormControlLabel
                        key={name}
                        control={(
                          <Checkbox
                            checked={selectedIngestFiles.includes(name)}
                            onChange={() => {
                              setSelectedIngestFiles((prev) => (
                                prev.includes(name) ? prev.filter((item) => item !== name) : [...prev, name]
                              ));
                            }}
                          />
                        )}
                        label={<Typography variant="body2" sx={{ fontFamily: 'monospace' }}>{name}</Typography>}
                      />
                    ))}
                  </FormGroup>
                )}
              </Paper>
            </Grid>

            <Grid item xs={12} md={5}>
              <Paper sx={{ p: 2, borderRadius: 3, border: '1px solid #eef0f3', boxShadow: 'none', backgroundColor: '#fafbfc' }}>
                <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>执行摄入</Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
                  已选中：{selectedIngestFiles.length} 个
                </Typography>

                <FormControlLabel
                  sx={{ mb: 1 }}
                  control={(
                    <Checkbox
                      checked={forceReingest}
                      onChange={(event) => setForceReingest(event.target.checked)}
                    />
                  )}
                  label={<Typography variant="body2">强制重摄入（会先清理该文档已有解析结果）</Typography>}
                />

                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} alignItems="stretch">
                  <Button
                    variant="contained"
                    startIcon={<PlayArrowRoundedIcon />}
                    disabled={!selectedIngestFiles.length || ingestRunning}
                    onClick={startIngestWebSocket}
                  >
                    {ingestRunning ? '摄入中…' : '开始摄入（实时日志）'}
                  </Button>
                  <Button
                    variant="outlined"
                    disabled={!selectedIngestFiles.length || ingestRunning}
                    onClick={startIngestBackground}
                  >
                    仅后台任务
                  </Button>
                </Stack>
                {ingestTaskId && (
                  <Button
                    variant="text"
                    size="small"
                    sx={{ mt: 1 }}
                    onClick={async () => {
                      try {
                        await loadIngestTask(ingestTaskId);
                        setMessage({ severity: 'info', text: '已刷新任务状态' });
                      } catch (error) {
                        setMessage({ severity: 'error', text: error.message || '刷新任务失败' });
                      }
                    }}
                  >
                    刷新后台任务状态
                  </Button>
                )}

                {ingestTaskDetail && (
                  <Box sx={{ mt: 2 }}>
                    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap sx={{ mb: 1 }}>
                      <Chip label={`状态：${taskStatus || '-'}`} color={statusColor(taskStatus)} size="small" />
                      {ingestTaskDetail?.started_at && <Chip label={`开始：${formatDate(ingestTaskDetail.started_at)}`} size="small" />}
                      {ingestTaskDetail?.ended_at && <Chip label={`结束：${formatDate(ingestTaskDetail.ended_at)}`} size="small" />}
                    </Stack>
                    {ingestTaskDetail?.run_dir && (
                      <Typography variant="caption" sx={{ display: 'block', fontFamily: 'monospace', wordBreak: 'break-all', mb: 1 }}>
                        运行目录：{ingestTaskDetail.run_dir}
                      </Typography>
                    )}
                    {ingestTaskDetail?.error && (
                      <Alert severity="error">任务失败：{ingestTaskDetail.error}</Alert>
                    )}
                    {processedFiles?.length ? (
                      <Alert severity="success" sx={{ mt: 1 }}>
                        已处理：
                        {(processedFiles || []).map((p) => (p && typeof p === 'object' && p.file ? p.file : String(p))).join('、')}
                      </Alert>
                    ) : null}
                  </Box>
                )}
              </Paper>
            </Grid>

            <Grid item xs={12}>
              <PageSection title="运行日志" description="与「内容摄入」页一致的控制台风格；关闭连接后会自动刷新概览。">
                {lastRunDir ? (
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1, fontFamily: 'monospace', wordBreak: 'break-all' }}>
                    本次运行目录（含 run.log、manifest.json、assets/）：{lastRunDir}
                  </Typography>
                ) : null}
                <Box
                  ref={ingestLogRef}
                  component="pre"
                  sx={{
                    ...terminalSx,
                    mt: 0,
                    minHeight: 360,
                    maxHeight: 640,
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                  }}
                >
                  {ingestLogs}
                </Box>
              </PageSection>
            </Grid>
          </Grid>
        </PageSection>
      </Stack>
    );
  };

  return (
    <AdminShell
      pageKey="knowledge-points"
      title="知识点管理"
      subtitle="在现有 8001 测试后台内直接查看知识点、专题包、桥接关系，并触发第三阶段检索索引同步。"
      breadcrumbs="统一测试控制台 / 知识点管理"
      actions={[
        <Button key="refresh" variant="outlined" startIcon={<RefreshRoundedIcon />} onClick={() => setRefreshTick((prev) => prev + 1)} disabled={loading || detailLoading || Boolean(syncingKey)}>
          刷新
        </Button>,
        <Button key="search" variant="contained" startIcon={<ManageSearchRoundedIcon />} onClick={() => { window.location.href = '/knowledge-retrieval'; }}>
          打开检索台
        </Button>,
      ]}
    >
      <Stack spacing={2.5}>
        {message && (
          <Alert severity={message.severity} onClose={() => setMessage(null)}>
            {message.text}
          </Alert>
        )}

        <Grid container spacing={2}>
          {[
            { label: '知识点', value: overview.counts?.knowledge_points ?? 0, caption: `审核态：${Object.entries(pointStatusBreakdown).map(([key, count]) => `${key}:${count}`).join(' / ') || '暂无'}` },
            { label: '专题包', value: overview.counts?.knowledge_packages ?? 0, caption: `解析态：${Object.entries(parseStatusBreakdown).map(([key, count]) => `${key}:${count}`).join(' / ') || '暂无'}` },
            { label: '知识块', value: overview.counts?.knowledge_blocks ?? 0, caption: `知识原子 ${overview.counts?.knowledge_atoms ?? 0}` },
            { label: '题目桥接', value: overview.counts?.knowledge_question_links ?? 0, caption: `知识关系 ${overview.counts?.knowledge_point_relations ?? 0}` },
            { label: '检索文档', value: overview.counts?.retrieval_documents ?? 0, caption: `向量点 ${overview.counts?.embedding_points ?? 0}` },
            { label: '检索后端', value: overview.backends?.vector_backend || '未配置', caption: `文本 ${overview.backends?.text_backend || '未配置'}` },
          ].map((item) => (
            <Grid item xs={12} sm={6} lg={4} key={item.label}>
              <Paper sx={cardSx}>
                <Typography variant="caption">{item.label}</Typography>
                <Typography variant="h4" sx={{ mt: 1 }}>{item.value}</Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>{item.caption}</Typography>
              </Paper>
            </Grid>
          ))}
        </Grid>

        {overview.flags && (
          <Alert severity={overview.flags.knowledge_rag_enabled ? 'info' : 'warning'}>
            功能开关状态：知识点 {overview.flags.knowledge_point_enabled ? '开启' : '关闭'} / RAG {overview.flags.knowledge_rag_enabled ? '开启' : '关闭'} / 图谱 {overview.flags.knowledge_graph_enabled ? '开启' : '关闭'} / 衍生层 {overview.flags.knowledge_derivative_enabled ? '开启' : '关闭'}。
            {!overview.flags.knowledge_rag_enabled ? ' 当前仍可浏览知识点数据，但检索同步与搜索会返回开关关闭提示。' : ''}
          </Alert>
        )}

        <Paper sx={{ borderRadius: 3, border: '1px solid #eef0f3', boxShadow: 'none' }}>
          <Tabs value={activeTab} onChange={(_, value) => setActiveTab(value)} sx={{ px: 2, pt: 1 }}>
            <Tab label="知识点" value="points" />
            <Tab label="专题包" value="packages" />
            <Tab label="文档摄入" value="ingest" />
            <Tab label="图谱" value="graph" />
            <Tab label="衍生层" value="derivative" />
          </Tabs>
          <Divider />
          <Box sx={{ p: { xs: 2, md: 2.5 } }}>
            {activeTab === 'points' && renderPointWorkspace()}
            {activeTab === 'packages' && renderPackageWorkspace()}
            {activeTab === 'ingest' && renderIngestWorkspace()}
            {activeTab === 'graph' && (
              <KnowledgeGraphWorkspace
                flags={overview.flags}
                onMessage={setMessage}
                onCountsRefresh={() => setRefreshTick((prev) => prev + 1)}
              />
            )}
            {activeTab === 'derivative' && (
              <KnowledgeDerivativeWorkspace
                flags={overview.flags}
                onMessage={setMessage}
                onCountsRefresh={() => setRefreshTick((prev) => prev + 1)}
              />
            )}
          </Box>
        </Paper>
      </Stack>
    </AdminShell>
  );
}

export default KnowledgePointManagement;
