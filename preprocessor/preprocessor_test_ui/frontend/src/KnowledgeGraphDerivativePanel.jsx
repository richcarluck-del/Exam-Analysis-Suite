import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  FormControl,
  Grid,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import PlayArrowRoundedIcon from '@mui/icons-material/PlayArrowRounded';
import SyncRoundedIcon from '@mui/icons-material/SyncRounded';
import CheckCircleOutlineRoundedIcon from '@mui/icons-material/CheckCircleOutlineRounded';
import HighlightOffRoundedIcon from '@mui/icons-material/HighlightOffRounded';
import ReplayRoundedIcon from '@mui/icons-material/ReplayRounded';
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded';

const cardSx = {
  p: 2,
  borderRadius: 3,
  border: '1px solid #eef0f3',
  backgroundColor: '#fafbfc',
  minHeight: 96,
};
const tableSx = {
  borderRadius: 2.5,
  boxShadow: 'none',
  border: '1px solid #eef0f3',
};

function formatApiDetail(data, fallback) {
  const d = data?.detail;
  if (typeof d === 'string') return d;
  if (d && typeof d === 'object') {
    const msg = typeof d.message === 'string' ? d.message : JSON.stringify(d);
    if (d.run_id) {
      return `${msg}（run_id=${d.run_id}：请在下方「衍生层执行日志」刷新列表后选该次运行查看 run.log）`;
    }
    return msg;
  }
  if (d != null) return String(d);
  return fallback;
}

const DERIVATIVE_TYPES = [
  { value: 'concept_explainer', label: '通俗讲解' },
  { value: 'exam_cheatsheet', label: '考点速记卡' },
  { value: 'common_pitfalls', label: '易错/陷阱' },
  { value: 'comparison', label: '易混对比' },
  { value: 'memory_tip', label: '记忆口诀' },
];
const TARGET_AUDIENCES = [
  { value: 'student', label: '学生' },
  { value: 'teacher', label: '教师/命题' },
  { value: 'parent', label: '家长' },
];
const REVIEW_STATUS_OPTIONS = [
  { value: '', label: '全部状态' },
  { value: 'draft', label: 'draft' },
  { value: 'approved', label: 'approved' },
  { value: 'rejected', label: 'rejected' },
];

function StatusChip({ status }) {
  const color =
    status === 'approved' ? 'success' : status === 'rejected' ? 'error' : 'default';
  return <Chip size="small" color={color} label={status || 'draft'} sx={{ textTransform: 'none' }} />;
}

function asFixed(value) {
  if (value === null || value === undefined) return '-';
  const n = Number(value);
  if (Number.isNaN(n)) return '-';
  return n.toFixed(2);
}

export function KnowledgeGraphWorkspace({ flags, onMessage, onCountsRefresh }) {
  const graphEnabled = !!flags?.knowledge_graph_enabled;
  const [summary, setSummary] = useState(null);
  const [loadingSummary, setLoadingSummary] = useState(false);
  const [busyKey, setBusyKey] = useState('');
  const [queryType, setQueryType] = useState('package');
  const [queryId, setQueryId] = useState('');
  const [edges, setEdges] = useState([]);

  const loadSummary = useCallback(async () => {
    setLoadingSummary(true);
    try {
      const response = await fetch('/api/knowledge-admin/graph/summary');
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data?.detail || '加载图谱摘要失败');
      }
      setSummary(data);
    } catch (error) {
      onMessage?.({ severity: 'error', text: error.message || '加载失败' });
    } finally {
      setLoadingSummary(false);
    }
  }, [onMessage]);

  useEffect(() => {
    loadSummary();
  }, [loadSummary]);

  const handleProjectAll = async () => {
    if (!graphEnabled) return;
    setBusyKey('all');
    try {
      const response = await fetch('/api/knowledge-admin/graph/projection/all', { method: 'POST' });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data?.detail || '全量投影失败');
      onMessage?.({
        severity: 'success',
        text: `全量投影完成：package_count=${data.package_count} inserted=${data.inserted} deleted=${data.deleted}`,
      });
      await loadSummary();
      onCountsRefresh?.();
    } catch (error) {
      onMessage?.({ severity: 'error', text: error.message || '投影失败' });
    } finally {
      setBusyKey('');
    }
  };

  const handleProjectScope = async () => {
    if (!graphEnabled) return;
    if (!queryId) {
      onMessage?.({ severity: 'warning', text: '请输入要投影的 ID' });
      return;
    }
    const path =
      queryType === 'package'
        ? `/api/knowledge-admin/graph/projection/package/${queryId}`
        : `/api/knowledge-admin/graph/projection/knowledge-point/${queryId}`;
    setBusyKey('scope');
    try {
      const response = await fetch(path, { method: 'POST' });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data?.detail || '投影失败');
      onMessage?.({
        severity: 'success',
        text: `投影完成：inserted=${data.inserted} deleted=${data.deleted}`,
      });
      await loadSummary();
      onCountsRefresh?.();
      await handleLoadEdges();
    } catch (error) {
      onMessage?.({ severity: 'error', text: error.message || '投影失败' });
    } finally {
      setBusyKey('');
    }
  };

  const handleLoadEdges = async () => {
    if (!queryId) {
      setEdges([]);
      return;
    }
    const params = new URLSearchParams();
    if (queryType === 'package') params.set('package_id', queryId);
    else params.set('knowledge_point_id', queryId);
    params.set('limit', '500');
    setBusyKey('edges');
    try {
      const response = await fetch(`/api/knowledge-admin/graph/edges?${params.toString()}`);
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data?.detail || '加载边列表失败');
      setEdges(Array.isArray(data.items) ? data.items : []);
    } catch (error) {
      onMessage?.({ severity: 'error', text: error.message || '加载失败' });
      setEdges([]);
    } finally {
      setBusyKey('');
    }
  };

  return (
    <Stack spacing={2.5}>
      {!graphEnabled && (
        <Alert severity="warning">
          图谱开关 <b>KNOWLEDGE_GRAPH_ENABLED=false</b>：可浏览已有边，但「立即投影」按钮不可用。开启方式：编辑项目根目录 <code>.env</code>，设置
          <code> KNOWLEDGE_GRAPH_ENABLED=true</code> 后重启 <code>preprocessor_test_ui</code>。之后摄入 DOCX 会自动投影；旧数据可在此页面点击「全量投影」一次性回填。
        </Alert>
      )}

      <Grid container spacing={2}>
        <Grid item xs={12} sm={6} lg={3}>
          <Paper sx={cardSx}>
            <Typography variant="caption">图谱边总数</Typography>
            <Typography variant="h4" sx={{ mt: 1 }}>
              {loadingSummary ? <CircularProgress size={20} /> : summary?.total ?? 0}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
              按业务关系投影到 entity_graph_edges。
            </Typography>
          </Paper>
        </Grid>
        <Grid item xs={12} sm={6} lg={9}>
          <Paper sx={{ ...cardSx, backgroundColor: '#fff' }}>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
              <Button
                variant="contained"
                startIcon={<SyncRoundedIcon />}
                onClick={handleProjectAll}
                disabled={!graphEnabled || Boolean(busyKey)}
              >
                全量投影（扫所有专题包）
              </Button>
              <Button variant="outlined" onClick={loadSummary} disabled={Boolean(busyKey)}>
                刷新摘要
              </Button>
            </Stack>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1.2 }}>
              图谱投影会依据
              <code> KnowledgeBlock / KnowledgeAtom / KnowledgePackagePoint / KnowledgePackageQuestion / KnowledgeQuestionLink / KnowledgePointRelation</code>
              把现有业务关联写入 <code>entity_graph_edges</code>，以便后续做图上 RAG、路径解释与跨实体推荐。写入 <code>source_origin=business_projection</code>，可与模型抽取的边共存。
            </Typography>
          </Paper>
        </Grid>
      </Grid>

      <Paper sx={{ p: 2, borderRadius: 3, border: '1px solid #eef0f3', boxShadow: 'none' }}>
        <Typography variant="subtitle1" sx={{ mb: 1 }}>按作用域投影 / 查看边</Typography>
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5} alignItems={{ md: 'center' }}>
          <FormControl size="small" sx={{ minWidth: 150 }}>
            <InputLabel>作用域</InputLabel>
            <Select value={queryType} label="作用域" onChange={(e) => setQueryType(e.target.value)}>
              <MenuItem value="package">专题包</MenuItem>
              <MenuItem value="knowledge_point">知识点</MenuItem>
            </Select>
          </FormControl>
          <TextField
            size="small"
            label="ID"
            value={queryId}
            onChange={(e) => setQueryId(e.target.value.replace(/[^0-9]/g, ''))}
            placeholder={queryType === 'package' ? 'KnowledgePackage.id' : 'KnowledgePoint.id'}
            sx={{ maxWidth: 240 }}
          />
          <Button
            variant="contained"
            startIcon={<PlayArrowRoundedIcon />}
            onClick={handleProjectScope}
            disabled={!graphEnabled || Boolean(busyKey)}
          >
            立即投影
          </Button>
          <Button variant="outlined" onClick={handleLoadEdges} disabled={Boolean(busyKey)}>
            加载边列表
          </Button>
        </Stack>

        <Divider sx={{ my: 2 }} />

        <Grid container spacing={2}>
          <Grid item xs={12} md={5}>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>边类型分布</Typography>
            <TableContainer component={Paper} sx={tableSx}>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>from</TableCell>
                    <TableCell>relation</TableCell>
                    <TableCell>to</TableCell>
                    <TableCell align="right">count</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {(summary?.groups || []).map((group) => (
                    <TableRow key={`${group.source_entity_type}-${group.relation_type}-${group.target_entity_type}`}>
                      <TableCell>{group.source_entity_type}</TableCell>
                      <TableCell><code>{group.relation_type}</code></TableCell>
                      <TableCell>{group.target_entity_type}</TableCell>
                      <TableCell align="right">{group.count}</TableCell>
                    </TableRow>
                  ))}
                  {(!summary || !summary.groups?.length) && (
                    <TableRow>
                      <TableCell colSpan={4} align="center">
                        <Typography variant="body2" color="text.secondary">
                          暂无投影数据。
                        </Typography>
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </TableContainer>
          </Grid>
          <Grid item xs={12} md={7}>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>
              边列表 {edges.length ? `（${edges.length} 条）` : ''}
            </Typography>
            <TableContainer component={Paper} sx={{ ...tableSx, maxHeight: 420 }}>
              <Table size="small" stickyHeader>
                <TableHead>
                  <TableRow>
                    <TableCell>id</TableCell>
                    <TableCell>source</TableCell>
                    <TableCell>relation</TableCell>
                    <TableCell>target</TableCell>
                    <TableCell align="right">weight</TableCell>
                    <TableCell align="right">conf</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {edges.map((edge) => (
                    <TableRow key={edge.id}>
                      <TableCell>{edge.id}</TableCell>
                      <TableCell>
                        {edge.source_entity_type}:{edge.source_entity_id}
                      </TableCell>
                      <TableCell>
                        <Tooltip title={edge.source_origin || ''} arrow>
                          <code>{edge.relation_type}</code>
                        </Tooltip>
                      </TableCell>
                      <TableCell>
                        {edge.target_entity_type}:{edge.target_entity_id}
                      </TableCell>
                      <TableCell align="right">{asFixed(edge.weight_score)}</TableCell>
                      <TableCell align="right">{asFixed(edge.confidence)}</TableCell>
                    </TableRow>
                  ))}
                  {!edges.length && (
                    <TableRow>
                      <TableCell colSpan={6} align="center">
                        <Typography variant="body2" color="text.secondary">
                          未加载。选择作用域、填写 ID 后点击「加载边列表」。
                        </Typography>
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </TableContainer>
          </Grid>
        </Grid>
      </Paper>
    </Stack>
  );
}

export function KnowledgeDerivativeWorkspace({ flags, onMessage, onCountsRefresh }) {
  const derivativeEnabled = !!flags?.knowledge_derivative_enabled;
  const ragEnabled = !!flags?.knowledge_rag_enabled;
  const [summary, setSummary] = useState(null);
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [busyKey, setBusyKey] = useState('');
  const [filter, setFilter] = useState({
    knowledge_point_id: '',
    package_id: '',
    review_status: '',
    derivative_type: '',
    target_audience: '',
  });
  const [genForm, setGenForm] = useState({
    scope: 'knowledge_point',
    scope_id: '',
    derivative_types: ['concept_explainer', 'exam_cheatsheet', 'common_pitfalls'],
    target_audiences: ['student'],
  });
  const [expanded, setExpanded] = useState(null);
  const [execLogText, setExecLogText] = useState('');
  const [lastRunMeta, setLastRunMeta] = useState(null);
  const [runHistory, setRunHistory] = useState([]);
  const [logLoading, setLogLoading] = useState(false);

  const fetchRunLogById = useCallback(async (runId) => {
    if (!runId) return;
    setLogLoading(true);
    try {
      const res = await fetch(`/api/knowledge-admin/derivatives/runs/${encodeURIComponent(runId)}`);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.detail || '加载日志失败');
      setExecLogText(data.content || '');
      setLastRunMeta({
        run_id: data.run_id,
        run_dir: data.run_dir,
        runs_root: data.runs_root,
        main_log: data.main_log,
      });
    } catch (e) {
      onMessage?.({ severity: 'error', text: e.message || '加载日志失败' });
    } finally {
      setLogLoading(false);
    }
  }, [onMessage]);

  const loadRunHistory = useCallback(async () => {
    try {
      const res = await fetch('/api/knowledge-admin/derivatives/runs?limit=25');
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return;
      setRunHistory(Array.isArray(data.items) ? data.items : []);
    } catch (_) {
      /* ignore */
    }
  }, []);

  const loadSummary = useCallback(async () => {
    try {
      const response = await fetch('/api/knowledge-admin/derivatives/summary');
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data?.detail || '加载衍生摘要失败');
      setSummary(data);
      await loadRunHistory();
    } catch (error) {
      onMessage?.({ severity: 'error', text: error.message || '加载失败' });
    }
  }, [onMessage, loadRunHistory]);

  const loadItems = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      Object.entries(filter).forEach(([k, v]) => {
        if (v !== '' && v !== null && v !== undefined) params.set(k, v);
      });
      params.set('limit', '100');
      const response = await fetch(`/api/knowledge-admin/derivatives?${params.toString()}`);
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data?.detail || '加载衍生列表失败');
      setItems(Array.isArray(data.items) ? data.items : []);
      setTotal(Number(data.total || 0));
    } catch (error) {
      onMessage?.({ severity: 'error', text: error.message || '加载失败' });
      setItems([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [filter, onMessage]);

  useEffect(() => {
    loadSummary();
  }, [loadSummary]);
  useEffect(() => {
    loadItems();
  }, [loadItems]);

  const toggleType = (value) => {
    setGenForm((prev) => ({
      ...prev,
      derivative_types: prev.derivative_types.includes(value)
        ? prev.derivative_types.filter((item) => item !== value)
        : [...prev.derivative_types, value],
    }));
  };
  const toggleAudience = (value) => {
    setGenForm((prev) => ({
      ...prev,
      target_audiences: prev.target_audiences.includes(value)
        ? prev.target_audiences.filter((item) => item !== value)
        : [...prev.target_audiences, value],
    }));
  };

  const handleGenerate = async () => {
    if (!derivativeEnabled) return;
    if (!genForm.scope_id) {
      onMessage?.({ severity: 'warning', text: '请填写作用域 ID（知识点或专题包）' });
      return;
    }
    if (!genForm.derivative_types.length || !genForm.target_audiences.length) {
      onMessage?.({ severity: 'warning', text: '至少选择一种衍生类型与一种受众' });
      return;
    }
    const scopeNum = Number(genForm.scope_id);
    if (!Number.isFinite(scopeNum) || scopeNum <= 0) {
      onMessage?.({ severity: 'warning', text: '请输入有效的知识点 ID 或专题包 ID（正整数）' });
      return;
    }
    const payload = {
      derivative_types: genForm.derivative_types,
      target_audiences: genForm.target_audiences,
    };
    if (genForm.scope === 'package') payload.package_id = scopeNum;
    else payload.knowledge_point_id = scopeNum;

    setBusyKey('gen');
    try {
      const response = await fetch('/api/knowledge-admin/derivatives/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(formatApiDetail(data, '生成衍生内容失败'));
      const okCount = Array.isArray(data.generated)
        ? data.generated.length
        : (typeof data.generated === 'number' ? data.generated : 0);
      onMessage?.({
        severity: data.status === 'ok' ? 'success' : 'warning',
        text: `生成完成：${data.status}，${okCount} 条成功${
          data.errors?.length ? `，${data.errors.length} 条失败` : ''
        }`,
      });
      if (data.run?.run_id) {
        setLastRunMeta(data.run);
        await fetchRunLogById(data.run.run_id);
      }
      await loadSummary();
      await loadItems();
      onCountsRefresh?.();
    } catch (error) {
      onMessage?.({ severity: 'error', text: error.message || '生成失败' });
    } finally {
      setBusyKey('');
    }
  };

  const handleReview = async (item, status) => {
    setBusyKey(`review-${item.id}`);
    try {
      const response = await fetch(`/api/knowledge-admin/derivatives/${item.id}/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ review_status: status }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data?.detail || '审核失败');
      onMessage?.({
        severity: 'success',
        text: `#${item.id} 状态已改为 ${status}${
          data.retrieval_sync?.status ? `（检索：${data.retrieval_sync.status}）` : ''
        }`,
      });
      await loadSummary();
      await loadItems();
      onCountsRefresh?.();
    } catch (error) {
      onMessage?.({ severity: 'error', text: error.message || '审核失败' });
    } finally {
      setBusyKey('');
    }
  };

  const handleRetry = async (item) => {
    if (!derivativeEnabled) return;
    setBusyKey(`retry-${item.id}`);
    try {
      const response = await fetch(`/api/knowledge-admin/derivatives/${item.id}/retry`, { method: 'POST' });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(formatApiDetail(data, '重试失败'));
      onMessage?.({
        severity: data.status === 'ok' ? 'success' : 'warning',
        text: `#${item.id} 重试完成：${data.status}`,
      });
      if (data.run?.run_id) {
        setLastRunMeta(data.run);
        await fetchRunLogById(data.run.run_id);
      }
      await loadRunHistory();
      await loadItems();
    } catch (error) {
      onMessage?.({ severity: 'error', text: error.message || '重试失败' });
    } finally {
      setBusyKey('');
    }
  };

  const handleDelete = async (item) => {
    if (!window.confirm(`确认删除衍生内容 #${item.id}？（会同时从检索库移除）`)) return;
    setBusyKey(`del-${item.id}`);
    try {
      const response = await fetch(`/api/knowledge-admin/derivatives/${item.id}`, { method: 'DELETE' });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data?.detail || '删除失败');
      onMessage?.({ severity: 'success', text: `已删除 #${item.id}` });
      await loadSummary();
      await loadItems();
      onCountsRefresh?.();
    } catch (error) {
      onMessage?.({ severity: 'error', text: error.message || '删除失败' });
    } finally {
      setBusyKey('');
    }
  };

  return (
    <Stack spacing={2.5}>
      {!derivativeEnabled && (
        <Alert severity="warning">
          衍生层开关 <b>KNOWLEDGE_DERIVATIVE_ENABLED=false</b>：已存在的衍生内容仍可浏览与审核，但
          <b>不能触发生成/重试</b>。开启方式：编辑项目根目录 <code>.env</code>，设置
          <code> KNOWLEDGE_DERIVATIVE_ENABLED=true</code> 后重启 <code>preprocessor_test_ui</code>。
          若还未配置 <code>analyzer.knowledge_derivative_generation</code> 的 LLM/提示词，系统会自动在首次调用时落库种子配置。
        </Alert>
      )}
      {!ragEnabled && (
        <Alert severity="info">
          当前 <b>KNOWLEDGE_RAG_ENABLED=false</b>：衍生内容即使审核通过也不会写入检索索引。把 <code>.env</code> 的
          <code> KNOWLEDGE_RAG_ENABLED=true</code> 后，approved 状态的衍生内容会自动进入 RAG 语料。
        </Alert>
      )}

      <Grid container spacing={2}>
        <Grid item xs={6} md={3}>
          <Paper sx={cardSx}>
            <Typography variant="caption">衍生内容总数</Typography>
            <Typography variant="h4" sx={{ mt: 1 }}>{summary?.total ?? 0}</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
              按类型/状态分组见下表。
            </Typography>
          </Paper>
        </Grid>
        <Grid item xs={12} md={9}>
          <Paper sx={{ ...cardSx, backgroundColor: '#fff' }}>
            <Typography variant="subtitle1" sx={{ mb: 1 }}>批量生成</Typography>
            <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5} alignItems={{ md: 'center' }}>
              <FormControl size="small" sx={{ minWidth: 150 }}>
                <InputLabel>作用域</InputLabel>
                <Select
                  value={genForm.scope}
                  label="作用域"
                  onChange={(e) => setGenForm((prev) => ({ ...prev, scope: e.target.value }))}
                >
                  <MenuItem value="knowledge_point">知识点</MenuItem>
                  <MenuItem value="package">专题包</MenuItem>
                </Select>
              </FormControl>
              <TextField
                size="small"
                label={genForm.scope === 'package' ? '专题包 ID' : '知识点 ID'}
                value={genForm.scope_id}
                onChange={(e) => setGenForm((prev) => ({ ...prev, scope_id: e.target.value.replace(/[^0-9]/g, '') }))}
                sx={{ maxWidth: 220 }}
              />
              <Button
                variant="contained"
                startIcon={<PlayArrowRoundedIcon />}
                onClick={handleGenerate}
                disabled={!derivativeEnabled || busyKey === 'gen'}
              >
                生成
              </Button>
            </Stack>
            <Box sx={{ mt: 1.5 }}>
              <Typography variant="caption" color="text.secondary">衍生类型：</Typography>
              <Stack direction="row" spacing={0.8} flexWrap="wrap" sx={{ mt: 0.5 }}>
                {DERIVATIVE_TYPES.map((item) => (
                  <Chip
                    key={item.value}
                    label={item.label}
                    size="small"
                    clickable
                    color={genForm.derivative_types.includes(item.value) ? 'primary' : 'default'}
                    variant={genForm.derivative_types.includes(item.value) ? 'filled' : 'outlined'}
                    onClick={() => toggleType(item.value)}
                  />
                ))}
              </Stack>
            </Box>
            <Box sx={{ mt: 1 }}>
              <Typography variant="caption" color="text.secondary">目标受众：</Typography>
              <Stack direction="row" spacing={0.8} flexWrap="wrap" sx={{ mt: 0.5 }}>
                {TARGET_AUDIENCES.map((item) => (
                  <Chip
                    key={item.value}
                    label={item.label}
                    size="small"
                    clickable
                    color={genForm.target_audiences.includes(item.value) ? 'primary' : 'default'}
                    variant={genForm.target_audiences.includes(item.value) ? 'filled' : 'outlined'}
                    onClick={() => toggleAudience(item.value)}
                  />
                ))}
              </Stack>
            </Box>
          </Paper>
        </Grid>
      </Grid>

      <Paper sx={{ p: 2, borderRadius: 3, border: '1px solid #eef0f3', boxShadow: 'none', backgroundColor: '#fff' }}>
        <Typography variant="subtitle1" sx={{ mb: 1 }}>衍生层执行日志</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          日志根目录（服务端绝对路径，每次生成会新建子目录并写 run.log + llm_*.json）：
        </Typography>
        <Typography variant="body2" sx={{ mb: 1, wordBreak: 'break-all', fontFamily: 'monospace' }}>
          {summary?.derivative_runs_root || '（加载摘要后显示）'}
        </Typography>
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ mb: 1 }} alignItems={{ sm: 'center' }}>
          <FormControl size="small" sx={{ minWidth: 280 }}>
            <InputLabel>历史运行</InputLabel>
            <Select
              label="历史运行"
              value={lastRunMeta?.run_id && runHistory.some((h) => h.run_id === lastRunMeta.run_id) ? lastRunMeta.run_id : ''}
              displayEmpty
              onChange={(e) => {
                const id = e.target.value;
                if (id) fetchRunLogById(id);
              }}
            >
              <MenuItem value="">
                <em>选择 run_id 查看主日志</em>
              </MenuItem>
              {runHistory.map((h) => (
                <MenuItem key={h.run_id} value={h.run_id}>{h.run_id}</MenuItem>
              ))}
            </Select>
          </FormControl>
          <Button size="small" variant="outlined" onClick={loadRunHistory} disabled={logLoading}>
            刷新列表
          </Button>
          {lastRunMeta?.main_log && (
            <Typography variant="caption" color="text.secondary" sx={{ wordBreak: 'break-all' }}>
              当前文件: {lastRunMeta.main_log}
            </Typography>
          )}
        </Stack>
        {logLoading ? (
          <CircularProgress size={22} sx={{ my: 1 }} />
        ) : (
          <TextField
            fullWidth
            multiline
            minRows={10}
            maxRows={24}
            value={execLogText}
            onChange={() => {}}
            InputProps={{ readOnly: true }}
            placeholder="生成或选择历史运行后，这里显示 run.log 内容；同目录下还有各组合的 llm_类型_受众.json（完整请求与响应）。"
            sx={{ '& textarea': { fontFamily: 'monospace', fontSize: 12 } }}
          />
        )}
      </Paper>

      <Paper sx={{ p: 2, borderRadius: 3, border: '1px solid #eef0f3', boxShadow: 'none' }}>
        <Typography variant="subtitle1" sx={{ mb: 1 }}>衍生内容列表</Typography>
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5} sx={{ mb: 1.5 }}>
          <FormControl size="small" sx={{ minWidth: 160 }}>
            <InputLabel>审核状态</InputLabel>
            <Select
              value={filter.review_status}
              label="审核状态"
              onChange={(e) => setFilter((prev) => ({ ...prev, review_status: e.target.value }))}
            >
              {REVIEW_STATUS_OPTIONS.map((item) => (
                <MenuItem key={item.value || 'all'} value={item.value}>{item.label}</MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl size="small" sx={{ minWidth: 160 }}>
            <InputLabel>衍生类型</InputLabel>
            <Select
              value={filter.derivative_type}
              label="衍生类型"
              onChange={(e) => setFilter((prev) => ({ ...prev, derivative_type: e.target.value }))}
            >
              <MenuItem value="">全部类型</MenuItem>
              {DERIVATIVE_TYPES.map((item) => (
                <MenuItem key={item.value} value={item.value}>{item.label}</MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl size="small" sx={{ minWidth: 140 }}>
            <InputLabel>受众</InputLabel>
            <Select
              value={filter.target_audience}
              label="受众"
              onChange={(e) => setFilter((prev) => ({ ...prev, target_audience: e.target.value }))}
            >
              <MenuItem value="">全部受众</MenuItem>
              {TARGET_AUDIENCES.map((item) => (
                <MenuItem key={item.value} value={item.value}>{item.label}</MenuItem>
              ))}
            </Select>
          </FormControl>
          <TextField
            size="small"
            label="知识点 ID"
            value={filter.knowledge_point_id}
            onChange={(e) => setFilter((prev) => ({
              ...prev,
              knowledge_point_id: e.target.value.replace(/[^0-9]/g, ''),
            }))}
            sx={{ maxWidth: 160 }}
          />
          <TextField
            size="small"
            label="专题包 ID"
            value={filter.package_id}
            onChange={(e) => setFilter((prev) => ({
              ...prev,
              package_id: e.target.value.replace(/[^0-9]/g, ''),
            }))}
            sx={{ maxWidth: 160 }}
          />
          <Button variant="outlined" onClick={loadItems} disabled={loading}>
            {loading ? <CircularProgress size={18} /> : '刷新'}
          </Button>
        </Stack>

        <TableContainer component={Paper} sx={{ ...tableSx, maxHeight: 540 }}>
          <Table size="small" stickyHeader>
            <TableHead>
              <TableRow>
                <TableCell>id</TableCell>
                <TableCell>kp</TableCell>
                <TableCell>type</TableCell>
                <TableCell>audience</TableCell>
                <TableCell>title</TableCell>
                <TableCell align="right">ground</TableCell>
                <TableCell align="right">cover</TableCell>
                <TableCell>状态</TableCell>
                <TableCell align="right">操作</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {items.map((item) => (
                <React.Fragment key={item.id}>
                  <TableRow hover>
                    <TableCell>{item.id}</TableCell>
                    <TableCell>{item.knowledge_point_id}</TableCell>
                    <TableCell><code>{item.derivative_type}</code></TableCell>
                    <TableCell>{item.target_audience}</TableCell>
                    <TableCell
                      sx={{ maxWidth: 260, cursor: 'pointer' }}
                      onClick={() => setExpanded((prev) => (prev === item.id ? null : item.id))}
                    >
                      <Typography variant="body2" noWrap title="点击展开/收起">
                        {item.title || '(无标题)'}
                      </Typography>
                    </TableCell>
                    <TableCell align="right">{asFixed(item.quality?.groundedness)}</TableCell>
                    <TableCell align="right">{asFixed(item.quality?.coverage)}</TableCell>
                    <TableCell><StatusChip status={item.review_status} /></TableCell>
                    <TableCell align="right">
                      <Stack direction="row" spacing={0.5} justifyContent="flex-end">
                        <Tooltip title="批准并入检索">
                          <span>
                            <Button
                              size="small"
                              color="success"
                              disabled={busyKey === `review-${item.id}` || item.review_status === 'approved'}
                              onClick={() => handleReview(item, 'approved')}
                              startIcon={<CheckCircleOutlineRoundedIcon />}
                            >
                              approve
                            </Button>
                          </span>
                        </Tooltip>
                        <Tooltip title="驳回">
                          <span>
                            <Button
                              size="small"
                              color="warning"
                              disabled={busyKey === `review-${item.id}` || item.review_status === 'rejected'}
                              onClick={() => handleReview(item, 'rejected')}
                              startIcon={<HighlightOffRoundedIcon />}
                            >
                              reject
                            </Button>
                          </span>
                        </Tooltip>
                        <Tooltip title="重新生成">
                          <span>
                            <Button
                              size="small"
                              disabled={!derivativeEnabled || busyKey === `retry-${item.id}`}
                              onClick={() => handleRetry(item)}
                              startIcon={<ReplayRoundedIcon />}
                            >
                              retry
                            </Button>
                          </span>
                        </Tooltip>
                        <Tooltip title="删除">
                          <span>
                            <Button
                              size="small"
                              color="error"
                              disabled={busyKey === `del-${item.id}`}
                              onClick={() => handleDelete(item)}
                              startIcon={<DeleteOutlineRoundedIcon />}
                            >
                              del
                            </Button>
                          </span>
                        </Tooltip>
                      </Stack>
                    </TableCell>
                  </TableRow>
                  {expanded === item.id && (
                    <TableRow>
                      <TableCell colSpan={9} sx={{ backgroundColor: '#fafbfc' }}>
                        <Stack spacing={0.8} sx={{ p: 1 }}>
                          <Typography variant="subtitle2">{item.title || '(无标题)'}</Typography>
                          {item.summary && (
                            <Typography variant="body2">摘要：{item.summary}</Typography>
                          )}
                          {Array.isArray(item.bullets) && item.bullets.length > 0 && (
                            <Box component="ul" sx={{ m: 0, pl: 3 }}>
                              {item.bullets.map((bullet, idx) => (
                                <li key={idx}><Typography variant="body2">{bullet}</Typography></li>
                              ))}
                            </Box>
                          )}
                          {item.body && (
                            <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
                              {item.body}
                            </Typography>
                          )}
                          {item.notes && (
                            <Typography variant="caption" color="text.secondary">
                              备注：{item.notes}
                            </Typography>
                          )}
                        </Stack>
                      </TableCell>
                    </TableRow>
                  )}
                </React.Fragment>
              ))}
              {!items.length && (
                <TableRow>
                  <TableCell colSpan={9} align="center">
                    <Typography variant="body2" color="text.secondary" sx={{ py: 2 }}>
                      暂无数据。先触发生成，或调整筛选条件。
                    </Typography>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
        <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
          共 {total} 条；列表按 id 倒序展示前 100 条。
        </Typography>
      </Paper>
    </Stack>
  );
}

export default { KnowledgeGraphWorkspace, KnowledgeDerivativeWorkspace };
