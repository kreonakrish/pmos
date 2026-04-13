import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Box,
  Paper,
  Stack,
  Typography,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  TextField,
  Button,
  Chip,
  IconButton,
  Tooltip,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import StopIcon from '@mui/icons-material/Stop';
import DeleteSweepIcon from '@mui/icons-material/DeleteSweep';
import VerticalAlignBottomIcon from '@mui/icons-material/VerticalAlignBottom';
import { listLogServices, openLiveTail, type LogLine } from '@/api/logs';

const LEVEL_COLORS: Record<string, 'default' | 'info' | 'warning' | 'error' | 'success'> = {
  DEBUG: 'default',
  INFO: 'info',
  WARN: 'warning',
  ERROR: 'error',
  UNKNOWN: 'default',
};

const MAX_LINES = 5000;

export default function LogsPage() {
  const [services, setServices] = useState<string[]>([]);
  const [service, setService] = useState<string>('gateway');
  const [level, setLevel] = useState<string>('');
  const [traceId, setTraceId] = useState<string>('');
  const [filterText, setFilterText] = useState<string>('');
  const [lines, setLines] = useState<LogLine[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const controllerRef = useRef<AbortController | null>(null);
  const logBoxRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    listLogServices().then(setServices).catch(() => setServices([]));
  }, []);

  useEffect(() => {
    return () => controllerRef.current?.abort();
  }, []);

  useEffect(() => {
    if (autoScroll && logBoxRef.current) {
      logBoxRef.current.scrollTop = 0;
    }
  }, [lines, autoScroll]);

  const start = () => {
    controllerRef.current?.abort();
    setLines([]);
    setError(null);
    setStreaming(true);
    controllerRef.current = openLiveTail(
      { service, level: level || undefined, traceId: traceId || undefined, tail: 300 },
      (line) => {
        setLines((prev) => {
          const next = prev.length >= MAX_LINES ? prev.slice(-MAX_LINES + 1) : prev.slice();
          next.push(line);
          return next;
        });
      },
      (err) => {
        setError(err instanceof Error ? err.message : String(err));
        setStreaming(false);
      },
    );
  };

  const stop = () => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setStreaming(false);
  };

  const clear = () => setLines([]);

  const filtered = useMemo(() => {
    if (!filterText) return lines;
    const needle = filterText.toLowerCase();
    return lines.filter(
      (l) =>
        l.msg.toLowerCase().includes(needle) ||
        (l.trace_id ?? '').toLowerCase().includes(needle) ||
        l.raw.toLowerCase().includes(needle),
    );
  }, [lines, filterText]);

  const displayed = useMemo(() => [...filtered].reverse(), [filtered]);

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 2 }}>
        Service Logs
      </Typography>

      <Paper sx={{ p: 2, mb: 2 }}>
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems="center">
          <FormControl size="small" sx={{ minWidth: 180 }}>
            <InputLabel>Service</InputLabel>
            <Select
              label="Service"
              value={service}
              onChange={(e) => setService(e.target.value)}
              disabled={streaming}
            >
              {services.map((s) => (
                <MenuItem key={s} value={s}>
                  {s}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          <FormControl size="small" sx={{ minWidth: 140 }}>
            <InputLabel>Level</InputLabel>
            <Select
              label="Level"
              value={level}
              onChange={(e) => setLevel(e.target.value)}
              disabled={streaming}
            >
              <MenuItem value="">All</MenuItem>
              <MenuItem value="DEBUG">DEBUG</MenuItem>
              <MenuItem value="INFO">INFO</MenuItem>
              <MenuItem value="WARN">WARN</MenuItem>
              <MenuItem value="ERROR">ERROR</MenuItem>
            </Select>
          </FormControl>

          <TextField
            size="small"
            label="Trace ID"
            value={traceId}
            onChange={(e) => setTraceId(e.target.value)}
            disabled={streaming}
            sx={{ minWidth: 220 }}
          />

          <TextField
            size="small"
            label="Filter (client-side)"
            value={filterText}
            onChange={(e) => setFilterText(e.target.value)}
            sx={{ minWidth: 220, flex: 1 }}
          />

          {streaming ? (
            <Button
              variant="contained"
              color="error"
              startIcon={<StopIcon />}
              onClick={stop}
            >
              Stop
            </Button>
          ) : (
            <Button
              variant="contained"
              startIcon={<PlayArrowIcon />}
              onClick={start}
              disabled={!service}
            >
              Tail
            </Button>
          )}

          <Tooltip title="Clear">
            <IconButton onClick={clear}>
              <DeleteSweepIcon />
            </IconButton>
          </Tooltip>

          <Tooltip title={autoScroll ? 'Auto-scroll on' : 'Auto-scroll off'}>
            <IconButton
              color={autoScroll ? 'primary' : 'default'}
              onClick={() => setAutoScroll((v) => !v)}
            >
              <VerticalAlignBottomIcon />
            </IconButton>
          </Tooltip>
        </Stack>

        {error && (
          <Typography variant="caption" color="error" sx={{ mt: 1, display: 'block' }}>
            {error}
          </Typography>
        )}
      </Paper>

      <Paper
        ref={logBoxRef}
        sx={{
          p: 1,
          height: 'calc(100vh - 260px)',
          overflow: 'auto',
          bgcolor: (t) => (t.palette.mode === 'dark' ? '#0b0f14' : '#f6f8fa'),
          fontFamily: 'monospace',
          fontSize: 12.5,
        }}
      >
        {displayed.length === 0 && (
          <Typography variant="body2" color="text.secondary" sx={{ p: 2 }}>
            {streaming ? 'Waiting for logs…' : 'Pick a service and press Tail.'}
          </Typography>
        )}
        {displayed.map((l, i) => (
          <Box
            key={i}
            sx={{
              display: 'flex',
              gap: 1,
              py: 0.25,
              px: 1,
              borderBottom: (t) => `1px dashed ${t.palette.divider}`,
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}
          >
            <Box sx={{ color: 'text.secondary', flexShrink: 0 }}>
              {l.ts.slice(11, 23)}
            </Box>
            <Chip
              size="small"
              label={l.level}
              color={LEVEL_COLORS[l.level] ?? 'default'}
              sx={{ height: 18, fontSize: 10, flexShrink: 0 }}
            />
            {l.trace_id && (
              <Box
                sx={{
                  color: 'primary.main',
                  flexShrink: 0,
                  cursor: 'pointer',
                  '&:hover': { textDecoration: 'underline' },
                }}
                onClick={() => setTraceId(l.trace_id ?? '')}
                title="Filter by this trace_id"
              >
                {l.trace_id.slice(0, 8)}
              </Box>
            )}
            <Box sx={{ flex: 1 }}>{l.msg}</Box>
          </Box>
        ))}
      </Paper>
    </Box>
  );
}
