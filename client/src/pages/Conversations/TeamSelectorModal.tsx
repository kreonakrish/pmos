import React, { useState, useMemo } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Grid,
  Card,
  CardContent,
  CardActionArea,
  Typography,
  TextField,
  Box,
  Chip,
  Skeleton,
} from '@mui/material';
import GroupsIcon from '@mui/icons-material/Groups';
import StarIcon from '@mui/icons-material/Star';
import { useTeams, useTeam } from '@/api/teams';
import { useCreateConversation } from '@/api/conversations';
import { useConversationStore } from '@/store/conversationStore';

interface TeamSelectorModalProps {
  open: boolean;
  onClose: () => void;
}

const TeamSelectorModal: React.FC<TeamSelectorModalProps> = ({ open, onClose }) => {
  const { data: teams, isLoading } = useTeams();
  const createConversation = useCreateConversation();
  const { setActiveConversation } = useConversationStore();

  const [search, setSearch] = useState('');
  const [selectedTeamId, setSelectedTeamId] = useState<string | null>(null);

  // Fetch full team details when one is selected (to get agent count)
  const { data: selectedTeamDetail } = useTeam(selectedTeamId);

  const filtered = useMemo(() => {
    if (!teams) return [];
    if (!search.trim()) return teams;
    const lower = search.toLowerCase();
    return teams.filter(
      (t) =>
        t.name.toLowerCase().includes(lower) ||
        (t.description && t.description.toLowerCase().includes(lower)),
    );
  }, [teams, search]);

  const handleCreate = () => {
    if (!selectedTeamId) return;
    const selectedTeam = teams?.find((t) => t.team_id === selectedTeamId);
    createConversation.mutate(
      { title: `Chat with ${selectedTeam?.name ?? 'Team'}`, team_id: selectedTeamId },
      {
        onSuccess: (conv) => {
          setActiveConversation(conv.id);
          setSelectedTeamId(null);
          setSearch('');
          onClose();
        },
      },
    );
  };

  const handleClose = () => {
    setSelectedTeamId(null);
    setSearch('');
    onClose();
  };

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="md" fullWidth>
      <DialogTitle>Select a Team for Conversation</DialogTitle>
      <DialogContent>
        <TextField
          fullWidth
          size="small"
          placeholder="Search teams..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          sx={{ mb: 2, mt: 1 }}
        />

        {isLoading && (
          <Grid container spacing={2}>
            {Array.from({ length: 4 }).map((_, i) => (
              <Grid item xs={12} sm={6} key={i}>
                <Skeleton variant="rounded" height={120} />
              </Grid>
            ))}
          </Grid>
        )}

        {!isLoading && filtered.length === 0 && (
          <Box sx={{ textAlign: 'center', py: 4 }}>
            <Typography color="text.secondary">
              {search ? 'No matching teams found.' : 'No teams available. Create a team in Team Studio first.'}
            </Typography>
          </Box>
        )}

        <Grid container spacing={2}>
          {filtered.map((team) => {
            const isSelected = selectedTeamId === team.team_id;
            const agentCount = isSelected && selectedTeamDetail?.agents
              ? selectedTeamDetail.agents.length
              : (team.agents?.length ?? 0);
            const orchestrator = isSelected && selectedTeamDetail?.agents
              ? selectedTeamDetail.agents.find((a) => a.role === 'orchestrator')
              : null;

            return (
              <Grid item xs={12} sm={6} key={team.team_id}>
                <Card
                  variant={isSelected ? 'elevation' : 'outlined'}
                  sx={{
                    border: isSelected ? 2 : 1,
                    borderColor: isSelected ? 'primary.main' : 'divider',
                    transition: 'all 0.15s',
                  }}
                >
                  <CardActionArea onClick={() => setSelectedTeamId(team.team_id)}>
                    <CardContent>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                        <GroupsIcon color="primary" fontSize="small" />
                        <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                          {team.name}
                        </Typography>
                      </Box>
                      {team.description && (
                        <Typography
                          variant="body2"
                          color="text.secondary"
                          sx={{
                            mb: 1,
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            display: '-webkit-box',
                            WebkitLineClamp: 2,
                            WebkitBoxOrient: 'vertical',
                          }}
                        >
                          {team.description}
                        </Typography>
                      )}
                      <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                        <Chip
                          label={`${agentCount} agent${agentCount !== 1 ? 's' : ''}`}
                          size="small"
                          variant="outlined"
                          color={agentCount > 0 ? 'primary' : 'default'}
                        />
                        <Chip label={team.retry_strategy} size="small" variant="outlined" />
                        {orchestrator && (
                          <Chip
                            icon={<StarIcon sx={{ fontSize: 14 }} />}
                            label={`Orch: ${(orchestrator as Record<string, unknown>).agent_name ?? '?'}`}
                            size="small"
                            variant="outlined"
                            color="warning"
                          />
                        )}
                      </Box>
                    </CardContent>
                  </CardActionArea>
                </Card>
              </Grid>
            );
          })}
        </Grid>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose}>Cancel</Button>
        <Button
          variant="contained"
          onClick={handleCreate}
          disabled={!selectedTeamId || createConversation.isPending}
        >
          Start Conversation
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default TeamSelectorModal;
