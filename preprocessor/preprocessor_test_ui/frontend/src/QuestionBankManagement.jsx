import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  FormControl,
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
  TablePagination,
  TableRow,
  Tooltip,
  Typography,
} from '@mui/material';
import RefreshRoundedIcon from '@mui/icons-material/RefreshRounded';
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded';
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

const formatIngestedAt = (value) => {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', { hour12: false });
};

function QuestionBankManagement() {
  const [sources, setSources] = useState([]);
  const [documents, setDocuments] = useState([]);
  const [selectedSourceId, setSelectedSourceId] = useState('all');
  const [selectedDocumentIds, setSelectedDocumentIds] = useState([]);
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(20);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState(null);

  const loadOverview = async () => {
    const response = await fetch('/api/content-ingestion/overview');
    if (!response.ok) {
      throw new Error('加载统计数据失败');
    }
    const data = await response.json();
    const nextSources = Array.isArray(data?.sources) ? data.sources : [];
    setSources(nextSources);
    return nextSources;
  };

  const loadDocuments = async (sourceId, sourceList = sources) => {
    if (!Array.isArray(sourceList) || sourceList.length === 0) {
      setDocuments([]);
      setSelectedDocumentIds([]);
      return;
    }

    if (sourceId === 'all') {
      const responses = await Promise.all(
        sourceList.map(async (source) => {
          const response = await fetch(`/api/content-sources/${source.id}/documents`);
          if (!response.ok) {
            throw new Error(`加载内容源 ${source.id} 文档失败`);
          }
          const payload = await response.json();
          return Array.isArray(payload?.documents) ? payload.documents : [];
        })
      );
      const merged = responses.flat();
      merged.sort((a, b) => (b.id || 0) - (a.id || 0));
      setDocuments(merged);
      setSelectedDocumentIds((prev) => prev.filter((id) => merged.some((item) => item.id === id)));
      return;
    }

    const response = await fetch(`/api/content-sources/${sourceId}/documents`);
    if (!response.ok) {
      throw new Error('加载内容源文档失败');
    }
    const payload = await response.json();
    const rows = Array.isArray(payload?.documents) ? payload.documents : [];
    setDocuments(rows);
    setSelectedDocumentIds((prev) => prev.filter((id) => rows.some((item) => item.id === id)));
  };

  const refreshAll = async (sourceOverride) => {
    setLoading(true);
    try {
      const nextSources = await loadOverview();
      const targetSourceId = sourceOverride ?? selectedSourceId;
      const fallbackSourceId = targetSourceId === 'all' || nextSources.some((item) => String(item.id) === String(targetSourceId))
        ? targetSourceId
        : (nextSources[0] ? String(nextSources[0].id) : 'all');

      if (fallbackSourceId !== selectedSourceId) {
        setSelectedSourceId(fallbackSourceId);
      }
      await loadDocuments(fallbackSourceId, nextSources);
      setMessage(null);
    } catch (error) {
      setMessage({ severity: 'error', text: error.message || '加载失败' });
      setDocuments([]);
      setSelectedDocumentIds([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refreshAll('all');
  }, []);

  useEffect(() => {
    setPage(0);
    setSelectedDocumentIds([]);
    refreshAll(selectedSourceId);
  }, [selectedSourceId]);

  const totalDocuments = documents.length;
  const successCount = useMemo(() => documents.filter((item) => item.parse_status === 'success').length, [documents]);
  const failedCount = useMemo(() => documents.filter((item) => item.parse_status === 'failed').length, [documents]);
  const pendingCount = totalDocuments - successCount - failedCount;

  const paginatedDocuments = useMemo(() => {
    const start = page * rowsPerPage;
    return documents.slice(start, start + rowsPerPage);
  }, [documents, page, rowsPerPage]);

  const pagedDocumentIds = useMemo(
    () => paginatedDocuments.map((item) => item.id).filter(Boolean),
    [paginatedDocuments]
  );

  const isAllPagedSelected =
    pagedDocumentIds.length > 0 &&
    pagedDocumentIds.every((id) => selectedDocumentIds.includes(id));

  const toggleDocumentSelection = (documentId) => {
    setSelectedDocumentIds((prev) => (
      prev.includes(documentId) ? prev.filter((id) => id !== documentId) : [...prev, documentId]
    ));
  };

  const toggleSelectAllPaged = () => {
    if (isAllPagedSelected) {
      setSelectedDocumentIds((prev) => prev.filter((id) => !pagedDocumentIds.includes(id)));
      return;
    }
    setSelectedDocumentIds((prev) => Array.from(new Set([...prev, ...pagedDocumentIds])));
  };

  const handleDeleteDocuments = async (documentIds) => {
    const ids = (documentIds || []).filter(Boolean);
    if (!ids.length) {
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
      const deletingRows = documents.filter((item) => ids.includes(item.id));
      for (const item of deletingRows) {
        const response = await fetch(`/api/content-sources/${item.source_id}/documents/${item.id}`, {
          method: 'DELETE',
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(data?.detail || `删除文档 ${item.id} 失败`);
        }
      }
      setMessage({ severity: 'success', text: `已删除 ${ids.length} 个文档及其解析结果` });
      setSelectedDocumentIds((prev) => prev.filter((id) => !ids.includes(id)));
      await refreshAll(selectedSourceId);
      setPage(0);
    } catch (error) {
      setMessage({ severity: 'error', text: error.message || '删除失败' });
    }
  };

  return (
    <AdminShell
      pageKey="question-bank-management"
      title="题库管理"
      subtitle="按内容源查看题库试卷文档，支持筛选、分页与删除。"
      breadcrumbs="统一测试控制台 / 题库管理"
      actions={[
        <Button key="refresh" variant="outlined" startIcon={<RefreshRoundedIcon />} onClick={() => refreshAll(selectedSourceId)} disabled={loading}>
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
            { label: '内容源总数', value: sources.length, caption: '可用于筛选文档' },
            { label: '文档总数', value: totalDocuments, caption: selectedSourceId === 'all' ? '全部内容源' : '当前内容源' },
            { label: '成功', value: successCount, caption: 'parse_status = success' },
            { label: '其他状态', value: pendingCount + failedCount, caption: `失败 ${failedCount} / 处理中 ${pendingCount}` },
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

        <PageSection
          title="试卷列表"
          description="支持按内容源筛选、每页条数切换、增序序号展示，保留单条与批量删除。"
          actions={(
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
              <FormControl size="small" sx={{ minWidth: 220 }}>
                <InputLabel>内容源筛选</InputLabel>
                <Select
                  value={selectedSourceId}
                  label="内容源筛选"
                  onChange={(event) => setSelectedSourceId(event.target.value)}
                >
                  <MenuItem value="all">全部内容源</MenuItem>
                  {sources.map((item) => (
                    <MenuItem key={item.id} value={String(item.id)}>{`${item.id} / ${item.source_name}`}</MenuItem>
                  ))}
                </Select>
              </FormControl>
              <Button
                size="small"
                variant="outlined"
                color="error"
                disabled={selectedDocumentIds.length === 0 || loading}
                onClick={() => handleDeleteDocuments(selectedDocumentIds)}
              >
                删除所选
              </Button>
            </Stack>
          )}
        >
          <TableContainer component={Paper} sx={tableSx}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell padding="checkbox">
                    <Checkbox
                      size="small"
                      checked={isAllPagedSelected}
                      indeterminate={selectedDocumentIds.length > 0 && !isAllPagedSelected}
                      onChange={toggleSelectAllPaged}
                    />
                  </TableCell>
                  <TableCell>序号</TableCell>
                  <TableCell>ID</TableCell>
                  <TableCell>内容源</TableCell>
                  <TableCell>文件</TableCell>
                  <TableCell>状态</TableCell>
                  <TableCell>标题</TableCell>
                  <TableCell>摄入时间</TableCell>
                  <TableCell align="right">操作</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {paginatedDocuments.map((item, index) => {
                  const isSelected = selectedDocumentIds.includes(item.id);
                  const serialNumber = page * rowsPerPage + index + 1;
                  return (
                    <TableRow key={item.id} hover selected={isSelected}>
                      <TableCell padding="checkbox">
                        <Checkbox size="small" checked={isSelected} onChange={() => toggleDocumentSelection(item.id)} />
                      </TableCell>
                      <TableCell>{serialNumber}</TableCell>
                      <TableCell>{item.id}</TableCell>
                      <TableCell>{item.source_name || `#${item.source_id}`}</TableCell>
                      <TableCell>{item.file_name || '-'}</TableCell>
                      <TableCell>
                        <Chip
                          size="small"
                          label={item.parse_status || 'unknown'}
                          color={item.parse_status === 'success' ? 'success' : item.parse_status === 'failed' ? 'error' : 'default'}
                          variant="outlined"
                        />
                      </TableCell>
                      <TableCell>{item.title || '-'}</TableCell>
                      <TableCell>{formatIngestedAt(item.created_at)}</TableCell>
                      <TableCell align="right">
                        <Tooltip title="删除此文档及其所有解析结果">
                          <span>
                            <IconButton
                              size="small"
                              color="error"
                              disabled={loading}
                              onClick={() => handleDeleteDocuments([item.id])}
                            >
                              <DeleteOutlineRoundedIcon fontSize="small" />
                            </IconButton>
                          </span>
                        </Tooltip>
                      </TableCell>
                    </TableRow>
                  );
                })}
                {!loading && documents.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={9} align="center">暂无文档</TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
            <TablePagination
              component="div"
              count={documents.length}
              page={page}
              onPageChange={(_, nextPage) => setPage(nextPage)}
              rowsPerPage={rowsPerPage}
              onRowsPerPageChange={(event) => {
                setRowsPerPage(Number(event.target.value));
                setPage(0);
              }}
              rowsPerPageOptions={[10, 20, 50, 100]}
              labelRowsPerPage="每页条数"
            />
          </TableContainer>
        </PageSection>
      </Stack>
    </AdminShell>
  );
}

export default QuestionBankManagement;
