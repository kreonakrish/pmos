import { useState, useCallback } from 'react';
import {
  Box,
  Typography,
  Drawer,
  IconButton,
  Divider,
  Chip,
  TextField,
  Button,
  List,
  ListItem,
  Pagination,
  Skeleton,
  Paper,
  Stack,
  useTheme,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import SearchIcon from '@mui/icons-material/Search';
import DescriptionIcon from '@mui/icons-material/Description';
import StorageIcon from '@mui/icons-material/Storage';
import LayersIcon from '@mui/icons-material/Layers';
import ScienceIcon from '@mui/icons-material/Science';
import HistoryIcon from '@mui/icons-material/History';
import { format } from 'date-fns';
import type { Document } from '@/types';
import { useTestRetrieval } from '@/api/documents';

interface DocumentDetailPanelProps {
  open: boolean;
  onClose: () => void;
  document: Document | null;
}

const STATUS_COLOR_MAP: Record<string, 'default' | 'info' | 'warning' | 'success' | 'error'> = {
  UPLOADING: 'info',
  CHUNKING: 'info',
  EMBEDDING: 'warning',
  INDEXED: 'success',
  FAILED: 'error',
};

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// Simulated chunk data for display
interface ChunkPreview {
  index: number;
  content: string;
  tokenCount: number;
}

const CHUNKS_PER_PAGE = 5;

export default function DocumentDetailPanel({ open, onClose, document: doc }: DocumentDetailPanelProps) {
  const theme = useTheme();
  const [testQuery, setTestQuery] = useState('');
  const [chunkPage, setChunkPage] = useState(1);

  const testRetrieval = useTestRetrieval();

  const handleTestRetrieval = useCallback(() => {
    if (!testQuery.trim() || !doc) return;
    testRetrieval.mutate({
      query: testQuery,
      document_id: doc.document_id,
      top_k: 5,
    });
  }, [testQuery, doc, testRetrieval]);

  if (!doc) return null;

  // Generate placeholder chunk previews based on chunk_count
  const totalChunks = doc.chunk_count ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalChunks / CHUNKS_PER_PAGE));
  const chunkPreviews: ChunkPreview[] = Array.from(
    { length: Math.min(CHUNKS_PER_PAGE, totalChunks - (chunkPage - 1) * CHUNKS_PER_PAGE) },
    (_, i) => ({
      index: (chunkPage - 1) * CHUNKS_PER_PAGE + i,
      content: `Chunk ${(chunkPage - 1) * CHUNKS_PER_PAGE + i + 1} content preview...`,
      tokenCount: Math.floor(Math.random() * 200) + 300,
    })
  );

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      PaperProps={{
        sx: {
          width: { xs: '100%', sm: 420 },
          bgcolor: 'background.paper',
        },
      }}
    >
      {/* Header */}
      <Box
        sx={{
          p: 2,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          borderBottom: `1px solid ${theme.palette.divider}`,
        }}
      >
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="subtitle1" fontWeight={700} noWrap>
            {doc.filename}
          </Typography>
          <Chip
            label={doc.status}
            size="small"
            color={STATUS_COLOR_MAP[doc.status] ?? 'default'}
            sx={{ mt: 0.5, fontWeight: 600, fontSize: '0.7rem' }}
          />
        </Box>
        <IconButton size="small" onClick={onClose}>
          <CloseIcon />
        </IconButton>
      </Box>

      <Box sx={{ overflow: 'auto', flex: 1 }}>
        {/* File Metadata */}
        <Box sx={{ p: 2 }}>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.5 }}>
            <DescriptionIcon fontSize="small" color="primary" />
            <Typography variant="subtitle2" fontWeight={700}>
              File Metadata
            </Typography>
          </Stack>
          <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1.5 }}>
            <Box>
              <Typography variant="caption" color="text.secondary">
                Filename
              </Typography>
              <Typography variant="body2" noWrap>
                {doc.filename}
              </Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">
                Size
              </Typography>
              <Typography variant="body2">{formatFileSize(doc.file_size)}</Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">
                MIME Type
              </Typography>
              <Typography variant="body2">{doc.mime_type}</Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">
                Uploaded
              </Typography>
              <Typography variant="body2">
                {format(new Date(doc.created_at), 'MMM d, yyyy HH:mm')}
              </Typography>
            </Box>
          </Box>
        </Box>

        <Divider />

        {/* Ingestion Details */}
        <Box sx={{ p: 2 }}>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.5 }}>
            <LayersIcon fontSize="small" color="primary" />
            <Typography variant="subtitle2" fontWeight={700}>
              Ingestion Details
            </Typography>
          </Stack>
          <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1.5 }}>
            <Box>
              <Typography variant="caption" color="text.secondary">
                Chunk Count
              </Typography>
              <Typography variant="body2" fontWeight={600}>
                {doc.chunk_count ?? 'N/A'}
              </Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">
                Embedding Model
              </Typography>
              <Typography variant="body2" sx={{ fontSize: '0.8rem' }}>
                {doc.embedding_model ?? 'all-mpnet-base-v2'}
              </Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">
                Agent
              </Typography>
              <Typography variant="body2">
                {doc.agent_id ? `Agent #${doc.agent_id}` : 'None'}
              </Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">
                Team
              </Typography>
              <Typography variant="body2">{doc.team_id ?? 'None'}</Typography>
            </Box>
          </Box>
        </Box>

        <Divider />

        {/* Vector Store Info */}
        <Box sx={{ p: 2 }}>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.5 }}>
            <StorageIcon fontSize="small" color="primary" />
            <Typography variant="subtitle2" fontWeight={700}>
              Vector Store
            </Typography>
          </Stack>
          <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
            <Chip label={`doc_${doc.document_id}`} size="small" variant="outlined" sx={{ fontSize: '0.7rem' }} />
            {doc.agent_id && (
              <Chip
                label={`agent_${doc.agent_id}`}
                size="small"
                variant="outlined"
                sx={{ fontSize: '0.7rem' }}
              />
            )}
          </Stack>
        </Box>

        <Divider />

        {/* Chunk Viewer */}
        {totalChunks > 0 && (
          <Box sx={{ p: 2 }}>
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.5 }}>
              <LayersIcon fontSize="small" color="primary" />
              <Typography variant="subtitle2" fontWeight={700}>
                Chunks ({totalChunks})
              </Typography>
            </Stack>
            <List dense disablePadding>
              {chunkPreviews.map((chunk) => (
                <ListItem
                  key={chunk.index}
                  sx={{
                    borderRadius: 1,
                    mb: 0.5,
                    bgcolor: 'background.default',
                    flexDirection: 'column',
                    alignItems: 'flex-start',
                  }}
                >
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', width: '100%', mb: 0.25 }}>
                    <Typography variant="caption" fontWeight={600}>
                      #{chunk.index + 1}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      ~{chunk.tokenCount} tokens
                    </Typography>
                  </Box>
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    sx={{
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      display: '-webkit-box',
                      WebkitLineClamp: 2,
                      WebkitBoxOrient: 'vertical',
                    }}
                  >
                    {chunk.content}
                  </Typography>
                </ListItem>
              ))}
            </List>
            {totalPages > 1 && (
              <Box sx={{ display: 'flex', justifyContent: 'center', mt: 1 }}>
                <Pagination
                  count={totalPages}
                  page={chunkPage}
                  onChange={(_, page) => setChunkPage(page)}
                  size="small"
                />
              </Box>
            )}
          </Box>
        )}

        <Divider />

        {/* Test Retrieval */}
        <Box sx={{ p: 2 }}>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.5 }}>
            <ScienceIcon fontSize="small" color="primary" />
            <Typography variant="subtitle2" fontWeight={700}>
              Test Retrieval
            </Typography>
          </Stack>
          <Box sx={{ display: 'flex', gap: 1, mb: 1.5 }}>
            <TextField
              size="small"
              fullWidth
              placeholder="Enter a test query..."
              value={testQuery}
              onChange={(e) => setTestQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleTestRetrieval()}
            />
            <Button
              variant="contained"
              size="small"
              onClick={handleTestRetrieval}
              disabled={!testQuery.trim() || testRetrieval.isPending}
              sx={{ minWidth: 'auto', px: 2 }}
            >
              <SearchIcon fontSize="small" />
            </Button>
          </Box>

          {testRetrieval.isPending && (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} variant="rectangular" height={48} sx={{ borderRadius: 1 }} />
              ))}
            </Box>
          )}

          {testRetrieval.data && (
            <List dense disablePadding>
              {testRetrieval.data.results.map((result, idx) => (
                <ListItem
                  key={idx}
                  sx={{
                    borderRadius: 1,
                    mb: 0.5,
                    bgcolor: 'background.default',
                    flexDirection: 'column',
                    alignItems: 'flex-start',
                  }}
                >
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', width: '100%', mb: 0.25 }}>
                    <Chip
                      label={result.source}
                      size="small"
                      sx={{ height: 18, fontSize: '0.6rem' }}
                    />
                    <Typography variant="caption" fontWeight={600} color="primary.main">
                      {(result.score * 100).toFixed(1)}%
                    </Typography>
                  </Box>
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    sx={{
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      display: '-webkit-box',
                      WebkitLineClamp: 3,
                      WebkitBoxOrient: 'vertical',
                    }}
                  >
                    {result.content}
                  </Typography>
                </ListItem>
              ))}
              {testRetrieval.data.results.length === 0 && (
                <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center', py: 2 }}>
                  No results found
                </Typography>
              )}
            </List>
          )}

          {testRetrieval.isError && (
            <Paper sx={{ p: 2, bgcolor: `${theme.palette.error.main}10` }}>
              <Typography variant="body2" color="error">
                Retrieval test failed. The RAG service may be unavailable.
              </Typography>
            </Paper>
          )}
        </Box>

        <Divider />

        {/* Activity placeholder */}
        <Box sx={{ p: 2 }}>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.5 }}>
            <HistoryIcon fontSize="small" color="primary" />
            <Typography variant="subtitle2" fontWeight={700}>
              Activity
            </Typography>
          </Stack>
          <Typography variant="body2" color="text.secondary">
            No activity recorded yet for this document.
          </Typography>
        </Box>
      </Box>
    </Drawer>
  );
}
