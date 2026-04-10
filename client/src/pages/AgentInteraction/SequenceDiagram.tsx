import React, { useRef, useEffect, useCallback, useMemo } from 'react';
import { Box, useTheme } from '@mui/material';
import * as d3 from 'd3';
import type { AgentInteraction } from '@/types';

/* ---- Props ---- */

interface Props {
  interactions: AgentInteraction[];
  participants: string[];
  onInteractionSelect: (interaction: AgentInteraction) => void;
  selectedId?: string;
}

/* ---- Constants ---- */

const LANE_WIDTH = 140;
const ROW_HEIGHT = 52;
const HEADER_HEIGHT = 60;
const PADDING_X = 40;
const PADDING_Y = 20;
const ARROW_HEAD_SIZE = 6;

/* ---- Interaction type -> color mapping ---- */

interface TypeStyle {
  color: string;
  dashed: boolean;
}

function useTypeStyles(): Record<string, TypeStyle> {
  const theme = useTheme();
  return useMemo(
    () => ({
      task_assignment: { color: theme.palette.info.main, dashed: false },
      tool_call: { color: theme.palette.success.main, dashed: false },
      tool_result: { color: theme.palette.success.light, dashed: true },
      score_evaluation: { color: theme.palette.warning.main, dashed: false },
      score_request: { color: theme.palette.warning.main, dashed: false },
      course_correction: { color: theme.palette.warning.dark, dashed: false },
      memory_read: { color: '#ab47bc', dashed: false },
      memory_write: { color: '#ab47bc', dashed: true },
      rag_query: { color: '#ab47bc', dashed: false },
      error: { color: theme.palette.error.main, dashed: false },
      fallback: { color: theme.palette.error.light, dashed: true },
      sub_agent_spawn: { color: '#ff7043', dashed: false },
      sub_agent_result: { color: '#ff7043', dashed: true },
    }),
    [theme],
  );
}

/* ---- Component ---- */

const SequenceDiagram: React.FC<Props> = ({
  interactions,
  participants,
  onInteractionSelect,
  selectedId,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const theme = useTheme();
  const typeStyles = useTypeStyles();

  const getStyle = useCallback(
    (type: string): TypeStyle => typeStyles[type] ?? { color: theme.palette.text.secondary, dashed: false },
    [typeStyles, theme],
  );

  useEffect(() => {
    if (!containerRef.current || participants.length === 0) return;

    const container = containerRef.current;
    d3.select(container).select('svg').remove();

    const totalWidth = participants.length * LANE_WIDTH + PADDING_X * 2;
    const totalHeight = HEADER_HEIGHT + interactions.length * ROW_HEIGHT + PADDING_Y * 2;

    const svg = d3
      .select(container)
      .append('svg')
      .attr('width', totalWidth)
      .attr('height', totalHeight);

    // Arrow markers for each type
    const defs = svg.append('defs');
    const usedTypes = new Set(interactions.map((i) => i.type));
    for (const t of usedTypes) {
      const style = getStyle(t);
      defs
        .append('marker')
        .attr('id', `arrow-${t}`)
        .attr('viewBox', '0 0 10 10')
        .attr('refX', 9)
        .attr('refY', 5)
        .attr('markerWidth', ARROW_HEAD_SIZE)
        .attr('markerHeight', ARROW_HEAD_SIZE)
        .attr('orient', 'auto')
        .append('path')
        .attr('d', 'M 0 0 L 10 5 L 0 10 z')
        .attr('fill', style.color);
    }

    const laneX = (idx: number) => PADDING_X + idx * LANE_WIDTH + LANE_WIDTH / 2;
    const participantIndex = new Map(participants.map((p, i) => [p, i]));

    // Header boxes
    const headerGroup = svg.append('g');
    participants.forEach((p, i) => {
      const x = laneX(i);
      headerGroup
        .append('rect')
        .attr('x', x - LANE_WIDTH / 2 + 8)
        .attr('y', 8)
        .attr('width', LANE_WIDTH - 16)
        .attr('height', 36)
        .attr('rx', 6)
        .attr('fill', theme.palette.background.paper)
        .attr('stroke', theme.palette.divider)
        .attr('stroke-width', 1);

      headerGroup
        .append('text')
        .attr('x', x)
        .attr('y', 30)
        .attr('text-anchor', 'middle')
        .attr('font-size', 11)
        .attr('font-weight', 600)
        .attr('fill', theme.palette.text.primary)
        .text(p.length > 14 ? p.slice(0, 13) + '\u2026' : p);
    });

    // Vertical lifelines
    participants.forEach((_, i) => {
      const x = laneX(i);
      svg
        .append('line')
        .attr('x1', x)
        .attr('y1', HEADER_HEIGHT)
        .attr('x2', x)
        .attr('y2', totalHeight - PADDING_Y)
        .attr('stroke', theme.palette.divider)
        .attr('stroke-width', 1)
        .attr('stroke-dasharray', '4,3');
    });

    // Interaction arrows
    const arrowGroup = svg.append('g');
    interactions.forEach((interaction, rowIdx) => {
      const y = HEADER_HEIGHT + PADDING_Y + rowIdx * ROW_HEIGHT + ROW_HEIGHT / 2;
      const fromIdx = participantIndex.get(interaction.from_service) ?? 0;
      const toIdx = participantIndex.get(interaction.to_service) ?? 0;
      const x1 = laneX(fromIdx);
      const x2 = laneX(toIdx);
      const style = getStyle(interaction.type);
      const isSelected = interaction.id === selectedId;
      const isSelfCall = fromIdx === toIdx;

      const rowGroup = arrowGroup
        .append('g')
        .style('cursor', 'pointer')
        .on('click', () => onInteractionSelect(interaction));

      // Hover highlight rect
      rowGroup
        .append('rect')
        .attr('x', PADDING_X)
        .attr('y', y - ROW_HEIGHT / 2)
        .attr('width', totalWidth - PADDING_X * 2)
        .attr('height', ROW_HEIGHT)
        .attr('fill', isSelected ? theme.palette.action.selected : 'transparent')
        .attr('rx', 4)
        .on('mouseenter', function () {
          d3.select(this).attr('fill', theme.palette.action.hover);
        })
        .on('mouseleave', function () {
          d3.select(this).attr('fill', isSelected ? theme.palette.action.selected : 'transparent');
        });

      if (isSelfCall) {
        // Self-call: draw a loop
        const loopW = 30;
        const loopH = 16;
        rowGroup
          .append('path')
          .attr('d', `M ${x1} ${y - loopH} L ${x1 + loopW} ${y - loopH} L ${x1 + loopW} ${y + loopH} L ${x1} ${y + loopH}`)
          .attr('fill', 'none')
          .attr('stroke', style.color)
          .attr('stroke-width', isSelected ? 2.5 : 1.5)
          .attr('stroke-dasharray', style.dashed ? '5,3' : 'none')
          .attr('marker-end', `url(#arrow-${interaction.type})`);
      } else {
        // Horizontal arrow
        rowGroup
          .append('line')
          .attr('x1', x1)
          .attr('y1', y)
          .attr('x2', x2)
          .attr('y2', y)
          .attr('stroke', style.color)
          .attr('stroke-width', isSelected ? 2.5 : 1.5)
          .attr('stroke-dasharray', style.dashed ? '5,3' : 'none')
          .attr('marker-end', `url(#arrow-${interaction.type})`);
      }

      // Label
      const midX = isSelfCall ? x1 + 35 : (x1 + x2) / 2;
      const labelY = isSelfCall ? y : y - 6;
      const summaryText = interaction.summary ?? interaction.type;
      rowGroup
        .append('text')
        .attr('x', midX)
        .attr('y', labelY)
        .attr('text-anchor', 'middle')
        .attr('font-size', 9)
        .attr('fill', style.color)
        .text(summaryText.length > 30 ? summaryText.slice(0, 29) + '\u2026' : summaryText);

      // Duration badge
      if (interaction.duration_ms != null) {
        const badgeX = isSelfCall ? x1 + 35 : (x1 + x2) / 2;
        const badgeY = isSelfCall ? y + 12 : y + 8;
        rowGroup
          .append('text')
          .attr('x', badgeX)
          .attr('y', badgeY)
          .attr('text-anchor', 'middle')
          .attr('font-size', 8)
          .attr('fill', theme.palette.text.secondary)
          .text(`${interaction.duration_ms}ms`);
      }

      // Timestamp
      const ts = new Date(interaction.timestamp);
      const timeStr = ts.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      rowGroup
        .append('text')
        .attr('x', PADDING_X - 4)
        .attr('y', y + 3)
        .attr('text-anchor', 'end')
        .attr('font-size', 8)
        .attr('fill', theme.palette.text.secondary)
        .text(timeStr);
    });

    return () => {
      d3.select(container).select('svg').remove();
    };
  }, [interactions, participants, selectedId, theme, getStyle, onInteractionSelect]);

  return (
    <Box
      ref={containerRef}
      sx={{
        width: '100%',
        height: '100%',
        overflow: 'auto',
        bgcolor: 'background.default',
      }}
    />
  );
};

export default SequenceDiagram;
