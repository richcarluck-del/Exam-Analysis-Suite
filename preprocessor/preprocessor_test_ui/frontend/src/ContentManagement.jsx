import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  Grid,
  IconButton,
  Paper,
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
import VisibilityRoundedIcon from '@mui/icons-material/VisibilityRounded';
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

const rowsPerPageOptions = [10, 20, 50, 100];

function formatDate(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', {
    hour12: false,
    timeZone: 'Asia/Shanghai',
  });
}

function ContentManagement() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState({ sources: 0, documents: 0 });
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(20);
  const [loading, setLoading] = useState(false);
  const [refreshTick, setRefreshTick] = useState(0);
  const [message, setMessage] = useState(null);
  const [deletingId, setDeletingId] = useState(null);

  const startNo = useMemo(() => page * rowsPerPage + 1, [page, rowsPerPage]);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const response = await fetch(`/api/content-management/documents?page=${page + 1}&page_size=${rowsPerPage}`);
        if (!response.ok) {
          throw new Error('加载内容列表失败');
        }
        const data = await response.json();
        setItems(Array.isArray(data?.items) ? data.items : []);
        setTotal(Number(data?.pagination?.total || 0));
        setStats({
          sources: Number(data?.stats?.sources || 0),
          documents: Number(data?.stats?.documents || 0),
        });
        setMessage(null);
      } catch (error) {
        setItems([]);
        setTotal(0);
        setMessage({ severity: 'error', text: error.message || '加载失败' });
      } finally {
        setLoading(false);
      }
    };

    load();
  }, [page, rowsPerPage, refreshTick]);

  const handleDelete = async (row) => {
    if (!row?.id || !row?.source_id) return;
    const confirmed = window.confirm(`确定删除文档 ID=${row.id} 吗？该操作不可恢复。`);
    if (!confirmed) return;

    setDeletingId(row.id);
    try {
      const response = await fetch(`/api/content-sources/${row.source_id}/documents/${row.id}`, {
        method: 'DELETE',
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data?.detail || '删除失败');
      }
      setMessage({ severity: 'success', text: `文档 ${row.id} 已删除` });
      if (items.length === 1 && page > 0) {
        setPage((prev) => prev - 1);
      } else {
        setRefreshTick((prev) => prev + 1);
      }
    } catch (error) {
      setMessage({ severity: 'error', text: error.message || '删除失败' });
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <AdminShell
      pageKey="content-management"
      title="内容管理"
      subtitle="统一查看所有试卷文档，支持分页浏览与删除操作。"
      breadcrumbs="统一测试控制台 / 内容管理"
      actions={[
        <Button
          key="refresh"
          variant="outlined"
          startIcon={<RefreshRoundedIcon />}
          onClick={() => setRefreshTick((prev) => prev + 1)}
          disabled={loading || deletingId !== null}
        >
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
          <Grid item xs={12} md={6}>
            <Paper sx={cardSx}>
              <Typography variant="caption">内容源数量</Typography>
              <Typography variant="h4" sx={{ mt: 1 }}>{stats.sources}</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                已登记并可用于内容摄入的内容源
              </Typography>
            </Paper>
          </Grid>
          <Grid item xs={12} md={6}>
            <Paper sx={cardSx}>
              <Typography variant="caption">内容数量</Typography>
              <Typography variant="h4" sx={{ mt: 1 }}>{stats.documents}</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                全部题库文档总数
              </Typography>
            </Paper>
          </Grid>
        </Grid>

        <PageSection
          title="试卷列表"
          description="展示当前文档对应的最新试卷信息，并补充最近一次摄入时间（北京时间）、Package ID、所属内容源和题目数量。"
        >
          <TableContainer component={Paper} sx={tableSx}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>序号</TableCell>
                  <TableCell>文档 ID</TableCell>
                  <TableCell>Package ID</TableCell>
                  <TableCell>文件</TableCell>
                  <TableCell>状态</TableCell>
                  <TableCell>标题</TableCell>
                  <TableCell>最近摄入时间</TableCell>
                  <TableCell>所属内容源</TableCell>
                  <TableCell align="right">题目数量</TableCell>
                  <TableCell align="right">操作</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {items.map((row, index) => (
                  <TableRow key={row.id} hover>
                    <TableCell>{startNo + index}</TableCell>
                    <TableCell>{row.id}</TableCell>
                    <TableCell>{row.package_id ?? '-'}</TableCell>
                    <TableCell>{row.file_name || '-'}</TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        label={row.parse_status || 'unknown'}
                        color={row.parse_status === 'success' ? 'success' : row.parse_status === 'failed' ? 'error' : 'default'}
                        variant="outlined"
                      />
                    </TableCell>
                    <TableCell>{row.title || '-'}</TableCell>
                    <TableCell>{formatDate(row.last_ingested_at)}</TableCell>
                    <TableCell>{row.source_name ? `${row.source_name} (${row.source_id})` : '-'}</TableCell>
                    <TableCell align="right">{row.question_count ?? 0}</TableCell>
                    <TableCell align="right">
                      <Stack direction="row" spacing={1} justifyContent="flex-end">
                        <Tooltip title="预览试卷内容">
                          <IconButton
                            size="small"
                            color="primary"
                            onClick={() => window.open(`/paper-preview?id=${row.id}`, '_blank')}
                          >
                            <VisibilityRoundedIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                        <Tooltip title="删除此文档及其所有解析结果">
                          <span>
                            <IconButton
                              size="small"
                              color="error"
                              disabled={loading || deletingId !== null}
                              onClick={() => handleDelete(row)}
                            >
                              <DeleteOutlineRoundedIcon fontSize="small" />
                            </IconButton>
                          </span>
                        </Tooltip>
                      </Stack>
                    </TableCell>
                  </TableRow>
                ))}
                {!loading && items.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={10} align="center">暂无内容</TableCell>
                  </TableRow>
                )}
                {loading && (
                  <TableRow>
                    <TableCell colSpan={10} align="center">加载中...</TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
            <Box>
              <TablePagination
                component="div"
                count={total}
                page={page}
                onPageChange={(_, newPage) => setPage(newPage)}
                rowsPerPage={rowsPerPage}
                onRowsPerPageChange={(event) => {
                  setRowsPerPage(Number(event.target.value));
                  setPage(0);
                }}
                rowsPerPageOptions={rowsPerPageOptions}
                labelRowsPerPage="每页条数"
              />
            </Box>
          </TableContainer>
        </PageSection>
      </Stack>
    </AdminShell>
  );
}

export default ContentManagement;
