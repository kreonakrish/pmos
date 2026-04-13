import { useState, useCallback, useRef } from 'react';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  addEdge,
  type Connection,
  type Edge,
  type Node,
  type NodeTypes,
  MarkerType,
  BackgroundVariant,
  type OnConnect,
} from 'reactflow';
import 'reactflow/dist/style.css';
import {
  Box,
  Typography,
  TextField,
  Button,
  IconButton,
  Drawer,
  Grid,
  Card,
  CardContent,
  CardActionArea,
  Chip,
  Stack,
  Tooltip,
  Divider,
  useTheme,
} from '@mui/material';
import SaveIcon from '@mui/icons-material/Save';
import DeleteIcon from '@mui/icons-material/Delete';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import FileDownloadIcon from '@mui/icons-material/FileDownload';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import AddIcon from '@mui/icons-material/Add';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import OrchestratorNode from './nodes/OrchestratorNode';
import SpecialistNode from './nodes/SpecialistNode';
import FallbackNode from './nodes/FallbackNode';
import HierarchyRulesPanel, { type NodeRules } from './HierarchyRulesPanel';
import TeamValidation from './TeamValidation';
import type { Team, Agent } from '@/types';

const nodeTypes: NodeTypes = {
  orchestratorNode: OrchestratorNode,
  specialistNode: SpecialistNode,
  fallbackNode: FallbackNode,
};

interface TeamCanvasProps {
  team: Team | null;
  agents: Agent[];
  isLoading: boolean;
  onSave: (team: Partial<Team>, nodes: Node[], edges: Edge[]) => void;
  onDelete: () => void;
  onDuplicate: () => void;
}

const DEFAULT_NODE_RULES: NodeRules = {
  executionMode: 'sequential',
  condition: '',
  maxRetries: 3,
  criticality: 'MEDIUM',
  timeout: 30,
  fallbackAgentId: null,
};

let nodeIdCounter = 0;
function getNextNodeId() {
  nodeIdCounter += 1;
  return `node-${Date.now()}-${nodeIdCounter}`;
}

export default function TeamCanvas({
  team,
  agents,
  isLoading,
  onSave,
  onDelete,
  onDuplicate,
}: TeamCanvasProps) {
  const theme = useTheme();
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  // Stable callback refs — avoids re-rendering nodes when callbacks change
  const cbRef = useRef<Record<string, (...args: unknown[]) => void>>({});

  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [teamName, setTeamName] = useState(team?.name ?? 'Untitled Team');
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [rulesPanelOpen, setRulesPanelOpen] = useState(false);
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [nodeRulesMap, setNodeRulesMap] = useState<Record<string, NodeRules>>({});

  // Stable callback wrappers that always delegate to the latest implementation via ref
  const stableCbs = useRef({
    onAgentChange: (nodeId: string, agentId: number) => cbRef.current.onAgentChange?.(nodeId, agentId),
    onRemove: (nodeId: string) => cbRef.current.onRemove?.(nodeId),
    onAddChild: (nodeId: string) => cbRef.current.onAddChild?.(nodeId),
    onSetFallback: (nodeId: string) => cbRef.current.onSetFallback?.(nodeId),
    onPromoteToOrchestrator: (nodeId: string) => cbRef.current.onPromoteToOrchestrator?.(nodeId),
  }).current;

  // Track loaded team to detect changes
  const [loadedTeamId, setLoadedTeamId] = useState<string | null>(null);

  // Build nodes from team data
  if (team && team.team_id !== loadedTeamId && agents.length > 0) {
    setLoadedTeamId(team.team_id);
    setTeamName(team.name);
    setNodeRulesMap({});

    const initialNodes: Node[] = [];
    const initialEdges: Edge[] = [];
    const matchAgent = (agentId: string) =>
      agents.find((a) => a.agent_id === agentId || String(a.id) === agentId);

    if (!team.agents || team.agents.length === 0) {
      const orchId = getNextNodeId();
      initialNodes.push({
        id: orchId, type: 'orchestratorNode', position: { x: 300, y: 50 },
        data: { agentId: null, agentName: 'Select Orchestrator', agents, onAgentChange: stableCbs.onAgentChange },
      });
    } else {
      const orchAgent = team.agents.find((a) => a.role === 'orchestrator') ?? team.agents[0];
      const specialists = team.agents.filter((a) => a.agent_id !== orchAgent.agent_id);
      const orchId = getNextNodeId();
      const matchedOrch = matchAgent(orchAgent.agent_id);

      initialNodes.push({
        id: orchId, type: 'orchestratorNode', position: { x: 300, y: 50 },
        data: { agentId: matchedOrch?.id ?? null, agentName: matchedOrch?.name ?? orchAgent.agent_id, agents, onAgentChange: stableCbs.onAgentChange },
      });

      specialists.forEach((ta, idx) => {
        const nodeId = getNextNodeId();
        const matched = matchAgent(ta.agent_id);
        const isFallback = ta.role === 'fallback';
        const xOffset = (idx - Math.floor(specialists.length / 2)) * 220;

        initialNodes.push({
          id: nodeId,
          type: isFallback ? 'fallbackNode' : 'specialistNode',
          position: { x: 300 + xOffset, y: 200 + Math.floor(idx / 3) * 150 },
          data: {
            agentId: matched?.id ?? null, agentName: matched?.name ?? ta.agent_id,
            role: ta.role ?? 'specialist', agents, colorIndex: idx,
            rules: {
              executionMode: ta.execution_mode ?? 'sequential',
              criticality: ta.criticality ?? 'MEDIUM',
              timeout: ta.timeout_seconds ?? 30,
              fallbackAgentId: ta.fallback_agent_id ?? null,
            },
            onAgentChange: stableCbs.onAgentChange, onRemove: stableCbs.onRemove,
            onAddChild: stableCbs.onAddChild, onSetFallback: stableCbs.onSetFallback,
            onPromoteToOrchestrator: stableCbs.onPromoteToOrchestrator,
          },
        });

        const parentId = ta.parent_agent_id ?? null;
        let sourceNodeId = orchId;
        if (parentId) {
          const pn = initialNodes.find((n) => { const pm = matchAgent(parentId); return n.data?.agentId === pm?.id; });
          if (pn) sourceNodeId = pn.id;
        }
        initialEdges.push({
          id: `edge-${sourceNodeId}-${nodeId}`, source: sourceNodeId, target: nodeId, type: 'default',
          style: { stroke: isFallback ? theme.palette.error.main : theme.palette.primary.main, strokeWidth: 2, strokeDasharray: isFallback ? '5 5' : undefined },
          markerEnd: { type: MarkerType.ArrowClosed, color: isFallback ? theme.palette.error.main : theme.palette.primary.main },
        });
      });
    }

    setNodes(initialNodes);
    setEdges(initialEdges);
  } else if (!team && loadedTeamId) {
    setLoadedTeamId(null);
    setNodes([]);
    setEdges([]);
    setTeamName('Untitled Team');
  }

  const handleAgentChange = useCallback(
    (nodeId: string, agentId: number) => {
      const agent = agents.find((a) => a.id === agentId);
      setNodes((nds) =>
        nds.map((n) =>
          n.id === nodeId
            ? { ...n, data: { ...n.data, agentId, agentName: agent?.name ?? '' } }
            : n
        )
      );
    },
    [agents, setNodes]
  );

  const handleRemoveNode = useCallback(
    (nodeId: string) => {
      setNodes((nds) => nds.filter((n) => n.id !== nodeId));
      setEdges((eds) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId));
      if (selectedNode?.id === nodeId) {
        setSelectedNode(null);
        setRulesPanelOpen(false);
      }
    },
    [setNodes, setEdges, selectedNode]
  );

  const handleAddChild = useCallback(
    (parentId: string) => {
      const parentNode = nodes.find((n) => n.id === parentId);
      if (!parentNode) return;

      const childId = getNextNodeId();
      const newNode: Node = {
        id: childId,
        type: 'specialistNode',
        position: {
          x: parentNode.position.x,
          y: parentNode.position.y + 150,
        },
        data: {
          agentId: null,
          agentName: '',
          role: '',
          agents,
          colorIndex: nodes.length,
          onAgentChange: stableCbs.onAgentChange,
          onRemove: stableCbs.onRemove,
          onAddChild: stableCbs.onAddChild,
          onSetFallback: stableCbs.onSetFallback,
        },
      };

      const newEdge: Edge = {
        id: `edge-${parentId}-${childId}`,
        source: parentId,
        target: childId,
        style: { stroke: theme.palette.primary.main, strokeWidth: 2 },
        markerEnd: { type: MarkerType.ArrowClosed, color: theme.palette.primary.main },
      };

      setNodes((nds) => [...nds, newNode]);
      setEdges((eds) => [...eds, newEdge]);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [nodes, agents, theme]
  );

  const handleSetFallback = useCallback(
    (nodeId: string) => {
      const sourceNode = nodes.find((n) => n.id === nodeId);
      if (!sourceNode) return;

      const fallbackId = getNextNodeId();
      const newNode: Node = {
        id: fallbackId,
        type: 'fallbackNode',
        position: {
          x: sourceNode.position.x + 200,
          y: sourceNode.position.y,
        },
        data: {
          agentId: null,
          agentName: '',
          primaryName: sourceNode.data?.agentName ?? 'Unknown',
          agents,
          onAgentChange: stableCbs.onAgentChange,
          onRemove: stableCbs.onRemove,
        },
      };

      const newEdge: Edge = {
        id: `edge-fallback-${nodeId}-${fallbackId}`,
        source: nodeId,
        target: fallbackId,
        style: {
          stroke: theme.palette.error.main,
          strokeWidth: 2,
          strokeDasharray: '6 3',
        },
        markerEnd: { type: MarkerType.ArrowClosed, color: theme.palette.error.main },
        label: 'fallback',
        labelStyle: { fill: theme.palette.error.main, fontSize: 10 },
      };

      setNodes((nds) => [...nds, newNode]);
      setEdges((eds) => [...eds, newEdge]);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [nodes, agents, theme]
  );

  // Promote a specialist node to orchestrator
  const handlePromoteToOrchestrator = useCallback(
    (nodeId: string) => {
      setNodes((nds) => {
        // Demote existing orchestrator to specialist
        const updated = nds.map((n) => {
          if (n.type === 'orchestratorNode') {
            return { ...n, type: 'specialistNode' as const, data: { ...n.data, role: 'specialist' } };
          }
          return n;
        });
        // Promote the selected node
        return updated.map((n) => {
          if (n.id === nodeId) {
            return { ...n, type: 'orchestratorNode' as const, data: { ...n.data, role: 'orchestrator' } };
          }
          return n;
        });
      });
    },
    [setNodes],
  );

  const onConnect: OnConnect = useCallback(
    (connection: Connection) => {
      setEdges((eds) =>
        addEdge(
          {
            ...connection,
            style: { stroke: theme.palette.primary.main, strokeWidth: 2 },
            markerEnd: { type: MarkerType.ArrowClosed, color: theme.palette.primary.main },
          },
          eds
        )
      );
    },
    [setEdges, theme]
  );

  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      setSelectedNode(node);
      setRulesPanelOpen(true);
      // Load rules from node data if they exist but aren't in the rules map yet
      if (!nodeRulesMap[node.id] && node.data?.rules) {
        setNodeRulesMap((prev) => ({ ...prev, [node.id]: { ...DEFAULT_NODE_RULES, ...node.data.rules } }));
      }
    },
    [nodeRulesMap],
  );

  // Update the callback ref with actual implementations (NOT the stable wrappers)
  cbRef.current = {
    onAgentChange: handleAgentChange,
    onRemove: handleRemoveNode,
    onAddChild: handleAddChild,
    onSetFallback: handleSetFallback,
    onPromoteToOrchestrator: handlePromoteToOrchestrator,
  } as Record<string, (...args: unknown[]) => void>;

  const handlePaneClick = useCallback(() => {
    setSelectedNode(null);
    setRulesPanelOpen(false);
  }, []);

  const handleAddAgentFromDrawer = useCallback(
    (agent: Agent) => {
      const nodeId = getNextNodeId();
      const newNode: Node = {
        id: nodeId,
        type: 'specialistNode',
        position: { x: 300, y: 300 },
        data: {
          agentId: agent.id,
          agentName: agent.name,
          role: agent.role ?? '',
          agents,
          colorIndex: nodes.length,
          onAgentChange: stableCbs.onAgentChange,
          onRemove: stableCbs.onRemove,
          onAddChild: stableCbs.onAddChild,
          onSetFallback: stableCbs.onSetFallback,
          onPromoteToOrchestrator: stableCbs.onPromoteToOrchestrator,
        },
      };

      setNodes((nds) => [...nds, newNode]);

      // Auto-connect to orchestrator if one exists
      const orchestrator = nodes.find((n) => n.type === 'orchestratorNode');
      if (orchestrator) {
        const newEdge: Edge = {
          id: `edge-${orchestrator.id}-${nodeId}`,
          source: orchestrator.id,
          target: nodeId,
          style: { stroke: theme.palette.primary.main, strokeWidth: 2 },
          markerEnd: { type: MarkerType.ArrowClosed, color: theme.palette.primary.main },
        };
        setEdges((eds) => [...eds, newEdge]);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [nodes, agents, theme]
  );

  const handleSave = useCallback(() => {
    onSave({ name: teamName }, nodes, edges);
  }, [onSave, teamName, nodes, edges]);

  const handleExportJSON = useCallback(() => {
    const exportData = {
      team: { name: teamName, team_id: team?.team_id },
      nodes: nodes.map((n) => ({
        id: n.id,
        type: n.type,
        position: n.position,
        agentId: n.data?.agentId,
        agentName: n.data?.agentName,
        role: n.data?.role,
      })),
      edges: edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
      })),
      rules: nodeRulesMap,
    };
    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${teamName.replace(/\s+/g, '_').toLowerCase()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [team, teamName, nodes, edges, nodeRulesMap]);

  const handleRulesChange = useCallback(
    (rules: NodeRules) => {
      if (!selectedNode) return;
      setNodeRulesMap((prev) => ({ ...prev, [selectedNode.id]: rules }));
    },
    [selectedNode]
  );

  const currentRules = selectedNode
    ? nodeRulesMap[selectedNode.id] ?? DEFAULT_NODE_RULES
    : DEFAULT_NODE_RULES;

  // Empty state: no team selected
  if (!team && !isLoading) {
    return (
      <Box
        sx={{
          flex: 1,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          bgcolor: 'background.default',
        }}
      >
        <Box sx={{ textAlign: 'center' }}>
          <Typography variant="h6" color="text.secondary" sx={{ mb: 1 }}>
            Select a team to start editing
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Choose a team from the left panel, or create a new one.
          </Typography>
        </Box>
      </Box>
    );
  }

  return (
    <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', position: 'relative' }}>
      {/* Top Bar */}
      <Box
        sx={{
          px: 2,
          py: 1,
          display: 'flex',
          alignItems: 'center',
          gap: 1.5,
          borderBottom: `1px solid ${theme.palette.divider}`,
          bgcolor: 'background.paper',
          flexWrap: 'wrap',
        }}
      >
        <TextField
          value={teamName}
          onChange={(e) => setTeamName(e.target.value)}
          variant="standard"
          InputProps={{
            sx: { fontSize: '1.1rem', fontWeight: 700 },
            disableUnderline: false,
          }}
          sx={{ minWidth: 180 }}
        />

        <Box sx={{ flex: 1 }} />

        <TeamValidation nodes={nodes} />

        <Divider orientation="vertical" flexItem />

        <Stack direction="row" spacing={0.5}>
          <Tooltip title="Save">
            <Button
              variant="contained"
              size="small"
              startIcon={<SaveIcon />}
              onClick={handleSave}
            >
              Save
            </Button>
          </Tooltip>
          <Tooltip title="Duplicate">
            <IconButton size="small" onClick={onDuplicate}>
              <ContentCopyIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <Tooltip title="Export JSON">
            <IconButton size="small" onClick={handleExportJSON}>
              <FileDownloadIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <Tooltip title="Test Team">
            <IconButton size="small" color="success">
              <PlayArrowIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <Tooltip title="Delete Team">
            <IconButton size="small" color="error" onClick={onDelete}>
              <DeleteIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Stack>
      </Box>

      {/* Canvas */}
      <Box ref={reactFlowWrapper} sx={{ flex: 1, position: 'relative' }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeClick={handleNodeClick}
          onPaneClick={handlePaneClick}
          onEdgeClick={(_, edge) => {
            // Select edge on click — then user can press Delete/Backspace to remove
            setEdges((eds) => eds.map((e) => ({ ...e, selected: e.id === edge.id })));
          }}
          nodeTypes={nodeTypes}
          deleteKeyCode={['Backspace', 'Delete']}
          fitView
          attributionPosition="bottom-left"
          defaultEdgeOptions={{ deletable: true }}
          style={{ background: theme.palette.background.default }}
        >
          <Background
            variant={BackgroundVariant.Dots}
            gap={20}
            size={1}
            color={theme.palette.divider}
          />
          <Controls
            style={{
              borderRadius: 8,
              border: `1px solid ${theme.palette.divider}`,
              backgroundColor: theme.palette.background.paper,
            }}
          />
          <MiniMap
            nodeColor={(node) => {
              if (node.type === 'orchestratorNode') return theme.palette.warning.main;
              if (node.type === 'fallbackNode') return theme.palette.error.main;
              return theme.palette.primary.main;
            }}
            maskColor={`${theme.palette.background.default}90`}
            style={{
              borderRadius: 8,
              border: `1px solid ${theme.palette.divider}`,
              backgroundColor: theme.palette.background.paper,
            }}
          />
        </ReactFlow>

        {/* Hierarchy Rules Panel */}
        <HierarchyRulesPanel
          open={rulesPanelOpen}
          onClose={() => {
            setRulesPanelOpen(false);
            setSelectedNode(null);
          }}
          selectedNode={selectedNode}
          rules={currentRules}
          onRulesChange={handleRulesChange}
          agents={agents}
        />
      </Box>

      {/* Add Agent Button */}
      <Tooltip title="Add Agent">
        <Button
          variant="contained"
          onClick={() => setDrawerOpen(!drawerOpen)}
          startIcon={drawerOpen ? <ExpandMoreIcon /> : <ExpandLessIcon />}
          endIcon={<AddIcon />}
          sx={{
            position: 'absolute',
            bottom: drawerOpen ? 260 : 16,
            left: '50%',
            transform: 'translateX(-50%)',
            zIndex: 5,
            borderRadius: 3,
            transition: 'bottom 0.3s ease',
          }}
        >
          Add Agent
        </Button>
      </Tooltip>

      {/* Agent Drawer */}
      <Drawer
        variant="persistent"
        anchor="bottom"
        open={drawerOpen}
        PaperProps={{
          sx: {
            position: 'absolute',
            height: 240,
            bgcolor: 'background.paper',
            borderTop: `1px solid ${theme.palette.divider}`,
          },
        }}
        ModalProps={{ keepMounted: true }}
      >
        <Box sx={{ p: 2, overflow: 'auto', height: '100%' }}>
          <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1.5 }}>
            Available Agents
          </Typography>
          {agents.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              No agents available. Create agents first.
            </Typography>
          ) : (
            <Grid container spacing={1.5}>
              {agents.map((agent) => (
                <Grid item xs={6} sm={4} md={3} lg={2} key={agent.id}>
                  <Card
                    variant="outlined"
                    sx={{
                      cursor: 'pointer',
                      transition: 'border-color 0.2s',
                      '&:hover': {
                        borderColor: 'primary.main',
                        boxShadow: `0 0 0 1px ${theme.palette.primary.main}`,
                      },
                    }}
                  >
                    <CardActionArea
                      onDoubleClick={() => handleAddAgentFromDrawer(agent)}
                      sx={{ p: 1.5 }}
                    >
                      <CardContent sx={{ p: '0 !important' }}>
                        <Typography variant="body2" fontWeight={600} noWrap>
                          {agent.name}
                        </Typography>
                        <Stack direction="row" spacing={0.5} sx={{ mt: 0.5, flexWrap: 'wrap' }} useFlexGap>
                          {agent.domains?.slice(0, 2).map((domain) => (
                            <Chip
                              key={domain}
                              label={domain}
                              size="small"
                              sx={{ height: 18, fontSize: '0.6rem' }}
                            />
                          ))}
                        </Stack>
                        <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
                          {agent.tools?.length ?? 0} tools
                        </Typography>
                      </CardContent>
                    </CardActionArea>
                  </Card>
                </Grid>
              ))}
            </Grid>
          )}
        </Box>
      </Drawer>
    </Box>
  );
}
