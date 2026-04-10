import { useState, useMemo, useCallback } from 'react';
import {
  Box,
  Typography,
  TextField,
  InputAdornment,
  Button,
  Chip,
  Stack,
  Grid,
  Card,
  CardContent,
  CardActionArea,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  IconButton,
  Tooltip,
  Skeleton,
  ToggleButtonGroup,
  ToggleButton,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
  useTheme,
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import CloudUploadIcon from '@mui/icons-material/CloudUpload';
import GridViewIcon from '@mui/icons-material/GridView';
import TableRowsIcon from '@mui/icons-material/TableRows';
import RefreshIcon from '@mui/icons-material/Refresh';
import DeleteIcon from '@mui/icons-material/Delete';
import ReplayIcon from '@mui/icons-material/Replay';
import PictureAsPdfIcon from '@mui/icons-material/PictureAsPdf';
import TableChartIcon from '@mui/icons-material/TableChart';
import DescriptionIcon from '@mui/icons-material/Description';
import DataObjectIcon from '@mui/icons-material/DataObject';
import ArticleIcon from '@mui/icons-material/Article';
import InsertDriveFileIcon from '@mui/icons-material/InsertDriveFile';
import { format } from 'date-fns';
import type { Document } from '@/types';
import { useDocuments, useDeleteDocument, useReindexDocument } from '@/api/documents';
import UploadDialog from './UploadDialog';
import DocumentDetailPanel from './DocumentDetailPanel';

type FileTypeFilter = 'ALL' | 'PDF' | 'CSV' | 'TXT' | 'JSON' | 'XLSX' | 'DOCX' | 'MD';
type ViewMode = 'grid' | 'table';

const FILE_TYPE_FILTERS: FileTypeFilter[] = ['ALL', 'PDF', 'CSV', 'TXT', 'JSON', 'XLSX', 'DOCX', 'MD'];

const STATUS_COLOR_MAP: Record<string, 'default' | 'info' | 'warning' | 'success' | 'error'> = {
  UPLOADING: 'info',
  CHUNKING: 'info',
  EMBEDDING: 'warning',
  INDEXED: 'success',
  FAILED: 'error',
};

const FILE_TYPE_ICONS: Record<string, typeof PictureAsPdfIcon> = {
  pdf: PictureAsPdfIcon,
  csv: TableChartIcon,
  txt: DescriptionIcon,
  json: DataObjectIcon,
  xlsx: TableChartIcon,
  docx: ArticleIcon,
  md: ArticleIcon,
};

const FILE_TYPE_COLORS: Record<string, string> = {
  pdf: 'error.main',
  csv: 'success.main',
  txt: 'text.secondary',
  json: 'warning.main',
  xlsx: 'success.dark',
  docx: 'primary.main',
  md: 'info.main',
};

function getFileExtension(filename: string): string {
  return filename.split('.').pop()?.toLowerCase() ?? '';
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function getFileIcon(filename: string) {
  const ext = getFileExtension(filename);
  return FILE_TYPE_ICONS[ext] ?? InsertDriveFileIcon;
}

function getFileColor(filename: string): string {
  const ext = getFileExtension(filename);
  return FILE_TYPE_COLORS[ext] ?? 'text.secondary';
}

export default function DocumentsPage() {
  const theme = useTheme();

  const [search, setSearch] = useState('');
  const [fileTypeFilter, setFileTypeFilter] = useState<FileTypeFilter>('ALL');
  const [viewMode, setViewMode] = useState<ViewMode>('grid');
  const [uploadOpen, setUploadOpen] = useState(false);
  const [selectedDoc, setSelectedDoc] = useState<Document | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<Document | null>(null);

  const { data: documents, isLoading, isError, refetch } = useDocuments();
  const deleteDocument = useDeleteDocument();
  const reindexDocument = useReindexDocument();

  const filtered = useMemo(() => {
    if (!documents) return [];
    return documents.filter((doc) => {
      const matchSearch =
        !search || doc.filename.toLowerCase().includes(search.toLowerCase());
      const matchType =
        fileTypeFilter === 'ALL' ||
        getFileExtension(doc.filename).toUpperCase() === fileTypeFilter;
      return matchSearch && matchType;
    });
  }, [documents, search, fileTypeFilter]);

  const handleDocClick = useCallback((doc: Document) => {
    setSelectedDoc(doc);
    setDetailOpen(true);
  }, []);

  const handleDelete = useCallback(
    (doc: Document) => {
      deleteDocument.mutate(doc.document_id, {
        onSuccess: () => {
          setDeleteConfirm(null);
          if (selectedDoc?.document_id === doc.document_id) {
            setDetailOpen(false);
            setSelectedDoc(null);
          }
        },
      });
    },
    [deleteDocument, selectedDoc]
  );

  const handleReindex = useCallback(
    (doc: Document) => {
      // Reindex with current parser config
      reindexDocument.mutate({
        docId: doc.document_id,
        chunk_strategy: 'sentence',
        chunk_size: 500,
      });
    },
    [reindexDocument]
  );

  // Loading state
  if (isLoading) {
    return (
      <Box sx={{ p: 3 }}>
        <Skeleton variant="text" width={200} height={40} />
        <Skeleton variant="rectangular" height={48} sx={{ mt: 2, borderRadius: 1 }} />
        <Grid container spacing={2} sx={{ mt: 2 }}>
          {Array.from({ length: 8 }).map((_, i) => (
            <Grid item xs={12} sm={6} md={4} lg={3} key={i}>
              <Skeleton variant="rectangular" height={160} sx={{ borderRadius: 2 }} />
            </Grid>
          ))}
        </Grid>
      </Box>
    );
  }

  // Error state
  if (isError) {
    return (
      <Box sx={{ p: 3, display: 'flex', justifyContent: 'center' }}>
        <Paper sx={{ p: 4, textAlign: 'center', maxWidth: 400 }}>
          <Typography variant="h6" color="error" gutterBottom>
            Failed to load documents
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Unable to fetch document data. The RAG service may be unavailable.
          </Typography>
          <Button variant="outlined" startIcon={<RefreshIcon />} onClick={() => refetch()}>
            Retry
          </Button>
        </Paper>
      </Box>
    );
  }

  return (
    <Box>
      {/* Top Bar */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h5" fontWeight={700}>
          Document Library
        </Typography>
        <Button
          variant="contained"
          startIcon={<CloudUploadIcon />}
          onClick={() => setUploadOpen(true)}
        >
          Upload Document
        </Button>
      </Box>

      {/* Search + Filters */}
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={2}
        alignItems="center"
        sx={{ mb: 3 }}
      >
        <TextField
          placeholder="Search documents..."
          size="small"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <SearchIcon fontSize="small" />
              </InputAdornment>
            ),
          }}
          sx={{ minWidth: 260 }}
        />

        <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ flex: 1 }}>
          {FILE_TYPE_FILTERS.map((ft) => (
            <Chip
              key={ft}
              label={ft}
              size="small"
              variant={fileTypeFilter === ft ? 'filled' : 'outlined'}
              color={fileTypeFilter === ft ? 'primary' : 'default'}
              onClick={() => setFileTypeFilter(ft)}
              sx={{ cursor: 'pointer' }}
            />
          ))}
        </Stack>

        <ToggleButtonGroup
          value={viewMode}
          exclusive
          onChange={(_, val) => val && setViewMode(val)}
          size="small"
        >
          <ToggleButton value="grid">
            <GridViewIcon fontSize="small" />
          </ToggleButton>
          <ToggleButton value="table">
            <TableRowsIcon fontSize="small" />
          </ToggleButton>
        </ToggleButtonGroup>
      </Stack>

      {/* Empty state */}
      {filtered.length === 0 ? (
        <Paper sx={{ p: 6, textAlign: 'center' }}>
          <InsertDriveFileIcon sx={{ fontSize: 48, color: 'text.secondary', mb: 1 }} />
          <Typography variant="h6" color="text.secondary">
            No documents found
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
            {search || fileTypeFilter !== 'ALL'
              ? 'Try adjusting your filters or search term.'
              : 'Upload your first document to get started.'}
          </Typography>
        </Paper>
      ) : viewMode === 'grid' ? (
        /* Grid View */
        <Grid container spacing={2}>
          {filtered.map((doc) => {
            const FileIcon = getFileIcon(doc.filename);
            const fileColor = getFileColor(doc.filename);

            return (
              <Grid item xs={12} sm={6} md={4} lg={3} key={doc.document_id}>
                <Card
                  variant="outlined"
                  sx={{
                    transition: 'border-color 0.2s, box-shadow 0.2s',
                    '&:hover': {
                      borderColor: 'primary.main',
                      boxShadow: `0 0 0 1px ${theme.palette.primary.main}`,
                    },
                  }}
                >
                  <CardActionArea onClick={() => handleDocClick(doc)}>
                    <CardContent>
                      <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1.5, mb: 1.5 }}>
                        <Box
                          sx={{
                            width: 40,
                            height: 40,
                            borderRadius: 1.5,
                            bgcolor: `${theme.palette.background.default}`,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            flexShrink: 0,
                          }}
                        >
                          <FileIcon sx={{ color: fileColor, fontSize: 24 }} />
                        </Box>
                        <Box sx={{ flex: 1, minWidth: 0 }}>
                          <Typography variant="body2" fontWeight={600} noWrap>
                            {doc.filename}
                          </Typography>
                          <Typography variant="caption" color="text.secondary">
                            {formatFileSize(doc.file_size)}
                          </Typography>
                        </Box>
                      </Box>

                      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                        <Chip
                          label={doc.status}
                          size="small"
                          color={STATUS_COLOR_MAP[doc.status] ?? 'default'}
                          sx={{ fontWeight: 600, fontSize: '0.65rem', height: 22 }}
                        />
                        {doc.chunk_count != null && (
                          <Typography variant="caption" color="text.secondary">
                            {doc.chunk_count} chunks
                          </Typography>
                        )}
                      </Box>

                      <Typography variant="caption" color="text.secondary">
                        {format(new Date(doc.created_at), 'MMM d, yyyy')}
                      </Typography>
                    </CardContent>
                  </CardActionArea>

                  <Box
                    sx={{
                      display: 'flex',
                      justifyContent: 'flex-end',
                      px: 1,
                      pb: 1,
                      gap: 0.5,
                    }}
                  >
                    <Tooltip title="Re-ingest">
                      <IconButton
                        size="small"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleReindex(doc);
                        }}
                        disabled={doc.status === 'UPLOADING' || doc.status === 'CHUNKING' || doc.status === 'EMBEDDING'}
                      >
                        <ReplayIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="Delete">
                      <IconButton
                        size="small"
                        color="error"
                        onClick={(e) => {
                          e.stopPropagation();
                          setDeleteConfirm(doc);
                        }}
                      >
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </Box>
                </Card>
              </Grid>
            );
          })}
        </Grid>
      ) : (
        /* Table View */
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Name</TableCell>
                <TableCell>Type</TableCell>
                <TableCell>Size</TableCell>
                <TableCell>Status</TableCell>
                <TableCell align="right">Chunks</TableCell>
                <TableCell>Uploaded</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {filtered.map((doc) => {
                const FileIcon = getFileIcon(doc.filename);
                const fileColor = getFileColor(doc.filename);
                const ext = getFileExtension(doc.filename).toUpperCase();

                return (
                  <TableRow
                    key={doc.document_id}
                    hover
                    sx={{ cursor: 'pointer' }}
                    onClick={() => handleDocClick(doc)}
                  >
                    <TableCell>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        <FileIcon sx={{ color: fileColor, fontSize: 20 }} />
                        <Typography variant="body2" fontWeight={600} noWrap sx={{ maxWidth: 200 }}>
                          {doc.filename}
                        </Typography>
                      </Box>
                    </TableCell>
                    <TableCell>
                      <Chip label={ext} size="small" sx={{ fontSize: '0.65rem', height: 20 }} />
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2">{formatFileSize(doc.file_size)}</Typography>
                    </TableCell>
                    <TableCell>
                      <Chip
                        label={doc.status}
                        size="small"
                        color={STATUS_COLOR_MAP[doc.status] ?? 'default'}
                        sx={{ fontWeight: 600, fontSize: '0.65rem', height: 22 }}
                      />
                    </TableCell>
                    <TableCell align="right">
                      <Typography variant="body2">{doc.chunk_count ?? '-'}</Typography>
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2">
                        {format(new Date(doc.created_at), 'MMM d, yyyy')}
                      </Typography>
                    </TableCell>
                    <TableCell align="right">
                      <Stack direction="row" spacing={0.5} justifyContent="flex-end">
                        <Tooltip title="Re-ingest">
                          <IconButton
                            size="small"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleReindex(doc);
                            }}
                            disabled={
                              doc.status === 'UPLOADING' ||
                              doc.status === 'CHUNKING' ||
                              doc.status === 'EMBEDDING'
                            }
                          >
                            <ReplayIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                        <Tooltip title="Delete">
                          <IconButton
                            size="small"
                            color="error"
                            onClick={(e) => {
                              e.stopPropagation();
                              setDeleteConfirm(doc);
                            }}
                          >
                            <DeleteIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      </Stack>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {/* Upload Dialog */}
      <UploadDialog open={uploadOpen} onClose={() => setUploadOpen(false)} />

      {/* Document Detail Panel */}
      <DocumentDetailPanel
        open={detailOpen}
        onClose={() => {
          setDetailOpen(false);
          setSelectedDoc(null);
        }}
        document={selectedDoc}
      />

      {/* Delete Confirmation */}
      <Dialog open={deleteConfirm !== null} onClose={() => setDeleteConfirm(null)}>
        <DialogTitle>Delete Document</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Are you sure you want to delete{' '}
            <strong>{deleteConfirm?.filename}</strong>? This will remove the document
            and all associated chunks from the vector store. This action cannot be
            undone.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteConfirm(null)}>Cancel</Button>
          <Button
            variant="contained"
            color="error"
            onClick={() => deleteConfirm && handleDelete(deleteConfirm)}
            disabled={deleteDocument.isPending}
          >
            {deleteDocument.isPending ? 'Deleting...' : 'Delete'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
