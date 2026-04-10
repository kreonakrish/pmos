import React, { useState, useMemo, useCallback } from 'react';
import {
  Box,
  TextField,
  List,
  ListItemButton,
  ListItemText,
  Typography,
  Button,
  Chip,
  Menu,
  MenuItem,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Skeleton,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import { formatDistanceToNow } from 'date-fns';
import {
  useConversations,
  useCreateConversation,
  useDeleteConversation,
  useRenameConversation,
} from '@/api/conversations';
import { useConversationStore } from '@/store/conversationStore';

const ConversationList: React.FC = () => {
  const { data: conversations, isLoading, isError } = useConversations();
  const createConversation = useCreateConversation();
  const deleteConversation = useDeleteConversation();
  const renameConversation = useRenameConversation();

  const { activeConversationId, setActiveConversation } = useConversationStore();

  const [search, setSearch] = useState('');
  const [contextMenu, setContextMenu] = useState<{
    mouseX: number;
    mouseY: number;
    conversationId: string;
  } | null>(null);
  const [renameDialog, setRenameDialog] = useState<{ id: string; title: string } | null>(null);

  const filtered = useMemo(() => {
    if (!conversations) return [];
    if (!search.trim()) return conversations;
    const lower = search.toLowerCase();
    return conversations.filter((c) => c.title.toLowerCase().includes(lower));
  }, [conversations, search]);

  const handleContextMenu = useCallback(
    (event: React.MouseEvent, conversationId: string) => {
      event.preventDefault();
      setContextMenu({ mouseX: event.clientX, mouseY: event.clientY, conversationId });
    },
    [],
  );

  const handleCloseContextMenu = useCallback(() => setContextMenu(null), []);

  const handleDelete = useCallback(() => {
    if (contextMenu) {
      deleteConversation.mutate(contextMenu.conversationId);
    }
    setContextMenu(null);
  }, [contextMenu, deleteConversation]);

  const handleRenameOpen = useCallback(() => {
    if (contextMenu) {
      const conv = conversations?.find((c) => c.id === contextMenu.conversationId);
      if (conv) {
        setRenameDialog({ id: conv.id, title: conv.title });
      }
    }
    setContextMenu(null);
  }, [contextMenu, conversations]);

  const handleRenameSubmit = useCallback(() => {
    if (renameDialog) {
      renameConversation.mutate({ id: renameDialog.id, title: renameDialog.title });
    }
    setRenameDialog(null);
  }, [renameDialog, renameConversation]);

  const handleCreate = useCallback(() => {
    createConversation.mutate(undefined, {
      onSuccess: (conv) => setActiveConversation(conv.id),
    });
  }, [createConversation, setActiveConversation]);

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* New conversation button */}
      <Box sx={{ p: 1.5 }}>
        <Button
          fullWidth
          variant="contained"
          startIcon={<AddIcon />}
          onClick={handleCreate}
          disabled={createConversation.isPending}
          size="small"
        >
          New Conversation
        </Button>
      </Box>

      {/* Search */}
      <Box sx={{ px: 1.5, pb: 1 }}>
        <TextField
          fullWidth
          size="small"
          placeholder="Search conversations..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </Box>

      {/* List */}
      <Box sx={{ flex: 1, overflow: 'auto' }}>
        {isLoading && (
          <Box sx={{ px: 2 }}>
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} height={56} sx={{ mb: 0.5 }} />
            ))}
          </Box>
        )}

        {isError && (
          <Box sx={{ p: 2 }}>
            <Typography variant="body2" color="error">
              Failed to load conversations.
            </Typography>
          </Box>
        )}

        {!isLoading && !isError && filtered.length === 0 && (
          <Box sx={{ p: 2, textAlign: 'center' }}>
            <Typography variant="body2" color="text.secondary">
              {search ? 'No matching conversations.' : 'No conversations yet.'}
            </Typography>
          </Box>
        )}

        <List disablePadding>
          {filtered.map((conv) => (
            <ListItemButton
              key={conv.id}
              selected={conv.id === activeConversationId}
              onClick={() => setActiveConversation(conv.id)}
              onContextMenu={(e) => handleContextMenu(e, conv.id)}
              sx={{ px: 2, py: 1 }}
            >
              <ListItemText
                primary={
                  <Typography variant="body2" noWrap sx={{ fontWeight: conv.id === activeConversationId ? 600 : 400 }}>
                    {conv.title}
                  </Typography>
                }
                secondary={
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mt: 0.25 }}>
                    <Typography variant="caption" color="text.secondary">
                      {formatDistanceToNow(new Date(conv.updated_at), { addSuffix: true })}
                    </Typography>
                    <Chip
                      label={conv.status}
                      size="small"
                      variant="outlined"
                      sx={{ height: 18, fontSize: '0.65rem' }}
                    />
                  </Box>
                }
              />
            </ListItemButton>
          ))}
        </List>
      </Box>

      {/* Right-click context menu */}
      <Menu
        open={contextMenu !== null}
        onClose={handleCloseContextMenu}
        anchorReference="anchorPosition"
        anchorPosition={
          contextMenu ? { top: contextMenu.mouseY, left: contextMenu.mouseX } : undefined
        }
      >
        <MenuItem onClick={handleRenameOpen}>Rename</MenuItem>
        <MenuItem onClick={handleDelete} sx={{ color: 'error.main' }}>
          Delete
        </MenuItem>
      </Menu>

      {/* Rename dialog */}
      <Dialog open={renameDialog !== null} onClose={() => setRenameDialog(null)}>
        <DialogTitle>Rename Conversation</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            fullWidth
            margin="dense"
            value={renameDialog?.title ?? ''}
            onChange={(e) =>
              setRenameDialog((prev) => (prev ? { ...prev, title: e.target.value } : null))
            }
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRenameDialog(null)}>Cancel</Button>
          <Button onClick={handleRenameSubmit} variant="contained">
            Save
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default ConversationList;
