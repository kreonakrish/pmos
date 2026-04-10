import { useState, useCallback, useRef } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Box,
  Typography,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  IconButton,
  LinearProgress,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  ListItemSecondaryAction,
  Chip,
  Slider,
  Divider,
  useTheme,
} from '@mui/material';
import CloudUploadIcon from '@mui/icons-material/CloudUpload';
import InsertDriveFileIcon from '@mui/icons-material/InsertDriveFile';
import CloseIcon from '@mui/icons-material/Close';
import DeleteIcon from '@mui/icons-material/Delete';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import TuneIcon from '@mui/icons-material/Tune';
import { useUploadDocument, useRagConfig } from '@/api/documents';
import { useAgents } from '@/api/agents';

type FileStatus = 'queued' | 'uploading' | 'chunking' | 'embedding' | 'indexed' | 'failed';

interface QueuedFile {
  file: File;
  id: string;
  status: FileStatus;
  progress: number;
}

interface UploadDialogProps {
  open: boolean;
  onClose: () => void;
}

const STATUS_LABELS: Record<FileStatus, string> = {
  queued: 'Queued',
  uploading: 'Uploading',
  chunking: 'Chunking',
  embedding: 'Embedding',
  indexed: 'Indexed',
  failed: 'Failed',
};

const ACCEPTED_FORMATS = '.pdf,.csv,.txt,.json,.xlsx,.docx,.md,.html,.htm';

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function UploadDialog({ open, onClose }: UploadDialogProps) {
  const theme = useTheme();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [files, setFiles] = useState<QueuedFile[]>([]);
  const [chunkStrategy, setChunkStrategy] = useState('sentence');
  const [chunkSize, setChunkSize] = useState(500);
  const [chunkOverlap, setChunkOverlap] = useState(50);
  const [embeddingModel, setEmbeddingModel] = useState('');
  const [agentId, setAgentId] = useState<number | ''>('');
  const [isUploading, setIsUploading] = useState(false);
  const [isDragOver, setIsDragOver] = useState(false);

  const uploadDocument = useUploadDocument();
  const { data: agents } = useAgents();
  const { data: ragConfig } = useRagConfig();

  const addFiles = useCallback((fileList: FileList | null) => {
    if (!fileList) return;
    const newFiles: QueuedFile[] = Array.from(fileList).map((file) => ({
      file,
      id: `${file.name}-${Date.now()}-${Math.random()}`,
      status: 'queued' as FileStatus,
      progress: 0,
    }));
    setFiles((prev) => [...prev, ...newFiles]);
  }, []);

  const removeFile = useCallback((id: string) => {
    setFiles((prev) => prev.filter((f) => f.id !== id));
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragOver(false);
      addFiles(e.dataTransfer.files);
    },
    [addFiles]
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setIsDragOver(false);
  }, []);

  const handleUpload = useCallback(async () => {
    if (files.length === 0) return;
    setIsUploading(true);

    for (let i = 0; i < files.length; i++) {
      const qf = files[i];
      if (qf.status !== 'queued') continue;

      setFiles((prev) =>
        prev.map((f) => (f.id === qf.id ? { ...f, status: 'uploading', progress: 20 } : f))
      );

      try {
        await uploadDocument.mutateAsync({
          file: qf.file,
          agent_id: agentId === '' ? undefined : agentId,
          chunk_strategy: chunkStrategy,
          chunk_size: chunkSize,
          chunk_overlap: chunkOverlap,
          embedding_model: embeddingModel || undefined,
        });

        setFiles((prev) =>
          prev.map((f) => (f.id === qf.id ? { ...f, status: 'chunking', progress: 50 } : f))
        );
        await new Promise((r) => setTimeout(r, 200));

        setFiles((prev) =>
          prev.map((f) => (f.id === qf.id ? { ...f, status: 'embedding', progress: 75 } : f))
        );
        await new Promise((r) => setTimeout(r, 200));

        setFiles((prev) =>
          prev.map((f) => (f.id === qf.id ? { ...f, status: 'indexed', progress: 100 } : f))
        );
      } catch {
        setFiles((prev) =>
          prev.map((f) => (f.id === qf.id ? { ...f, status: 'failed', progress: 0 } : f))
        );
      }
    }

    setIsUploading(false);
  }, [files, uploadDocument, agentId, chunkStrategy, chunkSize, chunkOverlap, embeddingModel]);

  const handleClose = useCallback(() => {
    if (isUploading) return;
    setFiles([]);
    setChunkStrategy('sentence');
    setChunkSize(ragConfig?.chunk_size ?? 500);
    setChunkOverlap(ragConfig?.chunk_overlap ?? 50);
    setEmbeddingModel('');
    setAgentId('');
    onClose();
  }, [isUploading, onClose, ragConfig]);

  const allDone = files.length > 0 && files.every((f) => f.status === 'indexed' || f.status === 'failed');

  const getStatusColor = (status: FileStatus) => {
    switch (status) {
      case 'indexed': return 'success';
      case 'failed': return 'error';
      case 'queued': return 'default';
      default: return 'info';
    }
  };

  const availableModels = ragConfig?.available_models ?? [
    'sentence-transformers/all-mpnet-base-v2',
    'sentence-transformers/all-MiniLM-L6-v2',
  ];
  const defaultModel = ragConfig?.embedding_model ?? 'sentence-transformers/all-mpnet-base-v2';

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="md" fullWidth>
      <DialogTitle sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        Upload Documents
        <IconButton size="small" onClick={handleClose} disabled={isUploading}>
          <CloseIcon />
        </IconButton>
      </DialogTitle>

      <DialogContent>
        {/* Drop Zone */}
        <Box
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onClick={() => fileInputRef.current?.click()}
          sx={{
            border: `2px dashed ${isDragOver ? theme.palette.primary.main : theme.palette.divider}`,
            borderRadius: 2,
            p: 3,
            textAlign: 'center',
            cursor: 'pointer',
            bgcolor: isDragOver ? `${theme.palette.primary.main}10` : 'transparent',
            transition: 'all 0.2s',
            mb: 2,
            '&:hover': { borderColor: 'primary.main', bgcolor: `${theme.palette.primary.main}05` },
          }}
        >
          <CloudUploadIcon sx={{ fontSize: 40, color: 'text.secondary', mb: 0.5 }} />
          <Typography variant="body1" fontWeight={600}>
            Drop files here or click to browse
          </Typography>
          <Typography variant="caption" color="text.secondary">
            PDF, DOCX, XLSX, CSV, TXT, JSON, MD, HTML
          </Typography>
        </Box>

        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPTED_FORMATS}
          multiple
          hidden
          onChange={(e) => addFiles(e.target.files)}
        />

        {/* File Queue */}
        {files.length > 0 && (
          <List dense sx={{ mb: 2, maxHeight: 200, overflow: 'auto' }}>
            {files.map((qf) => (
              <ListItem key={qf.id} sx={{ borderRadius: 1, mb: 0.5, bgcolor: 'background.default' }}>
                <ListItemIcon sx={{ minWidth: 36 }}>
                  {qf.status === 'indexed' ? (
                    <CheckCircleIcon color="success" fontSize="small" />
                  ) : qf.status === 'failed' ? (
                    <ErrorIcon color="error" fontSize="small" />
                  ) : (
                    <InsertDriveFileIcon fontSize="small" sx={{ color: 'text.secondary' }} />
                  )}
                </ListItemIcon>
                <ListItemText
                  primary={<Typography variant="body2" fontWeight={600} noWrap>{qf.file.name}</Typography>}
                  secondary={
                    <Box>
                      <Typography variant="caption" color="text.secondary">{formatFileSize(qf.file.size)}</Typography>
                      {qf.status !== 'queued' && (
                        <LinearProgress
                          variant="determinate" value={qf.progress}
                          color={qf.status === 'failed' ? 'error' : 'primary'}
                          sx={{ height: 3, borderRadius: 2, mt: 0.5 }}
                        />
                      )}
                    </Box>
                  }
                />
                <ListItemSecondaryAction>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Chip label={STATUS_LABELS[qf.status]} size="small" color={getStatusColor(qf.status)} sx={{ height: 20, fontSize: '0.65rem' }} />
                    {qf.status === 'queued' && (
                      <IconButton size="small" onClick={() => removeFile(qf.id)}><DeleteIcon fontSize="small" /></IconButton>
                    )}
                  </Box>
                </ListItemSecondaryAction>
              </ListItem>
            ))}
          </List>
        )}

        {/* Parser Configuration */}
        <Divider sx={{ my: 2 }}>
          <Chip icon={<TuneIcon />} label="Parser Configuration" size="small" />
        </Divider>

        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2.5 }}>
          {/* Row 1: Strategy + Embedding Model */}
          <Box sx={{ display: 'flex', gap: 2 }}>
            <FormControl size="small" sx={{ flex: 1 }}>
              <InputLabel>Chunk Strategy</InputLabel>
              <Select value={chunkStrategy} label="Chunk Strategy" onChange={(e) => setChunkStrategy(e.target.value)}>
                <MenuItem value="fixed">Fixed (character split)</MenuItem>
                <MenuItem value="sentence">Sentence (respects boundaries)</MenuItem>
                <MenuItem value="paragraph">Paragraph (double newlines)</MenuItem>
              </Select>
            </FormControl>

            <FormControl size="small" sx={{ flex: 1 }}>
              <InputLabel>Embedding Model</InputLabel>
              <Select
                value={embeddingModel || defaultModel}
                label="Embedding Model"
                onChange={(e) => setEmbeddingModel(e.target.value)}
              >
                {availableModels.map((m) => (
                  <MenuItem key={m} value={m}>
                    <Typography variant="body2" noWrap>
                      {m.replace('sentence-transformers/', '')}
                      {m === defaultModel && ' (default)'}
                    </Typography>
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Box>

          {/* Row 2: Chunk Size + Overlap */}
          <Box sx={{ display: 'flex', gap: 3 }}>
            <Box sx={{ flex: 1 }}>
              <Typography variant="caption" color="text.secondary" gutterBottom>
                Chunk Size: {chunkSize} tokens
              </Typography>
              <Slider
                value={chunkSize}
                onChange={(_e, val) => setChunkSize(val as number)}
                min={100}
                max={4000}
                step={50}
                marks={[
                  { value: 100, label: '100' },
                  { value: 500, label: '500' },
                  { value: 1000, label: '1K' },
                  { value: 2000, label: '2K' },
                  { value: 4000, label: '4K' },
                ]}
                size="small"
              />
            </Box>

            <Box sx={{ flex: 1 }}>
              <Typography variant="caption" color="text.secondary" gutterBottom>
                Chunk Overlap: {chunkOverlap} tokens
              </Typography>
              <Slider
                value={chunkOverlap}
                onChange={(_e, val) => setChunkOverlap(val as number)}
                min={0}
                max={Math.min(500, Math.floor(chunkSize / 2))}
                step={10}
                marks={[
                  { value: 0, label: '0' },
                  { value: 50, label: '50' },
                  { value: 100, label: '100' },
                ]}
                size="small"
              />
            </Box>
          </Box>

          {/* Row 3: Agent */}
          <FormControl size="small" fullWidth>
            <InputLabel>Associate with Agent (optional)</InputLabel>
            <Select value={agentId} label="Associate with Agent (optional)" onChange={(e) => setAgentId(e.target.value as number | '')}>
              <MenuItem value=""><em>None</em></MenuItem>
              {agents?.map((agent) => (
                <MenuItem key={agent.id} value={agent.id}>{agent.name}</MenuItem>
              ))}
            </Select>
          </FormControl>
        </Box>
      </DialogContent>

      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={handleClose} disabled={isUploading}>
          {allDone ? 'Close' : 'Cancel'}
        </Button>
        <Button variant="contained" onClick={handleUpload} disabled={files.length === 0 || isUploading || allDone}>
          {isUploading ? 'Processing...' : 'Upload & Index'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
