<script lang="ts">
  import type { MetricGrade } from '../types.js';
  import MiniHistogram from './MiniHistogram.svelte';

  interface Props {
    metricKey:   string;
    gcMetric:    MetricGrade | null;
    alarmMetric: MetricGrade | null;
    nDistricts?: number;
  }
  let { metricKey, gcMetric, alarmMetric, nDistricts = 14 }: Props = $props();

  // For demographic threshold metrics: build integer frequency histogram from draw_values
  function getHistogramData(metric: MetricGrade): { counts: number[]; edges: number[]; enacted: number | null } {
    const dbt = (metric as any).draw_values_by_threshold as Record<string, number[]> | undefined;
    if (dbt?.['0.50']) {
      const vals = dbt['0.50'] as number[];
      const maxVal = nDistricts;
      const counts = Array(maxVal + 1).fill(0);
      for (const v of vals) {
        const i = Math.round(v);
        if (i >= 0 && i <= maxVal) counts[i]++;
      }
      const edges = Array.from({ length: maxVal + 2 }, (_, i) => i - 0.5);
      const enacted = (metric as any).enacted_by_threshold?.['0.50'] ?? metric.enacted;
      return { counts, edges, enacted };
    }
    return { counts: metric.histogram.counts, edges: metric.histogram.edges, enacted: metric.histogram.enacted };
  }

  const gcData    = $derived(gcMetric    ? getHistogramData(gcMetric)    : null);
  const alarmData = $derived(alarmMetric ? getHistogramData(alarmMetric) : null);

  // Shared x-axis range (union of both histograms for fair visual comparison)
  const sharedXMin = $derived(Math.min(
    gcData    ? gcData.edges[0]              : Infinity,
    alarmData ? alarmData.edges[0]           : Infinity,
  ));
  const sharedXMax = $derived(Math.max(
    gcData    ? (gcData.edges.at(-1) ?? -Infinity)    : -Infinity,
    alarmData ? (alarmData.edges.at(-1) ?? -Infinity) : -Infinity,
  ));

  const GRADE_COLOR: Record<string, string> = {
    A: '#27ae60', B: '#2980b9', C: '#d68910', F: '#c0392b',
  };

  function gradeBg(g: string) {
    return GRADE_COLOR[g] ?? '#888';
  }

  function fmtVal(v: number | null | undefined): string {
    if (v == null) return '—';
    if (Number.isInteger(v) || Math.abs(v) >= 10) return String(Math.round(v));
    return v.toFixed(3);
  }

  function ordinal(n: number): string {
    const s = ['th','st','nd','rd'];
    const v = n % 100;
    return Math.round(n) + (s[(v - 20) % 10] || s[v] || s[0]);
  }

  const label = $derived(gcMetric?.label ?? alarmMetric?.label ?? metricKey);
</script>

<div class="compare-row">
  <!-- Metric label header -->
  <div class="row-header">{label}</div>

  <div class="row-body">

    <!-- ── GerryChain side ──────────────────────────────────────── -->
    {#if gcMetric && gcData}
      <div class="half gc-half">
        <!-- Stats panel (outer left) -->
        <div class="stats-panel">
          <div class="grade-badge" style="background:{gradeBg(gcMetric.grade)}">
            {gcMetric.grade}
          </div>
          <div class="stat-row"><span class="lbl">Enacted</span><span class="val">{fmtVal(gcData.enacted)}</span></div>
          <div class="stat-row"><span class="lbl">Percentile</span><span class="val">{ordinal(gcMetric.pct_rank)}</span></div>
          <div class="stat-row"><span class="lbl">Median</span><span class="val">{fmtVal(gcMetric.histogram.p50)}</span></div>
          <div class="stat-row range-row">
            <span class="lbl">IQR</span>
            <span class="val">{fmtVal(gcMetric.histogram.p25)}–{fmtVal(gcMetric.histogram.p75)}</span>
          </div>
        </div>
        <!-- Histogram (inner, facing divider) -->
        <div class="hist-wrap">
          <MiniHistogram
            counts={gcData.counts}
            edges={gcData.edges}
            enacted={gcData.enacted}
            p25={gcMetric.histogram.p25}
            p50={gcMetric.histogram.p50}
            p75={gcMetric.histogram.p75}
            aGradeRange={gcMetric.a_grade_range}
            xMin={sharedXMin}
            xMax={sharedXMax}
            color="#3D77BB"
          />
          <div class="hist-label">GerryChain · {gcMetric.histogram.counts.reduce((s,c)=>s+c,0).toLocaleString()} maps</div>
        </div>
      </div>
    {:else}
      <div class="half unavailable">
        <div class="unavail-text">GerryChain<br>not available</div>
      </div>
    {/if}

    <!-- Centre divider -->
    <div class="divider"></div>

    <!-- ── ALARM side ──────────────────────────────────────────── -->
    {#if alarmMetric && alarmData}
      <div class="half alarm-half">
        <!-- Histogram (inner, facing divider) -->
        <div class="hist-wrap">
          <MiniHistogram
            counts={alarmData.counts}
            edges={alarmData.edges}
            enacted={alarmData.enacted}
            p25={alarmMetric.histogram.p25}
            p50={alarmMetric.histogram.p50}
            p75={alarmMetric.histogram.p75}
            aGradeRange={alarmMetric.a_grade_range}
            xMin={sharedXMin}
            xMax={sharedXMax}
            color="#c0392b"
          />
          <div class="hist-label">ALARM/SMC · {alarmMetric.histogram.counts.reduce((s,c)=>s+c,0).toLocaleString()} maps</div>
        </div>
        <!-- Stats panel (outer right) -->
        <div class="stats-panel">
          <div class="grade-badge" style="background:{gradeBg(alarmMetric.grade)}">
            {alarmMetric.grade}
          </div>
          <div class="stat-row"><span class="lbl">Enacted</span><span class="val">{fmtVal(alarmData.enacted)}</span></div>
          <div class="stat-row"><span class="lbl">Percentile</span><span class="val">{ordinal(alarmMetric.pct_rank)}</span></div>
          <div class="stat-row"><span class="lbl">Median</span><span class="val">{fmtVal(alarmMetric.histogram.p50)}</span></div>
          <div class="stat-row range-row">
            <span class="lbl">IQR</span>
            <span class="val">{fmtVal(alarmMetric.histogram.p25)}–{fmtVal(alarmMetric.histogram.p75)}</span>
          </div>
        </div>
      </div>
    {:else}
      <div class="half unavailable">
        <div class="unavail-text">ALARM<br>not available</div>
      </div>
    {/if}

  </div><!-- row-body -->

  <!-- Takeaway (shared, or one per side if they differ) -->
  {#if gcMetric?.takeaway || alarmMetric?.takeaway}
    <div class="takeaway-row">
      {#if gcMetric?.takeaway && alarmMetric?.takeaway && gcMetric.takeaway !== alarmMetric.takeaway}
        <span class="algo-tag gc-tag">GC:</span> {gcMetric.takeaway}
        <span style="margin-left:.8rem;"></span>
        <span class="algo-tag alarm-tag">ALARM:</span> {alarmMetric.takeaway}
      {:else}
        {gcMetric?.takeaway ?? alarmMetric?.takeaway}
      {/if}
    </div>
  {/if}
</div>

<style>
  .compare-row {
    background: var(--card);
    border: 1.5px solid var(--border);
    border-radius: 8px;
    overflow: hidden;
    margin-bottom: .55rem;
  }
  .row-header {
    font-size: .73rem;
    font-weight: 700;
    text-align: center;
    padding: .38rem .8rem .3rem;
    background: var(--light);
    border-bottom: 1px solid var(--border);
    color: var(--text);
    letter-spacing: .01em;
  }
  .row-body {
    display: flex;
    align-items: stretch;
    min-height: 96px;
  }
  .half {
    flex: 1;
    display: flex;
    align-items: center;
    padding: .45rem .6rem;
    gap: .5rem;
    min-width: 0;
  }
  .gc-half {
    flex-direction: row;      /* [stats] [histogram] → facing divider */
  }
  .alarm-half {
    flex-direction: row-reverse; /* [stats] [histogram] → mirrored so stats are on right */
  }
  .divider {
    width: 2px;
    background: var(--border);
    flex-shrink: 0;
    align-self: stretch;
    margin: .3rem 0;
    border-radius: 1px;
  }
  .stats-panel {
    flex-shrink: 0;
    width: 106px;
    display: flex;
    flex-direction: column;
    gap: .18rem;
    padding: .1rem 0;
  }
  .grade-badge {
    display: inline-block;
    font-size: 1.3rem;
    font-weight: 800;
    line-height: 1;
    color: #fff;
    width: 2.1rem;
    height: 2.1rem;
    border-radius: 5px;
    display: flex;
    align-items: center;
    justify-content: center;
    margin-bottom: .25rem;
  }
  .stat-row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: .25rem;
    font-size: .68rem;
    line-height: 1.35;
  }
  .lbl {
    color: var(--gray);
    white-space: nowrap;
  }
  .val {
    font-family: monospace;
    font-size: .7rem;
    font-weight: 600;
    color: var(--text);
    text-align: right;
  }
  .range-row .val { font-size: .65rem; }
  .hist-wrap {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: .1rem;
  }
  .hist-label {
    font-size: .6rem;
    color: var(--gray);
    text-align: center;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .unavailable {
    justify-content: center;
    align-items: center;
    background: var(--light);
    opacity: .6;
  }
  .unavail-text {
    font-size: .68rem;
    color: var(--gray);
    text-align: center;
    line-height: 1.5;
  }
  .takeaway-row {
    font-size: .68rem;
    color: var(--gray);
    line-height: 1.5;
    padding: .3rem .9rem .4rem;
    border-top: 1px solid var(--border);
    background: var(--light);
    font-style: italic;
  }
  .algo-tag {
    font-style: normal;
    font-weight: 700;
    font-size: .63rem;
    padding: .05rem .3rem;
    border-radius: 3px;
    margin-right: .25rem;
  }
  .gc-tag   { background: #ddeeff; color: #2c5a99; }
  .alarm-tag { background: #fce8e8; color: #9b2222; }
</style>
