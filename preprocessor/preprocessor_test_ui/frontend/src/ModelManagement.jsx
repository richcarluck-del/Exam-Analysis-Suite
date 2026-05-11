import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
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
import AccountTreeOutlinedIcon from '@mui/icons-material/AccountTreeOutlined';
import AdminShell from './AdminShell';
import PageSection from './PageSection';

const infoCardSx = {
  p: 2,
  borderRadius: 3,
  border: '1px solid #eef0f3',
  backgroundColor: '#fafbfc',
  boxShadow: 'none',
};

const emptyProviderForm = {
  name: '',
  api_url: '',
  api_key: '',
};

const emptyModelForm = {
  provider_id: '',
  name: '',
};

function ModelManagement() {
  const [providers, setProviders] = useState([]);
  const [models, setModels] = useState([]);
  const [loading, setLoading] = useState(true);
  const [providerSubmitting, setProviderSubmitting] = useState(false);
  const [modelSubmitting, setModelSubmitting] = useState(false);
  const [providerForm, setProviderForm] = useState(emptyProviderForm);
  const [modelForm, setModelForm] = useState(emptyModelForm);
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
      const [providersRes, modelsRes] = await Promise.all([
        fetch('/api/main-db/providers'),
        fetch('/api/main-db/models'),
      ]);

      if (!providersRes.ok || !modelsRes.ok) {
        throw new Error('加载主数据库模型管理数据失败');
      }

      const [providersData, modelsData] = await Promise.all([
        providersRes.json(),
        modelsRes.json(),
      ]);

      setProviders(Array.isArray(providersData) ? providersData : []);
      setModels(Array.isArray(modelsData) ? modelsData : []);
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

  const handleProviderSubmit = async () => {
    setProviderSubmitting(true);
    try {
      const response = await fetch('/api/main-db/providers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(providerForm),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || '保存供应商失败');
      }

      const provider = payload.provider;
      setProviderForm(emptyProviderForm);
      setModelForm((prev) => ({
        ...prev,
        provider_id: provider?.id || prev.provider_id,
      }));
      await loadData();
      setMessage({
        severity: 'success',
        text: payload.created ? `已新增供应商：${provider.name}` : `已更新供应商：${provider.name}`,
      });
    } catch (error) {
      setMessage({ severity: 'error', text: error.message || '保存供应商失败' });
    } finally {
      setProviderSubmitting(false);
    }
  };

  const handleModelSubmit = async () => {
    setModelSubmitting(true);
    try {
      const response = await fetch(`/api/main-db/providers/${modelForm.provider_id}/models`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: modelForm.name }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || '新增模型失败');
      }

      setModelForm((prev) => ({ ...prev, name: '' }));
      await loadData();
      setMessage({
        severity: payload.created ? 'success' : 'info',
        text: payload.created ? `已新增模型：${payload.model.name}` : `模型已存在：${payload.model.name}`,
      });
    } catch (error) {
      setMessage({ severity: 'error', text: error.message || '新增模型失败' });
    } finally {
      setModelSubmitting(false);
    }
  };

  const providerSubmitDisabled = providerSubmitting || !providerForm.name.trim() || !providerForm.api_url.trim() || !providerForm.api_key.trim();
  const modelSubmitDisabled = modelSubmitting || !modelForm.provider_id || !modelForm.name.trim();

  return (
    <AdminShell
      pageKey="model-management"
      title="模型管理"
      subtitle="直接维护主数据库中的供应商与模型。功能逻辑保持不变，只改为更标准的后台管理页面布局。"
      breadcrumbs="预处理控制台 / 模型管理"
      actions={[
        <Button key="refresh" variant="outlined" startIcon={<RefreshRoundedIcon />} onClick={loadData} disabled={loading}>刷新</Button>,
        <Button key="routing" variant="contained" startIcon={<AccountTreeOutlinedIcon />} onClick={() => { window.location.href = '/model-routing'; }}>去模型路由</Button>,
      ]}
    >
      <Stack spacing={2.5}>
        {message && (
          <Alert severity={message.severity} onClose={() => setMessage(null)}>
            {message.text}
          </Alert>
        )}

        <Grid container spacing={2}>
          <Grid item xs={12} sm={6} lg={3}>
            <Paper sx={infoCardSx}>
              <Typography variant="caption" sx={{ display: 'block' }}>供应商数量</Typography>
              <Typography variant="h5" sx={{ mt: 0.5 }}>{providers.length}</Typography>
            </Paper>
          </Grid>
          <Grid item xs={12} sm={6} lg={3}>
            <Paper sx={infoCardSx}>
              <Typography variant="caption" sx={{ display: 'block' }}>模型数量</Typography>
              <Typography variant="h5" sx={{ mt: 0.5 }}>{models.length}</Typography>
            </Paper>
          </Grid>
          <Grid item xs={12} sm={6} lg={3}>
            <Paper sx={infoCardSx}>
              <Typography variant="caption" sx={{ display: 'block' }}>默认写入位置</Typography>
              <Typography variant="subtitle2" sx={{ mt: 0.5 }}>主数据库</Typography>
            </Paper>
          </Grid>
          <Grid item xs={12} sm={6} lg={3}>
            <Paper sx={infoCardSx}>
              <Typography variant="caption" sx={{ display: 'block' }}>后续操作</Typography>
              <Typography variant="subtitle2" sx={{ mt: 0.5 }}>新增后可去模型路由绑定步骤</Typography>
            </Paper>
          </Grid>
        </Grid>

        <Grid container spacing={2.5}>
          <Grid item xs={12} lg={4}>
            <Stack spacing={2.5}>
              <PageSection title="新增 / 更新供应商" description="采用原有同名更新策略，名称相同会更新 API URL 和 API Key。">
                <Stack spacing={2}>
                  <TextField
                    label="供应商名称"
                    value={providerForm.name}
                    onChange={(event) => setProviderForm((prev) => ({ ...prev, name: event.target.value }))}
                    placeholder="例如：Dashscope / DeepSeek / OpenAI"
                    fullWidth
                  />
                  <TextField
                    label="API URL"
                    value={providerForm.api_url}
                    onChange={(event) => setProviderForm((prev) => ({ ...prev, api_url: event.target.value }))}
                    placeholder="例如：https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
                    fullWidth
                  />
                  <TextField
                    label="API Key"
                    type="password"
                    value={providerForm.api_key}
                    onChange={(event) => setProviderForm((prev) => ({ ...prev, api_key: event.target.value }))}
                    placeholder="输入最新 API Key"
                    fullWidth
                  />
                  <Button variant="contained" onClick={handleProviderSubmit} disabled={providerSubmitDisabled}>
                    {providerSubmitting ? '保存中...' : '保存供应商'}
                  </Button>
                </Stack>
              </PageSection>

              <PageSection title="在供应商下新增模型" description="保持原有同供应商下去重策略，同名模型不会重复插入。">
                <Stack spacing={2}>
                  <FormControl fullWidth>
                    <InputLabel>供应商</InputLabel>
                    <Select value={modelForm.provider_id} label="供应商" onChange={(event) => setModelForm((prev) => ({ ...prev, provider_id: event.target.value }))}>
                      {providers.map((provider) => (
                        <MenuItem key={provider.id} value={provider.id}>{provider.name}</MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                  <TextField
                    label="模型名称"
                    value={modelForm.name}
                    onChange={(event) => setModelForm((prev) => ({ ...prev, name: event.target.value }))}
                    placeholder="例如：qwen3.5-plus / deepseek-chat"
                    fullWidth
                  />
                  <Button variant="contained" onClick={handleModelSubmit} disabled={modelSubmitDisabled}>
                    {modelSubmitting ? '保存中...' : '新增模型'}
                  </Button>
                </Stack>
              </PageSection>
            </Stack>
          </Grid>

          <Grid item xs={12} lg={8}>
            <Stack spacing={2.5}>
              <PageSection title="供应商列表" description="显示主数据库中当前可用的供应商与配置概况。">
                {loading ? (
                  <Typography color="text.secondary">加载中...</Typography>
                ) : providers.length === 0 ? (
                  <Typography color="text.secondary">主数据库中还没有供应商。</Typography>
                ) : (
                  <Grid container spacing={1.5}>
                    {providers.map((provider) => (
                      <Grid item xs={12} md={6} key={provider.id}>
                        <Paper sx={{ p: 2, borderRadius: 2.5, backgroundColor: '#fafbfc', boxShadow: 'none', border: '1px solid #eef0f3' }}>
                          <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1}>
                            <Box>
                              <Typography variant="subtitle1">{provider.name}</Typography>
                              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, wordBreak: 'break-all' }}>
                                {provider.api_url}
                              </Typography>
                            </Box>
                            <Chip label={`${provider.model_count || 0} 个模型`} color="primary" variant="outlined" />
                          </Stack>
                          <Box sx={{ mt: 1.5, display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                            <Chip size="small" label={`API Key：${provider.display_api_key || '未设置'}`} />
                          </Box>
                        </Paper>
                      </Grid>
                    ))}
                  </Grid>
                )}
              </PageSection>

              <PageSection title="模型列表" description="按供应商分组展示当前主数据库中的模型。">
                {loading ? (
                  <Typography color="text.secondary">加载中...</Typography>
                ) : models.length === 0 ? (
                  <Typography color="text.secondary">当前还没有模型。</Typography>
                ) : (
                  <Stack spacing={1.5}>
                    {providers.map((provider) => {
                      const providerModels = modelsByProvider[provider.id] || [];
                      if (providerModels.length === 0) {
                        return null;
                      }

                      return (
                        <Paper key={provider.id} sx={{ p: 2, borderRadius: 2.5, backgroundColor: '#fafbfc', boxShadow: 'none', border: '1px solid #eef0f3' }}>
                          <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1} sx={{ mb: 1.25 }}>
                            <Typography variant="subtitle2">{provider.name}</Typography>
                            <Chip size="small" label={`${providerModels.length} 个模型`} />
                          </Stack>
                          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                            {providerModels.map((model) => (
                              <Chip key={model.id} label={model.name} variant="outlined" />
                            ))}
                          </Box>
                        </Paper>
                      );
                    })}
                  </Stack>
                )}
              </PageSection>
            </Stack>
          </Grid>
        </Grid>
      </Stack>
    </AdminShell>
  );
}

export default ModelManagement;
