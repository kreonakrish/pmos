import { useState } from 'react';
import {
  Box,
  Typography,
  Paper,
  Grid,
  Tabs,
  Tab,
  Chip,
  Stack,
  Skeleton,
  Alert,
  Table,
  TableHead,
  TableRow,
  TableCell,
  TableBody,
  Button,
  IconButton,
  TextField,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Tooltip,
  Divider,
  MenuItem,
  Select,
  InputLabel,
  FormControl,
  FormControlLabel,
  Switch,
} from '@mui/material';
import StorageIcon from '@mui/icons-material/Storage';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import TableChartIcon from '@mui/icons-material/TableChart';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import GavelIcon from '@mui/icons-material/Gavel';
import CheckIcon from '@mui/icons-material/Check';
import EditIcon from '@mui/icons-material/Edit';
import CloseIcon from '@mui/icons-material/Close';
import RefreshIcon from '@mui/icons-material/Refresh';
import KeyIcon from '@mui/icons-material/Key';
import LinkIcon from '@mui/icons-material/Link';
import AddIcon from '@mui/icons-material/Add';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import {
  useCrawlers,
  useCrawlRuns,
  useRunCrawler,
  useCatalogAssets,
  useCatalogAssetDetail,
  useOntology,
  useMappingDecisions,
  useMappingDecisionsSummary,
  useReviewMapping,
  useCreateCrawler,
  CreateCrawlerInput,
  Crawler,
  MappingDecision,
} from '@/api/catalog';

function fmt(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return Number(n).toFixed(digits);
}
function fmtTs(ts: string | null | undefined): string {
  if (!ts) return '';
  try { return new Date(ts).toLocaleString(); } catch { return String(ts); }
}

// ---------------------------------------------------------------------------
// Source-type field schema for the Create Crawler form.
// Each source type has its own connection + options field list. Adding a new
// source type means: add an entry here, and (eventually) implement the
// matching <Type>Crawler in services/orchestrator/app/services/crawler/.
// ---------------------------------------------------------------------------
type FieldType = 'text' | 'password' | 'number' | 'boolean' | 'csv';
interface FieldDef {
  name: string;
  label: string;
  type: FieldType;
  required?: boolean;
  default?: string | number | boolean;
  helper?: string;
}
interface SourceSchema {
  label: string;
  description: string;
  implemented: boolean;
  connection: FieldDef[];
  options: FieldDef[];
}

const SOURCE_SCHEMAS: Record<string, SourceSchema> = {
  MYSQL: {
    label: 'MySQL',
    description: 'Crawls INFORMATION_SCHEMA over JDBC. Supports multiple schemas in one run.',
    implemented: true,
    connection: [
      { name: 'host', label: 'Host', type: 'text', required: true, default: 'host.docker.internal' },
      { name: 'port', label: 'Port', type: 'number', required: true, default: 3306 },
      { name: 'user', label: 'User', type: 'text', required: true, default: 'root' },
      { name: 'password', label: 'Password', type: 'password', helper: 'Optional — falls back to MYSQL_PASSWORD env in the orchestrator container' },
      { name: 'database', label: 'Database', type: 'text', required: true },
      { name: 'schemas', label: 'Schemas (comma-separated)', type: 'csv', helper: 'Defaults to the database name if empty' },
    ],
    options: [
      { name: 'include_views', label: 'Include views', type: 'boolean', default: true },
      { name: 'sample_rows', label: 'Sample rows per column', type: 'number', default: 3 },
      { name: 'skip_sensitive', label: 'Skip sensitive columns (PII regex)', type: 'boolean', default: true },
    ],
  },
  POSTGRES: {
    label: 'PostgreSQL',
    description: 'JDBC-style. Crawls pg_catalog and information_schema.',
    implemented: false,
    connection: [
      { name: 'host', label: 'Host', type: 'text', required: true },
      { name: 'port', label: 'Port', type: 'number', required: true, default: 5432 },
      { name: 'user', label: 'User', type: 'text', required: true },
      { name: 'password', label: 'Password', type: 'password' },
      { name: 'database', label: 'Database', type: 'text', required: true },
      { name: 'schemas', label: 'Schemas (comma-separated)', type: 'csv', default: 'public' },
      { name: 'sslmode', label: 'SSL mode', type: 'text', default: 'prefer' },
    ],
    options: [
      { name: 'include_views', label: 'Include views', type: 'boolean', default: true },
      { name: 'include_materialized_views', label: 'Include materialized views', type: 'boolean', default: true },
      { name: 'sample_rows', label: 'Sample rows per column', type: 'number', default: 3 },
    ],
  },
  SQLSERVER: {
    label: 'SQL Server',
    description: 'JDBC-style. Crawls sys.* views.',
    implemented: false,
    connection: [
      { name: 'host', label: 'Host', type: 'text', required: true },
      { name: 'port', label: 'Port', type: 'number', required: true, default: 1433 },
      { name: 'user', label: 'User', type: 'text', required: true },
      { name: 'password', label: 'Password', type: 'password' },
      { name: 'database', label: 'Database', type: 'text', required: true },
      { name: 'schemas', label: 'Schemas (comma-separated)', type: 'csv', default: 'dbo' },
      { name: 'encrypt', label: 'Encrypt connection', type: 'boolean', default: true },
    ],
    options: [
      { name: 'include_views', label: 'Include views', type: 'boolean', default: true },
      { name: 'include_procedures', label: 'Extract stored procedure metadata', type: 'boolean', default: false },
      { name: 'sample_rows', label: 'Sample rows per column', type: 'number', default: 3 },
    ],
  },
  ORACLE: {
    label: 'Oracle',
    description: 'JDBC-style. Crawls ALL_TABLES, ALL_TAB_COLUMNS, ALL_CONSTRAINTS.',
    implemented: false,
    connection: [
      { name: 'host', label: 'Host', type: 'text', required: true },
      { name: 'port', label: 'Port', type: 'number', required: true, default: 1521 },
      { name: 'service_name', label: 'Service name (or SID)', type: 'text', required: true },
      { name: 'user', label: 'User', type: 'text', required: true },
      { name: 'password', label: 'Password', type: 'password' },
      { name: 'schemas', label: 'Schemas (comma-separated)', type: 'csv', helper: 'Oracle schemas = users; defaults to the connecting user' },
    ],
    options: [
      { name: 'include_views', label: 'Include views', type: 'boolean', default: true },
      { name: 'include_packages', label: 'Include PL/SQL packages', type: 'boolean', default: false },
      { name: 'sample_rows', label: 'Sample rows per column', type: 'number', default: 3 },
    ],
  },
  TERADATA: {
    label: 'Teradata',
    description: 'Crawls DBC.* dictionary views.',
    implemented: false,
    connection: [
      { name: 'host', label: 'Host', type: 'text', required: true },
      { name: 'user', label: 'User', type: 'text', required: true },
      { name: 'password', label: 'Password', type: 'password' },
      { name: 'databases', label: 'Databases (comma-separated)', type: 'csv', required: true },
      { name: 'logmech', label: 'Auth mechanism', type: 'text', default: 'TD2' },
    ],
    options: [
      { name: 'sample_rows', label: 'Sample rows per column', type: 'number', default: 3 },
      { name: 'skip_temp_tables', label: 'Skip temp tables', type: 'boolean', default: true },
    ],
  },
  SNOWFLAKE: {
    label: 'Snowflake',
    description: 'Crawls INFORMATION_SCHEMA per database. Supports key-pair or password auth.',
    implemented: false,
    connection: [
      { name: 'account', label: 'Account', type: 'text', required: true, helper: 'e.g. xy12345.us-east-1' },
      { name: 'warehouse', label: 'Warehouse', type: 'text', required: true },
      { name: 'database', label: 'Database', type: 'text', required: true },
      { name: 'schema', label: 'Schema', type: 'text', helper: 'Optional — defaults to all schemas in the database' },
      { name: 'role', label: 'Role', type: 'text' },
      { name: 'user', label: 'User', type: 'text', required: true },
      { name: 'password', label: 'Password', type: 'password' },
    ],
    options: [
      { name: 'include_views', label: 'Include views', type: 'boolean', default: true },
      { name: 'include_secure_views', label: 'Include secure views', type: 'boolean', default: false },
      { name: 'sample_rows', label: 'Sample rows per column', type: 'number', default: 3 },
    ],
  },
  GLUE: {
    label: 'AWS Glue Data Catalog',
    description: 'Reads Glue databases and tables via the AWS API. Picks up S3-backed tables and partitions.',
    implemented: false,
    connection: [
      { name: 'aws_region', label: 'AWS region', type: 'text', required: true, default: 'us-east-1' },
      { name: 'aws_access_key_id', label: 'AWS access key id', type: 'text', helper: 'Or leave blank to use the orchestrator container IAM role' },
      { name: 'aws_secret_access_key', label: 'AWS secret access key', type: 'password' },
      { name: 'databases', label: 'Glue databases (comma-separated)', type: 'csv', helper: 'Empty = all databases visible to the credentials' },
    ],
    options: [
      { name: 'include_partitions', label: 'Include partition keys', type: 'boolean', default: true },
      { name: 'sample_rows', label: 'Sample rows per table (S3 read)', type: 'number', default: 0 },
    ],
  },
  S3: {
    label: 'AWS S3 (object metadata)',
    description: 'Lists objects under a bucket/prefix and infers schemas from Parquet/CSV/JSON files.',
    implemented: false,
    connection: [
      { name: 'bucket', label: 'Bucket', type: 'text', required: true },
      { name: 'prefix', label: 'Prefix (folder path)', type: 'text' },
      { name: 'aws_region', label: 'AWS region', type: 'text', required: true, default: 'us-east-1' },
      { name: 'aws_access_key_id', label: 'AWS access key id', type: 'text' },
      { name: 'aws_secret_access_key', label: 'AWS secret access key', type: 'password' },
    ],
    options: [
      { name: 'file_patterns', label: 'File patterns (comma-separated globs)', type: 'csv', default: '*.parquet,*.csv,*.json' },
      { name: 'max_files', label: 'Max files per crawl', type: 'number', default: 100 },
      { name: 'sample_lines', label: 'Sample lines per file', type: 'number', default: 5 },
      { name: 'detect_partitioning', label: 'Detect Hive-style partitioning', type: 'boolean', default: true },
    ],
  },
  EXCEL: {
    label: 'Excel workbook',
    description: 'Reads .xlsx files. Each sheet becomes a DataAsset; columns inferred from the header row.',
    implemented: false,
    connection: [
      { name: 'file_path', label: 'File path on the orchestrator host', type: 'text', required: true, helper: 'Absolute path inside /app/data (mounted volume)' },
    ],
    options: [
      { name: 'sheet_filter', label: 'Sheet name filter (comma-separated, empty = all)', type: 'csv' },
      { name: 'header_row', label: 'Header row (1-indexed)', type: 'number', default: 1 },
      { name: 'sample_rows', label: 'Sample rows per column', type: 'number', default: 5 },
    ],
  },
  CSV: {
    label: 'CSV file',
    description: 'Reads a single CSV file. Useful for quick imports of flat extracts.',
    implemented: false,
    connection: [
      { name: 'file_path', label: 'File path on the orchestrator host', type: 'text', required: true },
      { name: 'encoding', label: 'Encoding', type: 'text', default: 'utf-8' },
      { name: 'delimiter', label: 'Delimiter', type: 'text', default: ',' },
    ],
    options: [
      { name: 'has_header', label: 'Has header row', type: 'boolean', default: true },
      { name: 'sample_lines', label: 'Sample lines for type inference', type: 'number', default: 100 },
    ],
  },
  SSRS_RDL: {
    label: 'SQL Server Reporting Services (RDL)',
    description: 'Reads RDL XML files from an SSRS server. Each report becomes a DataAsset; embedded SQL is extracted via LLM.',
    implemented: false,
    connection: [
      { name: 'server_url', label: 'SSRS server URL', type: 'text', required: true, helper: 'e.g. http://reports.corp/ReportServer' },
      { name: 'folder_path', label: 'Folder path', type: 'text', helper: 'Empty = root folder' },
      { name: 'user', label: 'User', type: 'text' },
      { name: 'password', label: 'Password', type: 'password' },
      { name: 'auth_type', label: 'Auth type', type: 'text', default: 'NTLM', helper: 'NTLM / BASIC / NEGOTIATE' },
    ],
    options: [
      { name: 'extract_sql', label: 'Extract embedded dataset SQL via LLM', type: 'boolean', default: true },
      { name: 'recurse_folders', label: 'Recurse subfolders', type: 'boolean', default: true },
    ],
  },
};

function defaultValuesFor(fields: FieldDef[]): Record<string, any> {
  const out: Record<string, any> = {};
  for (const f of fields) {
    if (f.default !== undefined) out[f.name] = f.default;
    else if (f.type === 'boolean') out[f.name] = false;
    else if (f.type === 'csv') out[f.name] = '';
    else out[f.name] = '';
  }
  return out;
}

function coerceFields(fields: FieldDef[], values: Record<string, any>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of fields) {
    const raw = values[f.name];
    if (raw === undefined || raw === null || raw === '') {
      if (f.required) out[f.name] = ''; // let server reject if truly required
      continue;
    }
    if (f.type === 'number') {
      const n = Number(raw);
      out[f.name] = Number.isNaN(n) ? raw : n;
    } else if (f.type === 'boolean') {
      out[f.name] = Boolean(raw);
    } else if (f.type === 'csv') {
      const arr = String(raw).split(',').map((s) => s.trim()).filter(Boolean);
      out[f.name] = arr;
    } else {
      out[f.name] = String(raw);
    }
  }
  return out;
}

export default function DataCatalogPage() {
  const [tab, setTab] = useState(0);
  return (
    <Box>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
        <StorageIcon color="primary" />
        <Typography variant="h5" fontWeight={600}>Data Catalog</Typography>
        <Chip label="Systems integration" size="small" variant="outlined" />
      </Stack>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Crawl metadata from source systems, map physical columns to business
        entities via LLM, and audit every mapping decision with
        reinforcement feedback. The knowledge graph built here is what agents
        use to translate business questions into precise federated queries.
      </Typography>

      <Paper sx={{ mb: 2 }}>
        <Tabs value={tab} onChange={(_, v) => setTab(v)}>
          <Tab icon={<PlayArrowIcon />} iconPosition="start" label="Crawlers" />
          <Tab icon={<TableChartIcon />} iconPosition="start" label="Assets" />
          <Tab icon={<AccountTreeIcon />} iconPosition="start" label="Business Ontology" />
          <Tab icon={<GavelIcon />} iconPosition="start" label="Mapping Review" />
        </Tabs>
      </Paper>

      {tab === 0 && <CrawlersTab />}
      {tab === 1 && <AssetsTab />}
      {tab === 2 && <OntologyTab />}
      {tab === 3 && <MappingReviewTab />}
    </Box>
  );
}

// ---------------------------------------------------------------------------
// Tab 1 — Crawlers
// ---------------------------------------------------------------------------
function CrawlersTab() {
  const crawlersQ = useCrawlers();
  const runCrawler = useRunCrawler();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const runsQ = useCrawlRuns(selectedId, 20);

  const crawlers = crawlersQ.data?.crawlers ?? [];
  const effectiveId = selectedId ?? (crawlers[0]?.crawler_id ?? null);
  const effectiveRunsQ = useCrawlRuns(effectiveId, 20);
  const runs = effectiveRunsQ.data?.runs ?? runsQ.data?.runs ?? [];

  return (
    <Grid container spacing={2}>
      <Grid item xs={12} md={5}>
        <Paper sx={{ p: 2, height: 520, display: 'flex', flexDirection: 'column' }}>
          <Stack direction="row" alignItems="center" sx={{ mb: 1 }}>
            <Typography variant="subtitle2" sx={{ flex: 1 }}>
              Registered crawlers ({crawlers.length})
            </Typography>
            <Button
              size="small"
              variant="contained"
              startIcon={<AddIcon />}
              onClick={() => setCreateOpen(true)}
              sx={{ mr: 0.5 }}
            >
              Create
            </Button>
            <IconButton size="small" onClick={() => crawlersQ.refetch()}>
              <RefreshIcon fontSize="small" />
            </IconButton>
          </Stack>
          {crawlersQ.isLoading ? (
            <Skeleton height={300} />
          ) : crawlers.length === 0 ? (
            <Alert severity="info">
              No crawlers yet. Click <strong>Create</strong> to add one for any
              of the supported source systems.
            </Alert>
          ) : (
            <Box sx={{ flex: 1, overflowY: 'auto' }}>
              {crawlers.map((c) => (
                <CrawlerRow
                  key={c.crawler_id}
                  crawler={c}
                  selected={effectiveId === c.crawler_id}
                  running={runCrawler.isPending}
                  onSelect={() => setSelectedId(c.crawler_id)}
                  onRun={() => runCrawler.mutate(c.crawler_id)}
                />
              ))}
            </Box>
          )}
        </Paper>
      </Grid>
      <Grid item xs={12} md={7}>
        <Paper sx={{ p: 2, height: 520, display: 'flex', flexDirection: 'column' }}>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>
            Run history ({runs.length})
          </Typography>
          {!effectiveId ? (
            <Alert severity="info">Select a crawler to see its runs.</Alert>
          ) : effectiveRunsQ.isLoading ? (
            <Skeleton height={300} />
          ) : runs.length === 0 ? (
            <Alert severity="info">
              No runs yet. Click Run on the crawler to kick one off.
            </Alert>
          ) : (
            <Box sx={{ flex: 1, overflowY: 'auto' }}>
              <Table size="small" stickyHeader>
                <TableHead>
                  <TableRow>
                    <TableCell>Started</TableCell>
                    <TableCell>Status</TableCell>
                    <TableCell align="right">Assets</TableCell>
                    <TableCell align="right">Cols</TableCell>
                    <TableCell align="right">Mappings</TableCell>
                    <TableCell align="right">Duration</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {runs.map((r) => (
                    <TableRow key={r.run_id}>
                      <TableCell>
                        <Typography variant="caption">{fmtTs(r.started_at)}</Typography>
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={r.status}
                          size="small"
                          color={
                            r.status === 'SUCCESS' ? 'success' :
                            r.status === 'PARTIAL' ? 'warning' :
                            r.status === 'FAILURE' ? 'error' : 'default'
                          }
                          sx={{ height: 18, fontSize: 10 }}
                        />
                      </TableCell>
                      <TableCell align="right">{r.assets_found}</TableCell>
                      <TableCell align="right">{r.columns_found}</TableCell>
                      <TableCell align="right">{r.mappings_made}</TableCell>
                      <TableCell align="right">
                        {r.duration_ms ? `${(r.duration_ms / 1000).toFixed(1)}s` : '—'}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Box>
          )}
        </Paper>
      </Grid>

      <CreateCrawlerDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(id) => {
          setSelectedId(id);
          setCreateOpen(false);
        }}
      />
    </Grid>
  );
}

function CrawlerRow({
  crawler, selected, running, onSelect, onRun,
}: {
  crawler: Crawler; selected: boolean; running: boolean;
  onSelect: () => void; onRun: () => void;
}) {
  return (
    <Paper
      variant="outlined"
      sx={{
        p: 1.5, mb: 1, cursor: 'pointer',
        borderColor: selected ? 'primary.main' : undefined,
        bgcolor: selected ? 'action.hover' : undefined,
      }}
      onClick={onSelect}
    >
      <Stack direction="row" alignItems="center" spacing={1}>
        <Box sx={{ flex: 1 }}>
          <Typography variant="body2" fontWeight={500}>{crawler.name}</Typography>
          <Stack direction="row" spacing={0.5} sx={{ mt: 0.5 }}>
            <Chip label={crawler.source_type} size="small" variant="outlined" sx={{ height: 18, fontSize: 10 }} />
            <Chip
              label={crawler.status}
              size="small"
              color={crawler.status === 'ACTIVE' ? 'success' : 'default'}
              sx={{ height: 18, fontSize: 10 }}
            />
            {crawler.last_run_status && (
              <Chip
                label={`last: ${crawler.last_run_status}`}
                size="small"
                color={
                  crawler.last_run_status === 'SUCCESS' ? 'success' :
                  crawler.last_run_status === 'FAILURE' ? 'error' : 'warning'
                }
                sx={{ height: 18, fontSize: 10 }}
              />
            )}
          </Stack>
          {crawler.description && (
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
              {crawler.description.slice(0, 100)}
            </Typography>
          )}
        </Box>
        <Button
          size="small"
          variant="contained"
          startIcon={<PlayArrowIcon />}
          onClick={(e) => { e.stopPropagation(); onRun(); }}
          disabled={running}
        >
          Run
        </Button>
      </Stack>
    </Paper>
  );
}

// ---------------------------------------------------------------------------
// Create Crawler dialog
// ---------------------------------------------------------------------------
function CreateCrawlerDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (crawlerId: string) => void;
}) {
  const create = useCreateCrawler();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [sourceType, setSourceType] = useState<string>('MYSQL');
  const [scheduleCron, setScheduleCron] = useState('');
  const [connectionValues, setConnectionValues] = useState<Record<string, any>>(
    () => defaultValuesFor(SOURCE_SCHEMAS.MYSQL.connection),
  );
  const [optionsValues, setOptionsValues] = useState<Record<string, any>>(
    () => defaultValuesFor(SOURCE_SCHEMAS.MYSQL.options),
  );
  const [error, setError] = useState<string | null>(null);

  const schema = SOURCE_SCHEMAS[sourceType];

  // When source type changes, reset field values to that schema's defaults.
  const handleSourceTypeChange = (next: string) => {
    setSourceType(next);
    setConnectionValues(defaultValuesFor(SOURCE_SCHEMAS[next].connection));
    setOptionsValues(defaultValuesFor(SOURCE_SCHEMAS[next].options));
    setError(null);
  };

  const handleClose = () => {
    if (create.isPending) return;
    setName('');
    setDescription('');
    setSourceType('MYSQL');
    setConnectionValues(defaultValuesFor(SOURCE_SCHEMAS.MYSQL.connection));
    setOptionsValues(defaultValuesFor(SOURCE_SCHEMAS.MYSQL.options));
    setScheduleCron('');
    setError(null);
    onClose();
  };

  const handleSubmit = () => {
    setError(null);
    if (!name.trim()) {
      setError('Name is required');
      return;
    }
    // Required-field check
    for (const f of schema.connection) {
      if (f.required) {
        const v = connectionValues[f.name];
        if (v === undefined || v === null || v === '') {
          setError(`Connection field "${f.label}" is required`);
          return;
        }
      }
    }
    const body: CreateCrawlerInput = {
      name: name.trim(),
      description: description.trim() || undefined,
      source_type: sourceType,
      connection: coerceFields(schema.connection, connectionValues),
      options: coerceFields(schema.options, optionsValues),
      schedule_cron: scheduleCron.trim() || undefined,
    };
    create.mutate(body, {
      onSuccess: (data) => onCreated(data.crawler_id),
      onError: (err: any) => {
        const detail = err?.response?.data?.detail;
        const msg =
          (detail && typeof detail === 'object' && detail.error) ||
          err?.message ||
          'Failed to create crawler';
        setError(String(msg));
      },
    });
  };

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="md" fullWidth>
      <DialogTitle>
        <Stack direction="row" alignItems="center" spacing={1}>
          <AddIcon fontSize="small" />
          <span>Create crawler</span>
        </Stack>
      </DialogTitle>
      <DialogContent dividers>
        <Grid container spacing={2}>
          <Grid item xs={12} md={6}>
            <TextField
              fullWidth size="small" label="Name" required margin="dense"
              value={name} onChange={(e) => setName(e.target.value)}
            />
          </Grid>
          <Grid item xs={12} md={6}>
            <FormControl fullWidth size="small" margin="dense">
              <InputLabel>Source type</InputLabel>
              <Select
                label="Source type"
                value={sourceType}
                onChange={(e) => handleSourceTypeChange(String(e.target.value))}
              >
                {Object.entries(SOURCE_SCHEMAS).map(([key, s]) => (
                  <MenuItem key={key} value={key}>
                    {s.label} {!s.implemented && '· (impl pending)'}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={12}>
            <TextField
              fullWidth size="small" label="Description" margin="dense"
              multiline minRows={1} maxRows={3}
              value={description} onChange={(e) => setDescription(e.target.value)}
            />
          </Grid>
          <Grid item xs={12}>
            <Typography variant="caption" color="text.secondary">
              {schema.description}
            </Typography>
          </Grid>

          {!schema.implemented && (
            <Grid item xs={12}>
              <Alert severity="warning" icon={<WarningAmberIcon />}>
                The <strong>{schema.label}</strong> crawler implementation is
                pending. Saving registers the configuration so it shows up in the
                catalog, but clicking <strong>Run</strong> will fail until the
                matching <code>{sourceType}Crawler</code> is added under
                <code> services/orchestrator/app/services/crawler/</code> and
                registered in <code>runner.py:CRAWLER_CLASSES</code>.
              </Alert>
            </Grid>
          )}

          <Grid item xs={12}>
            <Divider sx={{ my: 1 }}>
              <Chip label="Connection" size="small" />
            </Divider>
          </Grid>
          {schema.connection.map((f) => (
            <Grid item xs={12} sm={6} key={`conn-${f.name}`}>
              <DynamicField
                field={f}
                value={connectionValues[f.name]}
                onChange={(v) =>
                  setConnectionValues((prev) => ({ ...prev, [f.name]: v }))
                }
              />
            </Grid>
          ))}

          <Grid item xs={12}>
            <Divider sx={{ my: 1 }}>
              <Chip label="Options" size="small" />
            </Divider>
          </Grid>
          {schema.options.length === 0 ? (
            <Grid item xs={12}>
              <Typography variant="caption" color="text.secondary">
                No crawler-specific options for this source type.
              </Typography>
            </Grid>
          ) : (
            schema.options.map((f) => (
              <Grid item xs={12} sm={6} key={`opt-${f.name}`}>
                <DynamicField
                  field={f}
                  value={optionsValues[f.name]}
                  onChange={(v) =>
                    setOptionsValues((prev) => ({ ...prev, [f.name]: v }))
                  }
                />
              </Grid>
            ))
          )}

          <Grid item xs={12}>
            <Divider sx={{ my: 1 }} />
          </Grid>
          <Grid item xs={12} md={6}>
            <TextField
              fullWidth size="small" label="Schedule cron (optional)" margin="dense"
              placeholder="e.g. 0 3 * * *"
              helperText="Reserved — runs are manual until a scheduler is wired up"
              value={scheduleCron}
              onChange={(e) => setScheduleCron(e.target.value)}
            />
          </Grid>

          {error && (
            <Grid item xs={12}>
              <Alert severity="error">{error}</Alert>
            </Grid>
          )}
        </Grid>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={create.isPending}>
          Cancel
        </Button>
        <Button
          variant="contained"
          onClick={handleSubmit}
          disabled={create.isPending}
          startIcon={<AddIcon />}
        >
          {create.isPending ? 'Creating…' : 'Create crawler'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

function DynamicField({
  field,
  value,
  onChange,
}: {
  field: FieldDef;
  value: any;
  onChange: (v: any) => void;
}) {
  if (field.type === 'boolean') {
    return (
      <FormControlLabel
        control={
          <Switch
            size="small"
            checked={!!value}
            onChange={(e) => onChange(e.target.checked)}
          />
        }
        label={
          <Box>
            <Typography variant="body2">{field.label}</Typography>
            {field.helper && (
              <Typography variant="caption" color="text.secondary">
                {field.helper}
              </Typography>
            )}
          </Box>
        }
      />
    );
  }

  const isPassword = field.type === 'password';
  const isNumber = field.type === 'number';
  return (
    <TextField
      fullWidth
      size="small"
      margin="dense"
      label={field.label + (field.required ? ' *' : '')}
      type={isPassword ? 'password' : isNumber ? 'number' : 'text'}
      value={value ?? ''}
      onChange={(e) => onChange(isNumber ? e.target.value : e.target.value)}
      helperText={field.helper}
      InputProps={isPassword ? { autoComplete: 'new-password' } : undefined}
    />
  );
}

// ---------------------------------------------------------------------------
// Tab 2 — Assets
// ---------------------------------------------------------------------------
function AssetsTab() {
  const assetsQ = useCatalogAssets();
  const [selectedFq, setSelectedFq] = useState<string | null>(null);
  const detailQ = useCatalogAssetDetail(selectedFq);
  const assets = assetsQ.data?.assets ?? [];

  return (
    <Grid container spacing={2}>
      <Grid item xs={12} md={5}>
        <Paper sx={{ p: 2, height: 580, display: 'flex', flexDirection: 'column' }}>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>
            Crawled assets ({assets.length})
          </Typography>
          {assetsQ.isLoading ? (
            <Skeleton height={400} />
          ) : assets.length === 0 ? (
            <Alert severity="info">
              No assets in the catalog yet. Run a crawler to populate.
            </Alert>
          ) : (
            <Box sx={{ flex: 1, overflowY: 'auto' }}>
              <Table size="small" stickyHeader>
                <TableHead>
                  <TableRow>
                    <TableCell>Asset</TableCell>
                    <TableCell>Type</TableCell>
                    <TableCell align="right">Cols</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {assets.map((a) => (
                    <TableRow
                      key={a.fq_name}
                      hover
                      selected={selectedFq === a.fq_name}
                      onClick={() => setSelectedFq(a.fq_name)}
                      sx={{ cursor: 'pointer' }}
                    >
                      <TableCell>
                        <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: 11 }}>
                          {a.fully_qualified}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          {a.source_name}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Chip label={a.asset_type} size="small" sx={{ height: 16, fontSize: 9 }} />
                      </TableCell>
                      <TableCell align="right">{a.column_count}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Box>
          )}
        </Paper>
      </Grid>
      <Grid item xs={12} md={7}>
        <Paper sx={{ p: 2, height: 580, overflowY: 'auto' }}>
          {!selectedFq ? (
            <Alert severity="info">Select an asset to see its columns and mappings.</Alert>
          ) : detailQ.isLoading ? (
            <Skeleton height={400} />
          ) : (
            <AssetDetail asset={detailQ.data?.asset as any} columns={detailQ.data?.columns ?? []} />
          )}
        </Paper>
      </Grid>
    </Grid>
  );
}

function AssetDetail({ asset, columns }: { asset: any; columns: any[] }) {
  if (!asset) return <Alert severity="warning">Asset not found.</Alert>;
  return (
    <Box>
      <Typography variant="subtitle2" sx={{ fontFamily: 'monospace', mb: 0.5 }}>
        {asset.fully_qualified || asset.fq_name}
      </Typography>
      <Stack direction="row" spacing={1} sx={{ mb: 2 }} flexWrap="wrap">
        <Chip label={asset.asset_type} size="small" />
        {asset.source_name && <Chip label={asset.source_name} size="small" variant="outlined" />}
        {asset.row_count !== null && asset.row_count !== undefined && (
          <Chip label={`${asset.row_count} rows`} size="small" variant="outlined" />
        )}
      </Stack>
      {asset.comment && (
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 2 }}>
          {asset.comment}
        </Typography>
      )}
      <Divider sx={{ my: 1 }} />
      <Typography variant="subtitle2" sx={{ mb: 1 }}>
        Columns ({columns.length})
      </Typography>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Column</TableCell>
            <TableCell>Type</TableCell>
            <TableCell>Business mapping</TableCell>
            <TableCell align="right">Conf</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {columns.map((c: any) => (
            <TableRow key={c.fq_name || c.name}>
              <TableCell>
                <Stack direction="row" spacing={0.5} alignItems="center">
                  <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
                    {c.name}
                  </Typography>
                  {c.is_pk && <KeyIcon sx={{ fontSize: 12, color: 'warning.main' }} />}
                  {c.is_fk && <LinkIcon sx={{ fontSize: 12, color: 'info.main' }} />}
                </Stack>
                {c.sample_values && c.sample_values.length > 0 && (
                  <Typography variant="caption" color="text.secondary">
                    samples: {(c.sample_values as string[]).slice(0, 3).join(', ')}
                  </Typography>
                )}
              </TableCell>
              <TableCell>
                <Typography variant="caption" sx={{ fontFamily: 'monospace' }}>
                  {c.data_type}
                </Typography>
              </TableCell>
              <TableCell>
                {c.entity ? (
                  <Box>
                    <Typography variant="caption" color="text.secondary">
                      {c.domain}
                    </Typography>
                    <Typography variant="body2">
                      {c.entity}.{c.attribute}
                    </Typography>
                  </Box>
                ) : (
                  <Typography variant="caption" color="text.secondary">(unmapped)</Typography>
                )}
              </TableCell>
              <TableCell align="right">
                {c.confidence !== null && c.confidence !== undefined ? (
                  <Chip
                    label={fmt(c.confidence)}
                    size="small"
                    color={c.confidence >= 0.8 ? 'success' : c.confidence >= 0.5 ? 'warning' : 'error'}
                    sx={{ height: 18, fontSize: 10 }}
                  />
                ) : '—'}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Box>
  );
}

// ---------------------------------------------------------------------------
// Tab 3 — Business Ontology
// ---------------------------------------------------------------------------
function OntologyTab() {
  const q = useOntology();
  const domains = q.data?.domains ?? [];
  return (
    <Box>
      {q.isLoading ? (
        <Skeleton height={300} />
      ) : domains.length === 0 ? (
        <Alert severity="info">
          No business ontology yet. Run a crawler to populate domains, entities, and attributes.
        </Alert>
      ) : (
        <Grid container spacing={2}>
          {domains.map((d) => (
            <Grid item xs={12} md={6} lg={4} key={d.domain || 'unknown'}>
              <Paper sx={{ p: 2 }}>
                <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
                  <AccountTreeIcon color="primary" fontSize="small" />
                  <Typography variant="subtitle1" fontWeight={600}>
                    {d.domain || '(unnamed)'}
                  </Typography>
                  <Chip
                    label={`${d.entities.length} entit${d.entities.length === 1 ? 'y' : 'ies'}`}
                    size="small"
                    variant="outlined"
                  />
                </Stack>
                <Box sx={{ pl: 1 }}>
                  {d.entities.map((e) => (
                    <Stack
                      key={e.entity}
                      direction="row"
                      alignItems="center"
                      spacing={1}
                      sx={{ py: 0.5, borderBottom: '1px dashed', borderColor: 'divider' }}
                    >
                      <Typography variant="body2" sx={{ flex: 1 }}>{e.entity}</Typography>
                      <Typography variant="caption" color="text.secondary">
                        {e.attributes} attrs
                      </Typography>
                    </Stack>
                  ))}
                </Box>
              </Paper>
            </Grid>
          ))}
        </Grid>
      )}
    </Box>
  );
}

// ---------------------------------------------------------------------------
// Tab 4 — Mapping Review (auditor workflow)
// ---------------------------------------------------------------------------
function MappingReviewTab() {
  const summaryQ = useMappingDecisionsSummary();
  const [statusFilter, setStatusFilter] = useState('AUTO_ACCEPTED');
  const decisionsQ = useMappingDecisions(statusFilter, 100);
  const review = useReviewMapping();

  const [editing, setEditing] = useState<MappingDecision | null>(null);
  const [formDomain, setFormDomain] = useState('');
  const [formEntity, setFormEntity] = useState('');
  const [formAttribute, setFormAttribute] = useState('');
  const [formNote, setFormNote] = useState('');

  const decisions = decisionsQ.data?.decisions ?? [];
  const summary = summaryQ.data;

  const openEdit = (d: MappingDecision) => {
    setEditing(d);
    setFormDomain(d.proposed_domain || '');
    setFormEntity(d.proposed_entity || '');
    setFormAttribute(d.proposed_attribute || '');
    setFormNote('');
  };

  const submitCorrect = () => {
    if (!editing) return;
    review.mutate(
      {
        decisionId: editing.decision_id,
        action: 'CORRECT',
        auditor_domain: formDomain,
        auditor_entity: formEntity,
        auditor_attribute: formAttribute,
        auditor_note: formNote,
      },
      { onSuccess: () => setEditing(null) },
    );
  };

  return (
    <Box>
      {/* Summary cards */}
      <Grid container spacing={2} sx={{ mb: 2 }}>
        <StatCard label="Total decisions" value={summary?.total} loading={summaryQ.isLoading} />
        <StatCard label="Auto-accepted" value={summary?.auto_accepted} loading={summaryQ.isLoading} />
        <StatCard label="Confirmed" value={summary?.confirmed} loading={summaryQ.isLoading} highlight={(summary?.confirmed ?? 0) > 0} />
        <StatCard label="Corrected" value={summary?.corrected} loading={summaryQ.isLoading} />
        <StatCard label="Rejected" value={summary?.rejected} loading={summaryQ.isLoading} />
        <StatCard
          label="Low confidence (<0.5)"
          value={summary?.low_confidence}
          loading={summaryQ.isLoading}
          highlight={(summary?.low_confidence ?? 0) > 0}
        />
        <StatCard
          label="Avg confidence"
          value={summary ? fmt(summary.avg_confidence, 3) : undefined}
          loading={summaryQ.isLoading}
        />
        <StatCard
          label="Review coverage"
          value={summary ? `${Math.round((summary.review_coverage || 0) * 100)}%` : undefined}
          loading={summaryQ.isLoading}
        />
      </Grid>

      <Paper sx={{ p: 2, mb: 2 }}>
        <Stack direction="row" spacing={1} alignItems="center">
          <Typography variant="subtitle2">Filter:</Typography>
          {(['AUTO_ACCEPTED', 'CONFIRMED', 'CORRECTED', 'REJECTED', ''] as const).map((s) => (
            <Chip
              key={s || 'ALL'}
              label={s || 'ALL'}
              size="small"
              onClick={() => setStatusFilter(s)}
              color={statusFilter === s ? 'primary' : 'default'}
              variant={statusFilter === s ? 'filled' : 'outlined'}
              sx={{ cursor: 'pointer' }}
            />
          ))}
          <Box sx={{ flex: 1 }} />
          <Typography variant="caption" color="text.secondary">
            Auditor feedback feeds the RL signal for the semantic mapper.
          </Typography>
        </Stack>
      </Paper>

      {decisionsQ.isLoading ? (
        <Skeleton height={400} />
      ) : decisions.length === 0 ? (
        <Alert severity="info">No decisions in this status bucket.</Alert>
      ) : (
        <Paper>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Physical</TableCell>
                <TableCell>Proposed mapping</TableCell>
                <TableCell align="right">Conf</TableCell>
                <TableCell>Status</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {decisions.map((d) => (
                <DecisionRow
                  key={d.decision_id}
                  d={d}
                  onConfirm={() => review.mutate({ decisionId: d.decision_id, action: 'CONFIRM' })}
                  onReject={() => review.mutate({ decisionId: d.decision_id, action: 'REJECT' })}
                  onCorrect={() => openEdit(d)}
                  disabled={review.isPending}
                />
              ))}
            </TableBody>
          </Table>
        </Paper>
      )}

      <Dialog open={!!editing} onClose={() => setEditing(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Correct mapping</DialogTitle>
        <DialogContent>
          {editing && (
            <Box>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                Column: <code>{editing.data_asset}.{editing.data_column}</code>
              </Typography>
              <TextField
                fullWidth size="small" label="Business domain" margin="dense"
                value={formDomain} onChange={(e) => setFormDomain(e.target.value)}
              />
              <TextField
                fullWidth size="small" label="Business entity" margin="dense"
                value={formEntity} onChange={(e) => setFormEntity(e.target.value)}
              />
              <TextField
                fullWidth size="small" label="Business attribute" margin="dense"
                value={formAttribute} onChange={(e) => setFormAttribute(e.target.value)}
              />
              <TextField
                fullWidth size="small" label="Auditor note (optional)" margin="dense"
                multiline rows={2}
                value={formNote} onChange={(e) => setFormNote(e.target.value)}
              />
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditing(null)}>Cancel</Button>
          <Button variant="contained" onClick={submitCorrect} disabled={review.isPending}>
            Save correction
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

function DecisionRow({
  d, onConfirm, onReject, onCorrect, disabled,
}: {
  d: MappingDecision;
  onConfirm: () => void; onReject: () => void; onCorrect: () => void; disabled: boolean;
}) {
  const conf = d.confidence ?? 0;
  const isReviewed = d.status !== 'AUTO_ACCEPTED' && d.status !== 'PENDING';
  return (
    <TableRow>
      <TableCell sx={{ maxWidth: 260 }}>
        <Typography variant="caption" sx={{ fontFamily: 'monospace', display: 'block' }}>
          {d.data_asset}
        </Typography>
        <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
          {d.data_column}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {d.data_type}
        </Typography>
      </TableCell>
      <TableCell sx={{ maxWidth: 300 }}>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
          {d.proposed_domain}
        </Typography>
        <Typography variant="body2">
          {d.proposed_entity}.{d.proposed_attribute}
        </Typography>
        {d.reasoning && (
          <Tooltip title={d.reasoning} placement="top">
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{
                display: '-webkit-box',
                WebkitLineClamp: 1,
                WebkitBoxOrient: 'vertical',
                overflow: 'hidden',
              }}
            >
              {d.reasoning}
            </Typography>
          </Tooltip>
        )}
        {d.auditor_entity && d.status !== 'AUTO_ACCEPTED' && (
          <Typography variant="caption" color="success.main">
            → corrected to: {d.auditor_entity}.{d.auditor_attribute}
          </Typography>
        )}
      </TableCell>
      <TableCell align="right">
        <Chip
          label={fmt(conf)}
          size="small"
          color={conf >= 0.8 ? 'success' : conf >= 0.5 ? 'warning' : 'error'}
          sx={{ height: 18, fontSize: 10 }}
        />
      </TableCell>
      <TableCell>
        <Chip
          label={d.status}
          size="small"
          color={
            d.status === 'CONFIRMED' ? 'success' :
            d.status === 'CORRECTED' ? 'warning' :
            d.status === 'REJECTED' ? 'error' : 'default'
          }
          sx={{ height: 18, fontSize: 10 }}
        />
      </TableCell>
      <TableCell align="right">
        {!isReviewed ? (
          <Stack direction="row" spacing={0.5} justifyContent="flex-end">
            <Tooltip title="Confirm (RL reward +1.0)">
              <span>
                <IconButton size="small" color="success" onClick={onConfirm} disabled={disabled}>
                  <CheckIcon fontSize="small" />
                </IconButton>
              </span>
            </Tooltip>
            <Tooltip title="Correct (RL reward -0.5)">
              <span>
                <IconButton size="small" color="warning" onClick={onCorrect} disabled={disabled}>
                  <EditIcon fontSize="small" />
                </IconButton>
              </span>
            </Tooltip>
            <Tooltip title="Reject (RL reward -1.0)">
              <span>
                <IconButton size="small" color="error" onClick={onReject} disabled={disabled}>
                  <CloseIcon fontSize="small" />
                </IconButton>
              </span>
            </Tooltip>
          </Stack>
        ) : (
          <Typography variant="caption" color="text.secondary">
            by {d.reviewed_by || 'auditor'}
          </Typography>
        )}
      </TableCell>
    </TableRow>
  );
}

// ---------------------------------------------------------------------------
// Shared
// ---------------------------------------------------------------------------
function StatCard({
  label, value, loading, highlight,
}: {
  label: string; value: number | string | undefined;
  loading?: boolean; highlight?: boolean;
}) {
  return (
    <Grid item xs={6} sm={3} md={1.5}>
      <Paper
        variant="outlined"
        sx={{ p: 1, textAlign: 'center', borderColor: highlight ? 'warning.main' : undefined }}
      >
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
          {label}
        </Typography>
        {loading ? (
          <Skeleton height={24} />
        ) : (
          <Typography variant="h6" fontWeight={600} sx={{ fontSize: 16 }}>
            {value ?? '—'}
          </Typography>
        )}
      </Paper>
    </Grid>
  );
}
