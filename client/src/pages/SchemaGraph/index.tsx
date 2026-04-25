import React, { useCallback, useMemo, useState } from 'react';
import {
  Box,
  Chip,
  Divider,
  Drawer,
  IconButton,
  Paper,
  Skeleton,
  Stack,
  Typography,
  useTheme,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import HubIcon from '@mui/icons-material/Hub';
import { useSchemaGraph } from '@/api/schemaGraph';
import type { SchemaNode } from '@/api/schemaGraph';
import SchemaGraphCanvas, {
  SCHEMA_NODE_CATEGORIES,
  categorizeSchemaNode,
  useSchemaCategoryColorMap,
} from '@/components/Graph/SchemaGraphCanvas';

const DRAWER_WIDTH = 360;

const SchemaGraphPage: React.FC = () => {
  const theme = useTheme();
  const colorMap = useSchemaCategoryColorMap();

  const { data, isLoading, isError } = useSchemaGraph();

  const [selectedNode, setSelectedNode] = useState<SchemaNode | null>(null);
  const drawerOpen = selectedNode !== null;

  const handleNodeClick = useCallback((node: SchemaNode) => {
    setSelectedNode(node);
  }, []);

  const handleCloseDrawer = useCallback(() => {
    setSelectedNode(null);
  }, []);

  /* Compute incoming/outgoing relationship type sets for the selected node. */
  const { incomingRels, outgoingRels } = useMemo(() => {
    if (!selectedNode || !data) {
      return { incomingRels: [] as string[], outgoingRels: [] as string[] };
    }
    const inc = new Set<string>();
    const out = new Set<string>();
    for (const e of data.edges) {
      if (!e.type) continue;
      if (e.to === selectedNode.id) inc.add(e.type);
      if (e.from === selectedNode.id) out.add(e.type);
    }
    return {
      incomingRels: Array.from(inc).sort(),
      outgoingRels: Array.from(out).sort(),
    };
  }, [selectedNode, data]);

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        height: 'calc(100vh - 112px)',
        overflow: 'hidden',
        mx: -3,
        mt: -3,
        mb: -3,
      }}
    >
      {/* Header */}
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          px: 3,
          py: 1.5,
          borderBottom: 1,
          borderColor: 'divider',
          bgcolor: 'background.paper',
        }}
      >
        <Stack direction="row" alignItems="center" spacing={1.5}>
          <HubIcon color="primary" />
          <Box>
            <Typography variant="h5" fontWeight={600} lineHeight={1.2}>
              Schema Graph
            </Typography>
            <Typography variant="caption" color="text.secondary">
              Neo4j ontology model used by the Translator service
            </Typography>
          </Box>
        </Stack>

        {/* Counts chip */}
        <Stack direction="row" spacing={1} alignItems="center">
          <Chip
            size="small"
            variant="outlined"
            label={`${data?.node_count ?? 0} nodes / ${data?.edge_count ?? 0} edges`}
          />
        </Stack>
      </Box>

      {/* Main area */}
      <Box sx={{ flex: 1, display: 'flex', overflow: 'hidden', position: 'relative' }}>
        {/* Canvas */}
        <Box sx={{ flex: 1, minWidth: 0, position: 'relative' }}>
          {isLoading && (
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                height: '100%',
              }}
            >
              <Skeleton variant="rounded" width="80%" height="70%" />
            </Box>
          )}

          {isError && (
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                height: '100%',
              }}
            >
              <Typography color="error">
                Failed to load schema graph. Please try again.
              </Typography>
            </Box>
          )}

          {data && !isLoading && data.nodes.length > 0 && (
            <SchemaGraphCanvas
              nodes={data.nodes}
              edges={data.edges}
              onNodeClick={handleNodeClick}
            />
          )}

          {data && !isLoading && data.nodes.length === 0 && (
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                height: '100%',
              }}
            >
              <Typography color="text.secondary">
                No schema nodes returned by Neo4j.
              </Typography>
            </Box>
          )}
        </Box>

        {/* Side drawer with node details */}
        <Drawer
          anchor="right"
          open={drawerOpen}
          onClose={handleCloseDrawer}
          variant="persistent"
          PaperProps={{
            sx: {
              width: DRAWER_WIDTH,
              position: 'absolute',
              borderLeft: 1,
              borderColor: 'divider',
            },
          }}
          sx={{
            '& .MuiDrawer-root': { position: 'absolute' },
            '& .MuiBackdrop-root': { display: 'none' },
          }}
        >
          {selectedNode && (
            <Paper
              square
              elevation={0}
              sx={{
                width: '100%',
                height: '100%',
                overflow: 'auto',
                display: 'flex',
                flexDirection: 'column',
              }}
            >
              {/* Drawer header */}
              <Box
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  p: 2,
                  borderBottom: 1,
                  borderColor: 'divider',
                }}
              >
                <Stack direction="row" alignItems="center" spacing={1}>
                  <Box
                    sx={{
                      width: 14,
                      height: 14,
                      borderRadius: '50%',
                      bgcolor: colorMap[categorizeSchemaNode(selectedNode.label)],
                      border: 2,
                      borderColor: 'background.paper',
                    }}
                  />
                  <Typography variant="subtitle1" fontWeight={600}>
                    {selectedNode.label}
                  </Typography>
                </Stack>
                <IconButton size="small" onClick={handleCloseDrawer}>
                  <CloseIcon fontSize="small" />
                </IconButton>
              </Box>

              {/* Drawer body */}
              <Box sx={{ p: 2, flex: 1 }}>
                {/* Properties */}
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{ fontWeight: 600, textTransform: 'uppercase', letterSpacing: 1 }}
                >
                  Properties
                </Typography>
                {selectedNode.properties.length === 0 ? (
                  <Typography variant="body2" sx={{ mt: 0.5, color: 'text.secondary' }}>
                    No properties indexed.
                  </Typography>
                ) : (
                  <Box sx={{ mt: 1, mb: 2 }}>
                    {selectedNode.properties.map((p, idx) => (
                      <Box
                        key={`${p.name}-${idx}`}
                        sx={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          py: 0.5,
                          px: 1,
                          borderRadius: 1,
                          bgcolor: idx % 2 === 0 ? 'action.hover' : 'transparent',
                        }}
                      >
                        <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
                          {p.name}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          {p.type}
                        </Typography>
                      </Box>
                    ))}
                  </Box>
                )}

                <Divider sx={{ my: 1.5 }} />

                {/* Outgoing relationships */}
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{ fontWeight: 600, textTransform: 'uppercase', letterSpacing: 1 }}
                >
                  Outgoing relationships
                </Typography>
                <Box sx={{ mt: 1, mb: 2, display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                  {outgoingRels.length === 0 ? (
                    <Typography variant="body2" color="text.secondary">
                      None
                    </Typography>
                  ) : (
                    outgoingRels.map((rel) => (
                      <Chip key={rel} label={rel} size="small" variant="outlined" />
                    ))
                  )}
                </Box>

                {/* Incoming relationships */}
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{ fontWeight: 600, textTransform: 'uppercase', letterSpacing: 1 }}
                >
                  Incoming relationships
                </Typography>
                <Box sx={{ mt: 1, display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                  {incomingRels.length === 0 ? (
                    <Typography variant="body2" color="text.secondary">
                      None
                    </Typography>
                  ) : (
                    incomingRels.map((rel) => (
                      <Chip key={rel} label={rel} size="small" variant="outlined" />
                    ))
                  )}
                </Box>
              </Box>
            </Paper>
          )}
        </Drawer>
      </Box>

      {/* Bottom legend */}
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 1.5,
          px: 2,
          py: 0.75,
          borderTop: 1,
          borderColor: 'divider',
          bgcolor: 'background.paper',
          flexWrap: 'wrap',
        }}
      >
        <Typography variant="caption" sx={{ color: 'text.secondary', fontWeight: 600 }}>
          Legend:
        </Typography>
        {SCHEMA_NODE_CATEGORIES.map((cat) => (
          <Box key={cat} sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <Box
              sx={{
                width: 10,
                height: 10,
                borderRadius: '50%',
                bgcolor: colorMap[cat],
                border: `1px solid ${theme.palette.divider}`,
              }}
            />
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
              {cat}
            </Typography>
          </Box>
        ))}
      </Box>
    </Box>
  );
};

export default SchemaGraphPage;
