import { Box, Typography, Button, useTheme } from '@mui/material';
import InboxIcon from '@mui/icons-material/Inbox';
import type { SvgIconComponent } from '@mui/icons-material';

interface EmptyStateProps {
  icon?: SvgIconComponent;
  title: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
}

export default function EmptyState({
  icon: Icon = InboxIcon,
  title,
  description,
  actionLabel,
  onAction,
}: EmptyStateProps) {
  const theme = useTheme();

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        py: 8,
        px: 3,
        textAlign: 'center',
      }}
    >
      <Icon
        sx={{
          fontSize: 64,
          color: theme.palette.text.disabled,
          mb: 2,
        }}
      />
      <Typography
        variant="h6"
        sx={{ color: theme.palette.text.primary, mb: 1 }}
      >
        {title}
      </Typography>
      {description && (
        <Typography
          variant="body2"
          sx={{
            color: theme.palette.text.secondary,
            maxWidth: 400,
            mb: actionLabel ? 3 : 0,
          }}
        >
          {description}
        </Typography>
      )}
      {actionLabel && onAction && (
        <Button variant="contained" onClick={onAction}>
          {actionLabel}
        </Button>
      )}
    </Box>
  );
}
