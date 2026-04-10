import { createTheme, type ThemeOptions } from '@mui/material/styles';

const sharedTypography: ThemeOptions['typography'] = {
  fontFamily: '"Inter", "Roboto", "Helvetica", "Arial", sans-serif',
  h1: { fontSize: '2.25rem', fontWeight: 700 },
  h2: { fontSize: '1.875rem', fontWeight: 700 },
  h3: { fontSize: '1.5rem', fontWeight: 600 },
  h4: { fontSize: '1.25rem', fontWeight: 600 },
  h5: { fontSize: '1.1rem', fontWeight: 600 },
  h6: { fontSize: '1rem', fontWeight: 600 },
  body1: { fontSize: '0.9375rem' },
  body2: { fontSize: '0.875rem' },
  caption: { fontSize: '0.75rem' },
};

const sharedComponents: ThemeOptions['components'] = {
  MuiCard: {
    styleOverrides: {
      root: {
        borderRadius: 12,
      },
    },
  },
  MuiPaper: {
    styleOverrides: {
      rounded: {
        borderRadius: 12,
      },
    },
  },
  MuiTextField: {
    defaultProps: {
      variant: 'filled',
      size: 'small',
    },
  },
  MuiTable: {
    styleOverrides: {
      root: {
        fontSize: '0.875rem',
      },
    },
  },
  MuiTableCell: {
    styleOverrides: {
      root: {
        padding: '8px 16px',
      },
    },
  },
  MuiButton: {
    styleOverrides: {
      root: {
        borderRadius: 8,
        textTransform: 'none',
        fontWeight: 600,
      },
    },
  },
  MuiChip: {
    styleOverrides: {
      root: {
        borderRadius: 8,
      },
    },
  },
};

export const darkTheme = createTheme({
  palette: {
    mode: 'dark',
    primary: {
      main: '#5c9ce6',
      light: '#8bb8ef',
      dark: '#3a7bd5',
      contrastText: '#ffffff',
    },
    secondary: {
      main: '#4db6ac',
      light: '#80cbc4',
      dark: '#00897b',
      contrastText: '#ffffff',
    },
    background: {
      default: '#0a1929',
      paper: '#1a2744',
    },
    error: {
      main: '#f44336',
      light: '#ef5350',
      dark: '#c62828',
    },
    warning: {
      main: '#ffa726',
      light: '#ffb74d',
      dark: '#f57c00',
    },
    success: {
      main: '#66bb6a',
      light: '#81c784',
      dark: '#388e3c',
    },
    info: {
      main: '#29b6f6',
      light: '#4fc3f7',
      dark: '#0288d1',
    },
    divider: 'rgba(255, 255, 255, 0.08)',
    text: {
      primary: '#e3e8ef',
      secondary: '#a0aec0',
    },
  },
  typography: sharedTypography,
  components: {
    ...sharedComponents,
    MuiDrawer: {
      styleOverrides: {
        paper: {
          backgroundColor: '#0f1f38',
          borderRight: '1px solid rgba(255, 255, 255, 0.06)',
        },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundColor: '#0f1f38',
          borderBottom: '1px solid rgba(255, 255, 255, 0.06)',
        },
      },
    },
  },
});

export const lightTheme = createTheme({
  palette: {
    mode: 'light',
    primary: {
      main: '#1976d2',
      light: '#42a5f5',
      dark: '#1565c0',
      contrastText: '#ffffff',
    },
    secondary: {
      main: '#00897b',
      light: '#4db6ac',
      dark: '#00695c',
      contrastText: '#ffffff',
    },
    background: {
      default: '#f5f7fa',
      paper: '#ffffff',
    },
    error: {
      main: '#d32f2f',
      light: '#ef5350',
      dark: '#c62828',
    },
    warning: {
      main: '#ed6c02',
      light: '#ff9800',
      dark: '#e65100',
    },
    success: {
      main: '#2e7d32',
      light: '#4caf50',
      dark: '#1b5e20',
    },
    info: {
      main: '#0288d1',
      light: '#03a9f4',
      dark: '#01579b',
    },
    divider: 'rgba(0, 0, 0, 0.08)',
    text: {
      primary: '#1a2027',
      secondary: '#637381',
    },
  },
  typography: sharedTypography,
  components: {
    ...sharedComponents,
    MuiDrawer: {
      styleOverrides: {
        paper: {
          backgroundColor: '#ffffff',
          borderRight: '1px solid rgba(0, 0, 0, 0.08)',
        },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundColor: '#ffffff',
          borderBottom: '1px solid rgba(0, 0, 0, 0.08)',
          color: '#1a2027',
        },
      },
    },
  },
});
