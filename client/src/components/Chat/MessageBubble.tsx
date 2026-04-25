import React, { useState } from 'react';
import {
  Box,
  Typography,
  Chip,
  Paper,
  Stack,
  useTheme,
  IconButton,
  Collapse,
  Tooltip,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import ThumbUpOutlinedIcon from '@mui/icons-material/ThumbUpOutlined';
import ThumbDownOutlinedIcon from '@mui/icons-material/ThumbDownOutlined';
import ThumbUpIcon from '@mui/icons-material/ThumbUp';
import ThumbDownIcon from '@mui/icons-material/ThumbDown';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Message } from '@/types';
import apiClient from '@/api/axios';
import ToolCallCard from './ToolCallCard';
import StepTimeline from './StepTimeline';
import CourseCorrectionBanner from './CourseCorrectionBanner';
import VisualizationBlock from './VisualizationBlock';

interface Props {
  message: Message;
}

/**
 * Rich markdown renderer with GFM support (tables, task lists, code blocks).
 */
function MarkdownContent({ content, isUser }: { content: string; isUser: boolean }) {
  return (
    <Box
      sx={{
        '& p': { my: 0.5, lineHeight: 1.6 },
        '& p:first-of-type': { mt: 0 },
        '& p:last-of-type': { mb: 0 },
        '& ul, & ol': { pl: 2.5, my: 0.5 },
        '& li': { mb: 0.25 },
        '& code': {
          bgcolor: isUser ? 'rgba(255,255,255,0.15)' : 'action.hover',
          px: 0.5,
          borderRadius: 0.5,
          fontSize: '0.85em',
          fontFamily: 'monospace',
        },
        '& pre': {
          bgcolor: isUser ? 'rgba(0,0,0,0.2)' : 'action.hover',
          p: 1.5,
          my: 1,
          borderRadius: 1,
          overflow: 'auto',
          fontSize: '0.85rem',
          '& code': { bgcolor: 'transparent', px: 0 },
        },
        '& table': {
          borderCollapse: 'collapse',
          width: '100%',
          my: 1,
          fontSize: '0.85rem',
        },
        '& th, & td': {
          border: '1px solid',
          borderColor: isUser ? 'rgba(255,255,255,0.3)' : 'divider',
          px: 1.5,
          py: 0.75,
          textAlign: 'left',
        },
        '& th': {
          fontWeight: 600,
          bgcolor: isUser ? 'rgba(0,0,0,0.15)' : 'action.hover',
        },
        '& blockquote': {
          borderLeft: '3px solid',
          borderColor: isUser ? 'rgba(255,255,255,0.4)' : 'primary.main',
          pl: 1.5,
          my: 1,
          opacity: 0.85,
        },
        '& h1, & h2, & h3, & h4': { mt: 1.5, mb: 0.5 },
        '& strong': { fontWeight: 600 },
        '& a': { color: isUser ? 'inherit' : 'primary.main' },
        '& hr': { my: 1.5, border: 0, borderTop: '1px solid', borderColor: 'divider' },
        '& img': { maxWidth: '100%', borderRadius: 1 },
      }}
    >
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </Box>
  );
}

function scoreBandColor(score: number | undefined, band: { low: number; high: number } | undefined, theme: import('@mui/material').Theme) {
  if (score == null || !band) return theme.palette.text.secondary;
  if (score >= band.high) return theme.palette.success.main;
  if (score >= band.low) return theme.palette.warning.main;
  return theme.palette.error.main;
}

const MessageBubble: React.FC<Props> = ({ message }) => {
  const theme = useTheme();
  const isUser = message.role === 'user';
  const [showSteps, setShowSteps] = useState(false);

  return (
    <Box
      sx={{
        display: 'flex',
        justifyContent: isUser ? 'flex-end' : 'flex-start',
        mb: 2,
        px: 2,
      }}
    >
      <Box sx={{ maxWidth: '75%', minWidth: 120 }}>
        {/* Course correction banner */}
        {message.course_correction && (
          <CourseCorrectionBanner correction={message.course_correction} />
        )}

        <Paper
          elevation={1}
          sx={{
            p: 2,
            borderRadius: 2,
            bgcolor: isUser ? 'primary.main' : 'background.paper',
            color: isUser ? 'primary.contrastText' : 'text.primary',
          }}
        >
          {/* Agent metadata row */}
          {!isUser && (
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.75, mb: 1, alignItems: 'center' }}>
              {message.agent_name && (
                <Chip
                  label={message.agent_name}
                  size="small"
                  color="primary"
                  variant="outlined"
                />
              )}
              {message.score != null && (
                <Chip
                  label={`Score: ${message.score.toFixed(2)}`}
                  size="small"
                  sx={{
                    bgcolor: scoreBandColor(message.score, message.band, theme),
                    color: theme.palette.getContrastText(
                      scoreBandColor(message.score, message.band, theme),
                    ),
                  }}
                />
              )}
              {message.latency_ms != null && (
                <Chip label={`${message.latency_ms}ms`} size="small" variant="outlined" />
              )}
              {message.model && (
                <Chip label={message.model} size="small" variant="outlined" />
              )}
            </Box>
          )}

          {/* Message content */}
          <MarkdownContent content={message.content} isUser={isUser} />

          {/* Visualizations — only on assistant messages with metadata.visualizations */}
          {!isUser &&
            message.metadata?.visualizations &&
            message.metadata.visualizations.length > 0 && (
              <Stack spacing={1.5} sx={{ mt: 1.5 }}>
                {message.metadata.visualizations.map((viz, i) => (
                  <VisualizationBlock key={i} viz={viz} />
                ))}
              </Stack>
            )}

          {/* Tool calls */}
          {message.tool_calls && message.tool_calls.length > 0 && (
            <Box sx={{ mt: 1.5 }}>
              {message.tool_calls.map((tc) => (
                <ToolCallCard key={tc.id} toolCall={tc} />
              ))}
            </Box>
          )}

          {/* Steps toggle */}
          {!isUser && message.steps && message.steps.length > 0 && (
            <Box sx={{ mt: 1 }}>
              <IconButton
                size="small"
                onClick={() => setShowSteps((prev) => !prev)}
                sx={{ color: isUser ? 'primary.contrastText' : 'text.secondary' }}
              >
                {showSteps ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
              </IconButton>
              <Typography
                component="span"
                variant="caption"
                sx={{
                  cursor: 'pointer',
                  color: isUser ? 'primary.contrastText' : 'text.secondary',
                }}
                onClick={() => setShowSteps((prev) => !prev)}
              >
                {showSteps ? 'Hide Steps' : 'Show Steps'}
              </Typography>
              <Collapse in={showSteps}>
                <StepTimeline steps={message.steps} />
              </Collapse>
            </Box>
          )}

          {/* Feedback + Timestamp */}
          <Box sx={{ display: 'flex', alignItems: 'center', mt: 1, gap: 0.5 }}>
            {!isUser && message.id !== '__streaming__' && (
              <FeedbackButtons
                conversationId={message.conversation_id}
                messageId={message.id}
              />
            )}
            <Typography
              variant="caption"
              sx={{
                ml: 'auto',
                textAlign: isUser ? 'right' : 'left',
                opacity: 0.7,
              }}
            >
              {new Date(message.timestamp).toLocaleTimeString()}
            </Typography>
          </Box>
        </Paper>
      </Box>
    </Box>
  );
};

function FeedbackButtons({ conversationId, messageId }: { conversationId: string; messageId: string }) {
  const [feedback, setFeedback] = useState<'positive' | 'negative' | null>(null);
  const [sending, setSending] = useState(false);

  const sendFeedback = async (type: 'positive' | 'negative') => {
    if (feedback || sending) return;
    setSending(true);
    try {
      await apiClient.post(`/v1/conversations/${conversationId}/feedback`, {
        message_id: messageId,
        feedback: type,
      });
      setFeedback(type);
    } catch {
      // Silently fail — feedback is best-effort
    } finally {
      setSending(false);
    }
  };

  return (
    <Box sx={{ display: 'inline-flex', gap: 0 }}>
      <Tooltip title={feedback === 'positive' ? 'Thanks!' : 'Good response'}>
        <IconButton
          size="small"
          onClick={() => sendFeedback('positive')}
          disabled={sending || feedback === 'negative'}
          sx={{
            width: 26, height: 26,
            color: feedback === 'positive' ? 'success.main' : 'text.disabled',
            '&:hover': { color: 'success.main' },
          }}
        >
          {feedback === 'positive' ? <ThumbUpIcon sx={{ fontSize: 16 }} /> : <ThumbUpOutlinedIcon sx={{ fontSize: 16 }} />}
        </IconButton>
      </Tooltip>
      <Tooltip title={feedback === 'negative' ? 'Noted' : 'Poor response'}>
        <IconButton
          size="small"
          onClick={() => sendFeedback('negative')}
          disabled={sending || feedback === 'positive'}
          sx={{
            width: 26, height: 26,
            color: feedback === 'negative' ? 'error.main' : 'text.disabled',
            '&:hover': { color: 'error.main' },
          }}
        >
          {feedback === 'negative' ? <ThumbDownIcon sx={{ fontSize: 16 }} /> : <ThumbDownOutlinedIcon sx={{ fontSize: 16 }} />}
        </IconButton>
      </Tooltip>
    </Box>
  );
}

export default MessageBubble;
