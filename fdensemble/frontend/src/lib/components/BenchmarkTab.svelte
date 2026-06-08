<script lang="ts">
  import type { Analysis, ElectionOption, MetricGrade } from '../types.js';
  import GradePanel           from './GradePanel.svelte';
  import MetricCard           from './MetricCard.svelte';
  import RiverChart           from './RiverChart.svelte';
  import BenchmarkMethodology from './BenchmarkMethodology.svelte';
  import MetricsGlossary      from './MetricsGlossary.svelte';

  interface Props {
    analysis: Analysis;
    selectedElectionIdx: number;
    onSwitchElection: (idx: number) => void;
  }
  let { analysis, selectedElectionIdx, onSwitchElection }: Props = $props();

  const PARTISAN_KEYS    = ['dem_seats', 'partisan_bias', 'efficiency_gap', 'mean_median'];
  const COMPETITIVE_KEYS = ['comp_seats_7pt', 'comp_seats_10pt', 'comp_seats'];
  const GEOGRAPHIC_KEYS  = ['polsby_popper', 'county_splits', 'muni_splits'];
  const MINORITY_KEYS    = ['maj_black', 'maj_hisp', 'maj_aian', 'maj_asian', 'min_coal'];

  function allMetrics(keys: string[]): MetricGrade[] {
    return keys
      .filter(k => k in analysis.grades && !k.startsWith('_'))
      .map(k => analysis.grades[k] as MetricGrade)
      .filter(m => m && 'histogram' in m);
  }

  const summary           = $derived(analysis.summary);
  const grades            = $derived(analysis.grades);
  const river             = $derived(analysis.river);
  const availableElections: ElectionOption[] = $derived(summary?.run?.elections ?? []);
</script>

<div>
  <!-- Methodology accordion -->
  {#if summary?.run}
    <BenchmarkMethodology run={summary.run} />
  {/if}

  <!-- Metrics glossary accordion -->
  <MetricsGlossary {analysis} />

  <!-- Run info strip -->
  <div style="background:var(--card);border-radius:8px;padding:.6rem 1rem;box-shadow:var(--shadow);
              border:1.5px solid var(--border);margin-bottom:.9rem;
              display:flex;gap:1.5rem;flex-wrap:wrap;font-size:.78rem;color:var(--gray);align-items:center;">
    <span><b>State:</b> {summary?.state_full}</span>
    <span><b>Chamber:</b> {(summary?.run?.chamber ?? summary?.plan_type ?? '').toUpperCase()}</span>
    <span><b>Cycle:</b> {summary?.plan_year}</span>
    <span><b>Plans:</b> {summary?.n_plans.toLocaleString()}</span>
    <span><b>Algorithm:</b> {summary?.run.algorithm}</span>
    <span><b>Run date:</b> {summary?.run.date}</span>
    {#if summary?.run.description}
      <span style="flex:1;min-width:200px;">{summary.run.description}</span>
    {/if}
    <!-- Election selector -->
    <span style="margin-left:auto;display:flex;align-items:center;gap:.7rem;">
      {#if availableElections.length > 1}
        <span class="no-print" style="display:flex;align-items:center;gap:.4rem;">
          <b>Election:</b>
          <select
            value={selectedElectionIdx}
            onchange={(e) => onSwitchElection(parseInt((e.target as HTMLSelectElement).value))}
            style="font-size:.78rem;padding:.2rem .4rem;border:1px solid var(--border);
                   border-radius:4px;background:var(--card);color:inherit;cursor:pointer;"
          >
            {#each availableElections as elec, i}
              <option value={i}>{elec.label}</option>
            {/each}
          </select>
        </span>
      {/if}
      <button class="export-pdf-btn no-print" onclick={() => window.print()} title="Export as PDF">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="6,9 6,2 18,2 18,9"/>
          <path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/>
          <rect x="6" y="14" width="12" height="8"/>
        </svg>
        Export PDF
      </button>
    </span>
  </div>

  <!-- Print-only title -->
  <div class="print-only" style="font-size:1.1rem;font-weight:700;margin-bottom:.6rem;color:#111;">
    Fair Districts GA — Redistricting Ensemble Analysis
    {#if summary}· {summary.state_full} {summary.plan_type.toUpperCase()} {summary.plan_year}{/if}
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

  <!-- Competitive metrics -->
  {#if allMetrics(COMPETITIVE_KEYS).length}
    <div style="font-size:.74rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;
                color:var(--gray);margin:.8rem 0 .4rem;">Competitiveness</div>
    <div style="display:flex;flex-direction:column;gap:.55rem;">
      {#each allMetrics(COMPETITIVE_KEYS) as metric}
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
      <RiverChart {river} enactedShares={null} />
    </div>
  {/if}
</div>
