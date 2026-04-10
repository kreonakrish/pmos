import React, { useState, useCallback, useRef } from 'react';
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
  const [serverGraphFilter, setServerGraphFilter] = useState('');

  // Pass team/graph filter to API (server-side filtering for teams)
  const { data: graphData, isLoading, isError, refetch } = useTaskGraph({
    teamId: selectedTeamId || undefined,
    graphId: serverGraphFilter || undefined,
  });

  const { graphDetailPanelOpen, setGraphDetailPanelOpen } = useUIStore();
  const [selectedNode, setSelectedNode] = useState<TaskNode | null>(null);
  const [statusFilter, setStatusFilter] = useState<TaskNodeStatus[]>(ALL_STATUSES);
  const [maxDepth, setMaxDepth] = useState(10);
  const [selectedAgent, setSelectedAgent] = useState('');
  const [selectedGraphId, setSelectedGraphId] = useState('');
  const canvasContainerRef = useRef<HTMLDivElement>(null);
  const legendColors = useStatusLegendColor();

  // Derive unique agents and graph_ids from data
  const uniqueAgents = React.useMemo(() => {
    if (!graphData?.nodes) return [];
    const set = new Set<string>();
    for (const n of graphData.nodes) {
      const a = n.agent_name || (n as Record<string, unknown>).assigned_agent_name as string;
      if (a) set.add(a);
    }
    return Array.from(set).sort();
  }, [graphData]);

  const uniqueGraphIds = React.useMemo(() => {
    if (!graphData?.nodes) return [];
    const set = new Set<string>();
    for (const n of graphData.nodes) {
      const g = (n as Record<string, unknown>).graph_id as string;
      if (g) set.add(g);
    }
    return Array.from(set);
  }, [graphData]);

  // Apply agent and graph filters to nodes/edges
  const filteredData = React.useMemo(() => {
    if (!graphData) return { nodes: [], edges: [] };
    let nodes = graphData.nodes;
    if (selectedAgent) {
      nodes = nodes.filter((n) => {
        const a = n.agent_name || (n as Record<string, unknown>).assigned_agent_name as string;
        return a === selectedAgent;
      });
    }
    if (selectedGraphId) {
      nodes = nodes.filter((n) => (n as Record<string, unknown>).graph_id === selectedGraphId);
    }
    const nodeIds = new Set(nodes.map((n) => n.task_id));
    const edges = (graphData.edges ?? []).filter(
      (e) => nodeIds.has(e.source as string) && nodeIds.has(e.target as string),
    );
    return { nodes, edges };
  }, [graphData, selectedAgent, selectedGraphId]);

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
        teams={(graphData as Record<string, unknown>)?.teams as Array<{team_id: string; name: string}> ?? []}
        selectedTeamId={selectedTeamId}
        onTeamChange={(tid) => { setSelectedTeamId(tid); refetch(); }}
        agents={uniqueAgents}
        selectedAgent={selectedAgent}
        onAgentChange={setSelectedAgent}
        graphIds={uniqueGraphIds}
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
