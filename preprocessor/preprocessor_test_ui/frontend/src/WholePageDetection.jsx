import React, { useEffect, useRef, useState } from 'react';
import {
  Alert,
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
  Snackbar,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import PlayArrowRoundedIcon from '@mui/icons-material/PlayArrowRounded';
import StopRoundedIcon from '@mui/icons-material/StopRounded';
import RefreshRoundedIcon from '@mui/icons-material/RefreshRounded';
import AdminShell from './AdminShell';
import PageSection from './PageSection';
import { terminalSx } from './adminTheme';

const wholePagePromptStepKeys = [
  'preprocessor.whole_page_perspective_correction',
  'preprocessor.whole_page_detection',
];

const infoCardSx = {
  p: 2,
  borderRadius: 3,
  border: '1px solid #eef0f3',
  backgroundColor: '#fafbfc',
  boxShadow: 'none',
};

function WholePageDetection() {
  const [providers, setProviders] = useState([]);
  const [models, setModels] = useState([]);
  const [promptConfigs, setPromptConfigs] = useState([]);
  const [versions, setVersions] = useState([]);

  const [selectedProvider, setSelectedProvider] = useState('');
  const [selectedModel, setSelectedModel] = useState('');
  const [useModelOverride, setUseModelOverride] = useState(false);
  const [inputDir, setInputDir] = useState('D:\\10739\\Exam-Analysis-Suite\\preprocessor\\my_test_images');
  const [selectedVersion, setSelectedVersion] = useState('');
  const [testMode, setTestMode] = useState('real');
  const [caseName, setCaseName] = useState('');

  const [stitchingMethod, setStitchingMethod] = useState('vstack');
  const [overlapPixels, setOverlapPixels] = useState(0);

  const [detectQuestions, setDetectQuestions] = useState(true);
  const [detectAnswers, setDetectAnswers] = useState(true);
  const [outputFormat, setOutputFormat] = useState('individual');

  const [logs, setLogs] = useState('欢迎使用整页画框测试工具。\n');
  const [isRunning, setIsRunning] = useState(false);
  const [previewImage, setPreviewImage] = useState(null);
  const [detectedQuestions, setDetectedQuestions] = useState([]);
  const [snackbar, setSnackbar] = useState({ open: false, message: '', severity: 'info' });

  const ws = useRef(null);
  const logsEndRef = useRef(null);

  const loadPromptConfigs = (versionOverride = '') => {
    const params = new URLSearchParams({ module_name: 'preprocessor' });
    if (versionOverride) {
      params.set('version_override', versionOverride);
    }
    fetch(`/api/prompt-step-configs?${params.toString()}`)
      .then((res) => res.json())
      .then((data) => {
        const filtered = (Array.isArray(data) ? data : []).filter((item) => wholePagePromptStepKeys.includes(item.step_key));
        setPromptConfigs(filtered);
      });
  };

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  useEffect(() => {
    fetch('/api/main-db/providers')
      .then((res) => res.json())
      .then((data) => {
        setProviders(data);
        if (data.length > 0) {
          const defaultProvider = data.find((provider) => provider.name === 'Dashscope') || data[0];
          setSelectedProvider(defaultProvider.id);
        }
      });

    fetch('/api/main-db/models')
      .then((res) => res.json())
      .then((data) => {
        setModels(data);
        if (data.length > 0) {
          const defaultModel = data.find((model) => model.name === 'qwen3.5-plus') || data[0];
          setSelectedModel(defaultModel.id);
        }
      });

    loadPromptConfigs();

    fetch('/api/prompts/versions')
      .then((res) => res.json())
      .then((data) => {
        setVersions(Array.isArray(data) ? data : []);
      });
  }, []);

  useEffect(() => {
    loadPromptConfigs(selectedVersion);
  }, [selectedVersion]);

  const appendLog = (message) => {
    setLogs((prev) => prev + '\n' + message);
  };

  const showSnackbar = (message, severity) => {
    setSnackbar({ open: true, message, severity });
  };

  const connectWebSocket = () => {
    ws.current = new WebSocket(`ws://${window.location.host}/ws/run-whole-page`);

    ws.current.onopen = () => {
      appendLog('[SYSTEM] WebSocket 连接已建立');
    };

    ws.current.onmessage = (event) => {
      appendLog(event.data);

      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'preview') {
          setPreviewImage(msg.image);
        } else if (msg.type === 'detection_result') {
          setDetectedQuestions(msg.questions);
        }
      } catch {
        // ignore non-json message
      }
    };

    ws.current.onclose = () => {
      appendLog('[SYSTEM] WebSocket 连接已关闭');
      setIsRunning(false);
    };

    ws.current.onerror = () => {
      appendLog('[SYSTEM-ERROR] WebSocket 错误');
      setIsRunning(false);
      showSnackbar('WebSocket 连接错误', 'error');
    };
  };

  const startTest = () => {
    if (!selectedProvider || !selectedModel) {
      showSnackbar('请选择模型提供商和模型', 'warning');
      return;
    }

    setIsRunning(true);
    setLogs('开始测试...\n');
    setDetectedQuestions([]);
    setPreviewImage(null);

    connectWebSocket();

    setTimeout(() => {
      const config = {
        provider_id: useModelOverride ? selectedProvider : undefined,
        model_id: useModelOverride ? selectedModel : undefined,
        use_model_override: useModelOverride,
        input_dir: inputDir,
        prompt_version: selectedVersion || undefined,
        stitching_method: stitchingMethod,
        overlap_pixels: overlapPixels,
        detect_questions: detectQuestions,
        detect_answers: detectAnswers,
        output_format: outputFormat,
        test_mode: testMode,
        case_name: caseName || `whole_page_${Date.now()}`,
      };

      ws.current.send(JSON.stringify(config));
    }, 1000);
  };

  const stopTest = () => {
    if (ws.current) {
      ws.current.close();
    }
    setIsRunning(false);
    appendLog('[SYSTEM] 测试已停止');
  };

  return (
    <>
      <AdminShell
        pageKey="whole-page"
        title="整页画框"
        subtitle="保留整页测试链路、拼接配置和识别配置，只调整为更轻量的后台布局。"
        breadcrumbs="预处理控制台 / 整页画框"
        actions={(
          <Button variant="outlined" startIcon={<RefreshRoundedIcon />} onClick={() => window.location.reload()}>
            刷新页面
          </Button>
        )}
      >
        <Grid container spacing={2.5}>
          <Grid item xs={12} xl={4}>
            <Stack spacing={2.5}>
              <PageSection title="基础配置" description="模型覆盖、提示词覆盖和测试模式保持现有功能。">
                <Stack spacing={2}>
                  <Box sx={infoCardSx}>
                    <FormControlLabel
                      control={<Checkbox checked={useModelOverride} onChange={(event) => setUseModelOverride(event.target.checked)} />}
                      label="启用全局模型覆盖（默认按数据库步骤路由执行）"
                      sx={{ alignItems: 'flex-start', m: 0 }}
                    />
                    <Typography variant="caption" sx={{ display: 'block', mt: 0.75 }}>
                      如需修改整页画框的正式模型绑定，请前往“模型路由”。
                    </Typography>
                  </Box>

                  <Grid container spacing={1.5}>
                    <Grid item xs={12} md={6}>
                      <FormControl fullWidth disabled={!useModelOverride}>
                        <InputLabel>模型提供商</InputLabel>
                        <Select value={selectedProvider} label="模型提供商" onChange={(event) => setSelectedProvider(event.target.value)}>
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
                          {models.map((model) => (
                            <MenuItem key={model.id} value={model.id}>{model.name}</MenuItem>
                          ))}
                        </Select>
                      </FormControl>
                    </Grid>
                  </Grid>

                  <TextField label="输入目录" fullWidth value={inputDir} onChange={(event) => setInputDir(event.target.value)} />

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
                  <Typography variant="caption">整页画框默认使用步骤路由中的提示词版本；这里只在调试时统一覆盖。</Typography>

                  <Box sx={infoCardSx}>
                    <FormControl component="fieldset" fullWidth>
                      <FormLabel component="legend">测试模式</FormLabel>
                      <RadioGroup row value={testMode} onChange={(event) => setTestMode(event.target.value)} sx={{ mt: 0.75 }}>
                        <FormControlLabel value="real" control={<Radio />} label="真实测试" />
                        <FormControlLabel value="record" control={<Radio />} label="录制模式" />
                      </RadioGroup>
                    </FormControl>
                  </Box>

                  {testMode === 'record' && (
                    <Box sx={infoCardSx}>
                      <TextField
                        fullWidth
                        label="案例名称（可选）"
                        value={caseName}
                        onChange={(event) => setCaseName(event.target.value)}
                        placeholder="留空则自动生成"
                      />
                    </Box>
                  )}
                </Stack>
              </PageSection>

              <PageSection title="图片拼接配置" description="拼接方式、重叠像素等参数保持不变。">
                <Stack spacing={2}>
                  <TextField
                    fullWidth
                    label="输入目录"
                    value={inputDir}
                    onChange={(event) => setInputDir(event.target.value)}
                    helperText="从此目录读取试卷图片"
                  />
                  <FormControl fullWidth>
                    <InputLabel>拼接方式</InputLabel>
                    <Select value={stitchingMethod} label="拼接方式" onChange={(event) => setStitchingMethod(event.target.value)}>
                      <MenuItem value="vstack">垂直拼接</MenuItem>
                      <MenuItem value="hstack">水平拼接</MenuItem>
                      <MenuItem value="smart">智能拼接</MenuItem>
                    </Select>
                  </FormControl>
                  <TextField
                    fullWidth
                    label="重叠像素（可选）"
                    type="number"
                    value={overlapPixels}
                    onChange={(event) => setOverlapPixels(parseInt(event.target.value, 10) || 0)}
                    helperText="防止题目被拼接缝切断"
                  />
                </Stack>
              </PageSection>

              <PageSection title="识别配置" description="识别选项和输出格式保持原有逻辑。">
                <Stack spacing={2}>
                  <Box sx={infoCardSx}>
                    <FormGroup>
                      <FormControlLabel control={<Checkbox checked={detectQuestions} onChange={(event) => setDetectQuestions(event.target.checked)} />} label="识别题目区域" />
                      <FormControlLabel control={<Checkbox checked={detectAnswers} onChange={(event) => setDetectAnswers(event.target.checked)} />} label="识别答案区域" />
                    </FormGroup>
                  </Box>
                  <Box sx={infoCardSx}>
                    <FormControl component="fieldset" fullWidth>
                      <FormLabel component="legend">输出格式</FormLabel>
                      <RadioGroup value={outputFormat} onChange={(event) => setOutputFormat(event.target.value)} sx={{ mt: 0.75 }}>
                        <FormControlLabel value="individual" control={<Radio />} label="每题单独图片" />
                        <FormControlLabel value="combined" control={<Radio />} label="题目 + 答案合并" />
                      </RadioGroup>
                    </FormControl>
                  </Box>
                  <Stack direction="row" spacing={1.25}>
                    <Button
                      variant="contained"
                      startIcon={isRunning ? <CircularProgress size={16} color="inherit" /> : <PlayArrowRoundedIcon />}
                      onClick={startTest}
                      disabled={isRunning}
                    >
                      {isRunning ? '测试中...' : '开始测试'}
                    </Button>
                    <Button variant="outlined" color="error" startIcon={<StopRoundedIcon />} onClick={stopTest} disabled={!isRunning}>
                      停止
                    </Button>
                  </Stack>
                </Stack>
              </PageSection>
            </Stack>
          </Grid>

          <Grid item xs={12} xl={8}>
            <Stack spacing={2.5}>
              <PageSection title="步骤提示词预览" description="用于确认整页画框流程当前会读取的提示词版本。">
                <Stack spacing={1.25} sx={{ maxHeight: 220, overflow: 'auto' }}>
                  {promptConfigs.map((config) => (
                    <Paper
                      key={config.step_key}
                      sx={{ p: 1.5, borderRadius: 2, backgroundColor: '#fafbfc', boxShadow: 'none', border: '1px solid #eef0f3' }}
                    >
                      <Typography variant="subtitle2">{config.step_label}</Typography>
                      <Typography variant="caption" sx={{ display: 'block', mb: 0.75 }}>
                        {config.prompt_key} / v{config.resolved_version || '-'} / {config.config_source}
                      </Typography>
                      <Typography variant="body2" component="pre" sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontFamily: 'inherit' }}>
                        {config.resolved_prompt_text || '暂无提示词内容'}
                      </Typography>
                    </Paper>
                  ))}
                  {promptConfigs.length === 0 && <Typography color="text.secondary">暂无步骤提示词配置</Typography>}
                </Stack>
              </PageSection>

              <PageSection title="拼接预览" description="测试开始后展示拼接后的长图。">
                {previewImage ? (
                  <Box component="img" src={previewImage} alt="拼接预览" sx={{ width: '100%', maxHeight: 460, objectFit: 'contain', borderRadius: 2 }} />
                ) : (
                  <Box
                    sx={{
                      height: 320,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      borderRadius: 2,
                      border: '1px dashed #c9cdd4',
                      backgroundColor: '#fafbfc',
                    }}
                  >
                    <Typography color="text.secondary">测试开始后将显示拼接后的长图预览</Typography>
                  </Box>
                )}
              </PageSection>

              {detectedQuestions.length > 0 && (
                <PageSection title="识别结果" description={`当前共识别 ${detectedQuestions.length} 道题。`}>
                  <Grid container spacing={1.5}>
                    {detectedQuestions.map((question, index) => (
                      <Grid item xs={12} sm={6} lg={4} key={index}>
                        <Paper sx={{ p: 1.75, borderRadius: 2.5, backgroundColor: '#fafbfc', boxShadow: 'none', border: '1px solid #eef0f3' }}>
                          <Typography variant="subtitle2">第 {question.number} 题</Typography>
                          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                            题目：{question.has_question ? '✓' : '✗'}
                          </Typography>
                          <Typography variant="body2" color="text.secondary">
                            答案：{question.has_answer ? '✓' : '✗'}
                          </Typography>
                        </Paper>
                      </Grid>
                    ))}
                  </Grid>
                </PageSection>
              )}

              <PageSection title="运行日志" description="保留原始运行日志输出，仅调整为控制台面板样式。">
                <Box sx={{ ...terminalSx, height: 420 }}>
                  {logs.split('\n').map((line, index) => (
                    <Box key={index} sx={{ mb: 0.5 }}>
                      {line.startsWith('[SYSTEM]') && <Typography component="span" sx={{ color: '#8fb2ff', fontSize: 'inherit' }}>{line}</Typography>}
                      {line.startsWith('[STDOUT]') && <Typography component="span" sx={{ color: '#8ad7a3', fontSize: 'inherit' }}>{line}</Typography>}
                      {line.startsWith('[STDERR]') && <Typography component="span" sx={{ color: '#ff9d9d', fontSize: 'inherit' }}>{line}</Typography>}
                      {line.startsWith('✅') && <Typography component="span" sx={{ color: '#a8e6b1', fontSize: 'inherit' }}>{line}</Typography>}
                      {!line.startsWith('[SYSTEM]') && !line.startsWith('[STDOUT]') && !line.startsWith('[STDERR]') && !line.startsWith('✅') && (
                        <Typography component="span" sx={{ color: 'inherit', fontSize: 'inherit' }}>{line}</Typography>
                      )}
                    </Box>
                  ))}
                  <div ref={logsEndRef} />
                </Box>
              </PageSection>
            </Stack>
          </Grid>
        </Grid>
      </AdminShell>

      <Snackbar open={snackbar.open} autoHideDuration={6000} onClose={() => setSnackbar({ ...snackbar, open: false })}>
        <Alert severity={snackbar.severity} sx={{ width: '100%' }}>
          {snackbar.message}
        </Alert>
      </Snackbar>
    </>
  );
}

export default WholePageDetection;
