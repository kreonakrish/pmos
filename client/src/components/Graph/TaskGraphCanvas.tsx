import React, { useRef, useEffect, useCallback } from 'react';
import { Box, useTheme } from '@mui/material';
import * as d3 from 'd3';
import type { TaskNode, TaskEdge, TaskNodeStatus } from '@/types';

type ZoomTransform = d3.ZoomTransform;

interface Props {
  nodes: TaskNode[];
  edges?: TaskEdge[];
  onNodeClick: (node: TaskNode) => void;
  maxDepth?: number;
  statusFilter?: string[];
}

interface SimNode extends d3.SimulationNodeDatum {
  data: TaskNode;
}

interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  relationship: string;
}

/**
 * Returns a theme-based color for each task status.
 * Uses MUI palette tokens so it adapts to light/dark mode.
 */
function useStatusColorMap(): Record<TaskNodeStatus, string> {
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

const TaskGraphCanvas: React.FC<Props> = ({
  nodes,
  edges = [],
  onNodeClick,
  maxDepth,
  statusFilter,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const simulationRef = useRef<d3.Simulation<SimNode, SimLink> | null>(null);
  const zoomTransformRef = useRef<ZoomTransform>(d3.zoomIdentity);
  const colorMap = useStatusColorMap();
  const theme = useTheme();

  /* Filter nodes */
  const filteredNodes = React.useMemo(() => {
    let result = nodes;
    if (maxDepth != null) {
      result = result.filter((n) => n.depth <= maxDepth);
    }
    if (statusFilter && statusFilter.length > 0) {
      result = result.filter((n) => statusFilter.includes(n.status));
    }
    return result;
  }, [nodes, maxDepth, statusFilter]);

  const filteredNodeIds = React.useMemo(
    () => new Set(filteredNodes.map((n) => n.task_id)),
    [filteredNodes],
  );

  const filteredEdges = React.useMemo(
    () => edges.filter((e) => filteredNodeIds.has(e.source) && filteredNodeIds.has(e.target)),
    [edges, filteredNodeIds],
  );

  /* Build / update D3 force simulation */
  const buildGraph = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;

    const width = container.clientWidth;
    const height = container.clientHeight;

    /* Clear previous */
    d3.select(container).select('svg').remove();

    const svg = d3
      .select(container)
      .append('svg')
      .attr('width', width)
      .attr('height', height);

    svgRef.current = svg.node();

    /* Arrow marker */
    svg
      .append('defs')
      .append('marker')
      .attr('id', 'arrowhead')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 20)
      .attr('refY', 0)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-5L10,0L0,5')
      .attr('fill', theme.palette.text.secondary);

    const g = svg.append('g');

    /* Zoom — persist transform across rebuilds */
    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.1, 4])
      .on('zoom', (event) => {
        zoomTransformRef.current = event.transform;
        g.attr('transform', event.transform);
      });

    svg.call(zoom);

    /* Restore previous zoom transform */
    if (zoomTransformRef.current !== d3.zoomIdentity) {
      svg.call(zoom.transform, zoomTransformRef.current);
    }

    /* Simulation data */
    const simNodes: SimNode[] = filteredNodes.map((n) => ({ data: n }));
    const nodeMap = new Map(simNodes.map((n) => [n.data.task_id, n]));

    const simLinks: SimLink[] = filteredEdges
      .map((e) => {
        const source = nodeMap.get(e.source);
        const target = nodeMap.get(e.target);
        if (!source || !target) return null;
        return { source, target, relationship: e.relationship } as SimLink;
      })
      .filter(Boolean) as SimLink[];

    /* Force simulation */
    const simulation = d3
      .forceSimulation<SimNode>(simNodes)
      .force(
        'link',
        d3
          .forceLink<SimNode, SimLink>(simLinks)
          .id((d) => d.data.task_id)
          .distance(100),
      )
      .force('charge', d3.forceManyBody().strength(-120))
      .force('center', d3.forceCenter(width / 2, height / 2).strength(0.03))
      .force('collision', d3.forceCollide(30));

    simulationRef.current = simulation;

    /* Links */
    const linkSel = g
      .selectAll<SVGLineElement, SimLink>('line')
      .data(simLinks)
      .join('line')
      .attr('stroke', theme.palette.divider)
      .attr('stroke-width', 1.5)
      .attr('marker-end', 'url(#arrowhead)');

    /* Node groups */
    const nodeSel = g
      .selectAll<SVGGElement, SimNode>('g.node')
      .data(simNodes)
      .join('g')
      .attr('class', 'node')
      .style('cursor', 'pointer')
      .on('click', (_event, d) => {
        onNodeClick(d.data);
      })
      .call(
        d3
          .drag<SVGGElement, SimNode>()
          .on('start', (event, d) => {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
          })
          .on('drag', (event, d) => {
            d.fx = event.x;
            d.fy = event.y;
          })
          .on('end', (event, d) => {
            if (!event.active) simulation.alphaTarget(0);
            // Keep node pinned where it was dropped
            d.fx = d.x;
            d.fy = d.y;
          }),
      );

    /* Circle */
    nodeSel
      .append('circle')
      .attr('r', 14)
      .attr('fill', (d) => colorMap[d.data.status] ?? theme.palette.grey[400])
      .attr('stroke', theme.palette.background.paper)
      .attr('stroke-width', 2);

    /* Label */
    nodeSel
      .append('text')
      .attr('dy', 28)
      .attr('text-anchor', 'middle')
      .attr('font-size', 10)
      .attr('fill', theme.palette.text.primary)
      .text((d) => {
        const desc = d.data.description ?? d.data.task_id;
        const label = desc.length > 20 ? desc.slice(0, 18) + '...' : desc;
        return d.data.agent_name ? `${label} (${d.data.agent_name})` : label;
      });

    /* Tick */
    simulation.on('tick', () => {
      linkSel
        .attr('x1', (d) => (d.source as SimNode).x ?? 0)
        .attr('y1', (d) => (d.source as SimNode).y ?? 0)
        .attr('x2', (d) => (d.target as SimNode).x ?? 0)
        .attr('y2', (d) => (d.target as SimNode).y ?? 0);

      nodeSel.attr('transform', (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
    });

    /* Expose zoom for external controls */
    (container as unknown as Record<string, unknown>).__d3Zoom = zoom;
    (container as unknown as Record<string, unknown>).__d3Svg = svg;
  }, [filteredNodes, filteredEdges, colorMap, onNodeClick, theme]);

  useEffect(() => {
    buildGraph();
    return () => {
      simulationRef.current?.stop();
    };
  }, [buildGraph]);

  /* Resize observer */
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const observer = new ResizeObserver(() => {
      buildGraph();
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, [buildGraph]);

  return (
    <Box
      ref={containerRef}
      sx={{
        width: '100%',
        height: '100%',
        minHeight: 400,
        bgcolor: 'background.default',
      }}
    />
  );
};

export default TaskGraphCanvas;
