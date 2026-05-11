import React, { useEffect, useMemo, useState } from 'react';
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
import StorageOutlinedIcon from '@mui/icons-material/StorageOutlined';
import AdminShell from './AdminShell';
import PageSection from './PageSection';

function ModelRoutingEditor() {
  const [configs, setConfigs] = useState([]);
  const [providers, setProviders] = useState([]);
  const [models, setModels] = useState([]);
  const [loading, setLoading] = useState(true);
  const [savingKey, setSavingKey] = useState('');
  const [message, setMessage] = useState(null);

  const modelsByProvider = useMemo(() => models.reduce((acc, model) => {
    const providerId = model.provider_id;
    if (!acc[providerId]) {
      acc[providerId] = [];
    }
    acc[providerId].push(model);
    return acc;
  }, {}), [models]);

  const loadData = async () => {
    setLoading(true);
    try {
      const [configsRes, providersRes, modelsRes] = await Promise.all([
        fetch('/api/main-db/llm-step-configs'),
        fetch('/api/main-db/providers'),
        fetch('/api/main-db/models'),
      ]);

      if (!configsRes.ok || !providersRes.ok || !modelsRes.ok) {
        throw new Error('加载模型路由配置失败');
      }

      const [configsData, providersData, modelsData] = await Promise.all([
        configsRes.json(),
        providersRes.json(),
        modelsRes.json(),
      ]);

      setConfigs(configsData);
      setProviders(providersData);
      setModels(modelsData);
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
    setConfigs((prev) => prev.map((item) => (item.step_key !== stepKey ? item : { ...item, ...patch })));
  };

  const handleProviderChange = (stepKey, providerId) => {
    const nextModels = modelsByProvider[providerId] || [];
    const nextModelId = nextModels[0]?.id || '';
    const nextModelName = nextModels[0]?.name || null;
    const nextProviderName = providers.find((item) => item.id === providerId)?.name || null;

    updateLocalConfig(stepKey, {
      provider_id: providerId,
      provider_name: nextProviderName,
      model_id: nextModelId,
      model_name: nextModelName,
    });
  };

  const handleModelChange = (stepKey, modelId) => {
    const model = models.find((item) => item.id === modelId);
    updateLocalConfig(stepKey, {
      model_id: modelId,
      model_name: model?.name || null,
    });
  };

  const handleSave = async (config) => {
    setSavingKey(config.step_key);
    try {
      const response = await fetch(`/api/main-db/llm-step-configs/${config.step_key}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider_id: config.provider_id,
          model_id: config.model_id,
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
      pageKey="model-routing"
      title="模型路由"
      subtitle="每个自动步骤绑定唯一的“供应商 + 模型”。功能保持原样，仅改为更紧凑的后台配置表格。"
      breadcrumbs="预处理控制台 / 模型路由"
      actions={[
        <Button key="refresh" variant="outlined" startIcon={<RefreshRoundedIcon />} onClick={loadData} disabled={loading}>刷新</Button>,
        <Button key="manage" variant="contained" startIcon={<StorageOutlinedIcon />} onClick={() => { window.location.href = '/model-management'; }}>模型管理</Button>,
      ]}
    >
      <Stack spacing={2.5}>
        {message && (
          <Alert severity={message.severity} onClose={() => setMessage(null)}>
            {message.text}
          </Alert>
        )}

        <PageSection title="主数据库统一路由" description="本页直接读写主数据库；新增供应商或模型请先到“模型管理”。">
          {loading ? (
            <Typography color="text.secondary">加载中...</Typography>
          ) : (
            <TableContainer component={Paper} sx={{ borderRadius: 2.5, boxShadow: 'none', border: '1px solid #eef0f3' }}>
              <Table>
                <TableHead>
                  <TableRow>
                    <TableCell>步骤</TableCell>
                    <TableCell>启用</TableCell>
                    <TableCell>供应商</TableCell>
                    <TableCell>模型</TableCell>
                    <TableCell>当前绑定</TableCell>
                    <TableCell align="right">操作</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {configs.map((config) => {
                    const availableModels = modelsByProvider[config.provider_id] || [];
                    const saveDisabled = !config.provider_id || !config.model_id || savingKey === config.step_key;
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
                            <InputLabel>供应商</InputLabel>
                            <Select value={config.provider_id || ''} label="供应商" onChange={(event) => handleProviderChange(config.step_key, event.target.value)}>
                              {providers.map((provider) => (
                                <MenuItem key={provider.id} value={provider.id}>{provider.name}</MenuItem>
                              ))}
                            </Select>
                          </FormControl>
                        </TableCell>
                        <TableCell sx={{ minWidth: 190 }}>
                          <FormControl fullWidth>
                            <InputLabel>模型</InputLabel>
                            <Select value={config.model_id || ''} label="模型" onChange={(event) => handleModelChange(config.step_key, event.target.value)}>
                              {availableModels.map((model) => (
                                <MenuItem key={model.id} value={model.id}>{model.name}</MenuItem>
                              ))}
                            </Select>
                          </FormControl>
                        </TableCell>
                        <TableCell sx={{ minWidth: 200 }}>
                          <Typography variant="body2">{config.provider_name || '未配置'} / {config.model_name || '未配置'}</Typography>
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

export default ModelRoutingEditor;
