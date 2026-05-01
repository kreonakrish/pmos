// Phase C.3 — per-message feedback widget.
//
// Sits beneath each assistant response in the Conversations page. Captures a
// thumbs-up/down + optional free-text comment and persists via the gateway.
// Once submitted, the widget shows a confirmation and disables further edits
// for that turn (the server-side row is the source of truth; reload to edit).

import { useState } from 'react';
import {
  Box,
  IconButton,
  TextField,
  Button,
  Stack,
  Typography,
  Tooltip,
} from '@mui/material';
import ThumbUpAltIcon from '@mui/icons-material/ThumbUpAlt';
import ThumbDownAltIcon from '@mui/icons-material/ThumbDownAlt';
import ThumbUpOffAltIcon from '@mui/icons-material/ThumbUpOffAlt';
import ThumbDownOffAltIcon from '@mui/icons-material/ThumbDownOffAlt';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import { postFeedback } from '@/api/feedback';

interface Props {
  conversationId: string;
  graphId?: string;
  traceId?: string;
  turnId?: string;
}

export default function FeedbackWidget({
  conversationId,
  graphId,
  traceId,
  turnId,
}: Props) {
  const [rating, setRating] = useState<'UP' | 'DOWN' | null>(null);
  const [comment, setComment] = useState<string>('');
  const [showComment, setShowComment] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (effectiveRating: 'UP' | 'DOWN' | 'NEUTRAL', text?: string) => {
    if (submitted || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await postFeedback(conversationId, {
        rating: effectiveRating,
        comment: text && text.trim() ? text.trim() : undefined,
        trace_id: traceId,
        graph_id: graphId,
        turn_id: turnId,
      });
      setSubmitted(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  if (submitted) {
    return (
      <Stack direction="row" spacing={0.5} alignItems="center" sx={{ mt: 0.5 }}>
        <CheckCircleIcon fontSize="inherit" color="success" />
        <Typography variant="caption" color="text.secondary">
          Thanks — feedback saved
        </Typography>
      </Stack>
    );
  }

  return (
    <Box sx={{ mt: 0.5 }}>
      <Stack direction="row" spacing={0.5} alignItems="center">
        <Tooltip title="Helpful">
          <IconButton
            size="small"
            disabled={submitting}
            onClick={() => {
              setRating('UP');
              if (!showComment) {
                void submit('UP');
              }
            }}
          >
            {rating === 'UP' ? (
              <ThumbUpAltIcon fontSize="small" color="success" />
            ) : (
              <ThumbUpOffAltIcon fontSize="small" />
            )}
          </IconButton>
        </Tooltip>
        <Tooltip title="Not helpful">
          <IconButton
            size="small"
            disabled={submitting}
            onClick={() => {
              setRating('DOWN');
              setShowComment(true);
            }}
          >
            {rating === 'DOWN' ? (
              <ThumbDownAltIcon fontSize="small" color="error" />
            ) : (
              <ThumbDownOffAltIcon fontSize="small" />
            )}
          </IconButton>
        </Tooltip>
        {!showComment && (
          <Button
            size="small"
            sx={{ textTransform: 'none', fontSize: '0.75rem' }}
            onClick={() => setShowComment(true)}
            disabled={submitting}
          >
            Add comment
          </Button>
        )}
      </Stack>

      {showComment && (
        <Stack direction="row" spacing={1} sx={{ mt: 0.5 }} alignItems="flex-end">
          <TextField
            size="small"
            placeholder={
              rating === 'DOWN'
                ? 'What was wrong? (optional)'
                : 'Share more (optional)'
            }
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            disabled={submitting}
            multiline
            maxRows={3}
            fullWidth
            inputProps={{ maxLength: 2000 }}
          />
          <Button
            size="small"
            variant="contained"
            disabled={submitting || (!rating && !comment.trim())}
            onClick={() => submit(rating ?? 'NEUTRAL', comment)}
          >
            Send
          </Button>
        </Stack>
      )}

      {error && (
        <Typography variant="caption" color="error" sx={{ display: 'block', mt: 0.5 }}>
          {error}
        </Typography>
      )}
    </Box>
  );
}
