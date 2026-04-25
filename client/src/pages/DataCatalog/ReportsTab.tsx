import { useMemo, useState } from 'react';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Button,
  FormControl,
  Grid,
  IconButton,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Skeleton,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import AssessmentIcon from '@mui/icons-material/Assessment';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import RefreshIcon from '@mui/icons-material/Refresh';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import {
  CatalogReport,
  CatalogReportDataset,
  ReportSystem,
  useReports,
} from '@/api/reports';

const SYSTEM_OPTIONS: Array<ReportSystem | ''> = [
  '',
  'SSRS',
  'COGNOS',
  'POWERBI',
  'TABLEAU',
  'CUSTOM',
];

export default function ReportsTab() {
  const [systemFilter, setSystemFilter] = useState<ReportSystem | ''>('');
  const [ownerFilter, setOwnerFilter] = useState<string>('');
  const [search, setSearch] = useState<string>('');
  const [attributesFor, setAttributesFor] = useState<CatalogReport | null>(null);

  // We pull on system; owner_team filter is applied client-side because we
  // also need the full distinct-values list to populate the dropdown.
  const reportsQ = useReports({
    system: systemFilter || undefined,
  });
  const allReports = reportsQ.data?.reports ?? [];

  const ownerTeams = useMemo<string[]>(() => {
    const set = new Set<string>();
    for (const r of allReports) {
      if (r.owner_team) set.add(r.owner_team);
    }
    return Array.from(set).sort();
  }, [allReports]);

  const filteredReports = useMemo(() => {
    const q = search.trim().toLowerCase();
    return allReports.filter((r) => {
      if (ownerFilter && r.owner_team !== ownerFilter) return false;
      if (q) {
        const hay = `${r.name} ${r.description}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [allReports, ownerFilter, search]);

  return (
    <Box>
      {/* Filter bar */}
      <Paper sx={{ p: 2, mb: 2 }}>
        <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap" useFlexGap>
          <FormControl size="small" sx={{ minWidth: 160 }}>
            <InputLabel>System</InputLabel>
            <Select
              label="System"
              value={systemFilter}
              onChange={(e) =>
                setSystemFilter((e.target.value as ReportSystem | '') ?? '')
              }
            >
              {SYSTEM_OPTIONS.map((s) => (
                <MenuItem key={s || 'ALL'} value={s}>
                  {s || 'All systems'}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl size="small" sx={{ minWidth: 200 }}>
            <InputLabel>Owner team</InputLabel>
            <Select
              label="Owner team"
              value={ownerFilter}
              onChange={(e) => setOwnerFilter(String(e.target.value))}
            >
              <MenuItem value="">All teams</MenuItem>
              {ownerTeams.map((t) => (
                <MenuItem key={t} value={t}>
                  {t}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <TextField
            size="small"
            label="Search name / description"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            sx={{ flex: 1, minWidth: 240 }}
          />
          <Box sx={{ flex: 0 }} />
          <Tooltip title="Refresh reports">
            <span>
              <IconButton size="small" onClick={() => reportsQ.refetch()}>
                <RefreshIcon fontSize="small" />
              </IconButton>
            </span>
          </Tooltip>
          <Typography variant="caption" color="text.secondary">
            {filteredReports.length} / {allReports.length} reports
          </Typography>
        </Stack>
      </Paper>

      {/* List */}
      {reportsQ.isLoading ? (
        <Skeleton height={400} />
      ) : reportsQ.isError ? (
        <Alert severity="error">
          Failed to load reports: {(reportsQ.error as Error)?.message ?? 'unknown error'}
        </Alert>
      ) : filteredReports.length === 0 ? (
        <Alert severity="info">
          No Report nodes match the current filters. Reports are ingested from
          source systems (SSRS, Power BI, Cognos, Tableau) and surface as
          deterministic short-circuit candidates in the Translator.
        </Alert>
      ) : (
        <Grid container spacing={2}>
          {filteredReports.map((r) => (
            <Grid key={r.report_id} item xs={12} md={6} lg={4}>
              <ReportCard
                report={r}
                onShowAttributes={() => setAttributesFor(r)}
              />
            </Grid>
          ))}
        </Grid>
      )}

      {/* Uses-attributes dialog */}
      <Dialog
        open={!!attributesFor}
        onClose={() => setAttributesFor(null)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>
          Business attributes used
          {attributesFor && (
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
              {attributesFor.name}
            </Typography>
          )}
        </DialogTitle>
        <DialogContent dividers>
          {attributesFor && attributesFor.uses_attributes.length > 0 ? (
            <Stack spacing={0.5}>
              {attributesFor.uses_attributes.map((a) => (
                <Typography
                  key={a}
                  variant="body2"
                  sx={{ fontFamily: 'monospace', fontSize: 12 }}
                >
                  {a}
                </Typography>
              ))}
            </Stack>
          ) : (
            <Typography variant="body2" color="text.secondary">
              No business attributes recorded for this report.
            </Typography>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAttributesFor(null)}>Close</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

// ---------------------------------------------------------------------------
// Per-report card. Clickable accordion lists each ReportDataset's command.
// ---------------------------------------------------------------------------
function ReportCard({
  report,
  onShowAttributes,
}: {
  report: CatalogReport;
  onShowAttributes: () => void;
}) {
  const noDatasets = report.datasets.length === 0;
  return (
    <Paper variant="outlined" sx={{ p: 1.5, height: '100%' }}>
      <Stack direction="row" alignItems="center" spacing={0.75} sx={{ mb: 0.75 }}>
        <AssessmentIcon fontSize="small" color="primary" />
        <Typography
          variant="body2"
          fontWeight={600}
          sx={{ flex: 1, minWidth: 0, wordBreak: 'break-word' }}
        >
          {report.name}
        </Typography>
        {noDatasets && (
          <Tooltip title="This report has no datasets bound">
            <WarningAmberIcon color="warning" fontSize="small" />
          </Tooltip>
        )}
      </Stack>
      <Stack
        direction="row"
        spacing={0.5}
        sx={{ mb: 1, flexWrap: 'wrap', rowGap: 0.5 }}
      >
        <Chip
          size="small"
          label={report.system}
          variant="outlined"
          sx={{ height: 18, fontSize: 10 }}
        />
        {report.owner_team && (
          <Chip
            size="small"
            label={report.owner_team}
            variant="outlined"
            sx={{ height: 18, fontSize: 10 }}
          />
        )}
        <Chip
          size="small"
          label={`uses ${report.uses_attributes.length} attr${report.uses_attributes.length === 1 ? '' : 's'}`}
          color={report.uses_attributes.length > 0 ? 'primary' : 'default'}
          variant={report.uses_attributes.length > 0 ? 'filled' : 'outlined'}
          onClick={report.uses_attributes.length > 0 ? onShowAttributes : undefined}
          sx={{
            height: 18,
            fontSize: 10,
            cursor: report.uses_attributes.length > 0 ? 'pointer' : 'default',
          }}
        />
        {noDatasets && (
          <Chip
            size="small"
            label="no datasets"
            color="warning"
            sx={{ height: 18, fontSize: 10 }}
          />
        )}
      </Stack>
      {report.description && (
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ display: 'block', mb: 1 }}
        >
          {report.description}
        </Typography>
      )}

      {!noDatasets && (
        <Box>
          {report.datasets.map((d) => (
            <DatasetAccordion key={d.dataset_id} dataset={d} />
          ))}
        </Box>
      )}
    </Paper>
  );
}

function DatasetAccordion({ dataset }: { dataset: CatalogReportDataset }) {
  return (
    <Accordion
      disableGutters
      square
      sx={{
        boxShadow: 'none',
        '&:before': { display: 'none' },
        border: '1px solid',
        borderColor: 'divider',
        mb: 0.5,
      }}
    >
      <AccordionSummary expandIcon={<ExpandMoreIcon fontSize="small" />} sx={{ minHeight: 32 }}>
        <Stack
          direction="row"
          spacing={0.5}
          alignItems="center"
          sx={{ flex: 1, flexWrap: 'wrap', rowGap: 0.25 }}
        >
          <Typography variant="caption" fontWeight={600} sx={{ flex: 1, minWidth: 0 }}>
            {dataset.name}
          </Typography>
          <Chip
            size="small"
            label={dataset.command_type}
            variant="outlined"
            sx={{ height: 16, fontSize: 9 }}
          />
          {dataset.source_name && (
            <Chip
              size="small"
              label={dataset.source_name}
              variant="outlined"
              sx={{ height: 16, fontSize: 9 }}
            />
          )}
        </Stack>
      </AccordionSummary>
      <AccordionDetails>
        <Box
          component="pre"
          sx={{
            m: 0,
            p: 1,
            bgcolor: (theme) =>
              theme.palette.mode === 'dark'
                ? 'rgba(255,255,255,0.04)'
                : 'rgba(0,0,0,0.04)',
            borderRadius: 0.5,
            fontFamily: 'monospace',
            fontSize: 11,
            overflowX: 'auto',
            whiteSpace: 'pre',
            maxHeight: 220,
            overflowY: 'auto',
          }}
        >
          {dataset.command}
        </Box>
        {dataset.source_uri && (
          <Typography
            variant="caption"
            color="text.secondary"
            sx={{ display: 'block', mt: 0.5, fontFamily: 'monospace' }}
          >
            runs on {dataset.source_uri}
          </Typography>
        )}
      </AccordionDetails>
    </Accordion>
  );
}
