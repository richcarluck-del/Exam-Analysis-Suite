import React, { useMemo, useState } from 'react';
import {
  AppBar,
  Box,
  Chip,
  CssBaseline,
  Divider,
  Drawer,
  IconButton,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Stack,
  Toolbar,
  Typography,
} from '@mui/material';
import { alpha, ThemeProvider } from '@mui/material/styles';
import MenuRoundedIcon from '@mui/icons-material/MenuRounded';
import DashboardOutlinedIcon from '@mui/icons-material/DashboardOutlined';
import CropFreeOutlinedIcon from '@mui/icons-material/CropFreeOutlined';
import FolderOpenOutlinedIcon from '@mui/icons-material/FolderOpenOutlined';
import Inventory2OutlinedIcon from '@mui/icons-material/Inventory2Outlined';
import LibraryBooksOutlinedIcon from '@mui/icons-material/LibraryBooksOutlined';
import DescriptionOutlinedIcon from '@mui/icons-material/DescriptionOutlined';
import ArticleIcon from '@mui/icons-material/Article';
import StorageOutlinedIcon from '@mui/icons-material/StorageOutlined';
import PsychologyAltOutlinedIcon from '@mui/icons-material/PsychologyAltOutlined';
import TravelExploreOutlinedIcon from '@mui/icons-material/TravelExploreOutlined';
import AccountTreeOutlinedIcon from '@mui/icons-material/AccountTreeOutlined';
import FactCheckOutlinedIcon from '@mui/icons-material/FactCheckOutlined';
import AssessmentOutlinedIcon from '@mui/icons-material/AssessmentOutlined';

import TextSnippetOutlinedIcon from '@mui/icons-material/TextSnippetOutlined';
import EditNoteOutlinedIcon from '@mui/icons-material/EditNoteOutlined';

import ChevronRightRoundedIcon from '@mui/icons-material/ChevronRightRounded';
import { adminTheme, drawerWidth } from './adminTheme';

/** 与 `analyzer/client-app/vite.config.js` 中 dev 端口一致；部署时可设 `VITE_ANALYZER_REPORT_URL` */
const reportSystemBaseUrl = (() => {
  const raw = import.meta.env.VITE_ANALYZER_REPORT_URL;
  if (typeof raw === 'string' && raw.trim()) {
    return raw.trim().replace(/\/$/, '');
  }
  return 'http://127.0.0.1:5174';
})();

const navigationItems = [
  { key: 'test', label: '测试运行', path: '/', icon: <DashboardOutlinedIcon fontSize="small" /> },
  { key: 'whole-page', label: '整页画框', path: '/whole-page', icon: <CropFreeOutlinedIcon fontSize="small" /> },
  { key: 'content-sources', label: '内容源管理', path: '/content-sources', icon: <FolderOpenOutlinedIcon fontSize="small" /> },
  { key: 'question-bank-management', label: '题库管理', path: '/question-bank-management', icon: <LibraryBooksOutlinedIcon fontSize="small" /> },
  { key: 'knowledge-points', label: '知识点管理', path: '/knowledge-points', icon: <PsychologyAltOutlinedIcon fontSize="small" /> },
  { key: 'knowledge-retrieval', label: '知识点检索', path: '/knowledge-retrieval', icon: <TravelExploreOutlinedIcon fontSize="small" /> },
  { key: 'content-ingestion', label: '内容摄入', path: '/content-ingestion', icon: <Inventory2OutlinedIcon fontSize="small" /> },
  { key: 'case-run-inspect', label: 'Bundle 检视', path: '/case-run-inspect', icon: <FactCheckOutlinedIcon fontSize="small" /> },
  {
    key: 'analyzer-reports',
    label: '学情报告系统',
    path: `${reportSystemBaseUrl}/`,
    external: true,
    icon: <AssessmentOutlinedIcon fontSize="small" />,
  },
  { key: 'content-management', label: '内容管理', path: '/content-management', icon: <DescriptionOutlinedIcon fontSize="small" /> },
  { key: 'paper-preview', label: '试卷预览', path: '/paper-preview', icon: <ArticleIcon fontSize="small" /> },
  { key: 'model-management', label: '模型管理', path: '/model-management', icon: <StorageOutlinedIcon fontSize="small" /> },


  { key: 'model-routing', label: '模型路由', path: '/model-routing', icon: <AccountTreeOutlinedIcon fontSize="small" /> },
  { key: 'prompt-routing', label: '提示词路由', path: '/prompt-routing', icon: <TextSnippetOutlinedIcon fontSize="small" /> },
  { key: 'prompt-editor', label: '提示词版本', path: '/prompt-editor', icon: <EditNoteOutlinedIcon fontSize="small" /> },
];


const normalizePath = (path) => {
  const normalized = path.replace(/\/$/, '');
  return normalized || '/';
};

function AdminShell({ pageKey, title, subtitle, actions, children, breadcrumbs }) {
  const [mobileOpen, setMobileOpen] = useState(false);

  const currentBreadcrumbs = useMemo(() => {
    if (breadcrumbs) {
      return breadcrumbs;
    }
    return `控制台 / ${title}`;
  }, [breadcrumbs, title]);

  const navigateTo = (path) => {
    if (normalizePath(window.location.pathname) !== normalizePath(path)) {
      window.location.href = path;
    }
  };

  const drawerContent = (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column', backgroundColor: '#fbfcff' }}>
      <Box sx={{ px: 2.25, py: 2 }}>
        <Stack direction="row" spacing={1.25} alignItems="center">
          <Box
            sx={{
              width: 34,
              height: 34,
              borderRadius: 2.5,
              background: 'linear-gradient(135deg, #5b6cff 0%, #7b61ff 100%)',
              boxShadow: '0 8px 18px rgba(91,108,255,0.22)',
            }}
          />
          <Box>
            <Typography variant="subtitle1" sx={{ fontWeight: 700, lineHeight: 1.2 }}>
              Exam Analysis
            </Typography>
            <Typography variant="caption">Unified Test UI</Typography>

          </Box>
        </Stack>
      </Box>
      <Divider />
      <Box sx={{ px: 1.25, py: 1.5, flex: 1, overflowY: 'auto' }}>
        <Typography variant="caption" sx={{ px: 1.25, display: 'block', mb: 1 }}>
          功能导航
        </Typography>
        <List disablePadding>
          {navigationItems.map((item) => {
            const isExternal = Boolean(item.external);
            const selected = !isExternal && item.key === pageKey;
            return (
              <ListItemButton
                key={item.key}
                {...(isExternal
                  ? { component: 'a', href: item.path, target: '_blank', rel: 'noopener noreferrer' }
                  : {})}
                selected={selected}
                onClick={() => {
                  setMobileOpen(false);
                  if (!isExternal) {
                    navigateTo(item.path);
                  }
                }}
                sx={{
                  color: selected ? 'primary.main' : 'text.primary',
                  backgroundColor: selected ? (theme) => alpha(theme.palette.primary.main, 0.08) : 'transparent',
                  textDecoration: 'none',
                  '&:hover': {
                    backgroundColor: selected
                      ? (theme) => alpha(theme.palette.primary.main, 0.12)
                      : '#f2f3f5',
                  },
                }}
              >
                <ListItemIcon sx={{ minWidth: 34, color: 'inherit' }}>{item.icon}</ListItemIcon>
                <ListItemText
                  primary={item.label}
                  primaryTypographyProps={{ fontSize: 14, fontWeight: selected ? 700 : 500 }}
                />
                {isExternal && (
                  <Typography
                    component="span"
                    variant="caption"
                    color="text.secondary"
                    sx={{ ml: 0.5, flexShrink: 0 }}
                    title="在新标签页打开"
                  >
                    ↗
                  </Typography>
                )}
                {selected && <ChevronRightRoundedIcon sx={{ fontSize: 18 }} />}
              </ListItemButton>
            );
          })}
        </List>
      </Box>
      <Divider />
      <Box sx={{ px: 2.25, py: 1.75 }}>
        <Typography variant="caption" sx={{ display: 'block' }}>
          风格：浅色后台控制台
        </Typography>
        <Typography variant="caption">功能逻辑保持不变</Typography>
      </Box>
    </Box>
  );

  return (
    <ThemeProvider theme={adminTheme}>
      <CssBaseline />
      <Box sx={{ display: 'flex', minHeight: '100vh', backgroundColor: 'background.default' }}>
        <AppBar
          position="fixed"
          color="inherit"
          sx={{
            width: { md: `calc(100% - ${drawerWidth}px)` },
            ml: { md: `${drawerWidth}px` },
            backgroundColor: 'rgba(255, 255, 255, 0.92)',
            backdropFilter: 'blur(10px)',
            borderBottom: '1px solid',
            borderColor: 'divider',
          }}
        >
          <Toolbar sx={{ minHeight: '56px !important', px: { xs: 2, md: 3 } }}>
            <IconButton
              color="inherit"
              edge="start"
              onClick={() => setMobileOpen(true)}
              sx={{ mr: 1, display: { md: 'none' } }}
            >
              <MenuRoundedIcon />
            </IconButton>
            <Box>
              <Typography variant="subtitle1" sx={{ lineHeight: 1.1 }}>
                {title}
              </Typography>
              <Typography variant="caption">Exam Analysis Suite</Typography>
            </Box>
            <Box sx={{ flexGrow: 1 }} />
            <Chip label="管理后台" color="primary" variant="outlined" />
          </Toolbar>
        </AppBar>

        <Box component="nav" sx={{ width: { md: drawerWidth }, flexShrink: { md: 0 } }}>
          <Drawer
            variant="temporary"
            open={mobileOpen}
            onClose={() => setMobileOpen(false)}
            ModalProps={{ keepMounted: true }}
            sx={{
              display: { xs: 'block', md: 'none' },
              '& .MuiDrawer-paper': { width: drawerWidth, boxSizing: 'border-box' },
            }}
          >
            {drawerContent}
          </Drawer>
          <Drawer
            variant="permanent"
            sx={{
              display: { xs: 'none', md: 'block' },
              '& .MuiDrawer-paper': {
                width: drawerWidth,
                boxSizing: 'border-box',
                borderRight: '1px solid #e5e6eb',
                backgroundColor: '#fbfcff',
              },
            }}
            open
          >
            {drawerContent}
          </Drawer>
        </Box>

        <Box
          component="main"
          sx={{
            flexGrow: 1,
            width: { md: `calc(100% - ${drawerWidth}px)` },
            minWidth: 0,
          }}
        >
          <Toolbar sx={{ minHeight: '56px !important' }} />
          <Box sx={{ px: { xs: 2, md: 3 }, py: { xs: 2, md: 3 } }}>
            <Stack
              direction={{ xs: 'column', md: 'row' }}
              justifyContent="space-between"
              alignItems={{ xs: 'flex-start', md: 'center' }}
              spacing={2}
              sx={{ mb: 2.5 }}
            >
              <Box>
                <Typography variant="caption" sx={{ display: 'block', mb: 0.5 }}>
                  {currentBreadcrumbs}
                </Typography>
                <Typography variant="h4">{title}</Typography>
                {subtitle && (
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75, maxWidth: 840 }}>
                    {subtitle}
                  </Typography>
                )}
              </Box>
              {actions && (
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                  {actions}
                </Stack>
              )}
            </Stack>
            {children}
          </Box>
        </Box>
      </Box>
    </ThemeProvider>
  );
}

export default AdminShell;
