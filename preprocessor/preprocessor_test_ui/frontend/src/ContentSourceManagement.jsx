import React, { useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Checkbox,
  FormControlLabel,
  FormGroup,
  Grid,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import RefreshRoundedIcon from '@mui/icons-material/RefreshRounded';
import SaveRoundedIcon from '@mui/icons-material/SaveRounded';
import AdminShell from './AdminShell';
import PageSection from './PageSection';

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

function ContentSourceManagement() {
  const [sources, setSources] = useState([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState(null);

  const [sourceName, setSourceName] = useState('高考真题题库');
  const [sourceType, setSourceType] = useState('question_bank');
  const [providerName, setProviderName] = useState('');
  const [tenantId, setTenantId] = useState('');
  const [remark, setRemark] = useState('');
  const [commercialAllowed, setCommercialAllowed] = useState(false);
  const [aiProcessingAllowed, setAiProcessingAllowed] = useState(true);
  const [trainingAllowed, setTrainingAllowed] = useState(false);

  const loadSources = async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/content-sources');
      if (!response.ok) {
        throw new Error('加载内容源失败');
      }
      const data = await response.json();
      setSources(Array.isArray(data) ? data : []);
      setMessage(null);
    } catch (error) {
      setMessage({ severity: 'error', text: error.message || '加载失败' });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSources();
  }, []);

  const handleCreate = async () => {
    const normalizedTenantId = tenantId.trim();
    if (normalizedTenantId && !/^\d+$/.test(normalizedTenantId)) {
      setMessage({ severity: 'error', text: 'Tenant ID 只能填写数字；如果当前未启用多租户，请留空。' });
      return;
    }

    setSubmitting(true);
    try {
      const response = await fetch('/api/content-sources', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_name: sourceName,
          source_type: sourceType,
          provider_name: providerName || undefined,
          tenant_id: normalizedTenantId ? Number(normalizedTenantId) : undefined,
          commercial_allowed: commercialAllowed,
          ai_processing_allowed: aiProcessingAllowed,
          training_allowed: trainingAllowed,
          remark: remark || undefined,
        }),
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(errorText || '创建内容源失败');
      }
      await response.json();
      setMessage({ severity: 'success', text: '内容源已创建' });
      await loadSources();
    } catch (error) {
      setMessage({ severity: 'error', text: error.message || '创建失败' });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AdminShell
      pageKey="content-sources"
      title="内容源管理"
      subtitle="运营侧独立维护内容源；内容摄入页只负责选择内容源并执行批量摄入或 Bundle 测试。"
      breadcrumbs="统一测试控制台 / 内容源管理"
      actions={[
        <Button key="refresh" variant="outlined" startIcon={<RefreshRoundedIcon />} onClick={loadSources} disabled={loading || submitting}>
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
          <Grid item xs={12} md={4}>
            <Paper sx={cardSx}>
              <Typography variant="caption">内容源总数</Typography>
              <Typography variant="h4" sx={{ mt: 1 }}>{sources.length}</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>供内容摄入、Bundle 匹配等链路复用</Typography>
            </Paper>
          </Grid>
          <Grid item xs={12} md={4}>
            <Paper sx={cardSx}>
              <Typography variant="caption">默认源类型</Typography>
              <Typography variant="h6" sx={{ mt: 1 }}>question_bank</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>当前页面默认用于题库场景</Typography>
            </Paper>
          </Grid>
          <Grid item xs={12} md={4}>
            <Paper sx={cardSx}>
              <Typography variant="caption">管理方式</Typography>
              <Typography variant="h6" sx={{ mt: 1 }}>独立创建</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>创建完成后到内容摄入页选择使用</Typography>
            </Paper>
          </Grid>
        </Grid>

        <Grid container spacing={2.5}>
          <Grid item xs={12} xl={5}>
            <PageSection title="创建内容源" description="建议先按业务维度建源，例如“全国高考真题库”“校本题库”等。">
              <Stack spacing={2}>
                <Grid container spacing={2}>
                  <Grid item xs={12} sm={6}>
                    <TextField label="源名称" value={sourceName} onChange={(event) => setSourceName(event.target.value)} fullWidth />
                  </Grid>
                  <Grid item xs={12} sm={6}>
                    <TextField label="源类型" value={sourceType} onChange={(event) => setSourceType(event.target.value)} fullWidth />
                  </Grid>
                  <Grid item xs={12} sm={6}>
                    <TextField label="Provider 名称" value={providerName} onChange={(event) => setProviderName(event.target.value)} fullWidth />
                  </Grid>
                  <Grid item xs={12} sm={6}>
                    <TextField
                      label="Tenant ID"
                      value={tenantId}
                      onChange={(event) => setTenantId(event.target.value)}
                      fullWidth
                      placeholder="留空或填写数字，例如 1"
                      helperText="仅支持数字；不启用多租户时可留空"
                    />
                  </Grid>

                  <Grid item xs={12}>
                    <TextField label="备注" value={remark} onChange={(event) => setRemark(event.target.value)} fullWidth multiline minRows={3} />
                  </Grid>
                </Grid>

                <FormGroup row>
                  <FormControlLabel control={<Checkbox checked={commercialAllowed} onChange={(event) => setCommercialAllowed(event.target.checked)} />} label="允许商用" />
                  <FormControlLabel control={<Checkbox checked={aiProcessingAllowed} onChange={(event) => setAiProcessingAllowed(event.target.checked)} />} label="允许 AI 处理" />
                  <FormControlLabel control={<Checkbox checked={trainingAllowed} onChange={(event) => setTrainingAllowed(event.target.checked)} />} label="允许训练" />
                </FormGroup>

                <Box>
                  <Button variant="contained" startIcon={<SaveRoundedIcon />} onClick={handleCreate} disabled={submitting || !sourceName.trim()}>
                    {submitting ? '创建中...' : '创建内容源'}
                  </Button>
                </Box>
              </Stack>
            </PageSection>
          </Grid>

          <Grid item xs={12} xl={7}>
            <PageSection title="已有内容源" description="内容摄入页将直接复用这里的内容源，不再在摄入页里创建。">
              <TableContainer component={Paper} sx={tableSx}>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>ID</TableCell>
                      <TableCell>名称</TableCell>
                      <TableCell>类型</TableCell>
                      <TableCell>Provider</TableCell>
                      <TableCell>Tenant</TableCell>
                      <TableCell>权限</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {sources.map((item) => (
                      <TableRow key={item.id} hover>
                        <TableCell>{item.id}</TableCell>
                        <TableCell>
                          <Typography variant="subtitle2">{item.source_name}</Typography>
                          <Typography variant="caption" color="text.secondary">{item.remark || '-'}</Typography>
                        </TableCell>
                        <TableCell>{item.source_type}</TableCell>
                        <TableCell>{item.provider_name || '-'}</TableCell>
                        <TableCell>{item.tenant_id ?? '-'}</TableCell>
                        <TableCell>
                          <Typography variant="caption">
                            {`商用:${item.commercial_allowed ? 'Y' : 'N'} / AI:${item.ai_processing_allowed ? 'Y' : 'N'} / 训练:${item.training_allowed ? 'Y' : 'N'}`}
                          </Typography>
                        </TableCell>
                      </TableRow>
                    ))}
                    {!loading && sources.length === 0 && (
                      <TableRow>
                        <TableCell colSpan={6} align="center">暂无内容源</TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </TableContainer>
            </PageSection>
          </Grid>
        </Grid>
      </Stack>
    </AdminShell>
  );
}

export default ContentSourceManagement;
