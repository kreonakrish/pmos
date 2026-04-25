import React, { useRef, useEffect, useCallback } from 'react';
import { Box, useTheme } from '@mui/material';
import * as d3 from 'd3';
import {
  categorizeSchemaNode,
  useSchemaCategoryColorMap,
} from './SchemaGraphCanvas';
import type {
  OntologySubgraphNode,
  OntologySubgraphEdge,
} from '@/api/translator';

interface Props {
  nodes: OntologySubgraphNode[];
  edges: OntologySubgraphEdge[];
  height?: number;
}

interface SimNode extends d3.SimulationNodeDatum {
  data: OntologySubgraphNode;
}

interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  type: string;
}

/**
 * A slimmed-down sibling of SchemaGraphCanvas designed for displaying the
 * small (~5-15 node) ontology subgraph used to translate one question.
 *
 * Differences vs. SchemaGraphCanvas:
 *   - No zoom controls (read-only static view).
 *   - No drag — simulation positions are accepted as-is.
 *   - No click handlers / drawer integration.
 *   - Smaller default height (~300 px).
 */
const TranslationSubgraphCanvas: React.FC<Props> = ({
  nodes,
  edges,
  height = 300,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const simulationRef = useRef<d3.Simulation<SimNode, SimLink> | null>(null);
  const colorMap = useSchemaCategoryColorMap();
  const theme = useTheme();

  const buildGraph = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;

    const width = container.clientWidth;
    const h = container.clientHeight || height;

    /* Clear previous */
    d3.select(container).select('svg').remove();

    if (nodes.length === 0) return;

    const svg = d3
      .select(container)
      .append('svg')
      .attr('width', width)
      .attr('height', h);

    /* Arrow marker */
    svg
      .append('defs')
      .append('marker')
      .attr('id', 'translation-arrowhead')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 18)
      .attr('refY', 0)
      .attr('markerWidth', 5)
      .attr('markerHeight', 5)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-5L10,0L0,5')
      .attr('fill', theme.palette.text.secondary);

    const g = svg.append('g');

    /* Simulation data — drop edges with missing endpoints */
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

    /* Force simulation tuned for small graphs */
    const simulation = d3
      .forceSimulation<SimNode>(simNodes)
      .force(
        'link',
        d3
          .forceLink<SimNode, SimLink>(simLinks)
          .id((d) => d.data.id)
          .distance(80),
      )
      .force('charge', d3.forceManyBody().strength(-160))
      .force('center', d3.forceCenter(width / 2, h / 2).strength(0.08))
      .force('collision', d3.forceCollide(28));

    simulationRef.current = simulation;

    /* Links */
    const linkGroup = g.append('g').attr('class', 'translation-links');

    const linkSel = linkGroup
      .selectAll<SVGLineElement, SimLink>('line')
      .data(simLinks)
      .join('line')
      .attr('stroke', theme.palette.divider)
      .attr('stroke-width', 1.25)
      .attr('marker-end', 'url(#translation-arrowhead)');

    /* Edge labels (relationship type) */
    const linkLabelSel = linkGroup
      .selectAll<SVGTextElement, SimLink>('text')
      .data(simLinks)
      .join('text')
      .attr('text-anchor', 'middle')
      .attr('font-size', 8)
      .attr('fill', theme.palette.text.secondary)
      .attr('pointer-events', 'none')
      .text((d) => d.type ?? '');

    /* Node groups (no drag, no click) */
    const nodeSel = g
      .append('g')
      .attr('class', 'translation-nodes')
      .selectAll<SVGGElement, SimNode>('g.node')
      .data(simNodes)
      .join('g')
      .attr('class', 'node');

    /* Circle */
    nodeSel
      .append('circle')
      .attr('r', 12)
      .attr('fill', (d) => colorMap[categorizeSchemaNode(d.data.label)])
      .attr('stroke', theme.palette.background.paper)
      .attr('stroke-width', 1.5);

    /* Node id label (truncated for visibility) */
    nodeSel
      .append('text')
      .attr('dy', 24)
      .attr('text-anchor', 'middle')
      .attr('font-size', 10)
      .attr('font-weight', 600)
      .attr('fill', theme.palette.text.primary)
      .text((d) => {
        const id = d.data.id ?? '';
        return id.length > 18 ? `${id.slice(0, 17)}…` : id;
      });

    /* Tick */
    simulation.on('tick', () => {
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
          return (sy + ty) / 2 - 3;
        });

      nodeSel.attr('transform', (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
    });
  }, [nodes, edges, colorMap, theme, height]);

  useEffect(() => {
    buildGraph();
    return () => {
      simulationRef.current?.stop();
    };
  }, [buildGraph]);

  /* Resize observer — rebuild on container resize */
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
        height,
        bgcolor: 'background.default',
        borderRadius: 1,
      }}
    />
  );
};

export default TranslationSubgraphCanvas;
