<script lang="ts">
  import type { Analysis, MetricGrade } from '../types.js';
  import AlgoCompareRow from './AlgoCompareRow.svelte';

  interface Props {
    gcAnalysis:    Analysis;
    alarmAnalysis: Analysis;
  }
  let { gcAnalysis, alarmAnalysis }: Props = $props();

  // Metric groups (matches ScoreTab ordering)
  const METRIC_GROUPS: { label: string; keys: string[] }[] = [
    { label: 'Demographic Representation',  keys: ['maj_white', 'maj_black', 'min_coal', 'min_influence'] },
    { label: 'Partisan Fairness',           keys: ['dem_seats', 'partisan_bias', 'efficiency_gap', 'mean_median'] },
    { label: 'Political Balance',           keys: ['comp_seats_7pt', 'comp_seats_10pt', 'comp_seats', 'rep_safe_seats', 'dem_safe_seats'] },
    { label: 'Geographic',                  keys: ['polsby_popper', 'county_splits', 'muni_splits'] },
  ];

  const gcSummary    = $derived(gcAnalysis.summary);
  const alarmSummary = $derived(alarmAnalysis.summary);

  function getMetric(analysis: Analysis, key: string): MetricGrade | null {
    const m = analysis.grades[key];
    if (!m || !('histogram' in m)) return null;
    return m as MetricGrade;
  }

  // Union of all metric keys that appear in either scorecard
  function rowsForGroup(keys: string[]): { key: string; gc: MetricGrade | null; alarm: MetricGrade | null }[] {
    return keys
      .map(k => ({ key: k, gc: getMetric(gcAnalysis, k), alarm: getMetric(alarmAnalysis, k) }))
      .filter(r => r.gc || r.alarm);
  }

  const nDistricts = $derived(gcSummary?.n_districts ?? alarmSummary?.n_districts ?? 14);
  const chamber    = $derived(
    gcSummary?.run?.chamber ?? gcSummary?.plan_type ?? ''
  );
  const CHAMBER_LABEL: Record<string, string> = {
    congress: 'U.S. Congressional Districts',
    senate:   'Georgia State Senate Districts',
    house:    'Georgia State House Districts',
    cd:       'U.S. Congressional Districts',
  };
  const chamberLabel = $derived(CHAMBER_LABEL[chamber] ?? chamber.toUpperCase());
</script>

<!-- Header strip -->
<div class="compare-header">
  <div class="chamber-title">{chamberLabel} — Algorithm Comparison</div>
  <div class="algo-columns">
    <div class="algo-col gc-col">
      <div class="algo-name">GerryChain / ReCom</div>
      <div class="algo-meta">
        {gcSummary?.n_plans?.toLocaleString() ?? '—'} simulated maps
        {#if gcSummary?.run?.date} · {gcSummary.run.date}{/if}
      </div>
    </div>
    <div class="algo-divider-label">vs</div>
    <div class="algo-col alarm-col">
      <div class="algo-name">ALARM / SMC (redist)</div>
      <div class="algo-meta">
        {alarmSummary?.n_plans?.toLocaleString() ?? '—'} simulated maps
        {#if alarmSummary?.run?.date} · {alarmSummary.run.date}{/if}
      </div>
    </div>
  </div>

  <!-- Legend -->
  <div class="legend">
    <span class="legend-item"><span class="legend-line enacted-line"></span> Enacted</span>
    <span class="legend-item"><span class="legend-line median-line"></span> Ensemble median</span>
    <span class="legend-item"><span class="legend-box iqr-box"></span> Interquartile range</span>
    <span class="legend-item"><span class="legend-box grade-box"></span> A-grade zone</span>
  </div>
</div>

<!-- Metric groups -->
{#each METRIC_GROUPS as group}
  {@const rows = rowsForGroup(group.keys)}
  {#if rows.length}
    <div class="group-label">{group.label}</div>
    <div class="metric-list">
      {#each rows as row}
        <AlgoCompareRow
          metricKey={row.key}
          gcMetric={row.gc}
          alarmMetric={row.alarm}
          {nDistricts}
        />
      {/each}
    </div>
  {/if}
{/each}

<!-- If there are any metrics outside the known groups, show them in an "Other" section -->
{#if (() => {
  const allKnown = new Set(METRIC_GROUPS.flatMap(g => g.keys));
  const extras = Object.keys(gcAnalysis.grades)
    .concat(Object.keys(alarmAnalysis.grades))
    .filter(k => !k.startsWith('_') && !allKnown.has(k));
  return extras.length > 0;
})()}
  {@const allKnown = new Set(METRIC_GROUPS.flatMap(g => g.keys))}
  {@const extraKeys = [...new Set(
    Object.keys(gcAnalysis.grades)
      .concat(Object.keys(alarmAnalysis.grades))
      .filter(k => !k.startsWith('_') && !allKnown.has(k) &&
        (getMetric(gcAnalysis, k) || getMetric(alarmAnalysis, k)))
  )]}
  {#if extraKeys.length}
    <div class="group-label">Other Metrics</div>
    <div class="metric-list">
      {#each extraKeys as key}
        <AlgoCompareRow
          metricKey={key}
          gcMetric={getMetric(gcAnalysis, key)}
          alarmMetric={getMetric(alarmAnalysis, key)}
          {nDistricts}
        />
      {/each}
    </div>
  {/if}
{/if}

<style>
  .compare-header {
    background: var(--card);
    border: 1.5px solid var(--border);
    border-radius: 8px;
    padding: .75rem 1rem .65rem;
    margin-bottom: .9rem;
  }
  .chamber-title {
    font-size: .85rem;
    font-weight: 700;
    color: var(--text);
    margin-bottom: .5rem;
  }
  .algo-columns {
    display: flex;
    align-items: center;
    gap: 1rem;
    margin-bottom: .55rem;
  }
  .algo-col {
    flex: 1;
    padding: .35rem .65rem;
    border-radius: 5px;
  }
  .gc-col    { background: #e8f0fb; border: 1px solid #b8d0f0; }
  .alarm-col { background: #fdecea; border: 1px solid #f0b8b8; }
  .algo-name {
    font-size: .76rem;
    font-weight: 700;
    margin-bottom: .12rem;
  }
  .gc-col    .algo-name { color: #2c5a99; }
  .alarm-col .algo-name { color: #9b2222; }
  .algo-meta {
    font-size: .65rem;
    color: var(--gray);
  }
  .algo-divider-label {
    font-size: .8rem;
    font-weight: 700;
    color: var(--gray);
    white-space: nowrap;
  }
  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: .6rem 1rem;
    font-size: .65rem;
    color: var(--gray);
    margin-top: .1rem;
  }
  .legend-item {
    display: flex;
    align-items: center;
    gap: .3rem;
  }
  .legend-line {
    display: inline-block;
    width: 18px;
    height: 2px;
  }
  .enacted-line  { border-top: 2px dashed #e74c3c; }
  .median-line   { border-top: 2px dashed #aaa; }
  .legend-box {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 2px;
  }
  .iqr-box   { background: #3D77BB; opacity: .15; border: 1px solid #3D77BB; }
  .grade-box { background: #27ae60; opacity: .25; border: 1px solid #27ae60; }

  .group-label {
    font-size: .72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .06em;
    color: var(--gray);
    margin: .8rem 0 .35rem;
  }
  .metric-list {
    display: flex;
    flex-direction: column;
    gap: 0;
  }
  .metric-list > :global(.compare-row) {
    border-radius: 0;
    border-bottom-width: 0;
  }
  .metric-list > :global(.compare-row:first-child) {
    border-radius: 8px 8px 0 0;
  }
  .metric-list > :global(.compare-row:last-child) {
    border-radius: 0 0 8px 8px;
    border-bottom-width: 1.5px;
  }
  .metric-list > :global(.compare-row:only-child) {
    border-radius: 8px;
    border-bottom-width: 1.5px;
  }
</style>
