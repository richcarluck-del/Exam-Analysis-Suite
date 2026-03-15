import React, { useState, useEffect, useRef } from 'react';
import {
  AppBar,
  Toolbar,
  Typography,
  Container,
  Grid,
  Paper,
  Select,
  MenuItem,
  InputLabel,
  FormControl,
  TextField,
  Button,
  Box,
  RadioGroup,
  FormControlLabel,
  Radio,
  FormLabel,
  Checkbox,
  FormGroup,
  CircularProgress,
} from '@mui/material';
import { createTheme, ThemeProvider } from '@mui/material/styles';

const theme = createTheme({
  palette: {
    mode: 'dark',
    primary: {
      main: '#90caf9',
    },
    background: {
      default: '#121212',
      paper: '#1e1e1e',
    },
  },
});

const pipelineSteps = [
    { id: 1, name: 'perspective_correction' },
    { id: 2, name: 'classify' },
    { id: 3, name: 'analyze_layout' },
    { id: 4, name: 'extract_content' },
    { id: 5, name: 'merge_results' },
    { id: 6, name: 'draw_output' },
];

const llmSteps = [1, 2, 4]; // Steps that use LLM

function App() {
  // Data states
  const [providers, setProviders] = useState([]);
  const [models, setModels] = useState([]);
  const [prompts, setPrompts] = useState([]);

  // Form states
  const [selectedProvider, setSelectedProvider] = useState('');
  const [selectedModel, setSelectedModel] = useState('');
  const [inputDir, setInputDir] = useState('D:\\10739\\Exam-Analysis-Suite\\preprocessor\\my_test_images');
  const [selectedPrompt, setSelectedPrompt] = useState('');
  const [testMode, setTestMode] = useState('real');
  const [mockSteps, setMockSteps] = useState([]);

  // UI/Connection states
  const [logs, setLogs] = useState('Welcome to the Preprocessor Test UI.\n');
  const [isRunning, setIsRunning] = useState(false);
  const ws = useRef(null);

  // Fetch initial data on component mount
  useEffect(() => {
    // Fetch providers
    fetch('/api/providers')
      .then(res => res.json())
      .then(data => {
        setProviders(data);
        if (data.length > 0) {
          const defaultProvider = data.find(p => p.name === 'Dashscope') || data[0];
          setSelectedProvider(defaultProvider.id);
        }
      });

    // Fetch models
    fetch('/api/models')
      .then(res => res.json())
      .then(data => {
        setModels(data);
         if (data.length > 0) {
          const defaultModel = data.find(m => m.name === 'qwen-vl-max') || data[0];
          setSelectedModel(defaultModel.id);
        }
      });

    // Fetch prompts
    fetch('/api/prompts')
      .then(res => res.json())
      .then(data => {
        setPrompts(data);
        if (data.length > 0) {
          const defaultPrompt = data.find(p => p.name.includes('v4')) || data[0];
          setSelectedPrompt(defaultPrompt.id);
        }
      });
  }, []);

  const handleStartTest = () => {
    setIsRunning(true);
    setLogs('[SYSTEM] Initializing test run...\n');
    
    ws.current = new WebSocket(`ws://${window.location.host}/ws/run-test`);

    ws.current.onopen = () => {
        const config = {
            provider_id: selectedProvider,
            model_id: selectedModel,
            input_dir: inputDir,
            prompt_id: selectedPrompt,
            test_mode: testMode,
            mock_steps: testMode === 'mock' ? mockSteps : [],
        };
        ws.current.send(JSON.stringify(config));
    };

    ws.current.onmessage = (event) => {
        setLogs(prevLogs => prevLogs + event.data + '\n');
    };

    ws.current.onerror = (error) => {
        setLogs(prevLogs => prevLogs + `[SYSTEM-ERROR] WebSocket error: ${error}\n`);
        setIsRunning(false);
    };

    ws.current.onclose = () => {
        setLogs(prevLogs => prevLogs + '\n[SYSTEM] Test finished. WebSocket closed.\n');
        setIsRunning(false);
    };
  };

  const handleMockStepChange = (stepId) => {
    setMockSteps(prev => 
      prev.includes(stepId) ? prev.filter(id => id !== stepId) : [...prev, stepId]
    );
  };

  const displayedProvider = providers.find(p => p.id === selectedProvider);
  const filteredModels = models.filter(m => m.provider_id === selectedProvider);
  const displayedPrompt = prompts.find(p => p.id === selectedPrompt);

  return (
    <ThemeProvider theme={theme}>
      <AppBar position="static">
        <Toolbar>
          <Typography variant="h6">Preprocessor Test UI</Typography>
        </Toolbar>
      </AppBar>
      <Container maxWidth={false} sx={{ mt: 4, mb: 4 }}>
        <Grid container spacing={3}>
          <Grid item xs={12} md={5}>
            <Paper sx={{ p: 3, height: '100%' }}>
              <Typography variant="h5" gutterBottom>测试配置</Typography>
              
              <FormControl fullWidth margin="normal">
                <InputLabel>1. 选择供应商</InputLabel>
                <Select 
                  value={selectedProvider} 
                  label="1. 选择供应商" 
                  onChange={e => setSelectedProvider(e.target.value)}
                  MenuProps={{ PaperProps: { sx: { '& .MuiMenuItem-root': { textAlign: 'left' } } } }}
                >
                  {providers.map(p => <MenuItem key={p.id} value={p.id}>{p.name}</MenuItem>)}
                </Select>
              </FormControl>

              <TextField label="API URL" variant="outlined" margin="normal" fullWidth disabled value={displayedProvider?.api_url || ''} />
              <TextField label="API Key" variant="outlined" margin="normal" fullWidth disabled value={displayedProvider?.encrypted_api_key || ''} />

              <FormControl fullWidth margin="normal">
                <InputLabel>2. 选择模型</InputLabel>
                <Select 
                  value={selectedModel} 
                  label="2. 选择模型" 
                  onChange={e => setSelectedModel(e.target.value)}
                  MenuProps={{ PaperProps: { sx: { '& .MuiMenuItem-root': { textAlign: 'left' } } } }}
                >
                  {filteredModels.map(m => <MenuItem key={m.id} value={m.id}>{m.name}</MenuItem>)}
                </Select>
              </FormControl>

              <TextField 
                label="3. 输入目录" 
                variant="outlined" 
                margin="normal" 
                fullWidth
                value={inputDir}
                onChange={e => setInputDir(e.target.value)}
                inputProps={{ style: { textAlign: 'left' } }}
              />

              <FormControl fullWidth margin="normal">
                <InputLabel>4. 选择提示词</InputLabel>
                <Select value={selectedPrompt} label="4. 选择提示词" onChange={e => setSelectedPrompt(e.target.value)}>
                   {prompts.map(p => <MenuItem key={p.id} value={p.id}>{p.name}</MenuItem>)}
                </Select>
              </FormControl>

              <Paper variant="outlined" sx={{ p: 2, mt: 1, backgroundColor: '#2d2d2d', minHeight: 150, overflow: 'auto', textAlign: 'left'}}>
                 <Typography variant="body2" style={{ whiteSpace: 'pre-wrap', textAlign: 'left' }}>
                  {displayedPrompt?.versions?.[0]?.prompt_text || 'Select a prompt to see its content.'}
                </Typography>
              </Paper>

              <FormControl component="fieldset" margin="normal">
                <FormLabel component="legend">5. 测试模式</FormLabel>
                <RadioGroup row value={testMode} onChange={e => setTestMode(e.target.value)}>
                  <FormControlLabel value="real" control={<Radio />} label="真实测试" />
                  <FormControlLabel value="mock" control={<Radio />} label="模拟测试" />
                </RadioGroup>
              </FormControl>

              {testMode === 'mock' && (
                <Box>
                  <Typography variant="subtitle2" gutterBottom sx={{ mt: 1 }}>如果选择模拟测试，请勾选需要 **模拟运行** 的步骤:</Typography>
                  <FormGroup row>
                    {pipelineSteps.map(step => (
                      <FormControlLabel 
                        key={step.id} 
                        control={<Checkbox 
                          disabled={!llmSteps.includes(step.id)}
                          checked={mockSteps.includes(step.id)}
                          onChange={() => handleMockStepChange(step.id)}
                        />} 
                        label={`${step.id}. ${step.name}`} 
                        sx={{ width: '48%' }}
                      />
                    ))}
                  </FormGroup>
                </Box>
              )}

            </Paper>
          </Grid>

          <Grid item xs={12} md={7}>
            <Paper sx={{ p: 3, height: 'calc(100vh - 128px)' }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Typography variant="h5" gutterBottom>日志输出</Typography>
                <Button variant="contained" color="primary" size="large" onClick={handleStartTest} disabled={isRunning}>
                  {isRunning ? <CircularProgress size={24} /> : '开始测试'}
                </Button>
              </Box>
              <Paper variant="outlined" sx={{ mt: 2, p: 2, flexGrow: 1, backgroundColor: '#000', color: '#fff', fontFamily: 'monospace', overflow: 'auto', textAlign: 'left' }}>
                <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all', textAlign: 'left' }}>{logs}</pre>
              </Paper>
            </Paper>
          </Grid>
        </Grid>
      </Container>
    </ThemeProvider>
  );
}

export default App;
