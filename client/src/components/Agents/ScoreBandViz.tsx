import { Box, useTheme } from '@mui/material';
import { alpha } from '@mui/material/styles';

interface Props {
  bandLow: number;
  bandHigh: number;
  currentScore?: number;
  height?: number;
}

export default function ScoreBandViz({
  bandLow,
  bandHigh,
  currentScore,
  height = 8,
}: Props) {
  const theme = useTheme();

  const clamp = (v: number) => Math.max(0, Math.min(1, v));
  const low = clamp(bandLow);
  const high = clamp(bandHigh);
  const score = currentScore !== undefined ? clamp(currentScore) : undefined;

  const withinBand =
    score !== undefined && score >= low && score <= high;

  const bandColor = theme.palette.info.main;
  const dotColor = withinBand
    ? theme.palette.success.main
    : theme.palette.error.main;

  return (
    <Box
      sx={{
        position: 'relative',
        width: '100%',
        height,
        borderRadius: height / 2,
        bgcolor: alpha(theme.palette.text.disabled, 0.15),
        overflow: 'visible',
      }}
    >
      {/* Band region */}
      <Box
        sx={{
          position: 'absolute',
          left: `${low * 100}%`,
          width: `${(high - low) * 100}%`,
          height: '100%',
          borderRadius: height / 2,
          bgcolor: alpha(bandColor, 0.35),
        }}
      />

      {/* Score dot */}
      {score !== undefined && (
        <Box
          sx={{
            position: 'absolute',
            left: `${score * 100}%`,
            top: '50%',
            transform: 'translate(-50%, -50%)',
            width: height + 6,
            height: height + 6,
            borderRadius: '50%',
            bgcolor: dotColor,
            border: `2px solid ${theme.palette.background.paper}`,
            boxShadow: `0 0 4px ${alpha(dotColor, 0.5)}`,
            zIndex: 1,
          }}
        />
      )}
    </Box>
  );
}
