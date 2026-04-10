import { useMemo, useState } from 'react';
import {
  Box,
  Typography,
  TextField,
  InputAdornment,
  Button,
  List,
  ListItemButton,
  ListItemText,
  Badge,
  Skeleton,
  useTheme,
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import AddIcon from '@mui/icons-material/Add';
import GroupsIcon from '@mui/icons-material/Groups';
import { format } from 'date-fns';
import type { Team } from '@/types';

interface TeamListProps {
  teams: Team[] | undefined;
  isLoading: boolean;
  selectedTeamId: string | null;
  onSelectTeam: (teamId: string) => void;
  onCreateTeam: () => void;
}

export default function TeamList({
  teams,
  isLoading,
  selectedTeamId,
  onSelectTeam,
  onCreateTeam,
}: TeamListProps) {
  const theme = useTheme();
  const [search, setSearch] = useState('');

  const filtered = useMemo(() => {
    if (!teams) return [];
    if (!search) return teams;
    const lower = search.toLowerCase();
    return teams.filter(
      (t) =>
        t.name.toLowerCase().includes(lower) ||
        t.description?.toLowerCase().includes(lower)
    );
  }, [teams, search]);

  return (
    <Box
      sx={{
        width: 260,
        height: '100%',
        borderRight: `1px solid ${theme.palette.divider}`,
        display: 'flex',
        flexDirection: 'column',
        bgcolor: 'background.paper',
        flexShrink: 0,
      }}
    >
      {/* Header */}
      <Box sx={{ p: 2, borderBottom: `1px solid ${theme.palette.divider}` }}>
        <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 1.5 }}>
          Teams
        </Typography>
        <TextField
          placeholder="Search teams..."
          size="small"
          fullWidth
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <SearchIcon fontSize="small" sx={{ color: 'text.secondary' }} />
              </InputAdornment>
            ),
          }}
          sx={{ mb: 1.5 }}
        />
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          fullWidth
          size="small"
          onClick={onCreateTeam}
        >
          Create Team
        </Button>
      </Box>

      {/* List */}
      <Box sx={{ flex: 1, overflow: 'auto' }}>
        {isLoading ? (
          <Box sx={{ p: 2, display: 'flex', flexDirection: 'column', gap: 1 }}>
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} variant="rectangular" height={56} sx={{ borderRadius: 1 }} />
            ))}
          </Box>
        ) : filtered.length === 0 ? (
          <Box sx={{ p: 3, textAlign: 'center' }}>
            <GroupsIcon sx={{ fontSize: 40, color: 'text.secondary', mb: 1 }} />
            <Typography variant="body2" color="text.secondary">
              {search ? 'No teams match your search' : 'No teams yet'}
            </Typography>
          </Box>
        ) : (
          <List disablePadding>
            {filtered.map((team) => {
              const isSelected = team.team_id === selectedTeamId;
              const agentCount = team.agents?.length ?? 0;

              return (
                <ListItemButton
                  key={team.team_id}
                  selected={isSelected}
                  onClick={() => onSelectTeam(team.team_id)}
                  sx={{
                    borderLeft: isSelected
                      ? `3px solid ${theme.palette.primary.main}`
                      : '3px solid transparent',
                    py: 1.5,
                    '&.Mui-selected': {
                      bgcolor: `${theme.palette.primary.main}10`,
                    },
                  }}
                >
                  <ListItemText
                    primary={
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        <Typography variant="body2" fontWeight={600} noWrap sx={{ flex: 1 }}>
                          {team.name}
                        </Typography>
                        <Badge
                          badgeContent={agentCount}
                          color="primary"
                          sx={{
                            '& .MuiBadge-badge': { fontSize: '0.65rem', height: 16, minWidth: 16 },
                          }}
                        >
                          <GroupsIcon sx={{ fontSize: 16, color: 'text.secondary' }} />
                        </Badge>
                      </Box>
                    }
                    secondary={
                      <Typography variant="caption" color="text.secondary">
                        {team.created_at
                          ? format(new Date(team.created_at), 'MMM d, yyyy')
                          : 'No date'}
                      </Typography>
                    }
                  />
                </ListItemButton>
              );
            })}
          </List>
        )}
      </Box>
    </Box>
  );
}
