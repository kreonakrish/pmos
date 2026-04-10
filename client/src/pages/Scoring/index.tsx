import { useState, useMemo } from 'react';
import {
  Box,
  Typography,
  Grid,
  Paper,
  Skeleton,
  Button,
} from '@mui/material';
import AssessmentIcon from '@mui/icons-material/Assessment';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import BuildIcon from '@mui/icons-material/Build';
import BugReportIcon from '@mui/icons-material/BugReport';
import RefreshIcon from '@mui/icons-material/Refresh';
import { useAgents } from '@/api/agents';
import { useScoreHistory } from '@/api/scoring';
import StatCard from '@/components/Scoring/StatCard';
import ScoreDistribution from '@/components/Scoring/ScoreDistribution';
import FeedbackDonut from '@/components/Scoring/FeedbackDonut';
import BandEvolutionChart from '@/components/Scoring/BandEvolutionChart';
import WeightConvergenceChart from '@/components/Scoring/WeightConvergenceChart';
import ScoreFeed from '@/components/Scoring/ScoreFeed';

export default function ScoringPage() {
  const [selectedAgentId, setSelectedAgentId] = useState<number | null>(null);

  const agentsQuery = useAgents();
  const agents = agentsQuery.data ?? [];

  // Use first agent as default when agents load
  const effectiveAgentId = selectedAgentId ?? (agents.length > 0 ? agents[0].id : null);

  const scoreHistoryQuery = useScoreHistory(effectiveAgentId, {
    enabled: effectiveAgentId > 0,
  });
  const scoreHistory = scoreHistoryQuery.data ?? [];

  // Compute stats
  const stats = useMemo(() => {
    if (scoreHistory.length === 0) {
      return { avgScore: 0, totalExec: 0, corrections: 0, gaps: 0 };
    }
    const scores = scoreHistory.map((s) => s.score);
    const avgScore = scores.reduce((a, b) => a + b, 0) / scores.length;
    const corrections = scoreHistory.filter((s) => !s.within_band).length;
    return {
      avgScore,
      totalExec: scoreHistory.length,
      corrections,
      gaps: 0, // Would come from meta-assembly API
    };
  }, [scoreHistory]);

  // Build feed items from score history
  const feedItems = useMemo(() => {
    return scoreHistory.slice(-50).reverse().map((entry, idx) => {
      const agent = agents.find((a) => a.id === entry.agent_id);
      return {
        id: entry.id ?? idx,
        agentName: agent?.name ?? `Agent #${entry.agent_id}`,
        score: entry.score,
        bandLow: entry.band_low,
        bandHigh: entry.band_high,
        recommendation: entry.within_band ? 'proceed' : 'course_correct',
        timestamp: entry.created_at,
      };
    });
  }, [scoreHistory, agents]);

  // Generate mock weight convergence data from score history
  const weightData = useMemo(() => {
    return scoreHistory.slice(-50).map((entry, idx) => ({
      update: idx + 1,
      relevance: entry.factors.relevance ?? 0,
      accuracy: entry.factors.accuracy ?? 0,
      tool_success: entry.factors.tool_success ?? 0,
      latency: entry.factors.latency ?? 0,
      memory_util: entry.factors.memory_util ?? 0,
      validation: entry.factors.validation ?? 0,
    }));
  }, [scoreHistory]);

  const isLoading = agentsQuery.isLoading;
  const isError = agentsQuery.isError;

  if (isError) {
    return (
      <Box sx={{ p: 3, display: 'flex', justifyContent: 'center' }}>
        <Paper sx={{ p: 4, textAlign: 'center', maxWidth: 400 }}>
          <Typography variant="h6" color="error" gutterBottom>
            Failed to load scoring data
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Unable to connect to the scoring service.
          </Typography>
          <Button
            variant="outlined"
            startIcon={<RefreshIcon />}
            onClick={() => agentsQuery.refetch()}
          >
            Retry
          </Button>
        </Paper>
      </Box>
    );
  }

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" fontWeight={700} sx={{ mb: 3 }}>
        Scoring Dashboard
      </Typography>

      {/* Top row: stat cards */}
      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={6} md={3}>
          {isLoading ? (
            <Skeleton variant="rectangular" height={100} sx={{ borderRadius: 1 }} />
          ) : (
            <StatCard
              label="Avg Score Today"
              value={stats.avgScore.toFixed(3)}
              trend={stats.avgScore >= 0.7 ? 'up' : 'down'}
              icon={AssessmentIcon}
            />
          )}
        </Grid>
        <Grid item xs={6} md={3}>
          {isLoading ? (
            <Skeleton variant="rectangular" height={100} sx={{ borderRadius: 1 }} />
          ) : (
            <StatCard
              label="Total Executions"
              value={stats.totalExec}
              icon={PlayArrowIcon}
            />
          )}
        </Grid>
        <Grid item xs={6} md={3}>
          {isLoading ? (
            <Skeleton variant="rectangular" height={100} sx={{ borderRadius: 1 }} />
          ) : (
            <StatCard
              label="Course Corrections"
              value={stats.corrections}
              trend={stats.corrections > 5 ? 'up' : undefined}
              icon={BuildIcon}
            />
          )}
        </Grid>
        <Grid item xs={6} md={3}>
          {isLoading ? (
            <Skeleton variant="rectangular" height={100} sx={{ borderRadius: 1 }} />
          ) : (
            <StatCard
              label="Gaps Detected"
              value={stats.gaps}
              icon={BugReportIcon}
            />
          )}
        </Grid>
      </Grid>

      {/* Second row: distribution + feedback donut */}
      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={12} md={7}>
          <Paper sx={{ p: 2 }}>
            <ScoreDistribution
              data={scoreHistory}
              loading={scoreHistoryQuery.isLoading && effectiveAgentId > 0}
            />
          </Paper>
        </Grid>
        <Grid item xs={12} md={5}>
          <Paper sx={{ p: 2 }}>
            <FeedbackDonut loading={isLoading} />
          </Paper>
        </Grid>
      </Grid>

      {/* Third row: band evolution + weight convergence */}
      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 2 }}>
            <BandEvolutionChart
              agents={agents}
              selectedAgentId={effectiveAgentId}
              onAgentChange={setSelectedAgentId}
              data={scoreHistory}
              loading={scoreHistoryQuery.isLoading}
            />
          </Paper>
        </Grid>
        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 2 }}>
            <WeightConvergenceChart
              agents={agents}
              selectedAgentId={effectiveAgentId}
              onAgentChange={setSelectedAgentId}
              data={weightData}
              loading={scoreHistoryQuery.isLoading}
            />
          </Paper>
        </Grid>
      </Grid>

      {/* Bottom: live feed */}
      <Paper sx={{ p: 2 }}>
        <ScoreFeed
          items={feedItems}
          loading={scoreHistoryQuery.isLoading && effectiveAgentId > 0}
        />
      </Paper>
    </Box>
  );
}
