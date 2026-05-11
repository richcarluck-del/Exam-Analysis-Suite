import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Box,
  Button,
  Checkbox,
  CircularProgress,
  FormControl,
  FormControlLabel,
  FormGroup,
  FormLabel,
  Grid,
  InputLabel,
  MenuItem,
  Paper,
  Radio,
  RadioGroup,
  Select,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import PlayArrowRoundedIcon from '@mui/icons-material/PlayArrowRounded';
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh';
import AdminShell from './AdminShell';
import PageSection from './PageSection';
import PromptEditor from './PromptEditor';
import WholePageDetection from './WholePageDetection';
import ModelRoutingEditor from './ModelRoutingEditor';
import ModelManagement from './ModelManagement';
import PromptRoutingEditor from './PromptRoutingEditor';
import ContentSourceManagement from './ContentSourceManagement';
import ContentIngestionTest from './ContentIngestionTest';
import ContentManagement from './ContentManagement';
import QuestionBankManagement from './QuestionBankManagement';
import KnowledgePointManagement from './KnowledgePointManagement';
import KnowledgeRetrievalWorkbench from './KnowledgeRetrievalWorkbench';
import QuestionPaperPreviewPage from './QuestionPaperPreviewPage';
import CaseRunInspectorPage from './CaseRunInspectorPage';
import { terminalSx } from './adminTheme';

const getPageType = () => {
  const path = window.location.pathname.replace(/\/$/, '');
  if (path.endsWith('/prompt-editor')) return 'prompt-editor';
  if (path.endsWith('/prompt-routing')) return 'prompt-routing';
  if (path.endsWith('/whole-page')) return 'whole-page';
  if (path.endsWith('/content-sources')) return 'content-sources';
  if (path.endsWith('/question-bank-management')) return 'question-bank-management';
  if (path.endsWith('/knowledge-points')) return 'knowledge-points';
  if (path.endsWith('/knowledge-retrieval')) return 'knowledge-retrieval';
  if (path.endsWith('/content-ingestion')) return 'content-ingestion';
  if (path.endsWith('/content-management')) return 'content-management';
  if (path.endsWith('/model-routing')) return 'model-routing';
  if (path.endsWith('/model-management')) return 'model-management';
  if (path.endsWith('/paper-preview')) return 'paper-preview';
  if (path.endsWith('/case-run-inspect')) return 'case-run-inspect';
  return 'test';
};

const fallbackPipelineSteps = [
  { id: 0, key: '0', name: 'preprocess_images', label: '预处理', description: '压缩并规范化输入图片' },
  { id: 1, key: '1', name: 'perspective_correction', label: '透视矫正', description: '透视纠正并输出矫正图' },
  { id: 2, key: '2', name: 'classify', label: '分类', description: '页面类型分类' },
  { id: 3, key: '3', name: 'analyze_layout', label: '版面分析', description: '分析题目区与答题区布局' },
  { id: 4, key: '4', name: 'extract_content', label: '内容提取', description: '提取题目内容与结构化结果' },
  { id: 4.5, key: '4.5', name: 'extract_answers', label: '答案提取', description: '补充答案切片与答案信息' },
  { id: 5, key: '5', name: 'merge_results', label: '结果合并', description: '合并题目、答案与版面结果' },
  { id: 6, key: '6', name: 'answer_card_recognition', label: '涂卡识别', description: '识别选择题涂卡区并生成完整单元' },
  { id: 7, key: '7', name: 'generate_complete_units', label: '生成完整单元', description: '生成完整单元图片输出' },
  { id: 8, key: '8', name: 'draw_output', label: '输出画框', description: '生成最终标注图片' },
  { id: 9, key: '9', name: 'export_analysis_bundle', label: '导出分析包', description: '导出 analyzer bundle' },
];

const previewPromptStepKeys = [
  'preprocessor.perspective_correction',
  'preprocessor.classify',
  'preprocessor.long_image_classification',
  'preprocessor.extract_content.exam_paper',
  'preprocessor.extract_content.answer_sheet',
  'preprocessor.extract_content.mixed',
  'preprocessor.answer_card_recognition',
];

const infoCardSx = {
  p: 2,
  borderRadius: 3,
  border: '1px solid #eef0f3',
  backgroundColor: '#fafbfc',
  boxShadow: 'none',
};

function App() {
  const pageType = getPageType();

  if (pageType === 'whole-page') {
    return <WholePageDetection />;
  }

  if (pageType === 'content-sources') {
    return <ContentSourceManagement />;
  }

  if (pageType === 'question-bank-management') {
    return <QuestionBankManagement />;
  }

  if (pageType === 'knowledge-points') {
    return <KnowledgePointManagement />;
  }

  if (pageType === 'knowledge-retrieval') {
    return <KnowledgeRetrievalWorkbench />;
  }

  if (pageType === 'content-ingestion') {
    return <ContentIngestionTest />;
  }

  if (pageType === 'content-management') {
    return <ContentManagement />;
  }

  if (pageType === 'prompt-editor') {
    return <PromptEditor />;
  }

  if (pageType === 'model-routing') {
    return <ModelRoutingEditor />;
  }

  if (pageType === 'model-management') {
    return <ModelManagement />;
  }

  if (pageType === 'prompt-routing') {
    return <PromptRoutingEditor />;
  }

  if (pageType === 'paper-preview') {
    return <QuestionPaperPreviewPage />;
  }

  if (pageType === 'case-run-inspect') {
    return <CaseRunInspectorPage />;
  }

  const [providers, setProviders] = useState([]);
  const [models, setModels] = useState([]);
  const [promptConfigs, setPromptConfigs] = useState([]);
  const [versions, setVersions] = useState([]);

  const [selectedProvider, setSelectedProvider] = useState('');
  const [selectedModel, setSelectedModel] = useState('');
  const [useModelOverride, setUseModelOverride] = useState(false);
  const [inputDir, setInputDir] = useState('D:\\10739\\Exam-Analysis-Suite\\preprocessor\\my_test_images');
  const [selectedVersion, setSelectedVersion] = useState('');
  const [a3Strategy, setA3Strategy] = useState('whole');
  const [classificationMethod, setClassificationMethod] = useState('long_image');
  const [testMode, setTestMode] = useState('real');
  const [pipelineSteps, setPipelineSteps] = useState(fallbackPipelineSteps);
  const [realSteps, setRealSteps] = useState([]);
  const [caseName, setCaseName] = useState('');
  const [mockCases, setMockCases] = useState([]);
  const [selectedMockCase, setSelectedMockCase] = useState('');

  const [logs, setLogs] = useState('Welcome to the Preprocessor Test UI.\n');
  const [isRunning, setIsRunning] = useState(false);
  const ws = useRef(null);

  const loadPromptConfigs = (versionOverride = '') => {
    const params = new URLSearchParams({ module_name: 'preprocessor' });
    if (versionOverride) {
      params.set('version_override', versionOverride);
    }

    fetch(`/api/prompt-step-configs?${params.toString()}`)
      .then((res) => res.json())
      .then((data) => {
        const filtered = (Array.isArray(data) ? data : []).filter((item) => previewPromptStepKeys.includes(item.step_key));
        setPromptConfigs(filtered);
      });
  };

  useEffect(() => {
    fetch('/api/main-db/providers')
      .then((res) => res.json())
      .then((data) => {
        setProviders(data);
        if (data.length > 0) {
          const defaultProvider = data.find((p) => p.name === 'Dashscope') || data[0];
          setSelectedProvider(defaultProvider.id);
        }
      });

    fetch('/api/main-db/models')
      .then((res) => res.json())
      .then((data) => {
        setModels(data);
        if (data.length > 0) {
          const defaultModel = data.find((m) => m.name === 'qwen3.5-plus') || data[0];
          setSelectedModel(defaultModel.id);
        }
      });

    loadPromptConfigs();

    fetch('/api/prompts/versions')
      .then((res) => res.json())
      .then((data) => {
        setVersions(Array.isArray(data) ? data : []);
      });

    fetch('/api/pipeline-steps')
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data) && data.length > 0) {
          setPipelineSteps(data);
        }
      });

    fetch('/api/mock-cases')
      .then((res) => res.json())
      .then((data) => {
        setMockCases(data);
        if (data.length > 0) {
          setSelectedMockCase(data[0].name);
        }
      });
  }, []);

  useEffect(() => {
    loadPromptConfigs(selectedVersion);
  }, [selectedVersion]);

  const handleStartTest = () => {
    setIsRunning(true);
    setLogs('[SYSTEM] Initializing test run...\n');

    ws.current = new WebSocket(`ws://${window.location.host}/ws/run-test`);

    ws.current.onopen = () => {
      const config = {
        provider_id: useModelOverride ? selectedProvider : undefined,
        model_id: useModelOverride ? selectedModel : undefined,
        use_model_override: useModelOverride,
        input_dir: inputDir,
        prompt_version: selectedVersion || undefined,
        a3_strategy: a3Strategy,
        classification_method: classificationMethod,
        test_mode: testMode,
        real_steps: testMode === 'mock' ? effectiveRealSteps : undefined,
        case_name: testMode === 'record' ? (caseName || `case_${new Date().getTime()}`) : undefined,
        mock_case: testMode === 'mock' ? selectedMockCase : undefined,
      };
      ws.current.send(JSON.stringify(config));
    };

    ws.current.onmessage = (event) => {
      setLogs((prevLogs) => prevLogs + event.data + '\n');
    };

    ws.current.onerror = (error) => {
      setLogs((prevLogs) => prevLogs + `[SYSTEM-ERROR] WebSocket error: ${error}\n`);
      setIsRunning(false);
    };

    ws.current.onclose = () => {
      setLogs((prevLogs) => prevLogs + '\n[SYSTEM] Test finished. WebSocket closed.\n');
      setIsRunning(false);
    };
  };

  const displayedProvider = providers.find((p) => p.id === selectedProvider);
  const filteredModels = models.filter((m) => m.provider_id === selectedProvider);
  const selectedMockCaseInfo = mockCases.find((mc) => mc.name === selectedMockCase);
  const availableMockStepKeys = selectedMockCaseInfo?.available_step_keys || [];
  const availableMockStepKeySet = useMemo(() => new Set(availableMockStepKeys), [availableMockStepKeys]);
  const effectiveRealSteps = pipelineSteps
    .filter((step) => realSteps.includes(step.id) || !availableMockStepKeySet.has(step.key))
    .map((step) => step.id);

  useEffect(() => {
    if (testMode !== 'mock') {
      return;
    }

    setRealSteps(
      pipelineSteps
        .filter((step) => !availableMockStepKeySet.has(step.key))
        .map((step) => step.id),
    );
  }, [testMode, selectedMockCase, pipelineSteps, availableMockStepKeySet]);

  const handleRealStepChange = (step) => {
    if (!availableMockStepKeySet.has(step.key)) {
      return;
    }

    setRealSteps((prev) => (
      prev.includes(step.id) ? prev.filter((id) => id !== step.id) : [...prev, step.id]
    ));
  };

  const previewConfigs = promptConfigs
    .slice()
    .sort((a, b) => (a.step_order || '').localeCompare(b.step_order || ''));

  return (
    <AdminShell
      pageKey="test"
      title="测试运行"
      subtitle="保留现有测试功能与接口逻辑，仅将界面调整为更紧凑的后台控制台风格。"
      breadcrumbs="预处理控制台 / 测试运行"
    >
      <Grid container spacing={2.5}>
        <Grid item xs={12} xl={5}>
          <Stack spacing={2.5}>
            <PageSection
              title="运行参数"
              description="全局模型覆盖、提示词覆盖和测试模式都保持原有能力，仅调整展示方式。"
            >
              <Stack spacing={2}>
                <Box sx={infoCardSx}>
                  <FormControlLabel
                    control={<Checkbox checked={useModelOverride} onChange={(event) => setUseModelOverride(event.target.checked)} />}
                    label="启用全局模型覆盖（调试用）"
                    sx={{ alignItems: 'flex-start', m: 0 }}
                  />
                  <Typography variant="caption" sx={{ display: 'block', mt: 0.75 }}>
                    默认仍按数据库步骤路由执行；如需修改正式步骤映射，请进入“模型路由”。
                  </Typography>
                </Box>

                <Grid container spacing={1.5}>
                  <Grid item xs={12} md={6}>
                    <FormControl fullWidth disabled={!useModelOverride}>
                      <InputLabel>供应商</InputLabel>
                      <Select value={selectedProvider} label="供应商" onChange={(event) => setSelectedProvider(event.target.value)}>
                        {providers.map((provider) => (
                          <MenuItem key={provider.id} value={provider.id}>{provider.name}</MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                  </Grid>
                  <Grid item xs={12} md={6}>
                    <FormControl fullWidth disabled={!useModelOverride}>
                      <InputLabel>模型</InputLabel>
                      <Select value={selectedModel} label="模型" onChange={(event) => setSelectedModel(event.target.value)}>
                        {filteredModels.map((model) => (
                          <MenuItem key={model.id} value={model.id}>{model.name}</MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                  </Grid>
                  <Grid item xs={12} md={6}>
                    <TextField label="API URL" fullWidth disabled value={displayedProvider?.api_url || ''} />
                  </Grid>
                  <Grid item xs={12} md={6}>
                    <TextField label="API Key" fullWidth disabled value={displayedProvider?.display_api_key || ''} />
                  </Grid>
                </Grid>

                <TextField
                  label="输入目录"
                  fullWidth
                  value={inputDir}
                  onChange={(event) => setInputDir(event.target.value)}
                />

                <FormControl fullWidth>
                  <InputLabel>全局提示词版本覆盖</InputLabel>
                  <Select value={selectedVersion} label="全局提示词版本覆盖" onChange={(event) => setSelectedVersion(event.target.value)}>
                    <MenuItem value="">按步骤路由（默认）</MenuItem>
                    {versions.map((version) => (
                      <MenuItem key={version.version} value={String(version.version)}>
                        {`统一覆盖到 v${version.version}（${version.count} 个提示词）`}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <Typography variant="caption">
                  不选择时，每个步骤使用自己绑定的固定版本；若未固定，则默认取数据库中的最高版本。
                </Typography>

                <Grid container spacing={1.5}>
                  <Grid item xs={12} md={6}>
                    <FormControl fullWidth>
                      <InputLabel>A3 处理策略</InputLabel>
                      <Select value={a3Strategy} label="A3 处理策略" onChange={(event) => setA3Strategy(event.target.value)}>
                        <MenuItem value="split">方案 A：分割成 A4</MenuItem>
                        <MenuItem value="whole">方案 B：整体识别</MenuItem>
                        <MenuItem value="both">A/B 对比测试</MenuItem>
                      </Select>
                    </FormControl>
                  </Grid>
                  <Grid item xs={12} md={6}>
                    <FormControl fullWidth>
                      <InputLabel>分类方法</InputLabel>
                      <Select value={classificationMethod} label="分类方法" onChange={(event) => setClassificationMethod(event.target.value)}>
                        <MenuItem value="long_image">长图分类</MenuItem>
                        <MenuItem value="single_page">单页分类</MenuItem>
                      </Select>
                    </FormControl>
                  </Grid>
                </Grid>

                <Box sx={infoCardSx}>
                  <FormControl component="fieldset" fullWidth>
                    <FormLabel component="legend">测试模式</FormLabel>
                    <RadioGroup row value={testMode} onChange={(event) => setTestMode(event.target.value)} sx={{ mt: 0.75 }}>
                      <FormControlLabel value="real" control={<Radio />} label="真实测试" />
                      <FormControlLabel value="mock" control={<Radio />} label="模拟测试" />
                      <FormControlLabel value="record" control={<Radio />} label="录制测试" />
                    </RadioGroup>
                  </FormControl>
                </Box>

                {testMode === 'record' && (
                  <Box sx={infoCardSx}>
                    <TextField
                      label="录制 Case 名称"
                      fullWidth
                      value={caseName}
                      onChange={(event) => setCaseName(event.target.value)}
                      placeholder="留空则自动生成（例：case_时间戳）"
                    />
                    <Typography variant="caption" sx={{ display: 'block', mt: 1 }}>
                      录制测试将使用真实 API 运行所有步骤，并将结果保存到 tests/mock_data/ 目录。
                    </Typography>
                  </Box>
                )}

                {testMode === 'mock' && (
                  <Box sx={infoCardSx}>
                    <Stack spacing={1.5}>
                      <FormControl fullWidth>
                        <InputLabel>选择 Mock Case</InputLabel>
                        <Select value={selectedMockCase} label="选择 Mock Case" onChange={(event) => setSelectedMockCase(event.target.value)}>
                          {mockCases.map((mockCase) => (
                            <MenuItem key={mockCase.name} value={mockCase.name}>
                              {`${mockCase.name} (${mockCase.created_at})`}
                            </MenuItem>
                          ))}
                        </Select>
                      </FormControl>
                      <Typography variant="body2" color="text.secondary">
                        勾选需要真实执行的步骤；未勾选的步骤将直接复用当前 Mock Case 的产物。
                      </Typography>
                      <Typography variant="caption">
                        当前 Case 可用于 Mock 的步骤：{availableMockStepKeys.length > 0 ? availableMockStepKeys.join(', ') : '无（将全部真实执行）'}
                      </Typography>
                      <FormGroup>
                        <Grid container spacing={1}>
                          {pipelineSteps.map((step) => {
                            const mockAvailable = availableMockStepKeySet.has(step.key);
                            const checked = effectiveRealSteps.includes(step.id);
                            return (
                              <Grid item xs={12} md={6} key={step.key}>
                                <Paper sx={{ p: 1.5, borderRadius: 2, backgroundColor: '#fff', boxShadow: 'none', border: '1px solid #eef0f3' }}>
                                  <FormControlLabel
                                    control={(
                                      <Checkbox
                                        disabled={!mockAvailable}
                                        checked={checked}
                                        onChange={() => handleRealStepChange(step)}
                                      />
                                    )}
                                    label={`${step.key}. ${step.name}`}
                                    sx={{ m: 0, alignItems: 'flex-start' }}
                                  />
                                  <Typography variant="caption" sx={{ display: 'block', pl: 4 }}>
                                    {step.label}{step.description ? ` · ${step.description}` : ''}
                                  </Typography>
                                  {!mockAvailable && (
                                    <Typography variant="caption" color="warning.main" sx={{ display: 'block', pl: 4, mt: 0.5 }}>
                                      当前 Mock Case 缺少该步骤产物，只能真实执行。
                                    </Typography>
                                  )}
                                </Paper>
                              </Grid>
                            );
                          })}
                        </Grid>
                      </FormGroup>
                    </Stack>
                  </Box>
                )}
              </Stack>
            </PageSection>

            <PageSection
              title="步骤提示词预览"
              description="用于确认本次测试实际读取的提示词来源与版本。"
            >
              <Stack spacing={1.25} sx={{ maxHeight: 360, overflow: 'auto' }}>
                {previewConfigs.map((config) => (
                  <Paper
                    key={config.step_key}
                    sx={{ p: 1.5, borderRadius: 2, backgroundColor: '#fafbfc', boxShadow: 'none', border: '1px solid #eef0f3' }}
                  >
                    <Typography variant="subtitle2">{config.step_label}</Typography>
                    <Typography variant="caption" sx={{ display: 'block', mb: 0.75 }}>
                      {config.prompt_key} / v{config.resolved_version || '-'} / {config.config_source}
                    </Typography>
                    <Typography
                      variant="body2"
                      component="pre"
                      sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontFamily: 'inherit' }}
                    >
                      {config.resolved_prompt_text || '暂无提示词内容'}
                    </Typography>
                  </Paper>
                ))}
                {previewConfigs.length === 0 && (
                  <Typography variant="body2" color="text.secondary">
                    暂无步骤提示词配置。
                  </Typography>
                )}
              </Stack>
            </PageSection>
          </Stack>
        </Grid>

        <Grid item xs={12} xl={7}>
          <Stack spacing={2.5}>
            <PageSection
              title="运行日志"
              description="原有 WebSocket 运行链路不变，日志区改为更紧凑的控制台样式。"
              actions={(
                <Button
                  variant="contained"
                  startIcon={isRunning ? <CircularProgress size={16} color="inherit" /> : <PlayArrowRoundedIcon />}
                  onClick={handleStartTest}
                  disabled={isRunning}
                >
                  {isRunning ? '运行中...' : '开始测试'}
                </Button>
              )}
            >
              <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                <Paper sx={infoCardSx}>
                  <Typography variant="caption" sx={{ display: 'block' }}>当前模式</Typography>
                  <Typography variant="subtitle2">
                    {testMode === 'real' ? '真实测试' : testMode === 'mock' ? '模拟测试' : '录制测试'}
                  </Typography>
                </Paper>
                <Paper sx={infoCardSx}>
                  <Typography variant="caption" sx={{ display: 'block' }}>模型覆盖</Typography>
                  <Typography variant="subtitle2">{useModelOverride ? '已启用' : '按步骤路由'}</Typography>
                </Paper>
                <Paper sx={infoCardSx}>
                  <Typography variant="caption" sx={{ display: 'block' }}>提示词版本</Typography>
                  <Typography variant="subtitle2">{selectedVersion ? `v${selectedVersion}` : '按步骤路由'}</Typography>
                </Paper>
                <Button
                  variant="outlined"
                  startIcon={<AutoFixHighIcon />}
                  onClick={() => { window.location.href = '/whole-page'; }}
                >
                  打开整页画框
                </Button>
              </Box>
              <Box sx={{ ...terminalSx, minHeight: 560, maxHeight: 720 }}>
                <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{logs}</pre>
              </Box>
            </PageSection>
          </Stack>
        </Grid>
      </Grid>
    </AdminShell>
  );
}

export default App;
