import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  FormControl,
  Grid,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import RefreshRoundedIcon from '@mui/icons-material/RefreshRounded';
import SearchRoundedIcon from '@mui/icons-material/SearchRounded';
import ManageAccountsRoundedIcon from '@mui/icons-material/ManageAccountsRounded';
import AdminShell from './AdminShell';
import PageSection from './PageSection';

const viewTypeOptions = [
  { value: 'kp_definition', label: '定义' },
  { value: 'kp_explainer', label: '讲解' },
  { value: 'kp_summary', label: '总结' },
  { value: 'kp_exam_focus', label: '考向' },
  { value: 'kp_pitfall', label: '易错点' },
  { value: 'kp_compare', label: '对比辨析' },
  { value: 'kp_table_row', label: '表格行' },
  { value: 'kp_mindmap_path', label: '脑图路径' },
  { value: 'kp_example_bridge', label: '例题桥接' },
  { value: 'kp_prerequisite', label: '前置知识' },
  { value: 'kp_source_restore', label: '原文还原' },
];

const entityTypeLabelMap = {
  knowledge_point: '知识点',
  knowledge_package: '专题包',
  knowledge_block: '知识块',
  knowledge_atom: '知识原子',
  knowledge_question_bridge: '题目桥接',
};

const cardSx = {
  p: 2,
  borderRadius: 3,
  border: '1px solid #eef0f3',
  backgroundColor: '#fafbfc',
  minHeight: 108,
};

function toggleFromList(list, value) {
  return list.includes(value) ? list.filter((item) => item !== value) : [...list, value];
}

function formatNumber(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-';
  return Number(value).toFixed(4);
}

function MetadataChip({ label }) {
  if (!label) return null;
  return <Chip size="small" label={label} variant="outlined" sx={{ maxWidth: '100%' }} />;
}

function ResultCard({ item }) {
  const metadata = item.metadata || {};
  const viewType = metadata.view_type || '';
  const title = item.title || metadata.knowledge_point_name || metadata.package_title || `${entityTypeLabelMap[item.entity_type] || item.entity_type} #${item.entity_id || '-'}`;

  return (
    <Paper sx={{ p: 2, borderRadius: 2.5, border: '1px solid #eef0f3', boxShadow: 'none', backgroundColor: '#fff' }}>
      <Stack spacing={1.5}>
        <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={1.5}>
          <Box>
            <Typography variant="subtitle1">{title}</Typography>
            <Typography variant="caption">
              {entityTypeLabelMap[item.entity_type] || item.entity_type} · view={viewType || '-'} · source={item.source_type || 'hybrid'}
            </Typography>
          </Box>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <Chip size="small" label={`总分 ${formatNumber(item.score)}`} color="primary" variant="outlined" />
            <Chip size="small" label={`向量 ${formatNumber(item.vector_score)}`} variant="outlined" />
            <Chip size="small" label={`词面 ${formatNumber(item.text_score)}`} variant="outlined" />
          </Stack>
        </Stack>

        <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
          {item.snippet || item.content || '暂无摘要'}
        </Typography>

        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          <MetadataChip label={metadata.subject ? `学科：${metadata.subject}` : ''} />
          <MetadataChip label={metadata.grade ? `年级：${metadata.grade}` : ''} />
          <MetadataChip label={metadata.knowledge_point_name ? `知识点：${metadata.knowledge_point_name}` : ''} />
          <MetadataChip label={metadata.package_title ? `专题包：${metadata.package_title}` : ''} />
          <MetadataChip label={metadata.section_path ? `章节：${metadata.section_path}` : ''} />
          <MetadataChip label={metadata.source_page_no ? `页码：${metadata.source_page_no}` : ''} />
          <MetadataChip label={metadata.relation_type ? `桥接：${metadata.relation_type}` : ''} />
        </Stack>

        {item.content && item.content !== item.snippet && (
          <Box component="details" sx={{ '& summary': { cursor: 'pointer', color: 'primary.main', fontSize: 13 } }}>
            <summary>展开完整内容</summary>
            <Box component="pre" sx={{ mt: 1.25, mb: 0, p: 1.5, borderRadius: 2, backgroundColor: '#0f1115', color: '#d7dde8', overflow: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: 12 }}>
              {item.content}
            </Box>
          </Box>
        )}
      </Stack>
    </Paper>
  );
}

function KnowledgeRetrievalWorkbench() {
  const searchParams = useMemo(() => new URLSearchParams(window.location.search), []);
  const [overview, setOverview] = useState({ flags: {}, counts: {}, backends: {}, subjects: [] });
  const [points, setPoints] = useState([]);
  const [packages, setPackages] = useState([]);
  const [query, setQuery] = useState(searchParams.get('q') || '');
  const [topK, setTopK] = useState(searchParams.get('top_k') || '8');
  const [subject, setSubject] = useState(searchParams.get('subject') || '');
  const [grade, setGrade] = useState(searchParams.get('grade') || '');
  const [knowledgePointId, setKnowledgePointId] = useState(searchParams.get('knowledge_point_id') || '');
  const [packageId, setPackageId] = useState(searchParams.get('package_id') || '');
  const [selectedViewTypes, setSelectedViewTypes] = useState(() => {
    const raw = searchParams.get('view_types');
    return raw ? raw.split(',').filter(Boolean) : [];
  });
  const [resultsPayload, setResultsPayload] = useState({ query: '', results: [], applied_filters: {}, backends: {} });
  const [loading, setLoading] = useState(false);
  const [searching, setSearching] = useState(false);
  const [message, setMessage] = useState(null);
  const [refreshTick, setRefreshTick] = useState(0);

  const subjects = overview.subjects || [];
  const resultGroups = useMemo(() => {
    const groups = {};
    for (const item of resultsPayload.results || []) {
      const key = item.metadata?.view_type || 'unknown';
      groups[key] = (groups[key] || 0) + 1;
    }
    return Object.entries(groups).map(([key, count]) => ({ key, count }));
  }, [resultsPayload]);

  useEffect(() => {
    let ignore = false;

    const load = async () => {
      setLoading(true);
      try {
        const [overviewRes, pointsRes, packagesRes] = await Promise.all([
          fetch('/api/knowledge-admin/overview'),
          fetch('/api/knowledge-points/points?limit=100'),
          fetch('/api/knowledge-points/packages?limit=100'),
        ]);

        if (!overviewRes.ok || !pointsRes.ok || !packagesRes.ok) {
          throw new Error('加载知识点检索台初始化数据失败');
        }

        const [overviewData, pointsData, packagesData] = await Promise.all([
          overviewRes.json(),
          pointsRes.json(),
          packagesRes.json(),
        ]);

        if (ignore) return;

        setOverview(overviewData || { flags: {}, counts: {}, backends: {}, subjects: [] });
        setPoints(Array.isArray(pointsData) ? pointsData : []);
        setPackages(Array.isArray(packagesData) ? packagesData : []);
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
  }, [refreshTick]);

  const handleSearch = async () => {
    if (!query.trim()) {
      setMessage({ severity: 'warning', text: '请输入检索问题或关键词。' });
      return;
    }

    setSearching(true);
    try {
      const response = await fetch('/api/knowledge-points/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: query.trim(),
          top_k: Number(topK || 8),
          subject: subject || undefined,
          grade: grade || undefined,
          package_id: packageId ? Number(packageId) : undefined,
          knowledge_point_id: knowledgePointId ? Number(knowledgePointId) : undefined,
          view_types: selectedViewTypes.length > 0 ? selectedViewTypes : undefined,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data?.detail || '检索失败');
      }
      setResultsPayload(data || { query: query.trim(), results: [], applied_filters: {}, backends: {} });
      setMessage({ severity: 'success', text: `检索完成，共返回 ${(data?.results || []).length} 条结果。` });
    } catch (error) {
      setResultsPayload({ query: query.trim(), results: [], applied_filters: {}, backends: {} });
      setMessage({ severity: 'error', text: error.message || '检索失败' });
    } finally {
      setSearching(false);
    }
  };

  return (
    <AdminShell
      pageKey="knowledge-retrieval"
      title="知识点检索台"
      subtitle="直接在现有 8001 测试后台里验证第三阶段的知识点混合检索、过滤与证据展示，不新起任何页面服务。"
      breadcrumbs="统一测试控制台 / 知识点检索台"
      actions={[
        <Button key="refresh" variant="outlined" startIcon={<RefreshRoundedIcon />} onClick={() => setRefreshTick((prev) => prev + 1)} disabled={loading || searching}>
          刷新配置
        </Button>,
        <Button key="manage" variant="contained" startIcon={<ManageAccountsRoundedIcon />} onClick={() => { window.location.href = '/knowledge-points'; }}>
          返回管理页
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
            { label: '知识点', value: overview.counts?.knowledge_points ?? 0, caption: '可作为知识点过滤条件' },
            { label: '专题包', value: overview.counts?.knowledge_packages ?? 0, caption: '可限定专题包范围检索' },
            { label: '检索文档', value: overview.counts?.retrieval_documents ?? 0, caption: '第三阶段检索投影总量' },
            { label: '向量点', value: overview.counts?.embedding_points ?? 0, caption: `向量后端：${overview.backends?.vector_backend || '未配置'}` },
          ].map((item) => (
            <Grid item xs={12} sm={6} lg={3} key={item.label}>
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
            当前 RAG 开关：{overview.flags.knowledge_rag_enabled ? '已开启' : '未开启'}。
            {overview.flags.knowledge_rag_enabled ? ' 你可以直接在这里验证知识点检索召回。' : ' 如果返回 503，说明需要先打开 `KNOWLEDGE_RAG_ENABLED`。'}
          </Alert>
        )}

        <Grid container spacing={2.5}>
          <Grid item xs={12} xl={4}>
            <PageSection title="检索条件" description="支持按学科、年级、知识点、专题包与视图类型做强过滤。">
              <Stack spacing={2}>
                <TextField
                  label="检索问题 / 关键词"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  fullWidth
                  multiline
                  minRows={3}
                  placeholder="例如：集合的定义和常见易错点"
                />
                <Grid container spacing={1.5}>
                  <Grid item xs={12} sm={6} xl={6}>
                    <FormControl fullWidth size="small">
                      <InputLabel>Top K</InputLabel>
                      <Select value={topK} label="Top K" onChange={(event) => setTopK(event.target.value)}>
                        {['5', '8', '10', '15'].map((item) => (
                          <MenuItem key={item} value={item}>{item}</MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                  </Grid>
                  <Grid item xs={12} sm={6} xl={6}>
                    <FormControl fullWidth size="small">
                      <InputLabel>学科</InputLabel>
                      <Select value={subject} label="学科" onChange={(event) => setSubject(event.target.value)}>
                        <MenuItem value="">全部学科</MenuItem>
                        {subjects.map((item) => (
                          <MenuItem key={item} value={item}>{item}</MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                  </Grid>
                  <Grid item xs={12} sm={6} xl={6}>
                    <TextField label="年级" value={grade} onChange={(event) => setGrade(event.target.value)} fullWidth size="small" placeholder="例如：高三" />
                  </Grid>
                  <Grid item xs={12} sm={6} xl={6}>
                    <FormControl fullWidth size="small">
                      <InputLabel>知识点</InputLabel>
                      <Select value={knowledgePointId} label="知识点" onChange={(event) => setKnowledgePointId(event.target.value)}>
                        <MenuItem value="">不限知识点</MenuItem>
                        {points.map((item) => (
                          <MenuItem key={item.id} value={String(item.id)}>{`${item.id} / ${item.canonical_name}`}</MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                  </Grid>
                  <Grid item xs={12}>
                    <FormControl fullWidth size="small">
                      <InputLabel>专题包</InputLabel>
                      <Select value={packageId} label="专题包" onChange={(event) => setPackageId(event.target.value)}>
                        <MenuItem value="">不限专题包</MenuItem>
                        {packages.map((item) => (
                          <MenuItem key={item.id} value={String(item.id)}>{`${item.id} / ${item.package_title}`}</MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                  </Grid>
                </Grid>

                <Box>
                  <Typography variant="subtitle2" sx={{ mb: 1 }}>视图类型</Typography>
                  <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                    {viewTypeOptions.map((item) => {
                      const selected = selectedViewTypes.includes(item.value);
                      return (
                        <Chip
                          key={item.value}
                          label={item.label}
                          color={selected ? 'primary' : 'default'}
                          variant={selected ? 'filled' : 'outlined'}
                          onClick={() => setSelectedViewTypes((prev) => toggleFromList(prev, item.value))}
                        />
                      );
                    })}
                  </Stack>
                </Box>

                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
                  <Button
                    variant="contained"
                    startIcon={searching ? <CircularProgress size={16} color="inherit" /> : <SearchRoundedIcon />}
                    disabled={loading || searching}
                    onClick={handleSearch}
                  >
                    {searching ? '检索中...' : '开始检索'}
                  </Button>
                  <Button
                    variant="outlined"
                    onClick={() => {
                      setQuery('');
                      setSubject('');
                      setGrade('');
                      setKnowledgePointId('');
                      setPackageId('');
                      setSelectedViewTypes([]);
                      setResultsPayload({ query: '', results: [], applied_filters: {}, backends: {} });
                    }}
                  >
                    清空条件
                  </Button>
                </Stack>
              </Stack>
            </PageSection>
          </Grid>

          <Grid item xs={12} xl={8}>
            <Stack spacing={2.5}>
              <PageSection title="结果组装摘要" description="按第三阶段检索结果做前端聚合展示，便于快速判断召回是否贴合意图。">
                <Stack spacing={1.5}>
                  <Typography variant="body2">查询：{resultsPayload.query || '尚未执行检索'}</Typography>
                  <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                    <Chip size="small" label={`结果数 ${(resultsPayload.results || []).length}`} variant="outlined" />
                    <Chip size="small" label={`向量后端 ${resultsPayload.backends?.vector_backend || overview.backends?.vector_backend || '未配置'}`} variant="outlined" />
                    <Chip size="small" label={`文本后端 ${resultsPayload.backends?.text_backend || overview.backends?.text_backend || '未配置'}`} variant="outlined" />
                    {(resultGroups || []).map((item) => (
                      <Chip key={item.key} size="small" label={`${item.key} × ${item.count}`} color="primary" variant="outlined" />
                    ))}
                  </Stack>
                  <Typography variant="caption">
                    已应用过滤：{JSON.stringify(resultsPayload.applied_filters || {}, null, 0)}
                  </Typography>
                </Stack>
              </PageSection>

              <PageSection title="检索结果" description="展示召回结果的标题、摘要、分数与元数据证据。">
                <Stack spacing={1.5}>
                  {(resultsPayload.results || []).map((item) => (
                    <ResultCard key={item.doc_id} item={item} />
                  ))}
                  {!searching && (!resultsPayload.results || resultsPayload.results.length === 0) && (
                    <Paper sx={{ p: 4, borderRadius: 2.5, border: '1px dashed #c9cdd4', boxShadow: 'none', textAlign: 'center', color: 'text.secondary' }}>
                      还没有检索结果。输入问题后点击“开始检索”，即可在当前后台直接验证第三阶段召回效果。
                    </Paper>
                  )}
                </Stack>
              </PageSection>
            </Stack>
          </Grid>
        </Grid>
      </Stack>
    </AdminShell>
  );
}

export default KnowledgeRetrievalWorkbench;
