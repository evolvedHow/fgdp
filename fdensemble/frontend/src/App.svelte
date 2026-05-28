<script lang="ts">
  import { onMount } from 'svelte';
  import type { RunMeta, Analysis, MetricGrade } from './lib/types.js';
  import Header     from './lib/components/Header.svelte';
  import GradePanel from './lib/components/GradePanel.svelte';
  import MetricCard from './lib/components/MetricCard.svelte';
  import RiverChart from './lib/components/RiverChart.svelte';

  let runs: RunMeta[]  = $state([]);
  let analysis: Analysis | null = $state(null);
  let selectedRunId: string  = $state('');
  let loading  = $state(false);
  let error    = $state('');

  // Separate metric keys by category, excluding composites
  const PARTISAN_KEYS    = ['dem_seats', 'partisan_bias', 'efficiency_gap', 'mean_median'];
  const COMPETITIVE_KEYS = ['comp_seats'];
  const GEOGRAPHIC_KEYS  = ['polsby_popper', 'county_splits', 'muni_splits'];
  const MINORITY_KEYS    = ['maj_black', 'maj_hisp', 'maj_aian', 'maj_asian', 'min_coal'];

  function metricsFor(keys: string[]): MetricGrade[] {
    if (!analysis) return [];
    return keys
      .filter(k => analysis!.grades[k] && !(analysis!.grades[k] as any).ensemble_pass !== undefined)
      .map(k => analysis!.grades[k] as MetricGrade)
      .filter(Boolean);
  }

  function allMetrics(keys: string[]): MetricGrade[] {
    if (!analysis) return [];
    return keys
      .filter(k => k in analysis!.grades && !k.startsWith('_'))
      .map(k => analysis!.grades[k] as MetricGrade)
      .filter(m => m && 'histogram' in m);
  }

  async function loadRuns() {
    const res  = await fetch('/api/runs');
    runs       = await res.json();
    if (runs.length) {
      selectedRunId = runs[0].id;
      await loadAnalysis(selectedRunId);
    }
  }

  async function loadAnalysis(runId: string) {
    loading = true;
    error   = '';
    try {
      const res = await fetch(`/api/analysis?run=${encodeURIComponent(runId)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      analysis = await res.json();
    } catch (e: any) {
      error = e.message ?? 'Failed to load analysis';
    } finally {
      loading = false;
    }
  }

  async function switchRun(runId: string) {
    selectedRunId = runId;
    await loadAnalysis(runId);
  }

  // Enacted district shares for river chart (sorted ascending)
  const enactedShares = $derived(
    analysis?.river ? null : null  // backend provides ribbon; enacted is overlay
  );

  const summary = $derived(analysis?.summary ?? null);
  const grades  = $derived(analysis?.grades  ?? {});
  const river   = $derived(analysis?.river   ?? null);

  onMount(loadRuns);
</script>

<Header {runs} {summary} {selectedRunId} onRunChange={switchRun} />

<main style="max-width:1280px;margin:1rem auto;padding:0 .9rem;">
  {#if loading}
    <div style="text-align:center;padding:4rem;color:var(--gray);font-size:.9rem;">Loading analysis…</div>

  {:else if error}
    <div style="background:#fef0f0;border:1px solid #f5a9a9;border-radius:8px;padding:1rem;color:var(--red);font-size:.85rem;margin-top:1rem;">
      Error: {error}
    </div>

  {:else if analysis}
    <!-- Run info strip -->
    <div style="background:var(--card);border-radius:8px;padding:.6rem 1rem;box-shadow:var(--shadow);
                border:1.5px solid var(--border);margin-bottom:.9rem;
                display:flex;gap:1.5rem;flex-wrap:wrap;font-size:.78rem;color:var(--gray);">
      <span><b>State:</b> {summary?.state_full}</span>
      <span><b>Chamber:</b> {summary?.plan_type.toUpperCase()}</span>
      <span><b>Cycle:</b> {summary?.plan_year}</span>
      <span><b>Plans:</b> {summary?.n_plans.toLocaleString()}</span>
      <span><b>Algorithm:</b> {summary?.run.algorithm}</span>
      <span><b>Run date:</b> {summary?.run.date}</span>
      {#if summary?.run.description}
        <span style="flex:1;min-width:200px;">{summary.run.description}</span>
      {/if}
    </div>

    <!-- Composite grade cards -->
    <GradePanel {grades} />

    <!-- Partisan metrics -->
    {#if allMetrics(PARTISAN_KEYS).length}
      <div style="font-size:.74rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;
                  color:var(--gray);margin:.8rem 0 .4rem;">Partisan Fairness</div>
      <div style="display:flex;flex-direction:column;gap:.55rem;">
        {#each allMetrics(PARTISAN_KEYS) as metric}
          <MetricCard {metric} />
        {/each}
      </div>
    {/if}

    <!-- Geographic metrics -->
    {#if allMetrics(GEOGRAPHIC_KEYS).length}
      <div style="font-size:.74rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;
                  color:var(--gray);margin:.8rem 0 .4rem;">Geographic</div>
      <div style="display:flex;flex-direction:column;gap:.55rem;">
        {#each allMetrics(GEOGRAPHIC_KEYS) as metric}
          <MetricCard {metric} />
        {/each}
      </div>
    {/if}

    <!-- Minority representation -->
    {#if allMetrics(MINORITY_KEYS).length}
      <div style="font-size:.74rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;
                  color:var(--gray);margin:.8rem 0 .4rem;">Minority Representation</div>
      <div style="display:flex;flex-direction:column;gap:.55rem;">
        {#each allMetrics(MINORITY_KEYS) as metric}
          <MetricCard {metric} />
        {/each}
      </div>
    {/if}

    <!-- River chart -->
    {#if river}
      <div style="margin:.8rem 0 .4rem;">
        <RiverChart {river} {enactedShares} />
      </div>
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
