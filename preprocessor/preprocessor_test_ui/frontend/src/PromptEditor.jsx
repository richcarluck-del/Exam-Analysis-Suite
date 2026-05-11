import React, { useEffect, useState } from 'react';
import axios from 'axios';
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Grid,
  MenuItem,
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
import EditOutlinedIcon from '@mui/icons-material/EditOutlined';
import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded';
import AdminShell from './AdminShell';
import PageSection from './PageSection';

const API_BASE_URL = '/api/prompts';

const infoCardSx = {
  p: 2,
  borderRadius: 3,
  border: '1px solid #eef0f3',
  backgroundColor: '#fafbfc',
  boxShadow: 'none',
};

const PromptEditor = () => {
  const [prompts, setPrompts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [message, setMessage] = useState(null);

  const [filters, setFilters] = useState({
    step: '',
    category: '',
    target_type: '',
    version: '',
    search: '',
  });

  const [editingPrompt, setEditingPrompt] = useState(null);
  const [editFormData, setEditFormData] = useState({
    prompt_text: '',
    version: '',
    status: 'published',
    change_log: '',
  });
  const [showEditModal, setShowEditModal] = useState(false);
  const [saving, setSaving] = useState(false);

  const [stats, setStats] = useState(null);

  const loadPrompts = async () => {
    try {
      setLoading(true);
      setError(null);

      const params = {};
      if (filters.step) params.step = parseInt(filters.step, 10);
      if (filters.category) params.category = filters.category;
      if (filters.target_type) params.target_type = filters.target_type;
      if (filters.version) params.version = parseInt(filters.version, 10);
      if (filters.search) params.search = filters.search;

      const response = await axios.get(`${API_BASE_URL}/all`, { params });
      setPrompts(response.data);

      const statsResponse = await axios.get(`${API_BASE_URL}/stats/summary`);
      setStats(statsResponse.data);
    } catch (err) {
      const nextError = '加载提示词失败：' + err.message;
      setError(nextError);
      console.error('Error loading prompts:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadPrompts();
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => {
      loadPrompts();
    }, 500);

    return () => clearTimeout(timer);
  }, [filters]);

  const handleFilterChange = (key, value) => {
    setFilters((prev) => ({
      ...prev,
      [key]: value,
    }));
  };

  const handleEdit = async (prompt) => {
    try {
      const response = await axios.get(`${API_BASE_URL}/${prompt.id}`);
      const promptDetail = response.data;

      setEditingPrompt(promptDetail);
      setEditFormData({
        prompt_text: promptDetail.prompt_text || (promptDetail.versions[0]?.prompt_text || ''),
        version: promptDetail.version + 1,
        status: 'published',
        change_log: '',
      });
      setShowEditModal(true);
    } catch (err) {
      setMessage({ severity: 'error', text: '获取提示词详情失败：' + err.message });
    }
  };

  const handleSave = async () => {
    try {
      setSaving(true);

      if (!editFormData.prompt_text || editFormData.prompt_text.length < 10) {
        setMessage({ severity: 'warning', text: '提示词内容至少需要 10 个字符' });
        return;
      }

      if (!editFormData.version || editFormData.version <= 0) {
        setMessage({ severity: 'warning', text: '版本号必须是正整数' });
        return;
      }

      await axios.put(`${API_BASE_URL}/${editingPrompt.id}`, null, {
        params: {
          prompt_text: editFormData.prompt_text,
          version: parseInt(editFormData.version, 10),
          status: editFormData.status,
          change_log: editFormData.change_log,
          is_latest: true,
        },
      });

      setMessage({ severity: 'success', text: '提示词已保存' });
      setShowEditModal(false);
      setEditingPrompt(null);
      loadPrompts();
    } catch (err) {
      setMessage({ severity: 'error', text: '保存失败：' + (err.response?.data?.detail || err.message) });
      console.error('Error saving prompt:', err);
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    setShowEditModal(false);
    setEditingPrompt(null);
  };

  const getStepName = (step) => {
    const stepMap = {
      1: '透视矫正',
      2: '页面分类',
      3: '布局分析',
      4: '内容提取',
      5: '结果合并',
      6: '绘制输出',
    };
    return stepMap[step] || `步骤${step}`;
  };

  const getStatusChip = (isLatest, isActive) => {
    if (!isActive) {
      return <Chip size="small" label="已禁用" variant="outlined" />;
    }
    if (isLatest) {
      return <Chip size="small" label="最新" color="success" />;
    }
    return <Chip size="small" label="历史" variant="outlined" />;
  };

  return (
    <AdminShell
      pageKey="prompt-editor"
      title="提示词版本"
      subtitle="保留现有提示词筛选、版本编辑和历史查看能力，仅调整为统一的后台管理页面样式。"
      breadcrumbs="预处理控制台 / 提示词版本"
      actions={(
        <Button variant="outlined" startIcon={<ArrowBackRoundedIcon />} onClick={() => window.history.back()}>
          返回上一页
        </Button>
      )}
    >
      <Stack spacing={2.5}>
        {message && (
          <Alert severity={message.severity} onClose={() => setMessage(null)}>
            {message.text}
          </Alert>
        )}
        {error && <Alert severity="error">{error}</Alert>}

        {stats && (
          <Grid container spacing={2}>
            <Grid item xs={12} sm={6} lg={3}>
              <Paper sx={infoCardSx}>
                <Typography variant="caption" sx={{ display: 'block' }}>总提示词数</Typography>
                <Typography variant="h5" sx={{ mt: 0.5 }}>{stats.total_prompts}</Typography>
              </Paper>
            </Grid>
            <Grid item xs={12} sm={6} lg={3}>
              <Paper sx={infoCardSx}>
                <Typography variant="caption" sx={{ display: 'block' }}>总版本数</Typography>
                <Typography variant="h5" sx={{ mt: 0.5 }}>{stats.total_versions}</Typography>
              </Paper>
            </Grid>
          </Grid>
        )}

        <PageSection title="筛选条件" description="步骤、类别、目标类型、版本和关键字搜索保持原有能力。">
          <Grid container spacing={1.5}>
            <Grid item xs={12} sm={6} md={4} lg={2}>
              <TextField select fullWidth label="步骤" value={filters.step} onChange={(event) => handleFilterChange('step', event.target.value)}>
                <MenuItem value="">所有步骤</MenuItem>
                <MenuItem value="1">步骤 1 - 透视矫正</MenuItem>
                <MenuItem value="2">步骤 2 - 页面分类</MenuItem>
                <MenuItem value="3">步骤 3 - 布局分析</MenuItem>
                <MenuItem value="4">步骤 4 - 内容提取</MenuItem>
                <MenuItem value="5">步骤 5 - 结果合并</MenuItem>
                <MenuItem value="6">步骤 6 - 绘制输出</MenuItem>
              </TextField>
            </Grid>
            <Grid item xs={12} sm={6} md={4} lg={2}>
              <TextField select fullWidth label="类别" value={filters.category} onChange={(event) => handleFilterChange('category', event.target.value)}>
                <MenuItem value="">所有类别</MenuItem>
                <MenuItem value="perspective_correction">透视矫正</MenuItem>
                <MenuItem value="classification">页面分类</MenuItem>
                <MenuItem value="layout_analysis">布局分析</MenuItem>
                <MenuItem value="content_extraction">内容提取</MenuItem>
                <MenuItem value="draw_output">绘制输出</MenuItem>
              </TextField>
            </Grid>
            <Grid item xs={12} sm={6} md={4} lg={2}>
              <TextField select fullWidth label="类型" value={filters.target_type} onChange={(event) => handleFilterChange('target_type', event.target.value)}>
                <MenuItem value="">所有类型</MenuItem>
                <MenuItem value="all_types">通用</MenuItem>
                <MenuItem value="full_page">整页</MenuItem>
                <MenuItem value="exam_paper">试卷</MenuItem>
                <MenuItem value="answer_sheet">答题纸</MenuItem>
                <MenuItem value="mixed">混合</MenuItem>
              </TextField>
            </Grid>
            <Grid item xs={12} sm={6} md={4} lg={2}>
              <TextField select fullWidth label="版本" value={filters.version} onChange={(event) => handleFilterChange('version', event.target.value)}>
                <MenuItem value="">所有版本</MenuItem>
                {stats && stats.by_version && Object.entries(stats.by_version).map(([version, count]) => (
                  <MenuItem key={version} value={version}>{`v${version} (${count} 个)`}</MenuItem>
                ))}
              </TextField>
            </Grid>
            <Grid item xs={12} md={8} lg={4}>
              <TextField fullWidth label="搜索提示词名称" value={filters.search} onChange={(event) => handleFilterChange('search', event.target.value)} placeholder="输入名称或显示名称关键字" />
            </Grid>
          </Grid>
        </PageSection>

        <PageSection title="提示词列表" description="与原页面一致，可查看、筛选并编辑提示词版本。">
          {loading ? (
            <Typography color="text.secondary">加载中...</Typography>
          ) : prompts.length === 0 ? (
            <Typography color="text.secondary">没有找到提示词。</Typography>
          ) : (
            <TableContainer component={Paper} sx={{ borderRadius: 2.5, boxShadow: 'none', border: '1px solid #eef0f3' }}>
              <Table>
                <TableHead>
                  <TableRow>
                    <TableCell>名称</TableCell>
                    <TableCell>版本</TableCell>
                    <TableCell>步骤</TableCell>
                    <TableCell>类型</TableCell>
                    <TableCell>状态</TableCell>
                    <TableCell>更新时间</TableCell>
                    <TableCell align="right">操作</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {prompts.map((prompt) => (
                    <TableRow key={prompt.id} hover>
                      <TableCell sx={{ minWidth: 260 }}>
                        <Typography variant="subtitle2" sx={{ fontFamily: 'monospace' }}>{prompt.name}</Typography>
                        {prompt.display_name && (
                          <Typography variant="caption" sx={{ display: 'block', mt: 0.5 }}>{prompt.display_name}</Typography>
                        )}
                      </TableCell>
                      <TableCell>{prompt.version}</TableCell>
                      <TableCell>{getStepName(prompt.pipeline_step)}</TableCell>
                      <TableCell>{prompt.target_type}</TableCell>
                      <TableCell>{getStatusChip(prompt.is_latest, prompt.is_active)}</TableCell>
                      <TableCell>{prompt.updated_at}</TableCell>
                      <TableCell align="right">
                        <Button variant="contained" size="small" startIcon={<EditOutlinedIcon />} onClick={() => handleEdit(prompt)}>
                          编辑
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </PageSection>
      </Stack>

      <Dialog open={showEditModal && Boolean(editingPrompt)} onClose={handleCancel} fullWidth maxWidth="lg">
        <DialogTitle>{editingPrompt ? `编辑提示词：${editingPrompt.name}` : '编辑提示词'}</DialogTitle>
        <DialogContent dividers>
          {editingPrompt && (
            <Stack spacing={2} sx={{ pt: 1 }}>
              <Grid container spacing={1.5}>
                <Grid item xs={12} md={6}>
                  <TextField fullWidth label="名称" value={editingPrompt.name} disabled />
                </Grid>
                <Grid item xs={12} md={3}>
                  <TextField
                    fullWidth
                    label="新版本号"
                    type="number"
                    value={editFormData.version}
                    onChange={(event) => setEditFormData({ ...editFormData, version: event.target.value })}
                    inputProps={{ min: 1 }}
                  />
                </Grid>
                <Grid item xs={12} md={3}>
                  <TextField select fullWidth label="状态" value={editFormData.status} onChange={(event) => setEditFormData({ ...editFormData, status: event.target.value })}>
                    <MenuItem value="draft">草稿</MenuItem>
                    <MenuItem value="review">审核中</MenuItem>
                    <MenuItem value="published">已发布</MenuItem>
                    <MenuItem value="deprecated">已废弃</MenuItem>
                  </TextField>
                </Grid>
              </Grid>

              <Grid container spacing={1.5}>
                <Grid item xs={12} md={6}>
                  <TextField fullWidth label="步骤" value={getStepName(editingPrompt.pipeline_step)} disabled />
                </Grid>
                <Grid item xs={12} md={6}>
                  <TextField fullWidth label="类型" value={editingPrompt.target_type} disabled />
                </Grid>
              </Grid>

              <TextField
                fullWidth
                multiline
                minRows={16}
                label={`提示词内容（${editFormData.prompt_text.length} 字符）`}
                value={editFormData.prompt_text}
                onChange={(event) => setEditFormData({ ...editFormData, prompt_text: event.target.value })}
                placeholder="输入提示词内容..."
              />

              <TextField
                fullWidth
                label="变更日志"
                value={editFormData.change_log}
                onChange={(event) => setEditFormData({ ...editFormData, change_log: event.target.value })}
                placeholder="本次修改说明（可选）"
                inputProps={{ maxLength: 500 }}
              />

              {editingPrompt.versions && editingPrompt.versions.length > 0 && (
                <Box>
                  <Typography variant="subtitle2" sx={{ mb: 1 }}>版本历史（最近 5 个）</Typography>
                  <Stack spacing={1}>
                    {editingPrompt.versions.slice(0, 5).map((version) => (
                      <Paper key={version.id} sx={{ p: 1.5, borderRadius: 2, backgroundColor: '#fafbfc', boxShadow: 'none', border: '1px solid #eef0f3' }}>
                        <Stack direction={{ xs: 'column', md: 'row' }} spacing={1} alignItems={{ xs: 'flex-start', md: 'center' }}>
                          <Chip size="small" color="primary" label={`v${version.version}`} />
                          <Typography variant="caption">{version.created_at}</Typography>
                          {version.change_log && <Typography variant="body2" color="text.secondary">{version.change_log}</Typography>}
                        </Stack>
                      </Paper>
                    ))}
                  </Stack>
                </Box>
              )}
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCancel} disabled={saving}>取消</Button>
          <Button variant="contained" onClick={handleSave} disabled={saving}>
            {saving ? '保存中...' : '保存为新版本'}
          </Button>
        </DialogActions>
      </Dialog>
    </AdminShell>
  );
};

export default PromptEditor;
