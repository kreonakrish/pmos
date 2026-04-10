import React, { useState, useCallback, useRef } from 'react';
import {
  Box,
  TextField,
  IconButton,
  Typography,
  Paper,
  LinearProgress,
  useTheme,
} from '@mui/material';
import SendIcon from '@mui/icons-material/Send';
import AttachFileIcon from '@mui/icons-material/AttachFile';
import StopCircleIcon from '@mui/icons-material/StopCircle';
import CloseIcon from '@mui/icons-material/Close';
import PictureAsPdfIcon from '@mui/icons-material/PictureAsPdf';
import DescriptionIcon from '@mui/icons-material/Description';
import TableChartIcon from '@mui/icons-material/TableChart';
import DataObjectIcon from '@mui/icons-material/DataObject';
import CodeIcon from '@mui/icons-material/Code';
import ArticleIcon from '@mui/icons-material/Article';
import InsertDriveFileIcon from '@mui/icons-material/InsertDriveFile';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import { useWSStore } from '@/store/wsStore';

export type FileUploadStatus = 'staged' | 'uploading' | 'success' | 'error';

export interface FileAttachment {
  file: File;
  status: FileUploadStatus;
  error?: string;
  documentId?: string;
  chunksIndexed?: number;
}

interface Props {
  onSend: (content: string, attachment?: FileAttachment) => void;
  onAttach?: (file: File) => Promise<{ document_id: string; chunks_indexed: number }>;
  disabled?: boolean;
}

const MAX_CHARS = 4000;
const MAX_ROWS = 4;

function getFileIcon(filename: string) {
  const ext = filename.split('.').pop()?.toLowerCase() ?? '';
  switch (ext) {
    case 'pdf': return <PictureAsPdfIcon sx={{ fontSize: 32, color: '#e53935' }} />;
    case 'docx': case 'doc': return <DescriptionIcon sx={{ fontSize: 32, color: '#1565c0' }} />;
    case 'xlsx': case 'xls': case 'csv': return <TableChartIcon sx={{ fontSize: 32, color: '#2e7d32' }} />;
    case 'json': return <DataObjectIcon sx={{ fontSize: 32, color: '#f57c00' }} />;
    case 'html': case 'htm': return <CodeIcon sx={{ fontSize: 32, color: '#7b1fa2' }} />;
    case 'md': return <ArticleIcon sx={{ fontSize: 32, color: '#455a64' }} />;
    default: return <InsertDriveFileIcon sx={{ fontSize: 32, color: '#78909c' }} />;
  }
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const ChatInput: React.FC<Props> = ({ onSend, onAttach, disabled = false }) => {
  const theme = useTheme();
  const [value, setValue] = useState('');
  const [attachment, setAttachment] = useState<FileAttachment | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { isStreaming, abort } = useWSStore();

  const canSend = (value.trim().length > 0 || attachment?.status === 'success') && !isStreaming && !disabled;
  const isUploading = attachment?.status === 'uploading';

  const handleSend = useCallback(() => {
    if (!canSend) return;
    const msg = value.trim() || (attachment ? `Uploaded: ${attachment.file.name}` : '');
    onSend(msg, attachment ?? undefined);
    setValue('');
    setAttachment(null);
  }, [canSend, value, onSend, attachment]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  const handleFileChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file || !onAttach) return;

      // Stage the file
      setAttachment({ file, status: 'staged' });

      // Start uploading
      setAttachment({ file, status: 'uploading' });

      try {
        const result = await onAttach(file);
        setAttachment({
          file,
          status: 'success',
          documentId: result.document_id,
          chunksIndexed: result.chunks_indexed,
        });
      } catch (err) {
        setAttachment({
          file,
          status: 'error',
          error: err instanceof Error ? err.message : 'Upload failed',
        });
      }

      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    },
    [onAttach],
  );

  const clearAttachment = useCallback(() => {
    if (!isUploading) setAttachment(null);
  }, [isUploading]);

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        borderTop: 1,
        borderColor: 'divider',
        bgcolor: 'background.paper',
      }}
    >
      {/* File preview card */}
      {attachment && (
        <Box sx={{ px: 2, pt: 1.5 }}>
          <Paper
            variant="outlined"
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 1.5,
              p: 1.5,
              borderRadius: 2,
              bgcolor: attachment.status === 'error'
                ? `${theme.palette.error.main}08`
                : attachment.status === 'success'
                ? `${theme.palette.success.main}08`
                : 'background.default',
              borderColor: attachment.status === 'error'
                ? 'error.main'
                : attachment.status === 'success'
                ? 'success.main'
                : 'divider',
            }}
          >
            {/* File icon */}
            {getFileIcon(attachment.file.name)}

            {/* File info */}
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography variant="body2" fontWeight={600} noWrap>
                {attachment.file.name}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {formatSize(attachment.file.size)}
                {attachment.status === 'success' && attachment.chunksIndexed != null && (
                  <> &middot; {attachment.chunksIndexed} chunk{attachment.chunksIndexed !== 1 ? 's' : ''} indexed</>
                )}
                {attachment.status === 'error' && (
                  <Box component="span" sx={{ color: 'error.main' }}> &middot; {attachment.error}</Box>
                )}
              </Typography>

              {/* Upload progress */}
              {attachment.status === 'uploading' && (
                <LinearProgress sx={{ mt: 0.5, height: 3, borderRadius: 2 }} />
              )}
            </Box>

            {/* Status icon */}
            {attachment.status === 'success' && (
              <CheckCircleIcon color="success" fontSize="small" />
            )}
            {attachment.status === 'error' && (
              <ErrorOutlineIcon color="error" fontSize="small" />
            )}

            {/* Close button */}
            {!isUploading && (
              <IconButton size="small" onClick={clearAttachment} sx={{ ml: -0.5 }}>
                <CloseIcon fontSize="small" />
              </IconButton>
            )}
          </Paper>
        </Box>
      )}

      {/* Input row */}
      <Box sx={{ display: 'flex', alignItems: 'flex-end', gap: 1, p: 2, pt: attachment ? 1 : 2 }}>
        {/* Hidden file input */}
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.csv,.txt,.json,.xlsx,.docx,.md,.html,.htm"
          hidden
          onChange={handleFileChange}
        />

        {/* Attach button */}
        <IconButton
          size="small"
          onClick={() => fileInputRef.current?.click()}
          disabled={isStreaming || disabled || isUploading}
          sx={{ color: 'text.secondary' }}
        >
          <AttachFileIcon />
        </IconButton>

        {/* Text input */}
        <Box sx={{ flex: 1, position: 'relative' }}>
          <TextField
            multiline
            maxRows={MAX_ROWS}
            fullWidth
            placeholder={attachment?.status === 'success' ? 'Add a message about this file...' : 'Type a message...'}
            value={value}
            onChange={(e) => setValue(e.target.value.slice(0, MAX_CHARS))}
            onKeyDown={handleKeyDown}
            disabled={disabled || isUploading}
            size="small"
            sx={{
              '& .MuiOutlinedInput-root': {
                borderRadius: 2,
                bgcolor: theme.palette.action.hover,
              },
            }}
          />
          <Typography
            variant="caption"
            sx={{
              position: 'absolute',
              bottom: -18,
              right: 4,
              color: value.length > MAX_CHARS * 0.9 ? 'warning.main' : 'text.disabled',
            }}
          >
            {value.length}/{MAX_CHARS}
          </Typography>
        </Box>

        {/* Send / Stop button */}
        {isStreaming ? (
          <IconButton onClick={abort} color="error" size="small">
            <StopCircleIcon />
          </IconButton>
        ) : (
          <IconButton
            onClick={handleSend}
            disabled={!canSend}
            color="primary"
            size="small"
          >
            <SendIcon />
          </IconButton>
        )}
      </Box>
    </Box>
  );
};

export default ChatInput;
