import React from 'react';
import { Box, Paper, Typography, Chip } from '@mui/material';
import PictureAsPdfIcon from '@mui/icons-material/PictureAsPdf';
import DescriptionIcon from '@mui/icons-material/Description';
import TableChartIcon from '@mui/icons-material/TableChart';
import DataObjectIcon from '@mui/icons-material/DataObject';
import CodeIcon from '@mui/icons-material/Code';
import ArticleIcon from '@mui/icons-material/Article';
import InsertDriveFileIcon from '@mui/icons-material/InsertDriveFile';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';

interface Props {
  filename: string;
  fileSize?: number;
  chunksIndexed?: number;
  timestamp: string;
}

function getFileIcon(filename: string) {
  const ext = filename.split('.').pop()?.toLowerCase() ?? '';
  const iconProps = { sx: { fontSize: 36 } };
  switch (ext) {
    case 'pdf': return <PictureAsPdfIcon {...iconProps} sx={{ ...iconProps.sx, color: '#e53935' }} />;
    case 'docx': case 'doc': return <DescriptionIcon {...iconProps} sx={{ ...iconProps.sx, color: '#1565c0' }} />;
    case 'xlsx': case 'xls': case 'csv': return <TableChartIcon {...iconProps} sx={{ ...iconProps.sx, color: '#2e7d32' }} />;
    case 'json': return <DataObjectIcon {...iconProps} sx={{ ...iconProps.sx, color: '#f57c00' }} />;
    case 'html': case 'htm': return <CodeIcon {...iconProps} sx={{ ...iconProps.sx, color: '#7b1fa2' }} />;
    case 'md': return <ArticleIcon {...iconProps} sx={{ ...iconProps.sx, color: '#455a64' }} />;
    default: return <InsertDriveFileIcon {...iconProps} sx={{ ...iconProps.sx, color: '#78909c' }} />;
  }
}

function getFileTypeLabel(filename: string): string {
  const ext = filename.split('.').pop()?.toUpperCase() ?? 'FILE';
  const labels: Record<string, string> = {
    PDF: 'PDF Document', DOCX: 'Word Document', DOC: 'Word Document',
    XLSX: 'Excel Spreadsheet', XLS: 'Excel Spreadsheet', CSV: 'CSV Data',
    JSON: 'JSON Data', HTML: 'HTML Page', HTM: 'HTML Page',
    MD: 'Markdown', TXT: 'Text File',
  };
  return labels[ext] ?? `${ext} File`;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const FileAttachmentBubble: React.FC<Props> = ({ filename, fileSize, chunksIndexed, timestamp }) => {
  return (
    <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 2, px: 2 }}>
      <Box sx={{ maxWidth: '75%', minWidth: 240 }}>
        <Paper
          elevation={1}
          sx={{
            borderRadius: 2,
            overflow: 'hidden',
            bgcolor: 'primary.main',
            color: 'primary.contrastText',
          }}
        >
          {/* File card */}
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 1.5,
              p: 1.5,
              bgcolor: 'rgba(255,255,255,0.12)',
              borderBottom: '1px solid rgba(255,255,255,0.1)',
            }}
          >
            {/* Icon with accent background */}
            <Box
              sx={{
                width: 48,
                height: 48,
                borderRadius: 1.5,
                bgcolor: 'rgba(255,255,255,0.9)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
              }}
            >
              {getFileIcon(filename)}
            </Box>

            {/* File details */}
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography variant="body2" fontWeight={600} noWrap>
                {filename}
              </Typography>
              <Typography variant="caption" sx={{ opacity: 0.8 }}>
                {getFileTypeLabel(filename)}
                {fileSize ? ` \u00B7 ${formatSize(fileSize)}` : ''}
              </Typography>
            </Box>

            <CheckCircleIcon sx={{ fontSize: 20, opacity: 0.9 }} />
          </Box>

          {/* Status bar */}
          <Box sx={{ px: 1.5, py: 1, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <Box sx={{ display: 'flex', gap: 0.75 }}>
              <Chip
                label="Indexed"
                size="small"
                sx={{
                  height: 20,
                  fontSize: '0.65rem',
                  bgcolor: 'rgba(255,255,255,0.2)',
                  color: 'inherit',
                }}
              />
              {chunksIndexed != null && (
                <Chip
                  label={`${chunksIndexed} chunk${chunksIndexed !== 1 ? 's' : ''}`}
                  size="small"
                  sx={{
                    height: 20,
                    fontSize: '0.65rem',
                    bgcolor: 'rgba(255,255,255,0.2)',
                    color: 'inherit',
                  }}
                />
              )}
            </Box>
            <Typography variant="caption" sx={{ opacity: 0.7 }}>
              {new Date(timestamp).toLocaleTimeString()}
            </Typography>
          </Box>
        </Paper>
      </Box>
    </Box>
  );
};

export default FileAttachmentBubble;
