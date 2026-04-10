import { Alert, AlertTitle, Button, Box, useTheme } from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';

interface ErrorCardProps {
  message: string;
  title?: string;
  onRetry?: () => void;
}

export default function ErrorCard({
  message,
  title = 'Something went wrong',
  onRetry,
}: ErrorCardProps) {
  const theme = useTheme();

  return (
    <Alert
      severity="error"
      sx={{
        borderRadius: 2,
        bgcolor:
          theme.palette.mode === 'dark'
            ? 'rgba(244, 67, 54, 0.08)'
            : 'rgba(211, 47, 47, 0.06)',
      }}
      action={
        onRetry ? (
          <Box sx={{ display: 'flex', alignItems: 'center', height: '100%' }}>
            <Button
              size="small"
              color="error"
              startIcon={<RefreshIcon />}
              onClick={onRetry}
            >
              Retry
            </Button>
          </Box>
        ) : undefined
      }
    >
      <AlertTitle>{title}</AlertTitle>
      {message}
    </Alert>
  );
}
