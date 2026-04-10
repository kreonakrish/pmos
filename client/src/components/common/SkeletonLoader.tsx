import { Box, Card, CardContent, Skeleton, useTheme } from '@mui/material';

export function CardSkeleton() {
  return (
    <Card>
      <CardContent>
        <Skeleton variant="text" width="60%" height={28} />
        <Skeleton variant="text" width="80%" height={20} sx={{ mt: 1 }} />
        <Skeleton variant="text" width="40%" height={20} sx={{ mt: 0.5 }} />
        <Skeleton
          variant="rectangular"
          width="100%"
          height={80}
          sx={{ mt: 2, borderRadius: 1 }}
        />
      </CardContent>
    </Card>
  );
}

export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  const theme = useTheme();
  return (
    <Box>
      {/* Header row */}
      <Box
        sx={{
          display: 'flex',
          gap: 2,
          p: 1.5,
          borderBottom: `1px solid ${theme.palette.divider}`,
        }}
      >
        {[120, 180, 100, 80, 60].map((w, i) => (
          <Skeleton key={i} variant="text" width={w} height={24} />
        ))}
      </Box>
      {/* Data rows */}
      {Array.from({ length: rows }).map((_, rowIdx) => (
        <Box
          key={rowIdx}
          sx={{
            display: 'flex',
            gap: 2,
            p: 1.5,
            borderBottom: `1px solid ${theme.palette.divider}`,
          }}
        >
          {[120, 180, 100, 80, 60].map((w, i) => (
            <Skeleton key={i} variant="text" width={w} height={20} />
          ))}
        </Box>
      ))}
    </Box>
  );
}

export function ChartSkeleton({ height = 200 }: { height?: number }) {
  return (
    <Card>
      <CardContent>
        <Skeleton variant="text" width="30%" height={24} />
        <Skeleton
          variant="rectangular"
          width="100%"
          height={height}
          sx={{ mt: 2, borderRadius: 1 }}
        />
      </CardContent>
    </Card>
  );
}

export function MessageSkeleton() {
  const theme = useTheme();
  return (
    <Box sx={{ display: 'flex', gap: 1.5, p: 2 }}>
      <Skeleton variant="circular" width={36} height={36} />
      <Box sx={{ flex: 1 }}>
        <Skeleton variant="text" width="25%" height={20} />
        <Skeleton
          variant="rectangular"
          width="70%"
          height={48}
          sx={{
            mt: 1,
            borderRadius: 1.5,
            bgcolor:
              theme.palette.mode === 'dark'
                ? 'rgba(255,255,255,0.04)'
                : 'rgba(0,0,0,0.04)',
          }}
        />
      </Box>
    </Box>
  );
}
