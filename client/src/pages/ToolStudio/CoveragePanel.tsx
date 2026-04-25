import { useMemo, useState } from 'react';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Card,
  CardContent,
  CardHeader,
  Chip,
  Paper,
  Skeleton,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import StorageIcon from '@mui/icons-material/Storage';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import TableViewIcon from '@mui/icons-material/TableView';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import {
  useToolCoverage,
  type ToolCoverageAsset,
  type ToolCoverageColumn,
  type ToolCoverageResponse,
} from '@/api/tools';

interface CoveragePanelProps {
  toolId: string | undefined;
}

type ViewMode = 'ontology' | 'asset';

function fmtConfidence(c: number | null): string {
  if (c === null || c === undefined || Number.isNaN(c)) return '—';
  return Number(c).toFixed(2);
}

function confidenceColor(c: number | null): 'success' | 'warning' | 'error' | 'default' {
  if (c === null || c === undefined) return 'default';
  if (c >= 0.8) return 'success';
  if (c >= 0.5) return 'warning';
  return 'error';
}

function formatSample(v: string | number | boolean | null): string {
  if (v === null || v === undefined) return 'null';
  if (typeof v === 'string') {
    return v.length > 24 ? `${v.slice(0, 24)}…` : v;
  }
  return String(v);
}

export default function CoveragePanel({ toolId }: CoveragePanelProps) {
  // Empty state when no tool selected — caller (ToolEditor) already short-circuits
  // when toolData is null, but we double-guard here so the hook stays disabled.
  if (!toolId) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: 200 }}>
        <Paper variant="outlined" sx={{ p: 4, textAlign: 'center', maxWidth: 480 }}>
          <Typography variant="subtitle2" color="text.secondary" gutterBottom>
            Save the tool first
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Coverage shows which catalog assets and business entities are bound to this
            tool. It becomes available once the tool has been saved.
          </Typography>
        </Paper>
      </Box>
    );
  }

  const { data, isLoading, isError, error } = useToolCoverage(toolId);
  const [viewMode, setViewMode] = useState<ViewMode>('ontology');
  // Click a "Business entity" chip at the top to focus the rest of the
  // panel on that entity only. Click the same chip again to clear and
  // see all entities. null means "no filter".
  const [selectedEntity, setSelectedEntity] = useState<string | null>(null);

  if (isLoading) {
    return (
      <Stack spacing={1.5}>
        <Skeleton variant="rectangular" height={28} />
        <Skeleton variant="rectangular" height={64} />
        <Skeleton variant="rectangular" height={64} />
        <Skeleton variant="rectangular" height={64} />
      </Stack>
    );
  }

  if (isError) {
    return (
      <Alert severity="error">
        Failed to load coverage: {(error as Error)?.message || 'unknown error'}
      </Alert>
    );
  }

  if (!data) {
    return <Alert severity="info">No coverage data returned.</Alert>;
  }

  const { assets, business_entities_covered } = data;
  const hasAssets = assets.length > 0;

  return (
    <Stack spacing={2}>
      {/* Business entities chip strip — click to filter the view to a single
          entity; click again to clear. Helps the user focus on one slice of
          the ontology this tool covers. */}
      <Box>
        <Stack direction="row" spacing={1} alignItems="center">
          <Typography variant="subtitle2">Business entities covered</Typography>
          {selectedEntity && (
            <Typography variant="caption" color="text.secondary">
              · filtering by{' '}
              <Box component="span" sx={{ fontWeight: 600 }}>{selectedEntity}</Box>{' '}
              <Box
                component="span"
                role="button"
                onClick={() => setSelectedEntity(null)}
                sx={{
                  ml: 0.5, color: 'primary.main', cursor: 'pointer',
                  textDecoration: 'underline',
                }}
              >
                clear
              </Box>
            </Typography>
          )}
        </Stack>
        {business_entities_covered.length === 0 ? (
          <Typography variant="caption" color="text.secondary">
            No business entities mapped yet.
          </Typography>
        ) : (
          <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ mt: 0.5 }}>
            {business_entities_covered.map((ent) => {
              const isSelected = selectedEntity === ent;
              const isDimmed = selectedEntity !== null && !isSelected;
              return (
                <Chip
                  key={ent}
                  label={ent}
                  size="small"
                  color="primary"
                  variant={isSelected ? 'filled' : 'outlined'}
                  clickable
                  onClick={() =>
                    setSelectedEntity(isSelected ? null : ent)
                  }
                  sx={{
                    opacity: isDimmed ? 0.55 : 1,
                    transition: 'opacity 120ms',
                  }}
                />
              );
            })}
          </Stack>
        )}
      </Box>

      {/* View-mode toggle — only meaningful when there are assets to show */}
      {hasAssets && (
        <Stack direction="row" justifyContent="flex-end">
          <ToggleButtonGroup
            value={viewMode}
            exclusive
            size="small"
            onChange={(_, next: ViewMode | null) => {
              if (next !== null) setViewMode(next);
            }}
            aria-label="coverage view mode"
          >
            <ToggleButton value="ontology" aria-label="By Ontology">
              <AccountTreeIcon fontSize="small" sx={{ mr: 0.5 }} />
              By Ontology
            </ToggleButton>
            <ToggleButton value="asset" aria-label="By Asset">
              <TableViewIcon fontSize="small" sx={{ mr: 0.5 }} />
              By Asset
            </ToggleButton>
          </ToggleButtonGroup>
        </Stack>
      )}

      {/* Assets — empty state */}
      {!hasAssets ? (
        <Paper variant="outlined" sx={{ p: 3 }}>
          <Stack direction="row" spacing={1.5} alignItems="flex-start">
            <StorageIcon color="disabled" />
            <Box>
              <Typography variant="subtitle2" gutterBottom>
                No catalog binding yet
              </Typography>
              <Typography variant="body2" color="text.secondary">
                This tool isn&apos;t bound to any DataSource in the catalog yet. Make
                sure a crawler has run against the tool&apos;s hostname/endpoint.
              </Typography>
            </Box>
          </Stack>
        </Paper>
      ) : viewMode === 'asset' ? (
        <ByAssetView data={data} entityFilter={selectedEntity} />
      ) : (
        <ByOntologyView data={data} entityFilter={selectedEntity} />
      )}
    </Stack>
  );
}

// ---------------------------------------------------------------------------
// View: By Asset (existing behaviour, lifted to its own sub-component)
// ---------------------------------------------------------------------------

function ByAssetView({
  data,
  entityFilter,
}: {
  data: ToolCoverageResponse;
  entityFilter: string | null;
}) {
  const { assets, tool_type } = data;
  // When an entity filter is on, drop assets with zero matching columns and
  // mark each remaining asset so the accordion can highlight only the
  // matching rows.
  const filteredAssets = useMemo(() => {
    if (!entityFilter) return assets;
    return assets
      .map((a) => ({
        ...a,
        columns: a.columns.filter((c) => c.business_entity === entityFilter),
      }))
      .filter((a) => a.columns.length > 0);
  }, [assets, entityFilter]);

  if (entityFilter && filteredAssets.length === 0) {
    return (
      <Alert severity="info">
        No physical columns mapped to <strong>{entityFilter}</strong> in this tool's
        bound assets.
      </Alert>
    );
  }

  return (
    <Box>
      <Typography variant="subtitle2" gutterBottom>
        Bound assets ({filteredAssets.length}
        {entityFilter ? ` matching ${entityFilter}` : ''})
      </Typography>
      {filteredAssets.map((asset) => (
        <AssetAccordion
          key={asset.asset_fq_name}
          asset={asset}
          toolType={tool_type}
          defaultExpanded={!!entityFilter}
        />
      ))}
    </Box>
  );
}

function AssetAccordion({
  asset,
  toolType,
  defaultExpanded = false,
}: {
  asset: ToolCoverageAsset;
  toolType: string;
  defaultExpanded?: boolean;
}) {
  return (
    <Accordion disableGutters defaultExpanded={defaultExpanded} sx={{ mb: 0.5 }}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Stack direction="row" spacing={1} alignItems="center" sx={{ flex: 1, minWidth: 0 }}>
          <Typography
            variant="body2"
            sx={{
              fontFamily: 'monospace',
              fontSize: 12,
              flex: 1,
              minWidth: 0,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {asset.asset_fq_name}
          </Typography>
          <Chip
            label={asset.source_name}
            size="small"
            variant="outlined"
            sx={{ height: 20, fontSize: 10 }}
          />
          <Chip
            label={toolType}
            size="small"
            color="info"
            sx={{ height: 20, fontSize: 10 }}
          />
          <Chip
            label={asset.asset_type}
            size="small"
            sx={{ height: 20, fontSize: 10 }}
          />
          <Typography variant="caption" color="text.secondary" sx={{ minWidth: 80, textAlign: 'right' }}>
            {asset.row_count !== null && asset.row_count !== undefined
              ? `${asset.row_count.toLocaleString()} rows`
              : '— rows'}
          </Typography>
        </Stack>
      </AccordionSummary>
      <AccordionDetails sx={{ pt: 0 }}>
        {asset.source_uri && (
          <Typography
            variant="caption"
            color="text.secondary"
            sx={{ fontFamily: 'monospace', display: 'block', mb: 1 }}
          >
            {asset.source_uri}
          </Typography>
        )}
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Name</TableCell>
              <TableCell>Data Type</TableCell>
              <TableCell>Business Mapping</TableCell>
              <TableCell align="right">Confidence</TableCell>
              <TableCell>Sample Values</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {asset.columns.map((col) => (
              <ColumnRow key={col.name} column={col} />
            ))}
          </TableBody>
        </Table>
      </AccordionDetails>
    </Accordion>
  );
}

function ColumnRow({ column }: { column: ToolCoverageColumn }) {
  const mapping =
    column.business_entity && column.business_attribute
      ? `${column.business_entity}.${column.business_attribute}`
      : '—';
  const samples = (column.sample_values ?? []).slice(0, 3);
  return (
    <TableRow>
      <TableCell>
        <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
          {column.name}
        </Typography>
      </TableCell>
      <TableCell>
        <Typography variant="caption" sx={{ fontFamily: 'monospace' }}>
          {column.data_type}
        </Typography>
      </TableCell>
      <TableCell>
        {mapping === '—' ? (
          <Typography variant="caption" color="text.secondary">
            —
          </Typography>
        ) : (
          <Box>
            {column.business_domain && (
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                {column.business_domain}
              </Typography>
            )}
            <Typography variant="body2">{mapping}</Typography>
          </Box>
        )}
      </TableCell>
      <TableCell align="right">
        {column.map_confidence !== null && column.map_confidence !== undefined ? (
          <Chip
            label={fmtConfidence(column.map_confidence)}
            size="small"
            color={confidenceColor(column.map_confidence)}
            sx={{ height: 18, fontSize: 10 }}
          />
        ) : (
          <Typography variant="caption" color="text.secondary">
            —
          </Typography>
        )}
      </TableCell>
      <TableCell>
        {samples.length === 0 ? (
          <Typography variant="caption" color="text.secondary">
            —
          </Typography>
        ) : (
          <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
            {samples.map((v, i) => (
              <Chip
                key={i}
                label={formatSample(v)}
                size="small"
                variant="outlined"
                sx={{ height: 18, fontSize: 10, fontFamily: 'monospace' }}
              />
            ))}
          </Stack>
        )}
      </TableCell>
    </TableRow>
  );
}

// ---------------------------------------------------------------------------
// View: By Ontology (new) — pivots assets[].columns[] into a
// BusinessDomain → BusinessEntity → BusinessAttribute → physical-columns tree.
// ---------------------------------------------------------------------------

interface PhysicalColumnRef {
  column: string;
  data_type: string | null;
  map_confidence: number | null;
  asset_fq_name: string;
  source_name: string | null;
  source_uri: string | null;
  sample_values: Array<string | number | boolean | null>;
}

interface AttributeGroup {
  attribute: string;
  physical_columns: PhysicalColumnRef[];
}

interface EntityGroup {
  entity: string;
  attributes: AttributeGroup[];
}

interface DomainGroup {
  domain: string;
  entities: EntityGroup[];
}

const UNCATEGORIZED_DOMAIN = 'Uncategorized';
const UNKNOWN_ENTITY = 'Unknown';

function buildOntologyTree(assets: ToolCoverageAsset[]): DomainGroup[] {
  // domain → entity → attribute → list of physical column refs
  const domainMap = new Map<string, Map<string, Map<string, PhysicalColumnRef[]>>>();

  for (const asset of assets) {
    for (const col of asset.columns) {
      const attr = col.business_attribute;
      // Skip physical-only columns — those belong to the per-asset view.
      if (!attr || attr.trim() === '') continue;

      const domain =
        col.business_domain && col.business_domain.trim() !== ''
          ? col.business_domain
          : UNCATEGORIZED_DOMAIN;
      const entity =
        col.business_entity && col.business_entity.trim() !== ''
          ? col.business_entity
          : UNKNOWN_ENTITY;

      let entityMap = domainMap.get(domain);
      if (!entityMap) {
        entityMap = new Map();
        domainMap.set(domain, entityMap);
      }
      let attrMap = entityMap.get(entity);
      if (!attrMap) {
        attrMap = new Map();
        entityMap.set(entity, attrMap);
      }
      let physList = attrMap.get(attr);
      if (!physList) {
        physList = [];
        attrMap.set(attr, physList);
      }
      physList.push({
        column: col.name,
        data_type: col.data_type,
        map_confidence: col.map_confidence,
        asset_fq_name: asset.asset_fq_name,
        source_name: asset.source_name,
        source_uri: asset.source_uri,
        sample_values: col.sample_values ?? [],
      });
    }
  }

  // Materialize sorted shape.
  const domains: DomainGroup[] = [];
  const sortedDomainKeys = Array.from(domainMap.keys()).sort((a, b) => a.localeCompare(b));
  for (const domain of sortedDomainKeys) {
    const entityMap = domainMap.get(domain)!;
    const entities: EntityGroup[] = [];
    const sortedEntityKeys = Array.from(entityMap.keys()).sort((a, b) => a.localeCompare(b));
    for (const entity of sortedEntityKeys) {
      const attrMap = entityMap.get(entity)!;
      const attributes: AttributeGroup[] = [];
      const sortedAttrKeys = Array.from(attrMap.keys()).sort((a, b) => a.localeCompare(b));
      for (const attribute of sortedAttrKeys) {
        attributes.push({
          attribute,
          physical_columns: attrMap.get(attribute)!,
        });
      }
      entities.push({ entity, attributes });
    }
    domains.push({ domain, entities });
  }
  return domains;
}

function shortAssetName(fq: string): string {
  // Take last segment of dot-separated FQN, e.g. "src.warehouse.public.customers" -> "customers".
  const parts = fq.split('.');
  return parts.length > 0 ? parts[parts.length - 1] : fq;
}

function dedupeSamples(
  cols: PhysicalColumnRef[],
  limit: number,
): Array<string | number | boolean | null> {
  const seen = new Set<string>();
  const out: Array<string | number | boolean | null> = [];
  for (const c of cols) {
    for (const v of c.sample_values) {
      const key = v === null || v === undefined ? '__null__' : `${typeof v}:${String(v)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(v);
      if (out.length >= limit) return out;
    }
  }
  return out;
}

function ByOntologyView({
  data,
  entityFilter,
}: {
  data: ToolCoverageResponse;
  entityFilter: string | null;
}) {
  const fullTree = useMemo(() => buildOntologyTree(data.assets), [data.assets]);
  const tree = useMemo(() => {
    if (!entityFilter) return fullTree;
    // Drop entities that don't match the filter; drop empty domains.
    return fullTree
      .map((d) => ({
        ...d,
        entities: d.entities.filter((e) => e.entity === entityFilter),
      }))
      .filter((d) => d.entities.length > 0);
  }, [fullTree, entityFilter]);

  if (fullTree.length === 0) {
    return (
      <Alert severity="info" icon={<AccountTreeIcon />}>
        No business-ontology mappings yet for this tool&apos;s assets. Run a crawl with
        semantic mapping enabled or check the Mapping Review tab.
      </Alert>
    );
  }

  if (entityFilter && tree.length === 0) {
    return (
      <Alert severity="info" icon={<AccountTreeIcon />}>
        No ontology mappings for <strong>{entityFilter}</strong> in this tool's reach.
      </Alert>
    );
  }

  const totalEntities = tree.reduce((acc, d) => acc + d.entities.length, 0);
  const totalAttributes = tree.reduce(
    (acc, d) => acc + d.entities.reduce((a, e) => a + e.attributes.length, 0),
    0,
  );

  return (
    <Box>
      <Typography variant="subtitle2" gutterBottom>
        {entityFilter
          ? `Ontology coverage (${entityFilter} only · ${totalAttributes} attribute${
              totalAttributes === 1 ? '' : 's'
            })`
          : `Ontology coverage (${tree.length} domain${
              tree.length === 1 ? '' : 's'
            }, ${totalEntities} entit${
              totalEntities === 1 ? 'y' : 'ies'
            }, ${totalAttributes} attribute${totalAttributes === 1 ? '' : 's'})`}
      </Typography>
      <Stack spacing={1.5}>
        {tree.map((domain) => (
          <DomainSection key={domain.domain} group={domain} />
        ))}
      </Stack>
    </Box>
  );
}

function DomainSection({ group }: { group: DomainGroup }) {
  return (
    <Accordion defaultExpanded disableGutters sx={{ mb: 0.5 }}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Stack direction="row" spacing={1} alignItems="center">
          <Typography variant="subtitle2">{group.domain}</Typography>
          <Chip
            label={`${group.entities.length} ${group.entities.length === 1 ? 'entity' : 'entities'}`}
            size="small"
            sx={{ height: 20, fontSize: 10 }}
          />
        </Stack>
      </AccordionSummary>
      <AccordionDetails sx={{ pt: 0 }}>
        <Stack spacing={1.5}>
          {group.entities.map((entity) => (
            <EntityCard key={entity.entity} group={entity} />
          ))}
        </Stack>
      </AccordionDetails>
    </Accordion>
  );
}

function EntityCard({ group }: { group: EntityGroup }) {
  return (
    <Card variant="outlined">
      <CardHeader
        sx={{ py: 1, px: 2 }}
        title={
          <Stack direction="row" spacing={1} alignItems="center">
            <Typography variant="body1" sx={{ fontWeight: 600 }}>
              {group.entity}
            </Typography>
            <Chip
              label={`${group.attributes.length} attr${group.attributes.length === 1 ? '' : 's'}`}
              size="small"
              color="primary"
              variant="outlined"
              sx={{ height: 20, fontSize: 10 }}
            />
          </Stack>
        }
      />
      <CardContent sx={{ pt: 0, pb: 1, '&:last-child': { pb: 1 } }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell sx={{ width: '22%' }}>Attribute</TableCell>
              <TableCell sx={{ width: '48%' }}>Physical Columns</TableCell>
              <TableCell>Sample Values</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {group.attributes.map((attr) => (
              <AttributeRow key={attr.attribute} group={attr} />
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function AttributeRow({ group }: { group: AttributeGroup }) {
  const cols = group.physical_columns;
  const distinctSources = new Set(cols.map((c) => c.source_name ?? '<unknown>')).size;
  const isSynonym = distinctSources > 1;
  const samples = dedupeSamples(cols, 3);

  return (
    <TableRow>
      <TableCell sx={{ verticalAlign: 'top' }}>
        <Stack spacing={0.5}>
          <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
            {group.attribute}
          </Typography>
          {isSynonym && (
            <Chip
              icon={<WarningAmberIcon sx={{ fontSize: 12 }} />}
              label={`synonym across ${distinctSources} sources`}
              size="small"
              color="warning"
              variant="outlined"
              sx={{ height: 18, fontSize: 10, alignSelf: 'flex-start' }}
            />
          )}
        </Stack>
      </TableCell>
      <TableCell sx={{ verticalAlign: 'top' }}>
        <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
          {cols.map((c, i) => {
            const label = `${c.source_name ?? '?'}.${shortAssetName(c.asset_fq_name)}.${c.column}`;
            const titleLines = [
              `Asset: ${c.asset_fq_name}`,
              `Column: ${c.column}`,
              c.data_type ? `Type: ${c.data_type}` : null,
              c.source_uri ? `URI: ${c.source_uri}` : null,
              c.map_confidence !== null && c.map_confidence !== undefined
                ? `Confidence: ${fmtConfidence(c.map_confidence)}`
                : null,
            ]
              .filter((s): s is string => s !== null)
              .join('\n');
            return (
              <Tooltip key={`${c.asset_fq_name}::${c.column}::${i}`} title={<pre style={{ margin: 0, fontFamily: 'inherit' }}>{titleLines}</pre>} arrow>
                <Chip
                  label={label}
                  size="small"
                  color={confidenceColor(c.map_confidence)}
                  variant="outlined"
                  sx={{ height: 20, fontSize: 10, fontFamily: 'monospace', maxWidth: '100%' }}
                />
              </Tooltip>
            );
          })}
        </Stack>
      </TableCell>
      <TableCell sx={{ verticalAlign: 'top' }}>
        {samples.length === 0 ? (
          <Typography variant="caption" color="text.secondary">
            —
          </Typography>
        ) : (
          <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
            {samples.map((v, i) => (
              <Chip
                key={i}
                label={formatSample(v)}
                size="small"
                variant="outlined"
                sx={{ height: 18, fontSize: 10, fontFamily: 'monospace' }}
              />
            ))}
          </Stack>
        )}
      </TableCell>
    </TableRow>
  );
}
