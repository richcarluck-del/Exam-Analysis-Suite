import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  FormControl,
  FormControlLabel,
  FormGroup,
  Grid,
  IconButton,
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
import RefreshRoundedIcon from '@mui/icons-material/RefreshRounded';
import PlayArrowRoundedIcon from '@mui/icons-material/PlayArrowRounded';
import SearchRoundedIcon from '@mui/icons-material/SearchRounded';
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded';
import VisibilityRoundedIcon from '@mui/icons-material/VisibilityRounded';
import AdminShell from './AdminShell';

import PageSection from './PageSection';
import { terminalSx } from './adminTheme';


const fallbackSteps = [
  { id: 0, key: '0', label: '内容源选择', description: '选择已有内容源' },
  { id: 1, key: '1', label: '批量文档登记', description: '扫描目录并登记题库文档' },
  { id: 2, key: '2', label: '批量题库摄入', description: '对已登记文档批量切题并建索引' },
  { id: 3, key: '3', label: 'Bundle 导入', description: '导入 preprocessor 导出的分析包' },
  { id: 4, key: '4', label: '试卷匹配', description: '将导入题目与题库进行匹配' },
];

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

function ContentIngestionTest() {
  const [pipelineSteps, setPipelineSteps] = useState(fallbackSteps);
  const [overview, setOverview] = useState({ counts: {}, sources: [], documents: [], exam_sessions: [], mock_cases: [], supported_extensions: [] });
  const [sourceDocuments, setSourceDocuments] = useState([]);
  const [selectedDocumentIds, setSelectedDocumentIds] = useState([]);
  const [scannedFiles, setScannedFiles] = useState([]);

  const [loading, setLoading] = useState(true);
  const [isRunning, setIsRunning] = useState(false);
  const [isScanning, setIsScanning] = useState(false);
  const [message, setMessage] = useState(null);
  const [logs, setLogs] = useState('Welcome to the Content Ingestion Test Console.\n');
  const ws = useRef(null);
  const logContainerRef = useRef(null);


  const [runScope, setRunScope] = useState('documents');
  const [testMode, setTestMode] = useState('real');
  const [realSteps, setRealSteps] = useState([]);
  const [caseName, setCaseName] = useState('');
  const [selectedMockCase, setSelectedMockCase] = useState('');

  const [selectedSourceId, setSelectedSourceId] = useState('');
  const [documentPath, setDocumentPath] = useState('D:\\10739\\Exam-Analysis-Suite\\analyzer\\knowledge_base');
  const [parseProfile, setParseProfile] = useState('default');
  const [documentVisibilityScope, setDocumentVisibilityScope] = useState('public');
  const [subject, setSubject] = useState('数学');
  const [grade, setGrade] = useState('3年级');
  const [year, setYear] = useState('2008');
  const [region, setRegion] = useState('全国');
  const [title, setTitle] = useState('2008年高考数学试卷（理）（全国卷Ⅰ）（解析卷）');
  const [forceReingest, setForceReingest] = useState(false);

  const [bundleDir, setBundleDir] = useState('');
  const [studentId, setStudentId] = useState('');
  const [examDate, setExamDate] = useState('');
  const [examVisibilityScope, setExamVisibilityScope] = useState('private');
  const [linkSourceDocument, setLinkSourceDocument] = useState(false);
  const [bundleSourceDocumentId, setBundleSourceDocumentId] = useState('');
  const [matchTopK, setMatchTopK] = useState('5');
  const [matchAcceptThreshold, setMatchAcceptThreshold] = useState('0.78');
  const [matchMinGap, setMatchMinGap] = useState('0.05');

  const latestSources = overview.sources || [];
  const latestDocuments = overview.documents || [];
  const latestSessions = overview.exam_sessions || [];
  const mockCases = overview.mock_cases || [];
  const counts = overview.counts || {};
  const supportedExtensions = overview.supported_extensions || [];

  const selectedSteps = useMemo(() => {
    const stepMap = {
      documents: ['0', '1', '2'],
      bundle: ['3', '4'],
      full: ['0', '1', '2', '3', '4'],
    };
    const keys = new Set(stepMap[runScope] || stepMap.full);
    return pipelineSteps.filter((step) => keys.has(step.key));
  }, [pipelineSteps, runScope]);

  const visibleSourceDocuments = useMemo(() => sourceDocuments.slice(0, 20), [sourceDocuments]);
  const visibleSourceDocumentIds = useMemo(
    () => visibleSourceDocuments.map((item) => item.id).filter(Boolean),
    [visibleSourceDocuments]
  );
  const isAllDocumentsSelected =
    visibleSourceDocumentIds.length > 0 &&
    visibleSourceDocumentIds.every((id) => selectedDocumentIds.includes(id));

  const loadData = async () => {

    setLoading(true);
    try {
      const [overviewRes, stepsRes] = await Promise.all([
        fetch('/api/content-ingestion/overview'),
        fetch('/api/content-ingestion/pipeline-steps'),
      ]);
      if (!overviewRes.ok || !stepsRes.ok) {
        throw new Error('加载内容摄入页面失败');
      }
      const [overviewData, stepsData] = await Promise.all([overviewRes.json(), stepsRes.json()]);
      setOverview(overviewData || { counts: {}, sources: [], documents: [], exam_sessions: [], mock_cases: [], supported_extensions: [] });
      setPipelineSteps(Array.isArray(stepsData) && stepsData.length > 0 ? stepsData : fallbackSteps);
      if (!selectedMockCase && Array.isArray(overviewData?.mock_cases) && overviewData.mock_cases.length > 0) {
        setSelectedMockCase(overviewData.mock_cases[0].name);
      }
      if (!selectedSourceId && Array.isArray(overviewData?.sources) && overviewData.sources.length > 0) {
        setSelectedSourceId(String(overviewData.sources[0].id));
      }
      setMessage(null);
    } catch (error) {
      setMessage({ severity: 'error', text: error.message || '加载失败' });
    } finally {
      setLoading(false);
    }
  };

  const loadSourceDocuments = async (sourceId) => {
    if (!sourceId) {
      setSourceDocuments([]);
      setSelectedDocumentIds([]);
      setBundleSourceDocumentId('');
      return;
    }

    try {
      const response = await fetch(`/api/content-sources/${sourceId}/documents`);
      if (!response.ok) {
        throw new Error('加载内容源文档失败');
      }
      const data = await response.json();
      const documents = Array.isArray(data?.documents) ? data.documents : [];
      setSourceDocuments(documents);
      setSelectedDocumentIds((prev) => prev.filter((id) => documents.some((item) => item.id === id)));
      if (bundleSourceDocumentId && !documents.some((item) => String(item.id) === String(bundleSourceDocumentId))) {
        setBundleSourceDocumentId('');
      }

    } catch (error) {
      setSourceDocuments([]);
      setBundleSourceDocumentId('');
      setMessage({ severity: 'error', text: error.message || '加载文档失败' });
    }
  };

  useEffect(() => {
    loadData();
    return () => {
      if (ws.current) {
        ws.current.close();
      }
    };
  }, []);

  useEffect(() => {
    loadSourceDocuments(selectedSourceId);
  }, [selectedSourceId]);

  useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logs]);

  const handleScan = async () => {

    setIsScanning(true);
    try {
      const response = await fetch('/api/content-ingestion/scan-documents', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ directory_path: documentPath }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data?.detail || '扫描目录失败');
      }
      setScannedFiles(Array.isArray(data?.files) ? data.files : []);
      setMessage({ severity: 'success', text: `扫描完成，共发现 ${data?.count || 0} 个文档` });
    } catch (error) {
      setScannedFiles([]);
      setMessage({ severity: 'error', text: error.message || '扫描失败' });
    } finally {
      setIsScanning(false);
    }
  };

  const toggleRealStep = (stepKey) => {
    setRealSteps((prev) => (prev.includes(stepKey) ? prev.filter((item) => item !== stepKey) : [...prev, stepKey]));
  };

  const toggleDocumentSelection = (documentId) => {
    setSelectedDocumentIds((prev) => (prev.includes(documentId) ? prev.filter((id) => id !== documentId) : [...prev, documentId]));
  };

  const toggleSelectAllDocuments = () => {
    if (isAllDocumentsSelected) {
      setSelectedDocumentIds((prev) => prev.filter((id) => !visibleSourceDocumentIds.includes(id)));
      return;
    }
    setSelectedDocumentIds((prev) => Array.from(new Set([...prev, ...visibleSourceDocumentIds])));
  };

  const handleDeleteDocuments = async (documentIds) => {
    const ids = (documentIds || []).filter(Boolean);
    if (!ids.length || !selectedSourceId) {
      return;
    }
    const confirmed = window.confirm(
      ids.length === 1
        ? `确定要删除文档 ID=${ids[0]} 及其所有解析结果吗？该操作不可恢复。`
        : `确定要删除选中的 ${ids.length} 个文档及其所有解析结果吗？该操作不可恢复。`
    );
    if (!confirmed) {
      return;
    }

    try {
      for (const documentId of ids) {
        const response = await fetch(`/api/content-sources/${selectedSourceId}/documents/${documentId}`, {
          method: 'DELETE',
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(data?.detail || `删除文档 ${documentId} 失败`);
        }
      }
      setMessage({ severity: 'success', text: `已删除 ${ids.length} 个文档及其解析结果` });
      setSelectedDocumentIds((prev) => prev.filter((id) => !ids.includes(id)));
      await loadData();
      await loadSourceDocuments(selectedSourceId);
    } catch (error) {
      setMessage({ severity: 'error', text: error.message || '删除失败' });
    }
  };

  const handleStart = () => {

    setIsRunning(true);
    setLogs('[SYSTEM] Initializing content ingestion test...\n');
    ws.current = new WebSocket(`ws://${window.location.host}/ws/run-content-ingestion`);
    ws.current.onopen = () => {
      ws.current.send(JSON.stringify({
        run_scope: runScope,
        test_mode: testMode,
        real_steps: testMode === 'mock' ? realSteps : undefined,
        case_name: testMode === 'record' ? (caseName || `case_${Date.now()}`) : undefined,
        mock_case: testMode === 'mock' ? selectedMockCase : undefined,
        existing_source_id: selectedSourceId || undefined,
        document_path: runScope !== 'bundle' ? (documentPath || undefined) : undefined,
        parse_profile: parseProfile,
        subject: subject || undefined,
        grade: grade || undefined,
        year: year || undefined,
        region: region || undefined,
        title: title || undefined,
        document_visibility_scope: documentVisibilityScope,
        force_reingest: forceReingest,
        bundle_dir: runScope !== 'documents' ? (bundleDir || undefined) : undefined,
        student_id: runScope !== 'documents' ? (studentId || undefined) : undefined,
        exam_date: runScope !== 'documents' ? (examDate || undefined) : undefined,
        exam_visibility_scope: examVisibilityScope,
        link_source_document: runScope !== 'documents' ? linkSourceDocument : false,
        bundle_source_document_id: runScope !== 'documents' && linkSourceDocument ? (bundleSourceDocumentId || undefined) : undefined,
        match_top_k: runScope !== 'documents' ? (matchTopK || undefined) : undefined,
        match_accept_threshold: runScope !== 'documents' ? (matchAcceptThreshold || undefined) : undefined,
        match_min_gap: runScope !== 'documents' ? (matchMinGap || undefined) : undefined,
      }));
    };
    ws.current.onmessage = (event) => {
      setLogs((prev) => prev + event.data + '\n');
    };
    ws.current.onerror = () => {
      setLogs((prev) => prev + '[SYSTEM-ERROR] WebSocket error.\n');
      setIsRunning(false);
    };
    ws.current.onclose = async () => {
      setLogs((prev) => prev + '\n[SYSTEM] Test finished. WebSocket closed.\n');
      setIsRunning(false);
      await loadData();
      if (selectedSourceId) {
        await loadSourceDocuments(selectedSourceId);
      }
    };
  };

  return (
    <AdminShell
      pageKey="content-ingestion"
      title="内容摄入测试"
      subtitle="把“批量登记 + 批量摄入”和“Bundle 测试 + 匹配”拆成可单独调试、也可串联运行的测试入口。"
      breadcrumbs="统一测试控制台 / 内容摄入测试"
      actions={[
        <Button key="refresh" variant="outlined" startIcon={<RefreshRoundedIcon />} onClick={loadData} disabled={loading || isRunning || isScanning}>
          刷新
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
            { label: '内容源', value: counts.sources ?? 0, caption: '由内容源管理页独立维护' },
            { label: '题库文档', value: counts.documents ?? 0, caption: '已登记文档总数' },
            { label: '试卷会话', value: counts.exam_sessions ?? 0, caption: 'Bundle 导入结果' },
            { label: 'Mock 案例', value: counts.mock_cases ?? 0, caption: '录制回放案例数' },
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

        <Grid container spacing={2.5}>
          <Grid item xs={12} xl={5}>
            <Stack spacing={2.5}>
              <PageSection title="运行方式" description="文档链路、Bundle 链路都可单独跑，也可串起来跑。">
                <Stack spacing={2}>
                  <FormControl fullWidth>
                    <InputLabel>运行范围</InputLabel>
                    <Select value={runScope} label="运行范围" onChange={(event) => setRunScope(event.target.value)}>
                      <MenuItem value="documents">仅批量登记 + 批量摄入</MenuItem>
                      <MenuItem value="bundle">仅 Bundle 导入 + 匹配</MenuItem>
                      <MenuItem value="full">整链路串联运行</MenuItem>
                    </Select>
                  </FormControl>
                  <Stack direction="row" spacing={1} flexWrap="wrap">
                    {selectedSteps.map((step) => (
                      <Chip key={step.key} label={step.label} size="small" variant="outlined" sx={{ mb: 1 }} />
                    ))}
                  </Stack>
                </Stack>
              </PageSection>

              <PageSection title="测试模式" description="继续支持 real / record / mock；mock 时只对当前运行范围内的步骤生效。">
                <Stack spacing={2}>
                  <FormControl fullWidth>
                    <InputLabel>模式</InputLabel>
                    <Select value={testMode} label="模式" onChange={(event) => setTestMode(event.target.value)}>
                      <MenuItem value="real">实时执行</MenuItem>
                      <MenuItem value="record">录制案例</MenuItem>
                      <MenuItem value="mock">Mock 回放</MenuItem>
                    </Select>
                  </FormControl>

                  {testMode === 'record' && (
                    <TextField label="录制案例名" value={caseName} onChange={(event) => setCaseName(event.target.value)} fullWidth />
                  )}

                  {testMode === 'mock' && (
                    <Stack spacing={2}>
                      <FormControl fullWidth>
                        <InputLabel>Mock 案例</InputLabel>
                        <Select value={selectedMockCase} label="Mock 案例" onChange={(event) => setSelectedMockCase(event.target.value)}>
                          {mockCases.map((item) => (
                            <MenuItem key={item.name} value={item.name}>{`${item.name}（${item.available_step_count} 步）`}</MenuItem>
                          ))}
                        </Select>
                      </FormControl>
                      <FormGroup>
                        {selectedSteps.map((step) => (
                          <FormControlLabel key={step.key} control={<Checkbox checked={realSteps.includes(step.key)} onChange={() => toggleRealStep(step.key)} />} label={`${step.label}（真实执行）`} />
                        ))}
                      </FormGroup>
                    </Stack>
                  )}
                </Stack>
              </PageSection>

              <PageSection title="内容源选择" description="内容源在左侧“内容源管理”菜单中创建；本页只负责选择。">
                <FormControl fullWidth>
                  <InputLabel>内容源</InputLabel>
                  <Select value={selectedSourceId} label="内容源" onChange={(event) => setSelectedSourceId(event.target.value)}>
                    {latestSources.map((item) => (
                      <MenuItem key={item.id} value={String(item.id)}>{`${item.id} / ${item.source_name}`}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </PageSection>

              {runScope !== 'bundle' && (
                <PageSection title="批量文档登记与摄入" description={`支持目录扫描，自动识别 ${supportedExtensions.join(', ') || '.pdf/.doc/.docx/.txt'}；兼容中文文件名与文件名空格。`}>
                  <Stack spacing={2}>
                    <TextField label="题库文档目录" value={documentPath} onChange={(event) => setDocumentPath(event.target.value)} fullWidth />
                    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
                      <Button variant="outlined" startIcon={<SearchRoundedIcon />} onClick={handleScan} disabled={isScanning || isRunning || !documentPath.trim()}>
                        {isScanning ? '扫描中...' : '扫描目录'}
                      </Button>
                      <Chip label={`已扫描 ${scannedFiles.length} 个文档`} size="small" variant="outlined" />
                    </Stack>
                    <Grid container spacing={2}>
                      <Grid item xs={12} sm={6}>
                        <TextField label="Parse Profile" value={parseProfile} onChange={(event) => setParseProfile(event.target.value)} fullWidth />
                      </Grid>
                      <Grid item xs={12} sm={6}>
                        <FormControl fullWidth>
                          <InputLabel>文档可见范围</InputLabel>
                          <Select value={documentVisibilityScope} label="文档可见范围" onChange={(event) => setDocumentVisibilityScope(event.target.value)}>
                            <MenuItem value="public">public</MenuItem>
                            <MenuItem value="tenant_private">tenant_private</MenuItem>
                            <MenuItem value="private">private</MenuItem>
                          </Select>
                        </FormControl>
                      </Grid>
                      <Grid item xs={12} sm={6}>
                        <TextField label="学科" value={subject} onChange={(event) => setSubject(event.target.value)} fullWidth />
                      </Grid>
                      <Grid item xs={12} sm={6}>
                        <TextField label="年级" value={grade} onChange={(event) => setGrade(event.target.value)} fullWidth />
                      </Grid>
                      <Grid item xs={12} sm={4}>
                        <TextField label="年份" value={year} onChange={(event) => setYear(event.target.value)} fullWidth />
                      </Grid>
                      <Grid item xs={12} sm={4}>
                        <TextField label="地区" value={region} onChange={(event) => setRegion(event.target.value)} fullWidth />
                      </Grid>
                      <Grid item xs={12} sm={4}>
                        <TextField label="标题基准" value={title} onChange={(event) => setTitle(event.target.value)} fullWidth />
                      </Grid>
                    </Grid>
                    <FormControlLabel control={<Checkbox checked={forceReingest} onChange={(event) => setForceReingest(event.target.checked)} />} label="强制重新摄入文档" />
                  </Stack>
                </PageSection>
              )}

              {runScope !== 'documents' && (
                <PageSection title="Bundle 导入与匹配" description="适合学生/家长触发的独立链路；也可以和题库摄入整链路串联执行。">
                  <Stack spacing={2}>
                    <TextField label="Bundle 目录" value={bundleDir} onChange={(event) => setBundleDir(event.target.value)} fullWidth />
                    <Grid container spacing={2}>
                      <Grid item xs={12} sm={6}>
                        <TextField label="Student ID" value={studentId} onChange={(event) => setStudentId(event.target.value)} fullWidth />
                      </Grid>
                      <Grid item xs={12} sm={6}>
                        <TextField label="考试日期 (YYYY-MM-DD)" value={examDate} onChange={(event) => setExamDate(event.target.value)} fullWidth />
                      </Grid>
                      <Grid item xs={12} sm={6}>
                        <FormControl fullWidth>
                          <InputLabel>Exam 可见范围</InputLabel>
                          <Select value={examVisibilityScope} label="Exam 可见范围" onChange={(event) => setExamVisibilityScope(event.target.value)}>
                            <MenuItem value="private">private</MenuItem>
                            <MenuItem value="tenant_private">tenant_private</MenuItem>
                            <MenuItem value="public">public</MenuItem>
                          </Select>
                        </FormControl>
                      </Grid>
                      <Grid item xs={12} sm={6}>
                        <FormControlLabel control={<Checkbox checked={linkSourceDocument} onChange={(event) => setLinkSourceDocument(event.target.checked)} />} label="Bundle 关联单个题库文档" />
                      </Grid>
                      {linkSourceDocument && (
                        <Grid item xs={12}>
                          <FormControl fullWidth>
                            <InputLabel>关联题库文档</InputLabel>
                            <Select value={bundleSourceDocumentId} label="关联题库文档" onChange={(event) => setBundleSourceDocumentId(event.target.value)}>
                              <MenuItem value="">不指定，按题库整体匹配</MenuItem>
                              {sourceDocuments.map((item) => (
                                <MenuItem key={item.id} value={String(item.id)}>{`${item.id} / ${item.file_name || item.title || '未命名文档'}`}</MenuItem>
                              ))}
                            </Select>
                          </FormControl>
                        </Grid>
                      )}
                      <Grid item xs={12} sm={4}>
                        <TextField label="Top K" value={matchTopK} onChange={(event) => setMatchTopK(event.target.value)} fullWidth />
                      </Grid>
                      <Grid item xs={12} sm={4}>
                        <TextField label="接受阈值" value={matchAcceptThreshold} onChange={(event) => setMatchAcceptThreshold(event.target.value)} fullWidth />
                      </Grid>
                      <Grid item xs={12} sm={4}>
                        <TextField label="最小分差" value={matchMinGap} onChange={(event) => setMatchMinGap(event.target.value)} fullWidth />
                      </Grid>
                    </Grid>
                  </Stack>
                </PageSection>
              )}

              <Button variant="contained" startIcon={<PlayArrowRoundedIcon />} onClick={handleStart} disabled={isRunning}>
                {isRunning ? '运行中...' : '开始内容摄入测试'}
              </Button>
            </Stack>
          </Grid>

          <Grid item xs={12} xl={7}>
            <Stack spacing={2.5}>
              <PageSection title="运行日志" description="支持实时日志；record 模式会自动把日志与步骤结果落盘到 analyzer/tests/mock_data。">
                <Box ref={logContainerRef} component="pre" sx={{ ...terminalSx, mt: 0, minHeight: 420, maxHeight: 760, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                  {logs}
                </Box>
              </PageSection>


              {runScope !== 'bundle' && (
                <PageSection title="扫描结果预览" description="目录扫描会递归识别支持的文档类型。">
                  <TableContainer component={Paper} sx={tableSx}>
                    <Table size="small">
                      <TableHead>
                        <TableRow>
                          <TableCell>文件名</TableCell>
                          <TableCell>类型</TableCell>
                          <TableCell>大小</TableCell>
                          <TableCell>路径</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {scannedFiles.slice(0, 30).map((item) => (
                          <TableRow key={item.path} hover>
                            <TableCell>{item.file_name}</TableCell>
                            <TableCell>{item.file_ext}</TableCell>
                            <TableCell>{item.size_bytes}</TableCell>
                            <TableCell>{item.path}</TableCell>
                          </TableRow>
                        ))}
                        {scannedFiles.length === 0 && (
                          <TableRow>
                            <TableCell colSpan={4} align="center">尚未扫描目录</TableCell>
                          </TableRow>
                        )}
                      </TableBody>
                    </Table>
                  </TableContainer>
                </PageSection>
              )}

              <PageSection
                title="当前内容源下的文档"
                description="供批量摄入复用，也供 Bundle 关联单个题库文档时选择。"
                actions={
                  <Button
                    size="small"
                    variant="outlined"
                    color="error"
                    disabled={selectedDocumentIds.length === 0 || isRunning || isScanning}
                    onClick={() => handleDeleteDocuments(selectedDocumentIds)}
                  >
                    删除所选
                  </Button>
                }
              >
                <TableContainer component={Paper} sx={tableSx}>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell padding="checkbox">
                          <Checkbox
                            size="small"
                            checked={isAllDocumentsSelected}
                            indeterminate={selectedDocumentIds.length > 0 && !isAllDocumentsSelected}
                            onChange={toggleSelectAllDocuments}
                          />
                        </TableCell>
                        <TableCell>ID</TableCell>
                        <TableCell>文件</TableCell>
                        <TableCell>状态</TableCell>
                        <TableCell>标题</TableCell>
                        <TableCell align="right">操作</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {visibleSourceDocuments.map((item) => {
                        const isSelected = selectedDocumentIds.includes(item.id);
                        return (
                          <TableRow key={item.id} hover selected={isSelected}>
                            <TableCell padding="checkbox">
                              <Checkbox size="small" checked={isSelected} onChange={() => toggleDocumentSelection(item.id)} />
                            </TableCell>
                            <TableCell>{item.id}</TableCell>
                            <TableCell>{item.file_name || '-'}</TableCell>
                            <TableCell>
                              <Chip size="small" label={item.parse_status || 'unknown'} color={item.parse_status === 'success' ? 'success' : item.parse_status === 'failed' ? 'error' : 'default'} variant="outlined" />
                            </TableCell>
                            <TableCell>{item.title || '-'}</TableCell>
                            <TableCell align="right">
                              <Stack direction="row" spacing={0.5} justifyContent="flex-end">
                                <Tooltip title="预览试卷内容">
                                  <IconButton
                                    size="small"
                                    color="primary"
                                    onClick={() => window.open(`/paper-preview?id=${item.id}`, '_blank')}
                                  >
                                    <VisibilityRoundedIcon fontSize="small" />
                                  </IconButton>
                                </Tooltip>
                                <Tooltip title="删除此文档及其所有解析结果">
                                  <span>
                                    <IconButton
                                      size="small"
                                      color="error"
                                      disabled={isRunning || isScanning}
                                      onClick={() => handleDeleteDocuments([item.id])}
                                    >
                                      <DeleteOutlineRoundedIcon fontSize="small" />
                                    </IconButton>
                                  </span>
                                </Tooltip>
                              </Stack>
                            </TableCell>
                          </TableRow>

                        );
                      })}
                      {sourceDocuments.length === 0 && (
                        <TableRow>
                          <TableCell colSpan={6} align="center">当前内容源暂无文档</TableCell>
                        </TableRow>
                      )}
                    </TableBody>
                  </Table>
                </TableContainer>
              </PageSection>


              <PageSection title="最近试卷会话" description="显示 Bundle 导入后的 ExamSession。">
                <TableContainer component={Paper} sx={tableSx}>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>ID</TableCell>
                        <TableCell>Student</TableCell>
                        <TableCell>学科</TableCell>
                        <TableCell>匹配状态</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {latestSessions.slice(0, 12).map((item) => (
                        <TableRow key={item.id} hover>
                          <TableCell>{item.id}</TableCell>
                          <TableCell>{item.student_id}</TableCell>
                          <TableCell>{item.subject || '-'}</TableCell>
                          <TableCell>
                            <Chip size="small" label={item.matching_status || 'pending'} color={item.matching_status === 'completed' ? 'success' : item.matching_status === 'failed' ? 'error' : 'default'} variant="outlined" />
                          </TableCell>
                        </TableRow>
                      ))}
                      {latestSessions.length === 0 && (
                        <TableRow>
                          <TableCell colSpan={4} align="center">暂无试卷会话</TableCell>
                        </TableRow>
                      )}
                    </TableBody>
                  </Table>
                </TableContainer>
              </PageSection>

              <PageSection title="最近全局文档" description="便于确认批量登记与批量摄入后的总体结果。">
                <TableContainer component={Paper} sx={tableSx}>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>ID</TableCell>
                        <TableCell>内容源</TableCell>
                        <TableCell>文件</TableCell>
                        <TableCell>状态</TableCell>
                        <TableCell align="right">操作</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {latestDocuments.slice(0, 12).map((item) => (
                        <TableRow key={item.id} hover>
                          <TableCell>{item.id}</TableCell>
                          <TableCell>{item.source_name || '-'}</TableCell>
                          <TableCell>{item.file_name || '-'}</TableCell>
                          <TableCell>
                            <Chip size="small" label={item.parse_status || 'unknown'} color={item.parse_status === 'success' ? 'success' : item.parse_status === 'failed' ? 'error' : 'default'} variant="outlined" />
                          </TableCell>
                          <TableCell align="right">
                            <Tooltip title="预览试卷内容">
                              <IconButton
                                size="small"
                                color="primary"
                                onClick={() => window.open(`/paper-preview?id=${item.id}`, '_blank')}
                              >
                                <VisibilityRoundedIcon fontSize="small" />
                              </IconButton>
                            </Tooltip>
                          </TableCell>
                        </TableRow>

                      ))}
                      {latestDocuments.length === 0 && (
                        <TableRow>
                          <TableCell colSpan={4} align="center">暂无文档</TableCell>
                        </TableRow>
                      )}
                    </TableBody>
                  </Table>
                </TableContainer>
              </PageSection>
            </Stack>
          </Grid>
        </Grid>
      </Stack>
    </AdminShell>
  );
};

export default ContentIngestionTest;

