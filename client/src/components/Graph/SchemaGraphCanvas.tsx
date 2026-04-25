import React, { useRef, useEffect, useCallback } from 'react';
import { Box, useTheme } from '@mui/material';
import * as d3 from 'd3';
import type { SchemaNode, SchemaEdge } from '@/api/schemaGraph';

type ZoomTransform = d3.ZoomTransform;

interface Props {
  nodes: SchemaNode[];
  edges: SchemaEdge[];
  onNodeClick: (node: SchemaNode) => void;
}

interface SimNode extends d3.SimulationNodeDatum {
  data: SchemaNode;
}

interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  type: string;
}

/**
 * Schema-graph node category. Drives node color and is also exported so the
 * page can render a matching legend.
 */
export type SchemaNodeCategory =
  | 'BusinessDomain'
  | 'BusinessEntity'
  | 'BusinessAttribute'
  | 'DataSource'
  | 'DataAsset'
  | 'DataColumn'
  | 'Tool'
  | 'TaskNode'
  | 'TaskGraph'
  | 'ExecutionEvent'
  | 'other';

export const SCHEMA_NODE_CATEGORIES: SchemaNodeCategory[] = [
  'BusinessDomain',
  'BusinessEntity',
  'BusinessAttribute',
  'DataSource',
  'DataAsset',
  'DataColumn',
  'Tool',
  'TaskNode',
  'TaskGraph',
  'ExecutionEvent',
  'other',
];

export function categorizeSchemaNode(label: string): SchemaNodeCategory {
  switch (label) {
    case 'BusinessDomain':
    case 'BusinessEntity':
    case 'BusinessAttribute':
    case 'DataSource':
    case 'DataAsset':
    case 'DataColumn':
    case 'Tool':
    case 'TaskNode':
    case 'TaskGraph':
    case 'ExecutionEvent':
      return label;
    default:
      return 'other';
  }
}

/**
 * Returns a theme-based color for each schema node category. Uses MUI palette
 * tokens so the graph adapts to light/dark mode and matches the rest of the
 * app.
 */
export function useSchemaCategoryColorMap(): Record<SchemaNodeCategory, string> {
  const theme = useTheme();
  return {
    // Business ontology — primary/secondary family
    BusinessDomain: theme.palette.primary.main,
    BusinessEntity: theme.palette.primary.light,
    BusinessAttribute: theme.palette.secondary.main,
    // Physical data — info family
    DataSource: theme.palette.info.dark,
    DataAsset: theme.palette.info.main,
    DataColumn: theme.palette.info.light,
    // Tooling — success
    Tool: theme.palette.success.main,
    // Execution graph — warning family
    TaskNode: theme.palette.warning.main,
    TaskGraph: theme.palette.warning.dark,
    ExecutionEvent: theme.palette.warning.light,
    // Anything else
    other: theme.palette.grey[500],
  };
}

const SchemaGraphCanvas: React.FC<Props> = ({ nodes, edges, onNodeClick }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const simulationRef = useRef<d3.Simulation<SimNode, SimLink> | null>(null);
  const zoomTransformRef = useRef<ZoomTransform>(d3.zoomIdentity);
  const colorMap = useSchemaCategoryColorMap();
  const theme = useTheme();

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
      .attr('id', 'schema-arrowhead')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 22)
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

    if (zoomTransformRef.current !== d3.zoomIdentity) {
      svg.call(zoom.transform, zoomTransformRef.current);
    }

    /* Simulation data — drop edges with missing endpoints (e.g. APOC fallback) */
    const simNodes: SimNode[] = nodes.map((n) => ({ data: n }));
    const nodeMap = new Map(simNodes.map((n) => [n.data.id, n]));

    const simLinks: SimLink[] = edges
      .map((e) => {
        if (!e.from || !e.to) return null;
        const source = nodeMap.get(e.from);
        const target = nodeMap.get(e.to);
        if (!source || !target) return null;
        return { source, target, type: e.type } as SimLink;
      })
      .filter(Boolean) as SimLink[];

    /* Force simulation — runs once to lay things out, then we freeze every
     * node so the user can drag freely and inspect a region without the
     * rest of the graph snapping back. */
    const simulation = d3
      .forceSimulation<SimNode>(simNodes)
      .force(
        'link',
        d3
          .forceLink<SimNode, SimLink>(simLinks)
          .id((d) => d.data.id)
          .distance(140),
      )
      .force('charge', d3.forceManyBody().strength(-260))
      .force('center', d3.forceCenter(width / 2, height / 2).strength(0.04))
      .force('collision', d3.forceCollide(40))
      // Settle faster — we only need an initial layout, then we freeze.
      .alphaDecay(0.05);

    simulationRef.current = simulation;

    /* Links */
    const linkGroup = g.append('g').attr('class', 'schema-links');

    const linkSel = linkGroup
      .selectAll<SVGLineElement, SimLink>('line')
      .data(simLinks)
      .join('line')
      .attr('stroke', theme.palette.divider)
      .attr('stroke-width', 1.5)
      .attr('marker-end', 'url(#schema-arrowhead)');

    /* Edge labels (relationship type) */
    const linkLabelSel = linkGroup
      .selectAll<SVGTextElement, SimLink>('text')
      .data(simLinks)
      .join('text')
      .attr('text-anchor', 'middle')
      .attr('font-size', 9)
      .attr('fill', theme.palette.text.secondary)
      .attr('pointer-events', 'none')
      .text((d) => d.type ?? '');

    /* Node groups */
    const nodeSel = g
      .append('g')
      .attr('class', 'schema-nodes')
      .selectAll<SVGGElement, SimNode>('g.node')
      .data(simNodes)
      .join('g')
      .attr('class', 'node')
      .style('cursor', 'grab')
      .on('click', (_event, d) => {
        onNodeClick(d.data);
      })
      .call(
        d3
          .drag<SVGGElement, SimNode>()
          // Keep the entire layout frozen while one node is being moved —
          // no `simulation.restart()`, no alphaTarget bumps. The dragged
          // node moves freely; everyone else stays exactly where they were.
          .on('start', function (_event, d) {
            d3.select(this).style('cursor', 'grabbing');
            d.fx = d.x ?? 0;
            d.fy = d.y ?? 0;
          })
          .on('drag', (event, d) => {
            d.fx = event.x;
            d.fy = event.y;
            // Re-render this node + its incident links manually since the
            // simulation is frozen (no auto-tick).
            ticked();
          })
          .on('end', function (_event, d) {
            d3.select(this).style('cursor', 'grab');
            // Pin the new position permanently so the layout never
            // "remembers" the original gravity-driven spot.
            d.fx = d.x ?? 0;
            d.fy = d.y ?? 0;
          }),
      );

    /* Circle */
    nodeSel
      .append('circle')
      .attr('r', 18)
      .attr('fill', (d) => colorMap[categorizeSchemaNode(d.data.label)])
      .attr('stroke', theme.palette.background.paper)
      .attr('stroke-width', 2);

    /* Label */
    nodeSel
      .append('text')
      .attr('dy', 34)
      .attr('text-anchor', 'middle')
      .attr('font-size', 11)
      .attr('font-weight', 600)
      .attr('fill', theme.palette.text.primary)
      .text((d) => d.data.label);

    /* Tick — extracted so drag handlers can rerun it while the simulation
     * is frozen (single-node moves shouldn't restart global forces). */
    function ticked() {
      linkSel
        .attr('x1', (d) => (d.source as SimNode).x ?? 0)
        .attr('y1', (d) => (d.source as SimNode).y ?? 0)
        .attr('x2', (d) => (d.target as SimNode).x ?? 0)
        .attr('y2', (d) => (d.target as SimNode).y ?? 0);

      linkLabelSel
        .attr('x', (d) => {
          const sx = (d.source as SimNode).x ?? 0;
          const tx = (d.target as SimNode).x ?? 0;
          return (sx + tx) / 2;
        })
        .attr('y', (d) => {
          const sy = (d.source as SimNode).y ?? 0;
          const ty = (d.target as SimNode).y ?? 0;
          return (sy + ty) / 2 - 4;
        });

      nodeSel.attr('transform', (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
    }

    simulation.on('tick', ticked);

    // Once the initial layout settles, freeze every node in place. From
    // here forward the only motion comes from the user dragging a node,
    // and only THAT node moves — the rest of the schema stays put so the
    // user can inspect neighborhoods without losing context.
    simulation.on('end', () => {
      simNodes.forEach((n) => {
        n.fx = n.x ?? 0;
        n.fy = n.y ?? 0;
      });
      ticked();
    });

    /* Expose zoom for external controls */
    (container as unknown as Record<string, unknown>).__d3Zoom = zoom;
    (container as unknown as Record<string, unknown>).__d3Svg = svg;
  }, [nodes, edges, colorMap, onNodeClick, theme]);

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

export default SchemaGraphCanvas;
