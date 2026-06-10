<script lang="ts">
  import { onMount } from 'svelte';
  import type { RunMeta, Analysis } from './lib/types.js';
  import Header           from './lib/components/Header.svelte';
  import EnsembleStoryTab from './lib/components/EnsembleStoryTab.svelte';
  import ScoreTab         from './lib/components/ScoreTab.svelte';
  import { apiGet } from './lib/api.js';

  let runs: RunMeta[]           = $state([]);
  let analysis: Analysis | null = $state(null);
  let companionAnalysis: Analysis | null = $state(null);
  let selectedRunId             = $state('');
  let selectedElectionIdx       = $state(0);
  let loading                   = $state(false);
  let error                     = $state('');

  function getCompanionRunId(runId: string): string | null {
    const isAlarm = runId.endsWith('_alarm');
    const paired  = isAlarm ? runId.slice(0, -6) : `${runId}_alarm`;
    return runs.find(r => r.id === paired)?.id ?? null;
  }

  const companionRunId = $derived(getCompanionRunId(selectedRunId));

  async function loadRuns() {
    runs = await apiGet<RunMeta[]>('/runs');
    if (runs.length) {
      selectedRunId = runs[0].id;
      await loadAnalysis(selectedRunId, 0);
    }
  }

  async function loadAnalysis(runId: string, electionIdx = 0) {
    loading = true;
    error   = '';
    try {
      analysis = await apiGet<Analysis>('/analysis', {
        run:      runId,
        election: String(electionIdx),
      });
    } catch (e: any) {
      error = e.message ?? 'Failed to load analysis';
    } finally {
      loading = false;
    }
    const paired = getCompanionRunId(runId);
    if (paired) {
      try {
        companionAnalysis = await apiGet<Analysis>('/analysis', { run: paired, election: '0' });
      } catch {
        companionAnalysis = null;
      }
    } else {
      companionAnalysis = null;
    }
  }

  async function switchRun(runId: string) {
    selectedRunId       = runId;
    selectedElectionIdx = 0;
    await loadAnalysis(runId, 0);
  }

  async function switchElection(idx: number) {
    selectedElectionIdx = idx;
    await loadAnalysis(selectedRunId, idx);
  }

  const summary = $derived(analysis?.summary ?? null);

  onMount(loadRuns);
</script>

<div class="no-print">
  <Header {runs} {summary} {selectedRunId} onRunChange={switchRun} />
</div>

<main style="max-width:1280px;margin:1rem auto;padding:0 .9rem;">
  {#if loading}
    <div style="text-align:center;padding:4rem;color:var(--gray);font-size:.9rem;">Loading analysis…</div>

  {:else if error}
    <div style="background:#fef0f0;border:1px solid #f5a9a9;border-radius:8px;padding:1rem;
                color:var(--red);font-size:.85rem;margin-top:1rem;">
      Error: {error}
    </div>

  {:else if analysis}
    <div class="print-only" style="font-size:1.1rem;font-weight:700;margin-bottom:.6rem;color:#111;">
      Fair Districts GA — Redistricting Ensemble Analysis
      {#if summary}· {summary.state_full} {summary.plan_type.toUpperCase()} {summary.plan_year}{/if}
    </div>

    <EnsembleStoryTab
      {runs}
      {analysis}
      selectedRunId={selectedRunId}
      onRunChange={switchRun}
    />

    <ScoreTab
      {analysis}
      {companionRunId}
      selectedRunId={selectedRunId}
      {selectedElectionIdx}
      onSwitchElection={switchElection}
      onAddPlan={() => {}}
    />

  {:else}
    <div style="text-align:center;padding:4rem;color:var(--gray);">No data available.</div>
  {/if}
</main>

<footer style="text-align:center;padding:1.5rem;font-size:.72rem;color:var(--gray);margin-top:2rem;
               border-top:1px solid var(--border);">
  fdensemble · Fair Districts GA ·
  <a href="https://alarm-redist.org" target="_blank" rel="noopener" style="color:var(--blue);">ALARM Project</a> ·
  <a href="https://gerrymander.princeton.edu" target="_blank" rel="noopener" style="color:var(--blue);">Princeton Gerrymandering Project</a>
</footer>
