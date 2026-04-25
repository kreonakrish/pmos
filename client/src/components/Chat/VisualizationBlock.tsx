/* ---------------------------------------------------------------
 * VisualizationBlock — render a single Visualization payload as a
 * recharts chart (bar/line/pie/area) or a plain MUI table, with
 * a header toolbar that lets the user switch chart type and
 * download the underlying data as CSV.
 *
 * The component is fully self-contained — it reads only its `viz`
 * prop and the MUI theme, owns its own toggle/state, and never
 * mutates the input data. Recharts gets pulled in per-chart so
 * Vite tree-shakes the bits we don't need.
 * --------------------------------------------------------------- */

import { useMemo, useState } from 'react';
import {
  Alert,
  Box,
  IconButton,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from '@mui/material';
import { useTheme } from '@mui/material/styles';
import DownloadIcon from '@mui/icons-material/Download';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { ChartType, Visualization } from '@/api/visualization';

interface Props {
  viz: Visualization;
}

const CHART_HEIGHT = 320;
const TABLE_MAX_HEIGHT = 360;

/** Toggle modes shown in the header. (`area` is reachable via the
 * inferer's initial `viz.type` but isn't offered as a manual toggle —
 * the spec only requires bar/line/pie/table.) */
type ToggleMode = 'bar' | 'line' | 'pie' | 'table';

const TOGGLE_MODES: ToggleMode[] = ['bar', 'line', 'pie', 'table'];

/* -----------------------------------------------------------------
 * Helpers
 * ----------------------------------------------------------------- */

/** Sanitize a title for use as a CSV filename. */
function sanitizeFilename(name: string): string {
  const cleaned = name
    .trim()
    .replace(/[^\w\d\-_.\s]+/g, '')
    .replace(/\s+/g, '_')
    .slice(0, 80);
  return (cleaned || 'visualization') + '.csv';
}

/** Quote a single CSV cell when it contains a comma, quote, or newline. */
function csvEscape(value: unknown): string {
  if (value === null || value === undefined) return '';
  const s = typeof value === 'string' ? value : String(value);
  if (/[",\n\r]/.test(s)) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}

/** Build a CSV string from rows + the canonical header order. */
function buildCsv(
  rows: Array<Record<string, string | number | boolean | null>>,
  headers: string[],
): string {
  const headerLine = headers.map(csvEscape).join(',');
  const bodyLines = rows.map((r) =>
    headers.map((h) => csvEscape(r[h])).join(','),
  );
  return [headerLine, ...bodyLines].join('\r\n');
}

function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // Defer revoke so Safari/Firefox have time to trigger the download.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** True if every y-series value across every row is nullish. */
function allYsNull(
  rows: Array<Record<string, string | number | boolean | null>>,
  yFields: string[],
): boolean {
  if (rows.length === 0 || yFields.length === 0) return true;
  for (const row of rows) {
    for (const y of yFields) {
      const v = row[y];
      if (v !== null && v !== undefined && v !== '') return false;
    }
  }
  return true;
}

/* -----------------------------------------------------------------
 * Component
 * ----------------------------------------------------------------- */

export default function VisualizationBlock({ viz }: Props) {
  const theme = useTheme();

  // Cycle through the MUI palette for series colors.
  const seriesColors = useMemo(
    () => [
      theme.palette.primary.main,
      theme.palette.secondary.main,
      theme.palette.info.main,
      theme.palette.success.main,
      theme.palette.warning.main,
      theme.palette.error.main,
    ],
    [theme],
  );

  // Map the wire `ChartType` to one of the four toggle modes. `area`
  // collapses to `line` for the toggle UI but the AreaChart stays the
  // initial render until the user clicks something.
  const initialMode: ToggleMode = useMemo(() => {
    const t: ChartType = viz.type;
    if (t === 'bar' || t === 'line' || t === 'pie' || t === 'table') return t;
    return 'line'; // 'area' falls through to the line toggle
  }, [viz.type]);

  const [mode, setMode] = useState<ToggleMode>(initialMode);
  // Track separately whether the very first render should use AreaChart
  // (server said `area`) or the toggle's chart. Once the user clicks a
  // toggle button, we always honor `mode`.
  const [userPickedMode, setUserPickedMode] = useState(false);
  const showAreaInitial = viz.type === 'area' && !userPickedMode;

  const headers = useMemo(
    () => [viz.x_field, ...viz.y_fields],
    [viz.x_field, viz.y_fields],
  );

  const dataIsEmpty = !Array.isArray(viz.data) || viz.data.length === 0;
  const ysAllNull = !dataIsEmpty && allYsNull(viz.data, viz.y_fields);
  const pieAllowed = viz.y_fields.length === 1 && viz.data.length <= 12;

  const handleModeChange = (
    _event: React.MouseEvent<HTMLElement>,
    next: ToggleMode | null,
  ) => {
    if (next == null) return; // ToggleButtonGroup fires null on deselect
    setMode(next);
    setUserPickedMode(true);
  };

  const handleDownload = () => {
    if (dataIsEmpty) return;
    const csv = buildCsv(viz.data, headers);
    downloadCsv(sanitizeFilename(viz.title), csv);
  };

  /* ---------------- chart renderers ---------------- */

  const renderBar = () => (
    <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
      <BarChart data={viz.data} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={theme.palette.divider} />
        <XAxis dataKey={viz.x_field} tick={{ fontSize: 11 }} />
        <YAxis tick={{ fontSize: 11 }} width={40} />
        <RechartsTooltip
          contentStyle={{
            backgroundColor: theme.palette.background.paper,
            border: `1px solid ${theme.palette.divider}`,
            fontSize: 12,
          }}
        />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        {viz.y_fields.map((y, i) => (
          <Bar key={y} dataKey={y} fill={seriesColors[i % seriesColors.length]} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );

  const renderLine = () => (
    <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
      <LineChart data={viz.data} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={theme.palette.divider} />
        <XAxis dataKey={viz.x_field} tick={{ fontSize: 11 }} />
        <YAxis tick={{ fontSize: 11 }} width={40} />
        <RechartsTooltip
          contentStyle={{
            backgroundColor: theme.palette.background.paper,
            border: `1px solid ${theme.palette.divider}`,
            fontSize: 12,
          }}
        />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        {viz.y_fields.map((y, i) => (
          <Line
            key={y}
            type="monotone"
            dataKey={y}
            stroke={seriesColors[i % seriesColors.length]}
            strokeWidth={2}
            dot={false}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );

  const renderArea = () => (
    <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
      <AreaChart data={viz.data} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={theme.palette.divider} />
        <XAxis dataKey={viz.x_field} tick={{ fontSize: 11 }} />
        <YAxis tick={{ fontSize: 11 }} width={40} />
        <RechartsTooltip
          contentStyle={{
            backgroundColor: theme.palette.background.paper,
            border: `1px solid ${theme.palette.divider}`,
            fontSize: 12,
          }}
        />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        {viz.y_fields.map((y, i) => {
          const color = seriesColors[i % seriesColors.length];
          return (
            <Area
              key={y}
              type="monotone"
              dataKey={y}
              stroke={color}
              fill={color}
              fillOpacity={0.18}
              strokeWidth={2}
            />
          );
        })}
      </AreaChart>
    </ResponsiveContainer>
  );

  const renderPie = () => {
    const yField = viz.y_fields[0];
    // recharts wants a flat number for `value`; coerce defensively.
    const pieData = viz.data.map((row) => {
      const raw = row[yField];
      const num = typeof raw === 'number' ? raw : Number(raw);
      return {
        name: String(row[viz.x_field] ?? ''),
        value: Number.isFinite(num) ? num : 0,
      };
    });
    return (
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <PieChart>
          <RechartsTooltip
            contentStyle={{
              backgroundColor: theme.palette.background.paper,
              border: `1px solid ${theme.palette.divider}`,
              fontSize: 12,
            }}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Pie
            data={pieData}
            dataKey="value"
            nameKey="name"
            cx="50%"
            cy="50%"
            outerRadius={110}
            label={({ name, percent }) =>
              `${name} ${(((percent as number) ?? 0) * 100).toFixed(0)}%`
            }
          >
            {pieData.map((_, i) => (
              <Cell key={i} fill={seriesColors[i % seriesColors.length]} />
            ))}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
    );
  };

  const renderTable = () => (
    <TableContainer sx={{ maxHeight: TABLE_MAX_HEIGHT }}>
      <Table size="small" stickyHeader>
        <TableHead>
          <TableRow>
            {headers.map((h) => (
              <TableCell key={h} sx={{ fontWeight: 600, bgcolor: 'background.paper' }}>
                {h}
              </TableCell>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>
          {viz.data.map((row, idx) => (
            <TableRow key={idx} hover>
              {headers.map((h) => {
                const v = row[h];
                return (
                  <TableCell key={h}>
                    {v === null || v === undefined ? '' : String(v)}
                  </TableCell>
                );
              })}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );

  /* ---------------- body switch ---------------- */

  const renderBody = () => {
    if (dataIsEmpty || ysAllNull) {
      return <Alert severity="info">No data to plot.</Alert>;
    }
    if (mode === 'table') return renderTable();
    if (mode === 'pie') {
      if (!pieAllowed) {
        return (
          <Alert severity="warning">
            Pie needs 1 numeric series and ≤12 categories.
          </Alert>
        );
      }
      return renderPie();
    }
    if (mode === 'bar') return renderBar();
    // mode === 'line' — but if the user hasn't toggled yet and the
    // server suggested 'area', honor that for the first render.
    if (showAreaInitial) return renderArea();
    return renderLine();
  };

  /* ---------------- header ---------------- */

  return (
    <Paper
      variant="outlined"
      sx={{
        p: 1.5,
        bgcolor: 'background.paper',
        borderColor: 'divider',
      }}
    >
      <Stack
        direction="row"
        alignItems="flex-start"
        spacing={1}
        sx={{ mb: 1, flexWrap: 'wrap' }}
      >
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 600 }} noWrap>
            {viz.title}
          </Typography>
          {viz.description && (
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{ display: 'block', lineHeight: 1.4 }}
            >
              {viz.description}
            </Typography>
          )}
        </Box>

        <ToggleButtonGroup
          size="small"
          value={mode}
          exclusive
          onChange={handleModeChange}
          aria-label="chart type"
        >
          {TOGGLE_MODES.map((m) => {
            const disabled = m === 'pie' && !pieAllowed;
            const button = (
              <ToggleButton
                key={m}
                value={m}
                disabled={disabled}
                sx={{ textTransform: 'capitalize', px: 1.25, py: 0.25, fontSize: 11 }}
              >
                {m}
              </ToggleButton>
            );
            if (disabled) {
              return (
                <Tooltip
                  key={m}
                  title="Pie needs 1 numeric series and ≤12 categories"
                >
                  {/* span wrapper because disabled buttons swallow tooltip events */}
                  <span>{button}</span>
                </Tooltip>
              );
            }
            return button;
          })}
        </ToggleButtonGroup>

        <Tooltip title="Download CSV">
          <span>
            <IconButton
              size="small"
              onClick={handleDownload}
              disabled={dataIsEmpty}
              aria-label="download csv"
            >
              <DownloadIcon fontSize="small" />
            </IconButton>
          </span>
        </Tooltip>
      </Stack>

      <Box>{renderBody()}</Box>

      {viz.truncated_from != null && (
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ display: 'block', mt: 0.75, textAlign: 'right' }}
        >
          Showing 200 of {viz.truncated_from} rows
        </Typography>
      )}
    </Paper>
  );
}
