import { createTheme } from '@mui/material/styles';

export const drawerWidth = 220;

export const panelSx = {
  p: { xs: 2, md: 2.5 },
  borderRadius: 3,
};

export const terminalSx = {
  mt: 2,
  p: 2,
  borderRadius: 2,
  border: '1px solid #1d2129',
  backgroundColor: '#0f1115',
  color: '#d7dde8',
  fontFamily: '"SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace',
  fontSize: '12px',
  lineHeight: 1.65,
  overflow: 'auto',
};

export const adminTheme = createTheme({
  palette: {
    mode: 'light',
    primary: {
      main: '#5b6cff',
    },
    secondary: {
      main: '#7b61ff',
    },
    background: {
      default: '#f5f7fa',
      paper: '#ffffff',
    },
    text: {
      primary: '#1f2329',
      secondary: '#4e5969',
    },
    divider: '#e5e6eb',
    success: {
      main: '#00b578',
    },
    warning: {
      main: '#ff9f00',
    },
    error: {
      main: '#f53f3f',
    },
    info: {
      main: '#4080ff',
    },
  },
  shape: {
    borderRadius: 10,
  },
  typography: {
    fontFamily: 'Inter, "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif',
    fontSize: 14,
    h4: {
      fontSize: '1.4rem',
      fontWeight: 700,
      letterSpacing: '-0.01em',
    },
    h5: {
      fontSize: '1.15rem',
      fontWeight: 600,
    },
    h6: {
      fontSize: '1rem',
      fontWeight: 600,
    },
    subtitle1: {
      fontSize: '0.95rem',
      fontWeight: 600,
    },
    body1: {
      fontSize: '0.875rem',
      lineHeight: 1.7,
    },
    body2: {
      fontSize: '0.8125rem',
      lineHeight: 1.7,
    },
    caption: {
      fontSize: '0.75rem',
      lineHeight: 1.5,
      color: '#86909c',
    },
    button: {
      fontSize: '0.875rem',
      fontWeight: 600,
    },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        'html, body, #root': {
          minHeight: '100%',
          width: '100%',
        },
        body: {
          margin: 0,
          backgroundColor: '#f5f7fa',
        },
        '*': {
          boxSizing: 'border-box',
        },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          boxShadow: 'none',
        },
      },
    },
    MuiPaper: {
      defaultProps: {
        elevation: 0,
      },
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          border: '1px solid #e5e6eb',
          boxShadow: '0 2px 8px rgba(31,35,41,0.06)',
        },
      },
    },
    MuiButton: {
      defaultProps: {
        disableElevation: true,
        size: 'medium',
      },
      styleOverrides: {
        root: {
          minWidth: 'auto',
          textTransform: 'none',
          borderRadius: 8,
          fontWeight: 600,
        },
        sizeMedium: {
          height: 34,
          padding: '0 14px',
        },
        sizeSmall: {
          height: 30,
          padding: '0 12px',
          fontSize: '0.8125rem',
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: {
          height: 24,
          borderRadius: 6,
          fontSize: '0.75rem',
          fontWeight: 600,
        },
      },
    },
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          borderRadius: 8,
          backgroundColor: '#ffffff',
          minHeight: 36,
          '& fieldset': {
            borderColor: '#dcdfe6',
          },
          '&:hover fieldset': {
            borderColor: '#94a0ff',
          },
          '&.Mui-focused fieldset': {
            borderWidth: 1,
            borderColor: '#5b6cff',
          },
        },
        input: {
          padding: '8px 12px',
        },
        multiline: {
          padding: 0,
        },
      },
    },
    MuiInputLabel: {
      styleOverrides: {
        root: {
          fontSize: '0.875rem',
        },
      },
    },
    MuiFormHelperText: {
      styleOverrides: {
        root: {
          marginLeft: 0,
          fontSize: '0.75rem',
        },
      },
    },
    MuiSelect: {
      styleOverrides: {
        select: {
          minHeight: 'unset',
          paddingTop: 8,
          paddingBottom: 8,
        },
      },
    },
    MuiTableCell: {
      styleOverrides: {
        head: {
          padding: '11px 14px',
          backgroundColor: '#fafbfc',
          color: '#1f2329',
          fontWeight: 700,
          whiteSpace: 'nowrap',
        },
        root: {
          padding: '12px 14px',
          borderBottom: '1px solid #eef0f3',
          verticalAlign: 'top',
        },
      },
    },
    MuiTableRow: {
      styleOverrides: {
        root: {
          '&:last-child td': {
            borderBottom: 'none',
          },
        },
      },
    },
    MuiListItemButton: {
      styleOverrides: {
        root: {
          minHeight: 38,
          borderRadius: 10,
          marginBottom: 4,
          paddingTop: 7,
          paddingBottom: 7,
        },
      },
    },
    MuiAlert: {
      styleOverrides: {
        root: {
          borderRadius: 10,
        },
      },
    },
    MuiFormControlLabel: {
      styleOverrides: {
        label: {
          fontSize: '0.875rem',
        },
      },
    },
    MuiSwitch: {
      defaultProps: {
        size: 'small',
      },
    },
  },
});
