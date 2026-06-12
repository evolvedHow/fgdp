<script lang="ts">
  import { onMount } from 'svelte';
  import type { RunMeta, Analysis } from './lib/types.js';
  import Header                from './lib/components/Header.svelte';
  import EnsembleStoryTab      from './lib/components/EnsembleStoryTab.svelte';
  import ScoreTab              from './lib/components/ScoreTab.svelte';
  import AlgorithmCompareView  from './lib/components/AlgorithmCompareView.svelte';
  import { apiGet } from './lib/api.js';

  // ── Single-run mode state ─────────────────────────────────────────────────
  let runs: RunMeta[]           = $state([]);
  let analysis: Analysis | null = $state(null);
  let companionAnalysis: Analysis | null = $state(null);
  let selectedRunId             = $state('');
  let selectedElectionIdx       = $state(0);
  let loading                   = $state(false);
  let error                     = $state('');

  // ── Compare mode state ────────────────────────────────────────────────────
  let compareMode               = $state(false);
  let leftRunId                 = $state('');   // '' = None
  let rightRunId                = $state('');   // '' = None
  let leftAnalysis: Analysis | null  = $state(null);
  let rightAnalysis: Analysis | null = $state(null);
  let leftLoading               = $state(false);
  let rightLoading              = $state(false);
  let leftError                 = $state('');
  let rightError                = $state('');

  // ── Run label helpers ─────────────────────────────────────────────────────
  const CHAMBER_LABEL: Record<string, string> = {
    congress: 'U.S. Congress',
    senate:   'GA Senate',
    house:    'GA House',
  };

  function runLabel(r: RunMeta): string {
    const chamber = r.chamber ? (CHAMBER_LABEL[r.chamber] ?? r.chamber) : '';
    const algo    = r.source === 'alarm' ? 'ALARM' : 'GerryChain';
    const plans   = r.n_plans ? ` (${(r.n_plans / 1000).toFixed(0)}K)` : '';
    return chamber ? `${chamber} — ${algo}${plans}` : (r.name || r.id);
  }

  function getCompanionRunId(runId: string): string | null {
    const isAlarm = runId.endsWith('_alarm');
    const paired  = isAlarm ? runId.slice(0, -6) : `${runId}_alarm`;
    return runs.find(r => r.id === paired)?.id ?? null;
  }

  const companionRunId = $derived(getCompanionRunId(selectedRunId));

  // ── Single-run loading ────────────────────────────────────────────────────
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

  // ── Compare mode loading ──────────────────────────────────────────────────
  async function loadLeft(runId: string) {
    leftRunId    = runId;
    leftAnalysis = null;
    leftError    = '';
    if (!runId) return;
    leftLoading = true;
    try {
      leftAnalysis = await apiGet<Analysis>('/analysis', { run: runId, election: '0' });
    } catch (e: any) {
      leftError = e.message ?? 'Failed to load';
    } finally {
      leftLoading = false;
    }
  }

  async function loadRight(runId: string) {
    rightRunId    = runId;
    rightAnalysis = null;
    rightError    = '';
    if (!runId) return;
    rightLoading = true;
    try {
      rightAnalysis = await apiGet<Analysis>('/analysis', { run: runId, election: '0' });
    } catch (e: any) {
      rightError = e.message ?? 'Failed to load';
    } finally {
      rightLoading = false;
    }
  }

  function enterCompareMode() {
    compareMode = true;
    // Default left = first non-alarm run, right = its alarm pair if available else ''
    const firstGC = runs.find(r => r.source !== 'alarm') ?? runs[0];
    const defaultLeft  = firstGC?.id ?? '';
    const defaultRight = defaultLeft ? (getCompanionRunId(defaultLeft) ?? '') : '';
    loadLeft(defaultLeft);
    loadRight(defaultRight);
  }

  function exitCompareMode() {
    compareMode   = false;
    leftAnalysis  = null;
    rightAnalysis = null;
    leftError     = '';
    rightError    = '';
  }

  const summary = $derived(analysis?.summary ?? null);

  onMount(loadRuns);
</script>

<!-- Mode toggle bar -->
<div class="mode-bar no-print">
  <button
    class="mode-btn {!compareMode ? 'active' : ''}"
    onclick={exitCompareMode}
  >Single Benchmark</button>
  {#if runs.length > 0}
    <button
      class="mode-btn {compareMode ? 'active' : ''}"
      onclick={enterCompareMode}
    >Compare</button>
  {/if}
</div>

<div class="no-print">
  {#if !compareMode}
    <Header {runs} {summary} {selectedRunId} onRunChange={switchRun} />
  {:else}
    <!-- Compare mode header: two independent dropdowns -->
    <div class="compare-mode-bar">
      <div class="compare-selects">
        <div class="compare-select-group">
          <label class="select-label">Left panel</label>
          <select
            class="run-select"
            value={leftRunId}
            onchange={(e) => loadLeft((e.target as HTMLSelectElement).value)}
          >
            <option value="">— None —</option>
            {#each runs as r}
              <option value={r.id}>{runLabel(r)}</option>
            {/each}
          </select>
        </div>
        <div class="compare-divider">vs</div>
        <div class="compare-select-group">
          <label class="select-label">Right panel</label>
          <select
            class="run-select"
            value={rightRunId}
            onchange={(e) => loadRight((e.target as HTMLSelectElement).value)}
          >
            <option value="">— None —</option>
            {#each runs as r}
              <option value={r.id}>{runLabel(r)}</option>
            {/each}
          </select>
        </div>
      </div>
    </div>
  {/if}
</div>

<main style="max-width:1280px;margin:1rem auto;padding:0 .9rem;">

  {#if !compareMode}
    <!-- ── Single benchmark view ───────────────────────────────── -->
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

  {:else}
    <!-- ── Compare mode view ───────────────────────────────────── -->
    {#if leftAnalysis && rightAnalysis}
      <AlgorithmCompareView gcAnalysis={leftAnalysis} alarmAnalysis={rightAnalysis} />

    {:else}
      <div class="compare-panels">
        <!-- Left panel -->
        <div class="compare-panel">
          {#if !leftRunId}
            <div class="panel-empty">Select a benchmark above</div>
          {:else if leftLoading}
            <div class="panel-loading">Loading…</div>
          {:else if leftError}
            <div class="panel-error">{leftError}</div>
          {:else if leftAnalysis}
            <ScoreTab
              analysis={leftAnalysis}
              companionRunId={null}
              selectedRunId={leftRunId}
              selectedElectionIdx={0}
              onSwitchElection={() => {}}
              onAddPlan={() => {}}
            />
          {/if}
        </div>

        <!-- Right panel -->
        <div class="compare-panel">
          {#if !rightRunId}
            <div class="panel-empty">Select a benchmark above</div>
          {:else if rightLoading}
            <div class="panel-loading">Loading…</div>
          {:else if rightError}
            <div class="panel-error">{rightError}</div>
          {:else if rightAnalysis}
            <ScoreTab
              analysis={rightAnalysis}
              companionRunId={null}
              selectedRunId={rightRunId}
              selectedElectionIdx={0}
              onSwitchElection={() => {}}
              onAddPlan={() => {}}
            />
          {/if}
        </div>
      </div>
    {/if}
  {/if}

</main>

<footer style="text-align:center;padding:1.5rem;font-size:.72rem;color:var(--gray);margin-top:2rem;
               border-top:1px solid var(--border);">
  fdensemble · Fair Districts GA ·
  <a href="https://alarm-redist.org" target="_blank" rel="noopener" style="color:var(--blue);">ALARM Project</a> ·
  <a href="https://gerrymander.princeton.edu" target="_blank" rel="noopener" style="color:var(--blue);">Princeton Gerrymandering Project</a>
</footer>

<style>
  .mode-bar {
    display: flex;
    justify-content: center;
    gap: 0;
    padding: .5rem 1rem .3rem;
    background: var(--card);
    border-bottom: 1.5px solid var(--border);
  }
  .mode-btn {
    padding: .3rem .9rem;
    font-size: .78rem;
    font-weight: 600;
    border: 1.5px solid var(--border);
    background: var(--light);
    color: var(--gray);
    cursor: pointer;
    transition: background .12s, color .12s;
  }
  .mode-btn:first-child { border-radius: 5px 0 0 5px; }
  .mode-btn:last-child  { border-radius: 0 5px 5px 0; border-left: none; }
  .mode-btn.active {
    background: var(--blue);
    border-color: var(--blue);
    color: #fff;
  }

  /* Compare header */
  .compare-mode-bar {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: .6rem 1.2rem;
    background: var(--card);
    border-bottom: 1.5px solid var(--border);
  }
  .compare-selects {
    display: flex;
    align-items: center;
    gap: .75rem;
  }
  .compare-select-group {
    display: flex;
    flex-direction: column;
    gap: .2rem;
  }
  .select-label {
    font-size: .68rem;
    font-weight: 600;
    color: var(--gray);
    text-transform: uppercase;
    letter-spacing: .04em;
  }
  .run-select {
    padding: .28rem .5rem;
    font-size: .8rem;
    border: 1.5px solid var(--border);
    border-radius: 5px;
    background: var(--light);
    color: var(--text);
    cursor: pointer;
    min-width: 220px;
  }
  .compare-divider {
    font-size: .78rem;
    font-weight: 700;
    color: var(--gray);
    margin-top: 1.1rem;
  }

  /* Side-by-side single panels (when both aren't loaded) */
  .compare-panels {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
    margin-top: 1rem;
  }
  .compare-panel {
    min-width: 0;
  }
  .panel-empty {
    text-align: center;
    padding: 4rem 1rem;
    color: var(--gray);
    font-size: .88rem;
    border: 1.5px dashed var(--border);
    border-radius: 8px;
  }
  .panel-loading {
    text-align: center;
    padding: 4rem 1rem;
    color: var(--gray);
    font-size: .88rem;
  }
  .panel-error {
    padding: 1rem;
    background: #fef0f0;
    border: 1px solid #f5a9a9;
    border-radius: 8px;
    color: var(--red);
    font-size: .84rem;
  }
</style>
