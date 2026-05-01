import React, { useEffect, useRef, useCallback, useState, useMemo } from 'react';
import {
  Box,
  Typography,
  Skeleton,
  IconButton,
  Drawer,
  Button,
  useTheme,
  useMediaQuery,
  TextField,
  List,
  ListItemButton,
  ListItemText,
  Chip,
  Menu,
  MenuItem,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
} from '@mui/material';
import MenuIcon from '@mui/icons-material/Menu';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import SwapHorizIcon from '@mui/icons-material/SwapHoriz';
import TimelineIcon from '@mui/icons-material/Timeline';
import AddIcon from '@mui/icons-material/Add';
import { useNavigate } from 'react-router-dom';
import { formatDistanceToNow, isToday, isYesterday, isThisWeek } from 'date-fns';
import {
  useConversations,
  useConversationMessages,
  useSendMessage,
  useDeleteConversation,
  useRenameConversation,
} from '@/api/conversations';
import { useConversationStore } from '@/store/conversationStore';
import { useUIStore } from '@/store/uiStore';
import { useWSStore } from '@/store/wsStore';
import MessageBubble from '@/components/Chat/MessageBubble';
import ChatInput from '@/components/Chat/ChatInput';
import FileAttachmentBubble from '@/components/Chat/FileAttachmentBubble';
import TeamSelectorModal from './TeamSelectorModal';
import type { Conversation } from '@/types';

interface FileUploadRecord {
  id: string;
  filename: string;
  fileSize: number;
  chunksIndexed: number;
  timestamp: string;
}

const SIDEBAR_WIDTH = 280;

interface GroupedConversations {
  label: string;
  conversations: Conversation[];
}

function groupByDate(conversations: Conversation[]): GroupedConversations[] {
  const groups: Record<string, Conversation[]> = {
    Today: [],
    Yesterday: [],
    'This Week': [],
    Older: [],
  };

  for (const conv of conversations) {
    const date = new Date(conv.updated_at);
    if (isToday(date)) {
      groups['Today'].push(conv);
    } else if (isYesterday(date)) {
      groups['Yesterday'].push(conv);
    } else if (isThisWeek(date)) {
      groups['This Week'].push(conv);
    } else {
      groups['Older'].push(conv);
    }
  }

  return Object.entries(groups)
    .filter(([, convs]) => convs.length > 0)
    .map(([label, conversations]) => ({ label, conversations }));
}

const ConversationsPage: React.FC = () => {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('md'));
  const navigate = useNavigate();
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const { activeConversationId, streamingContent } = useConversationStore();
  const { setActiveConversation } = useConversationStore();
  const { sidebarOpen, setSidebarOpen, toggleSidebar } = useUIStore();
  const { isStreaming } = useWSStore();
  const sendMessage = useSendMessage();
  const deleteConversation = useDeleteConversation();
  const renameConversation = useRenameConversation();

  const { data: conversations, isLoading: convsLoading, isError: convsError } = useConversations();
  const {
    data: messages,
    isLoading: messagesLoading,
    isError: messagesError,
  } = useConversationMessages(activeConversationId);

  const [teamModalOpen, setTeamModalOpen] = useState(false);
  const [pendingUserMessage, setPendingUserMessage] = useState<string | null>(null);
  const [isWaitingForAgent, setIsWaitingForAgent] = useState(false);
  const [search, setSearch] = useState('');
  const [contextMenu, setContextMenu] = useState<{
    mouseX: number;
    mouseY: number;
    conversationId: string;
  } | null>(null);
  const [renameDialog, setRenameDialog] = useState<{ id: string; title: string } | null>(null);
  const [fileUploads, setFileUploads] = useState<FileUploadRecord[]>([]);

  const filtered = useMemo(() => {
    if (!conversations) return [];
    if (!search.trim()) return conversations;
    const lower = search.toLowerCase();
    return conversations.filter((c) => c.title.toLowerCase().includes(lower));
  }, [conversations, search]);

  const grouped = useMemo(() => groupByDate(filtered), [filtered]);

  /* Auto-scroll to bottom on new messages */
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent]);

  /* Close sidebar on mobile when conversation is selected */
  useEffect(() => {
    if (isMobile && activeConversationId) {
      setSidebarOpen(false);
    }
  }, [activeConversationId, isMobile, setSidebarOpen]);

  const handleSend = useCallback(
    (content: string) => {
      if (!activeConversationId) return;
      // Show user message immediately (optimistic)
      setPendingUserMessage(content);
      setIsWaitingForAgent(true);
      sendMessage.mutate(
        { conversationId: activeConversationId, content },
        {
          onSettled: () => {
            setPendingUserMessage(null);
            setIsWaitingForAgent(false);
          },
        },
      );
    },
    [activeConversationId, sendMessage],
  );

  const handleFileAttach = useCallback(
    async (file: File): Promise<{ document_id: string; chunks_indexed: number }> => {
      if (!activeConversationId) throw new Error('No conversation');
      const formData = new FormData();
      formData.append('file', file);
      formData.append('conversation_id', activeConversationId);
      formData.append('chunk_strategy', 'sentence');
      const { default: apiClient } = await import('@/api/axios');
      const { data } = await apiClient.post('/v1/documents/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 120_000,
      });
      // Track successful upload for display in chat
      setFileUploads((prev) => [
        ...prev,
        {
          id: data.document_id,
          filename: file.name,
          fileSize: file.size,
          chunksIndexed: data.chunks_indexed,
          timestamp: new Date().toISOString(),
        },
      ]);
      return { document_id: data.document_id, chunks_indexed: data.chunks_indexed };
    },
    [activeConversationId],
  );

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
      const deletingActive = contextMenu.conversationId === activeConversationId;
      deleteConversation.mutate(contextMenu.conversationId, {
        onSuccess: () => {
          if (deletingActive) {
            setActiveConversation(null as unknown as string);
          }
        },
      });
    }
    setContextMenu(null);
  }, [contextMenu, deleteConversation, activeConversationId, setActiveConversation]);

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

  /* ---------- Sidebar content ---------- */
  const sidebarContent = (
    <Box
      sx={{
        width: SIDEBAR_WIDTH,
        height: '100%',
        borderRight: 1,
        borderColor: 'divider',
        bgcolor: 'background.default',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* New conversation button */}
      <Box sx={{ p: 1.5 }}>
        <Button
          fullWidth
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => setTeamModalOpen(true)}
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

      {/* Grouped list */}
      <Box sx={{ flex: 1, overflow: 'auto' }}>
        {convsLoading && (
          <Box sx={{ px: 2 }}>
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} height={56} sx={{ mb: 0.5 }} />
            ))}
          </Box>
        )}

        {convsError && (
          <Box sx={{ p: 2 }}>
            <Typography variant="body2" color="error">
              Failed to load conversations.
            </Typography>
          </Box>
        )}

        {!convsLoading && !convsError && filtered.length === 0 && (
          <Box sx={{ p: 2, textAlign: 'center' }}>
            <Typography variant="body2" color="text.secondary">
              {search ? 'No matching conversations.' : 'No conversations yet.'}
            </Typography>
          </Box>
        )}

        {grouped.map((group) => (
          <Box key={group.label}>
            <Typography
              variant="caption"
              sx={{
                px: 2,
                py: 0.5,
                display: 'block',
                color: 'text.secondary',
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: 0.5,
                fontSize: '0.65rem',
              }}
            >
              {group.label}
            </Typography>
            <List disablePadding>
              {group.conversations.map((conv) => (
                <ListItemButton
                  key={conv.id}
                  selected={conv.id === activeConversationId}
                  onClick={() => setActiveConversation(conv.id)}
                  onContextMenu={(e) => handleContextMenu(e, conv.id)}
                  sx={{ px: 2, py: 1 }}
                >
                  <ListItemText
                    disableTypography
                    primary={
                      <Typography
                        variant="body2"
                        noWrap
                        sx={{ fontWeight: conv.id === activeConversationId ? 600 : 400 }}
                      >
                        {conv.title}
                      </Typography>
                    }
                    secondary={
                      <Box component="span" sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mt: 0.25 }}>
                        <Typography variant="caption" color="text.secondary" component="span">
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
        ))}
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
        <MenuItem
          onClick={() => {
            if (contextMenu) {
              const conv = conversations?.find((c) => c.id === contextMenu.conversationId);
              const teamId = (conv as Record<string, unknown> | undefined)?.team_id;
              if (teamId) {
                navigate(`/team-studio?team=${teamId}`);
              }
            }
            setContextMenu(null);
          }}
        >
          View Team
        </MenuItem>
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

  return (
    <Box sx={{ display: 'flex', height: 'calc(100vh - 112px)', overflow: 'hidden', mx: -3, mt: -3, mb: -3 }}>
      {/* Sidebar -- responsive */}
      {isMobile ? (
        <Drawer
          open={sidebarOpen}
          onClose={() => setSidebarOpen(false)}
          ModalProps={{ keepMounted: true }}
        >
          {sidebarContent}
        </Drawer>
      ) : (
        sidebarOpen && sidebarContent
      )}

      {/* Main chat area */}
      <Box
        sx={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          height: '100%',
          minWidth: 0,
          overflow: 'hidden',
        }}
      >
        {/* Header — always visible, never scrolls */}
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 1,
            px: 2,
            py: 1,
            borderBottom: 1,
            borderColor: 'divider',
            bgcolor: 'background.paper',
            flexShrink: 0,
            zIndex: 1,
          }}
        >
          <IconButton size="small" onClick={toggleSidebar}>
            <MenuIcon />
          </IconButton>
          <Typography variant="subtitle1" noWrap sx={{ flex: 1 }}>
            {activeConversationId ? 'Conversation' : 'Select or start a conversation'}
          </Typography>
          {isStreaming && (
            <Typography variant="caption" sx={{ color: 'info.main' }}>
              Streaming...
            </Typography>
          )}
          {activeConversationId && (
            <>
              <Button
                size="small"
                startIcon={<AccountTreeIcon />}
                onClick={() => navigate(`/conversations/${activeConversationId}/decomposition`)}
              >
                Decomposition
              </Button>
              <Button
                size="small"
                startIcon={<SwapHorizIcon />}
                onClick={() => navigate(`/conversations/${activeConversationId}/interactions`)}
              >
                Interactions
              </Button>
              <Button
                size="small"
                startIcon={<TimelineIcon />}
                onClick={() => navigate(`/conversations/${activeConversationId}/timeline`)}
              >
                Timeline
              </Button>
            </>
          )}
        </Box>

        {/* Messages area */}
        <Box sx={{ flex: 1, overflow: 'auto', py: 2 }}>
          {!activeConversationId && (
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                height: '100%',
              }}
            >
              <Typography variant="h6" color="text.secondary">
                Select a conversation or create a new one
              </Typography>
            </Box>
          )}

          {activeConversationId && messagesLoading && (
            <Box sx={{ px: 2 }}>
              {Array.from({ length: 4 }).map((_, i) => (
                <Box
                  key={i}
                  sx={{
                    display: 'flex',
                    justifyContent: i % 2 === 0 ? 'flex-end' : 'flex-start',
                    mb: 2,
                    px: 2,
                  }}
                >
                  <Skeleton
                    variant="rounded"
                    width="60%"
                    height={i % 2 === 0 ? 48 : 100}
                  />
                </Box>
              ))}
            </Box>
          )}

          {activeConversationId && messagesError && (
            <Box sx={{ p: 3, textAlign: 'center' }}>
              <Typography color="error">
                Failed to load messages. Please try again.
              </Typography>
            </Box>
          )}

          {messages?.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))}

          {/* File attachment bubbles */}
          {fileUploads.map((fu) => (
            <FileAttachmentBubble
              key={fu.id}
              filename={fu.filename}
              fileSize={fu.fileSize}
              chunksIndexed={fu.chunksIndexed}
              timestamp={fu.timestamp}
            />
          ))}

          {/* Optimistic user message (shown before backend responds) */}
          {pendingUserMessage && (
            <MessageBubble
              message={{
                id: '__pending_user__',
                conversation_id: activeConversationId ?? '',
                role: 'user',
                content: pendingUserMessage,
                timestamp: new Date().toISOString(),
              }}
            />
          )}

          {/* Team is working indicator */}
          {isWaitingForAgent && (
            <Box sx={{ display: 'flex', justifyContent: 'flex-start', mb: 2, px: 2 }}>
              <Box
                sx={{
                  maxWidth: '75%',
                  p: 2,
                  borderRadius: 2,
                  bgcolor: 'background.paper',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 1.5,
                }}
              >
                <Box
                  sx={{
                    display: 'flex',
                    gap: 0.5,
                    '& > span': {
                      width: 8,
                      height: 8,
                      borderRadius: '50%',
                      bgcolor: 'primary.main',
                      animation: 'pulse 1.4s ease-in-out infinite',
                    },
                    '& > span:nth-of-type(2)': { animationDelay: '0.2s' },
                    '& > span:nth-of-type(3)': { animationDelay: '0.4s' },
                    '@keyframes pulse': {
                      '0%, 80%, 100%': { opacity: 0.3, transform: 'scale(0.8)' },
                      '40%': { opacity: 1, transform: 'scale(1)' },
                    },
                  }}
                >
                  <span /><span /><span />
                </Box>
                <Typography variant="body2" color="text.secondary">
                  Team is working on your request...
                </Typography>
              </Box>
            </Box>
          )}

          {/* Streaming partial content */}
          {streamingContent && (
            <MessageBubble
              message={{
                id: '__streaming__',
                conversation_id: activeConversationId ?? '',
                role: 'agent',
                content: streamingContent,
                timestamp: new Date().toISOString(),
              }}
            />
          )}

          <div ref={messagesEndRef} />
        </Box>

        {/* Input bar */}
        <ChatInput
          onSend={handleSend}
          onAttach={handleFileAttach}
          disabled={!activeConversationId || isWaitingForAgent}
        />
      </Box>

      {/* Team selector modal */}
      <TeamSelectorModal open={teamModalOpen} onClose={() => setTeamModalOpen(false)} />
    </Box>
  );
};

export default ConversationsPage;
