<script lang="ts">
  import { onMount } from 'svelte';
  import type { RunMeta, Analysis, ScoredPlan } from './lib/types.js';
  import Header            from './lib/components/Header.svelte';
  import EnsembleStoryTab  from './lib/components/EnsembleStoryTab.svelte';
  import AnalysisTab       from './lib/components/AnalysisTab.svelte';
  import { getAllScoredPlans, saveScoredPlan, deleteScoredPlan } from './lib/db.js';
  import { apiGet } from './lib/api.js';

  type Tab = 'story' | 'analyze';
  let tab: Tab = $state('story');

  let runs: RunMeta[]             = $state([]);
  let analysis: Analysis | null   = $state(null);
  let companionAnalysis: Analysis | null = $state(null);
  let selectedRunId: string       = $state('');
  let selectedElectionIdx         = $state(0);
  let loading                     = $state(false);
  let error                       = $state('');

  // Derive the paired run ID (GerryChain ↔ ALARM)
  function getCompanionRunId(runId: string): string | null {
    const isAlarm  = runId.endsWith('_alarm');
    const paired   = isAlarm ? runId.slice(0, -6) : `${runId}_alarm`;
    return runs.find(r => r.id === paired)?.id ?? null;
  }

  const companionRunId = $derived(getCompanionRunId(selectedRunId));

  let scoredPlans: ScoredPlan[] = $state([]);

  async function loadRuns() {
    runs = await apiGet<RunMeta[]>('/runs');
    if (runs.length) {
      selectedRunId = runs[0].id;
      await Promise.all([
        loadAnalysis(selectedRunId, 0),
        loadScoredPlans(selectedRunId),
      ]);
    }
  }

  async function loadScoredPlans(runId: string) {
    const run = runs.find(r => r.id === runId);
    const enactedRaw = run?.plans?.[0];
    const enacted: ScoredPlan[] = enactedRaw
      ? [{ ...enactedRaw, run_id: runId, source: 'catalog' as const }]
      : [];
    const allUploaded = await getAllScoredPlans();
    const uploads = allUploaded.filter(p => p.run_id === runId);
    scoredPlans = [...enacted, ...uploads];
  }

  async function loadAnalysis(runId: string, electionIdx = 0) {
    loading = true;
    error   = '';
    try {
      analysis = await apiGet<Analysis>('/analysis', {
        run: runId,
        election: String(electionIdx),
      });
    } catch (e: any) {
      error = e.message ?? 'Failed to load analysis';
    } finally {
      loading = false;
    }
    // Load companion run (ALARM ↔ GerryChain) in background — non-blocking
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
    await Promise.all([
      loadAnalysis(runId, 0),
      loadScoredPlans(runId),
    ]);
  }

  async function switchElection(idx: number) {
    selectedElectionIdx = idx;
    await loadAnalysis(selectedRunId, idx);
  }

  async function addScoredPlan(plan: ScoredPlan) {
    await saveScoredPlan(plan);
    scoredPlans = [scoredPlans[0], plan, ...scoredPlans.slice(1)];
    tab = 'analyze';
  }

  async function removeScoredPlan(id: string) {
    await deleteScoredPlan(id);
    scoredPlans = scoredPlans.filter(p => p.id !== id);
  }

  const summary = $derived(analysis?.summary ?? null);

  const TAB_LABELS: Record<Tab, string> = {
    story:   'Ensemble',
    analyze: 'Score a Map',
  };

  onMount(loadRuns);
</script>

<div class="no-print">
  <Header {runs} {summary} {selectedRunId} onRunChange={switchRun} />
</div>

<!-- Tab bar -->
<div class="no-print" style="background:var(--card);border-bottom:2px solid var(--border);
     display:flex;gap:0;padding:0 1rem;overflow-x:auto;">
  {#each (['story', 'analyze'] as Tab[]) as t}
    <button
      onclick={() => tab = t}
      style="padding:.55rem 1.1rem;border:none;background:transparent;cursor:pointer;
             font-size:.82rem;font-weight:{tab === t ? '700' : '500'};
             color:{tab === t ? 'var(--blue)' : 'var(--gray)'};
             border-bottom:{tab === t ? '2.5px solid var(--blue)' : '2.5px solid transparent'};
             margin-bottom:-2px;white-space:nowrap;transition:color .15s;"
    >
      {TAB_LABELS[t]}
    </button>
  {/each}
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
    <!-- Print header -->
    <div class="print-only" style="font-size:1.1rem;font-weight:700;margin-bottom:.6rem;color:#111;">
      Fair Districts GA — Redistricting Ensemble Analysis
      {#if summary}· {summary.state_full} {summary.plan_type.toUpperCase()} {summary.plan_year}{/if}
    </div>

    {#if tab === 'story'}
      <EnsembleStoryTab
        {runs}
        {analysis}
        selectedRunId={selectedRunId}
        {selectedElectionIdx}
        onRunChange={switchRun}
        onSwitchElection={switchElection}
      />

    {:else if tab === 'analyze'}
      <AnalysisTab
        {runs}
        {analysis}
        {companionAnalysis}
        {companionRunId}
        selectedRunId={selectedRunId}
        {selectedElectionIdx}
        onSwitchElection={switchElection}
        onAddPlan={addScoredPlan}
      />
    {/if}

  {:else}
    <div style="text-align:center;padding:4rem;color:var(--gray);">No data available.</div>
  {/if}
</main>

<!-- Footer -->
<footer style="text-align:center;padding:1.5rem;font-size:.72rem;color:var(--gray);margin-top:2rem;
               border-top:1px solid var(--border);">
  fdensemble · Fair Districts GA ·
  <a href="https://alarm-redist.org" target="_blank" rel="noopener" style="color:var(--blue);">ALARM Project</a> ·
  <a href="https://gerrymander.princeton.edu" target="_blank" rel="noopener" style="color:var(--blue);">Princeton Gerrymandering Project</a>
</footer>
