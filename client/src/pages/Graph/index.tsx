import React, { useState, useCallback, useRef, useEffect } from 'react';
import {
  Box,
  Typography,
  Skeleton,
  useTheme,
} from '@mui/material';
import { useTaskGraph } from '@/api/graph';
import { useUIStore } from '@/store/uiStore';
import type { TaskNode, TaskNodeStatus } from '@/types';
import TaskGraphCanvas from '@/components/Graph/TaskGraphCanvas';
import NodeDetailPanel from '@/components/Graph/NodeDetailPanel';
import GraphControls from '@/components/Graph/GraphControls';
import * as d3 from 'd3';

const ALL_STATUSES: TaskNodeStatus[] = [
  'PENDING',
  'RUNNING',
  'SUCCESS',
  'FAILED',
  'CORRECTING',
  'SKIPPED',
];

function useStatusLegendColor() {
  const theme = useTheme();
  return {
    PENDING: theme.palette.grey[500],
    RUNNING: theme.palette.info.main,
    SUCCESS: theme.palette.success.main,
    FAILED: theme.palette.error.main,
    CORRECTING: theme.palette.warning.main,
    SKIPPED: theme.palette.grey[300],
  };
}

const GraphPage: React.FC = () => {
  const [selectedTeamId, setSelectedTeamId] = useState('');
  // selectedGraphId drives BOTH client-side display filtering AND the
  // server-side `graph_id` query param, so picking a graph in the dropdown
  // tells the orchestrator to return only that subgraph (efficient on large
  // datasets). When empty, the full graph is fetched.
  const [selectedGraphId, setSelectedGraphId] = useState('');

  const { data: graphData, isLoading, isError, refetch } = useTaskGraph({
    teamId: selectedTeamId || undefined,
    graphId: selectedGraphId || undefined,
  });

  const { graphDetailPanelOpen, setGraphDetailPanelOpen } = useUIStore();
  const [selectedNode, setSelectedNode] = useState<TaskNode | null>(null);
  const [statusFilter, setStatusFilter] = useState<TaskNodeStatus[]>(ALL_STATUSES);
  const [maxDepth, setMaxDepth] = useState(10);
  const [selectedAgent, setSelectedAgent] = useState('');
  const canvasContainerRef = useRef<HTMLDivElement>(null);
  const legendColors = useStatusLegendColor();

  // Derive unique agents from currently-loaded data
  const uniqueAgents = React.useMemo(() => {
    if (!graphData?.nodes) return [];
    const set = new Set<string>();
    for (const n of graphData.nodes) {
      const a = n.agent_name || n.assigned_agent_name;
      if (a) set.add(a);
    }
    return Array.from(set).sort();
  }, [graphData]);

  // Cache of all graph_ids ever seen on an UNFILTERED fetch, so the dropdown
  // doesn't collapse to a single option after a server-side filter is applied.
  const [knownGraphIds, setKnownGraphIds] = useState<string[]>([]);
  useEffect(() => {
    if (selectedGraphId) return; // skip refresh on filtered fetches
    if (!graphData?.nodes) return;
    const set = new Set<string>();
    for (const n of graphData.nodes) {
      if (n.graph_id) set.add(n.graph_id);
    }
    const next = Array.from(set).sort();
    setKnownGraphIds((prev) =>
      prev.length === next.length && prev.every((v, i) => v === next[i]) ? prev : next,
    );
  }, [graphData, selectedGraphId]);

  // Apply agent filter to nodes/edges (graph filter is now server-side)
  const filteredData = React.useMemo(() => {
    if (!graphData) return { nodes: [], edges: [] };
    let nodes = graphData.nodes;
    if (selectedAgent) {
      nodes = nodes.filter((n) => {
        const a = n.agent_name || n.assigned_agent_name;
        return a === selectedAgent;
      });
    }
    const nodeIds = new Set(nodes.map((n) => n.task_id));
    const edges = (graphData.edges ?? []).filter(
      (e) => nodeIds.has(e.source as string) && nodeIds.has(e.target as string),
    );
    return { nodes, edges };
  }, [graphData, selectedAgent]);

  const handleNodeClick = useCallback(
    (node: TaskNode) => {
      setSelectedNode(node);
      setGraphDetailPanelOpen(true);
    },
    [setGraphDetailPanelOpen],
  );

  const handleCloseDetail = useCallback(() => {
    setSelectedNode(null);
    setGraphDetailPanelOpen(false);
  }, [setGraphDetailPanelOpen]);

  /* D3 zoom helpers — access the internal zoom behavior from the canvas container */
  const getZoomContext = useCallback(() => {
    const container = canvasContainerRef.current?.querySelector('[class]')
      ?? canvasContainerRef.current?.firstElementChild;
    if (!container) return null;
    const el = container as unknown as Record<string, unknown>;
    const zoomBehavior = el.__d3Zoom as d3.ZoomBehavior<SVGSVGElement, unknown> | undefined;
    const svg = el.__d3Svg as d3.Selection<SVGSVGElement, unknown, null, undefined> | undefined;
    if (!zoomBehavior || !svg) return null;
    return { zoom: zoomBehavior, svg };
  }, []);

  const handleZoomIn = useCallback(() => {
    const ctx = getZoomContext();
    if (ctx) ctx.svg.transition().duration(300).call(ctx.zoom.scaleBy, 1.3);
  }, [getZoomContext]);

  const handleZoomOut = useCallback(() => {
    const ctx = getZoomContext();
    if (ctx) ctx.svg.transition().duration(300).call(ctx.zoom.scaleBy, 0.7);
  }, [getZoomContext]);

  const handleFitToScreen = useCallback(() => {
    const ctx = getZoomContext();
    if (ctx) {
      ctx.svg
        .transition()
        .duration(500)
        .call(ctx.zoom.transform, d3.zoomIdentity);
    }
  }, [getZoomContext]);

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 112px)', overflow: 'hidden', mx: -3, mt: -3, mb: -3 }}>
      {/* Top toolbar */}
      <GraphControls
        statusFilter={statusFilter}
        onStatusFilterChange={setStatusFilter}
        maxDepth={maxDepth}
        onMaxDepthChange={setMaxDepth}
        onZoomIn={handleZoomIn}
        onZoomOut={handleZoomOut}
        onFitToScreen={handleFitToScreen}
        onRefresh={() => refetch()}
        teams={graphData?.teams ?? []}
        selectedTeamId={selectedTeamId}
        onTeamChange={(tid) => { setSelectedTeamId(tid); refetch(); }}
        agents={uniqueAgents}
        selectedAgent={selectedAgent}
        onAgentChange={setSelectedAgent}
        graphIds={knownGraphIds}
        selectedGraphId={selectedGraphId}
        onGraphIdChange={setSelectedGraphId}
        nodeCount={filteredData.nodes.length}
        edgeCount={filteredData.edges.length}
      />

      {/* Main area */}
      <Box sx={{ flex: 1, display: 'flex', overflow: 'hidden', position: 'relative' }}>
        {/* Graph canvas */}
        <Box ref={canvasContainerRef} sx={{ flex: 1, minWidth: 0 }}>
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
                Failed to load task graph. Please try again.
              </Typography>
            </Box>
          )}

          {graphData && !isLoading && filteredData.nodes.length > 0 && (
            <TaskGraphCanvas
              nodes={filteredData.nodes}
              edges={filteredData.edges}
              onNodeClick={handleNodeClick}
              maxDepth={maxDepth}
              statusFilter={statusFilter}
            />
          )}

          {graphData && filteredData.nodes.length === 0 && !isLoading && (
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                height: '100%',
              }}
            >
              <Typography color="text.secondary">
                No task nodes to display.
              </Typography>
            </Box>
          )}
        </Box>

        {/* Node detail panel — slides in from right */}
        {graphDetailPanelOpen && (
          <NodeDetailPanel node={selectedNode} onClose={handleCloseDetail} />
        )}
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
        {ALL_STATUSES.map((status) => (
          <Box key={status} sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <Box
              sx={{
                width: 10,
                height: 10,
                borderRadius: '50%',
                bgcolor: legendColors[status],
              }}
            />
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
              {status}
            </Typography>
          </Box>
        ))}
      </Box>
    </Box>
  );
};

export default GraphPage;
