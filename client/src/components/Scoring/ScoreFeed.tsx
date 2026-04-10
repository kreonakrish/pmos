import { useRef, useEffect } from 'react';
import {
  Box,
  Typography,
  List,
  ListItem,
  Chip,
  Skeleton,
} from '@mui/material';
import { useTheme, alpha } from '@mui/material/styles';
import ScoreBandViz from '@/components/Agents/ScoreBandViz';

interface FeedItem {
  id: number;
  agentName: string;
  score: number;
  bandLow: number;
  bandHigh: number;
  recommendation: string;
  timestamp: string;
}

interface Props {
  items: FeedItem[];
  loading?: boolean;
}

const recommendationColor: Record<string, 'success' | 'warning' | 'error' | 'info'> = {
  proceed: 'success',
  course_correct: 'warning',
  escalate: 'error',
  halt: 'error',
};

export default function ScoreFeed({ items, loading }: Props) {
  const theme = useTheme();
  const listRef = useRef<HTMLUListElement>(null);

  // Auto-scroll to top when new items arrive
  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = 0;
    }
  }, [items.length]);

  if (loading) {
    return (
      <Box>
        <Typography variant="subtitle2" gutterBottom>
          Real-time Score Feed
        </Typography>
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} variant="rectangular" height={48} sx={{ mb: 1, borderRadius: 1 }} />
        ))}
      </Box>
    );
  }

  if (items.length === 0) {
    return (
      <Box>
        <Typography variant="subtitle2" gutterBottom>
          Real-time Score Feed
        </Typography>
        <Box sx={{ py: 4, textAlign: 'center' }}>
          <Typography variant="body2" color="text.secondary">
            No scoring events yet. Events will appear here as agents execute tasks.
          </Typography>
        </Box>
      </Box>
    );
  }

  return (
    <Box>
      <Typography variant="subtitle2" gutterBottom>
        Real-time Score Feed
      </Typography>
      <List
        ref={listRef}
        sx={{
          maxHeight: 400,
          overflow: 'auto',
          bgcolor: alpha(theme.palette.background.default, 0.5),
          borderRadius: 1,
          border: 1,
          borderColor: 'divider',
        }}
        disablePadding
      >
        {items.slice(0, 50).map((item) => (
          <ListItem
            key={item.id}
            sx={{
              display: 'flex',
              gap: 2,
              alignItems: 'center',
              py: 1,
              px: 2,
              borderBottom: 1,
              borderColor: 'divider',
              '&:last-child': { borderBottom: 0 },
            }}
          >
            <Typography variant="body2" fontWeight={600} sx={{ minWidth: 100 }} noWrap>
              {item.agentName}
            </Typography>
            <Typography
              variant="body2"
              fontWeight={700}
              color={item.score >= 0.7 ? 'success.main' : item.score >= 0.4 ? 'warning.main' : 'error.main'}
              sx={{ minWidth: 50 }}
            >
              {item.score.toFixed(3)}
            </Typography>
            <Box sx={{ flex: 1, minWidth: 80 }}>
              <ScoreBandViz
                bandLow={item.bandLow}
                bandHigh={item.bandHigh}
                currentScore={item.score}
                height={6}
              />
            </Box>
            <Chip
              label={item.recommendation.replace('_', ' ')}
              size="small"
              color={recommendationColor[item.recommendation] ?? 'default'}
              sx={{ fontSize: '0.65rem', height: 22 }}
            />
            <Typography variant="caption" color="text.secondary" sx={{ minWidth: 70, textAlign: 'right' }}>
              {new Date(item.timestamp).toLocaleTimeString()}
            </Typography>
          </ListItem>
        ))}
      </List>
    </Box>
  );
}
