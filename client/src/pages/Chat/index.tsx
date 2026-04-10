import React, { useEffect, useRef, useCallback, useState } from 'react';
import {
  Box,
  Typography,
  Skeleton,
  IconButton,
  Drawer,
  useTheme,
  useMediaQuery,
} from '@mui/material';
import MenuIcon from '@mui/icons-material/Menu';
import { useConversationMessages, useSendMessage } from '@/api/conversations';
import { useConversationStore } from '@/store/conversationStore';
import { useUIStore } from '@/store/uiStore';
import { useWSStore } from '@/store/wsStore';
import MessageBubble from '@/components/Chat/MessageBubble';
import ChatInput from '@/components/Chat/ChatInput';
import FileAttachmentBubble from '@/components/Chat/FileAttachmentBubble';
import ConversationList from '@/components/Chat/ConversationList';

interface FileUploadRecord {
  id: string;
  filename: string;
  fileSize: number;
  chunksIndexed: number;
  timestamp: string;
}

const SIDEBAR_WIDTH = 280;

const ChatPage: React.FC = () => {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('md'));
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const { activeConversationId, streamingContent } = useConversationStore();
  const { sidebarOpen, setSidebarOpen, toggleSidebar } = useUIStore();
  const { isStreaming } = useWSStore();
  const sendMessage = useSendMessage();
  const [fileUploads, setFileUploads] = useState<FileUploadRecord[]>([]);

  const {
    data: messages,
    isLoading: messagesLoading,
    isError: messagesError,
  } = useConversationMessages(activeConversationId);

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
      sendMessage.mutate({ conversationId: activeConversationId, content });
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

  /* ---------- Sidebar content ---------- */
  const sidebarContent = (
    <Box
      sx={{
        width: SIDEBAR_WIDTH,
        height: '100%',
        borderRight: 1,
        borderColor: 'divider',
        bgcolor: 'background.default',
      }}
    >
      <ConversationList />
    </Box>
  );

  return (
    <Box sx={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
      {/* Sidebar — responsive */}
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
        }}
      >
        {/* Header */}
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
          disabled={!activeConversationId}
        />
      </Box>
    </Box>
  );
};

export default ChatPage;
