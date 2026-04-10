import React, { useRef, useEffect, useCallback } from 'react';
import { Box, useTheme } from '@mui/material';
import * as d3 from 'd3';
import type { TaskNode } from '@/types';

/* ---- Props ---- */

interface Props {
  nodes: TaskNode[];
  edges: Array<{ source: string; target: string; label: string }>;
  onNodeSelect: (node: TaskNode) => void;
  selectedNodeId?: string;
}

/* ---- Constants ---- */

const NODE_RX = 8;
const NODE_WIDTH = 180;
const NODE_HEIGHT = 52;
const LABEL_MAX = 28;

function truncate(text: string, max: number): string {
  return text.length > max ? text.slice(0, max - 1) + '\u2026' : text;
}

/* ---- Simulation types ---- */

interface SimNode extends d3.SimulationNodeDatum {
  data: TaskNode;
  /** true when the user has manually pinned this node via drag */
  pinned?: boolean;
}

interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  label: string;
}

/* ---- Component ---- */

const DecompositionTree: React.FC<Props> = ({ nodes, edges, onNodeSelect, selectedNodeId }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const simulationRef = useRef<d3.Simulation<SimNode, SimLink> | null>(null);
  const zoomTransformRef = useRef<d3.ZoomTransform | null>(null);
  /** Keep track of pinned positions across rebuilds keyed by task_id */
  const pinnedPositionsRef = useRef<Map<string, { x: number; y: number }>>(new Map());
  const theme = useTheme();

  const statusColor = useCallback(
    (status: string): string => {
      switch (status) {
        case 'PENDING':
          return theme.palette.grey[500];
        case 'RUNNING':
          return theme.palette.info.main;
        case 'SUCCESS':
          return theme.palette.success.main;
        case 'FAILED':
          return theme.palette.error.main;
        case 'CORRECTING':
          return theme.palette.warning.main;
        case 'SKIPPED':
          return theme.palette.grey[400];
        default:
          return theme.palette.grey[500];
      }
    },
    [theme],
  );

  useEffect(() => {
    if (!containerRef.current || nodes.length === 0) return;

    const container = containerRef.current;
    const width = container.clientWidth;
    const height = container.clientHeight;

    // Stop previous simulation
    simulationRef.current?.stop();

    // Clear previous SVG
    d3.select(container).select('svg').remove();

    const svg = d3
      .select(container)
      .append('svg')
      .attr('width', width)
      .attr('height', height);

    const g = svg.append('g');

    // Arrow marker
    svg
      .append('defs')
      .append('marker')
      .attr('id', 'decomp-arrow')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 22)
      .attr('refY', 0)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-5L10,0L0,5')
      .attr('fill', theme.palette.text.secondary);

    // Build simulation data
    const pinned = pinnedPositionsRef.current;
    const simNodes: SimNode[] = nodes.map((n) => {
      const pin = pinned.get(n.task_id);
      return {
        data: n,
        x: pin?.x ?? width / 2 + (Math.random() - 0.5) * 200,
        y: pin?.y ?? height / 2 + (Math.random() - 0.5) * 200,
        fx: pin?.x ?? undefined,
        fy: pin?.y ?? undefined,
        pinned: !!pin,
      };
    });
    const nodeMap = new Map(simNodes.map((n) => [n.data.task_id, n]));

    // edges: source SPAWNED_BY target => draw arrow from target (parent) to source (child)
    const simLinks: SimLink[] = edges
      .map((e) => {
        const source = nodeMap.get(e.target); // parent
        const target = nodeMap.get(e.source); // child
        if (!source || !target) return null;
        return { source, target, label: e.label } as SimLink;
      })
      .filter(Boolean) as SimLink[];

    // Determine root nodes for hierarchical initial layout push
    const childSet = new Set(edges.map((e) => e.source));
    const rootIds = new Set(nodes.filter((n) => !childSet.has(n.task_id)).map((n) => n.task_id));

    // Force simulation — gentler forces for interactive exploration
    const simulation = d3
      .forceSimulation<SimNode>(simNodes)
      .force(
        'link',
        d3
          .forceLink<SimNode, SimLink>(simLinks)
          .id((d) => d.data.task_id)
          .distance(140)
          .strength(0.6),
      )
      .force('charge', d3.forceManyBody().strength(-250))
      .force('center', d3.forceCenter(width / 2, height / 2).strength(0.02))
      .force('collision', d3.forceCollide(50))
      .force(
        'y',
        d3.forceY<SimNode>((d) => {
          // Push root nodes toward top, deeper nodes further down
          return 80 + d.data.depth * 120;
        }).strength(0.15),
      )
      .alphaDecay(0.03);

    simulationRef.current = simulation;

    // Links
    const linkSel = g
      .selectAll<SVGLineElement, SimLink>('line.link')
      .data(simLinks)
      .join('line')
      .attr('class', 'link')
      .attr('stroke', theme.palette.divider)
      .attr('stroke-width', 1.5)
      .attr('marker-end', 'url(#decomp-arrow)');

    // Edge labels
    const edgeLabelSel = g
      .selectAll<SVGTextElement, SimLink>('text.edge-label')
      .data(simLinks)
      .join('text')
      .attr('class', 'edge-label')
      .attr('text-anchor', 'middle')
      .attr('font-size', 8)
      .attr('fill', theme.palette.text.secondary)
      .attr('opacity', 0.6)
      .text((d) => d.label);

    // Node groups
    const nodeSel = g
      .selectAll<SVGGElement, SimNode>('g.node')
      .data(simNodes)
      .join('g')
      .attr('class', 'node')
      .style('cursor', 'pointer')
      .on('click', (_event, d) => {
        onNodeSelect(d.data);
      })
      .call(
        d3
          .drag<SVGGElement, SimNode>()
          .on('start', (event, d) => {
            if (!event.active) simulation.alphaTarget(0.15).restart();
            d.fx = d.x;
            d.fy = d.y;
          })
          .on('drag', (event, d) => {
            d.fx = event.x;
            d.fy = event.y;
          })
          .on('end', (event, d) => {
            if (!event.active) simulation.alphaTarget(0);
            // Keep node pinned where dropped
            d.fx = d.x;
            d.fy = d.y;
            d.pinned = true;
            pinnedPositionsRef.current.set(d.data.task_id, { x: d.x!, y: d.y! });
          }),
      );

    // Double-click to unpin
    nodeSel.on('dblclick', (_event, d) => {
      d.fx = null;
      d.fy = null;
      d.pinned = false;
      pinnedPositionsRef.current.delete(d.data.task_id);
      simulation.alpha(0.3).restart();
    });

    // Node rectangle
    nodeSel
      .append('rect')
      .attr('x', -NODE_WIDTH / 2)
      .attr('y', -NODE_HEIGHT / 2)
      .attr('width', NODE_WIDTH)
      .attr('height', NODE_HEIGHT)
      .attr('rx', NODE_RX)
      .attr('ry', NODE_RX)
      .attr('fill', (d) => {
        const c = statusColor(d.data.status);
        return c + '22';
      })
      .attr('stroke', (d) => {
        if (d.data.task_id === selectedNodeId) return theme.palette.primary.main;
        return statusColor(d.data.status);
      })
      .attr('stroke-width', (d) => (d.data.task_id === selectedNodeId ? 2.5 : 1.5))
      .attr('stroke-dasharray', (d) => (d.data.status === 'SKIPPED' ? '5,3' : 'none'));

    // Root node special styling
    nodeSel
      .filter((d) => rootIds.has(d.data.task_id))
      .select('rect')
      .attr('fill', theme.palette.primary.dark + '30')
      .attr('stroke', theme.palette.primary.main)
      .attr('stroke-width', 2);

    // Status dot
    nodeSel
      .append('circle')
      .attr('cx', -NODE_WIDTH / 2 + 14)
      .attr('cy', 0)
      .attr('r', 5)
      .attr('fill', (d) => statusColor(d.data.status));

    // Pin indicator
    nodeSel
      .filter((d) => d.pinned === true)
      .append('circle')
      .attr('class', 'pin-indicator')
      .attr('cx', NODE_WIDTH / 2 - 10)
      .attr('cy', -NODE_HEIGHT / 2 + 10)
      .attr('r', 3)
      .attr('fill', theme.palette.warning.main);

    // Label text — description
    nodeSel
      .append('text')
      .attr('x', -NODE_WIDTH / 2 + 26)
      .attr('y', -4)
      .attr('font-size', 11)
      .attr('font-weight', 500)
      .attr('fill', theme.palette.text.primary)
      .text((d) => truncate(d.data.description, LABEL_MAX));

    // Subtitle — status + agent
    nodeSel
      .append('text')
      .attr('x', -NODE_WIDTH / 2 + 26)
      .attr('y', 12)
      .attr('font-size', 9)
      .attr('fill', theme.palette.text.secondary)
      .text((d) => {
        const tn = d.data as unknown as Record<string, unknown>;
        const agentName = (tn.assigned_agent_name || tn.agent_name || '') as string;
        const bidConf = tn.bid_confidence != null ? ` (${(Number(tn.bid_confidence) * 100).toFixed(0)}%)` : '';
        const agentLabel = agentName ? ` | ${agentName}${bidConf}` : '';
        return `${d.data.status || 'PENDING'}${agentLabel}`;
      });

    // Tick
    simulation.on('tick', () => {
      linkSel
        .attr('x1', (d) => (d.source as SimNode).x ?? 0)
        .attr('y1', (d) => (d.source as SimNode).y ?? 0)
        .attr('x2', (d) => (d.target as SimNode).x ?? 0)
        .attr('y2', (d) => (d.target as SimNode).y ?? 0);

      edgeLabelSel
        .attr('x', (d) => (((d.source as SimNode).x ?? 0) + ((d.target as SimNode).x ?? 0)) / 2)
        .attr('y', (d) => (((d.source as SimNode).y ?? 0) + ((d.target as SimNode).y ?? 0)) / 2 - 6);

      nodeSel.attr('transform', (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
    });

    // Zoom — persist across rebuilds
    const zoomBehavior = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.15, 4])
      .on('zoom', (event) => {
        zoomTransformRef.current = event.transform;
        g.attr('transform', event.transform.toString());
      });

    svg.call(zoomBehavior);

    if (zoomTransformRef.current) {
      svg.call(zoomBehavior.transform, zoomTransformRef.current);
    }

    // Expose for external zoom controls
    const containerEl = container as unknown as Record<string, unknown>;
    containerEl.__d3Zoom = zoomBehavior;
    containerEl.__d3Svg = svg;

    return () => {
      simulation.stop();
      d3.select(container).select('svg').remove();
    };
  }, [nodes, edges, selectedNodeId, theme, statusColor, onNodeSelect]);

  return (
    <Box
      ref={containerRef}
      sx={{
        width: '100%',
        height: '100%',
        overflow: 'hidden',
        bgcolor: 'background.default',
        borderRadius: 1,
      }}
    />
  );
};

export default DecompositionTree;
