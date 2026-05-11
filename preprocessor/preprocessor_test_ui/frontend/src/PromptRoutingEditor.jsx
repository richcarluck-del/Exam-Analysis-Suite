import React, { useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material';
import RefreshRoundedIcon from '@mui/icons-material/RefreshRounded';
import AdminShell from './AdminShell';
import PageSection from './PageSection';

function PromptRoutingEditor() {
  const [configs, setConfigs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [savingKey, setSavingKey] = useState('');
  const [message, setMessage] = useState(null);

  const loadData = async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/prompt-step-configs');
      if (!response.ok) {
        throw new Error('加载提示词路由配置失败');
      }
      const data = await response.json();
      setConfigs(data);
      setMessage(null);
    } catch (error) {
      setMessage({ severity: 'error', text: error.message || '加载失败' });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const updateLocalConfig = (stepKey, patch) => {
    setConfigs((prev) => prev.map((item) => (item.step_key === stepKey ? { ...item, ...patch } : item)));
  };

  const handleSave = async (config) => {
    setSavingKey(config.step_key);
    try {
      const response = await fetch(`/api/prompt-step-configs/${config.step_key}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          selected_version: config.selected_version ?? null,
          is_active: config.is_active,
        }),
      });

      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || '保存失败');
      }

      updateLocalConfig(config.step_key, payload);
      setMessage({ severity: 'success', text: `已保存 ${config.step_label}` });
    } catch (error) {
      setMessage({ severity: 'error', text: error.message || '保存失败' });
    } finally {
      setSavingKey('');
    }
  };

  return (
    <AdminShell
      pageKey="prompt-routing"
      title="提示词路由"
      subtitle="每个步骤绑定标准 Prompt Key，并可选择固定版本或默认最高版本。功能逻辑保持不变。"
      breadcrumbs="预处理控制台 / 提示词路由"
      actions={(
        <Button variant="outlined" startIcon={<RefreshRoundedIcon />} onClick={loadData} disabled={loading}>
          刷新
        </Button>
      )}
    >
      <Stack spacing={2.5}>
        {message && (
          <Alert severity={message.severity} onClose={() => setMessage(null)}>
            {message.text}
          </Alert>
        )}

        <PageSection title="数据库统一提示词路由" description="这里的配置会直接影响自动流程运行；界面仅调整为后台表格式布局。">
          {loading ? (
            <Typography color="text.secondary">加载中...</Typography>
          ) : (
            <TableContainer component={Paper} sx={{ borderRadius: 2.5, boxShadow: 'none', border: '1px solid #eef0f3' }}>
              <Table>
                <TableHead>
                  <TableRow>
                    <TableCell>步骤</TableCell>
                    <TableCell>启用</TableCell>
                    <TableCell>版本策略</TableCell>
                    <TableCell>当前解析</TableCell>
                    <TableCell>Prompt 预览</TableCell>
                    <TableCell align="right">操作</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {configs.map((config) => {
                    const saveDisabled = savingKey === config.step_key;
                    const selectValue = config.selected_version ?? 'latest';

                    return (
                      <TableRow key={config.step_key} hover>
                        <TableCell sx={{ minWidth: 240 }}>
                          <Typography variant="subtitle2">{config.step_label}</Typography>
                          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.25 }}>
                            {config.description}
                          </Typography>
                          <Typography variant="caption" sx={{ display: 'block', mt: 0.5 }}>
                            {config.step_key}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <Stack spacing={0.5} alignItems="flex-start">
                            <Switch checked={Boolean(config.is_active)} onChange={(event) => updateLocalConfig(config.step_key, { is_active: event.target.checked })} />
                            <Chip size="small" label={config.is_active ? '启用' : '停用'} color={config.is_active ? 'success' : 'default'} variant={config.is_active ? 'filled' : 'outlined'} />
                          </Stack>
                        </TableCell>
                        <TableCell sx={{ minWidth: 180 }}>
                          <FormControl fullWidth>
                            <InputLabel>版本策略</InputLabel>
                            <Select
                              value={selectValue}
                              label="版本策略"
                              onChange={(event) => {
                                const value = event.target.value;
                                updateLocalConfig(config.step_key, {
                                  selected_version: value === 'latest' ? null : Number(value),
                                });
                              }}
                            >
                              <MenuItem value="latest">默认最高版本</MenuItem>
                              {(config.available_versions || []).map((version) => (
                                <MenuItem key={version} value={version}>{`固定 v${version}`}</MenuItem>
                              ))}
                            </Select>
                          </FormControl>
                        </TableCell>
                        <TableCell sx={{ minWidth: 240 }}>
                          <Typography variant="body2">{config.prompt_display_name || config.prompt_key}</Typography>
                          <Typography variant="caption" sx={{ display: 'block', mt: 0.5 }}>
                            Prompt Key：{config.prompt_key}
                          </Typography>
                          <Typography variant="caption" sx={{ display: 'block' }}>
                            v{config.resolved_version || '-'} / {config.config_source}
                          </Typography>
                        </TableCell>
                        <TableCell sx={{ minWidth: 320 }}>
                          <Box
                            sx={{
                              maxHeight: 96,
                              overflow: 'auto',
                              borderRadius: 2,
                              border: '1px solid #eef0f3',
                              backgroundColor: '#fafbfc',
                              p: 1.25,
                            }}
                          >
                            <Typography variant="body2" component="pre" sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontFamily: 'inherit' }}>
                              {config.resolved_prompt_text || '暂无提示词内容'}
                            </Typography>
                          </Box>
                        </TableCell>
                        <TableCell align="right">
                          <Button variant="contained" size="small" onClick={() => handleSave(config)} disabled={saveDisabled}>
                            {savingKey === config.step_key ? '保存中...' : '保存'}
                          </Button>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </PageSection>
      </Stack>
    </AdminShell>
  );
}

export default PromptRoutingEditor;
