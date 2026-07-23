<script lang="ts">
  import { tick } from 'svelte';
  import type { MetricGrade } from '../types.js';
  import { captureElement } from '../capture.js';

  interface PlanMetricOverlay {
    value: number;
    pct_rank: number;
    grade: string;
  }
  interface Props {
    metric: MetricGrade;
    metricKey?: string;         // scorecard key, e.g. "dem_seats" — used for partisan lean
    planMetric?: PlanMetricOverlay | null;
    demoThresholdKey?: string;  // e.g. "0.50", "0.20" — for demographic metrics only
    nDistricts?: number;        // total districts (congress=14, senate=56, house=180)
  }
  let { metric, metricKey = '', planMetric = null, demoThresholdKey = '', nDistricts = 14 }: Props = $props();

  // ── Demographic threshold override ────────────────────────────────────────
  // When demoThresholdKey is set and the metric has pre-computed threshold arrays,
  // use that threshold's draw_values and enacted count instead of the defaults.

  // Active draw_values: threshold-specific array if available, else metric default
  const activeDrawValues = $derived.by((): number[] => {
    const dbt = (metric as any).draw_values_by_threshold as Record<string, number[]> | undefined;
    if (demoThresholdKey && dbt && dbt[demoThresholdKey]) return dbt[demoThresholdKey];
    return (metric as any).draw_values as number[] ?? [];
  });

  // Active enacted count: threshold-specific if available, else metric default
  const activeEnacted = $derived.by((): number => {
    const ebt = (metric as any).enacted_by_threshold as Record<string, number> | undefined;
    if (demoThresholdKey && ebt && ebt[demoThresholdKey] !== undefined) return ebt[demoThresholdKey];
    return metric.enacted;
  });

  // Recomputed percentile rank using the active draw_values and active enacted
  const displayedPctRank = $derived.by((): number => {
    const dv = activeDrawValues;
    if (!dv || !dv.length || !demoThresholdKey) return metric.pct_rank;
    const enacted = activeEnacted;
    return (dv.filter((v: number) => v <= enacted).length / dv.length) * 100;
  });

  // Recomputed grade using the active percentile rank
  const displayedGrade = $derived.by((): string => {
    if (!demoThresholdKey) return metric.grade;
    const gradeFn = (metric as any).grade_fn as string || 'simple';
    const hib = (metric as any).higher_is_better as boolean | null;
    const pct = displayedPctRank;
    if (gradeFn === 'seats') {
      if (pct >= 50) return 'A'; if (pct >= 20) return 'B'; if (pct >= 5) return 'C'; return 'F';
    }
    if (gradeFn === 'comp') {
      if (pct >= 95) return 'A'; if (pct >= 64) return 'B'; if (pct >= 5) return 'C'; return 'F';
    }
    if (gradeFn === 'simple' || hib === null || hib === undefined) {
      const d = Math.abs(pct - 50);
      if (d <= 10) return 'A'; if (d <= 30) return 'B'; if (d <= 45) return 'C'; return 'F';
    }
    const rank = hib ? pct : (100 - pct);
    if (rank >= 95) return 'A'; if (rank >= 64) return 'B'; if (rank >= 5) return 'C'; return 'F';
  });

  // Plain let — NOT $state(). Chart.js calls Object.defineProperty on canvas
  // elements internally (resize observer), which Svelte 5's reactive proxy blocks.
  let canvas: HTMLCanvasElement;
  let chart: any;
  let cardEl: HTMLElement;
  let capturing = $state(false);

  async function doCapture() {
    if (capturing || !cardEl) return;
    capturing = true;
    try { await captureElement(cardEl, `metric-${metric.label.toLowerCase().replace(/\s+/g, '-')}`); }
    finally { capturing = false; }
  }

  const gradeColor: Record<string, string> = {
    A: '#27ae60', B: '#2980b9', C: '#d68910', D: '#e67e22', F: '#c0392b',
  };

  const categoryColor: Record<string, string> = {
    partisan:    '#3D77BB',
    competitive: '#17a589',
    geographic:  '#7f8c8d',
    minority:    '#8e44ad',
  };

  // ── Partisan lean: R = Republican advantage, D = Democrat advantage, neutral ────
  function getPartisanLean(): 'R' | 'D' | 'neutral' {
    if (!metricKey) return 'neutral';
    const pct  = metric.pct_rank;
    const hib  = (metric as any).higher_is_better as boolean | null;
    const val  = metric.enacted;
    const med  = metric.histogram.p50;
    const BAND = 15; // ±15 pctile of median = neutral zone

    if (hib === true) {
      if (Math.abs(pct - 50) <= BAND) return 'neutral';
      return pct < 50 ? 'R' : 'D';
    }
    if (hib === false) {
      if (Math.abs(pct - 50) <= BAND) return 'neutral';
      return pct > 50 ? 'R' : 'D';
    }
    // hib === null: metric-specific direction
    if (Math.abs(pct - 50) <= BAND) return 'neutral';
    switch (metricKey) {
      case 'dem_seats':      return val < med ? 'R' : 'D';
      case 'rep_safe_seats': return val > med ? 'R' : 'D';
      case 'dem_safe_seats': return val > med ? 'R' : 'D'; // D vote packing = R benefit
      case 'efficiency_gap': return val > med ? 'R' : 'D';
      case 'mean_median':    return val > med ? 'R' : 'D';
      case 'partisan_bias':  return val > med ? 'R' : 'D';
      case 'maj_black':      return val < med ? 'R' : 'D';
      case 'min_coal':       return val < med ? 'R' : 'D';
      case 'maj_white':      return val > med ? 'R' : 'neutral';
      default:               return 'neutral';
    }
  }
  const lean = $derived(getPartisanLean());

  function binIndex(edges: number[], val: number): number {
    let idx = edges.findIndex((e: number, i: number) => val >= e && val < edges[i + 1]);
    if (idx < 0) {
      if (val >= edges[0]) idx = edges.length - 2;
      else idx = 0;
    }
    return idx;
  }

  // Build integer histogram for threshold slider metrics.
  // draw_values_by_threshold stores counts 0–nDistricts; the original float
  // histogram edges (0.0–4.0) can't hold values > 4, so we always use integer
  // bins when threshold data is active.
  async function buildIntegerChart(drawVals: number[], enactedVal: number) {
    const { Chart, BarController, BarElement, CategoryScale, LinearScale, Tooltip } = await import('chart.js');
    Chart.register(BarController, BarElement, CategoryScale, LinearScale, Tooltip);

    if (chart) { chart.destroy(); chart = null; }

    const col = categoryColor[metric.category] ?? '#888';
    const N = nDistricts;

    // Integer bins 0 … N
    const allLabels = Array.from({length: N + 1}, (_, i) => String(i));
    const counts = new Array(N + 1).fill(0);
    for (const v of drawVals) {
      const idx = Math.min(Math.max(Math.round(v), 0), N);
      counts[idx]++;
    }
    const enactedBin = Math.min(Math.max(Math.round(enactedVal), 0), N);

    // Trim to populated range — include enacted bin, add 1-slot buffer each side
    let first = 0, last = N;
    while (first < N && counts[first] === 0) first++;
    while (last > 0 && counts[last] === 0) last--;
    first = Math.max(0, Math.min(first, enactedBin) - 1);
    last  = Math.min(N, Math.max(last,  enactedBin) + 1);

    const labels     = allLabels.slice(first, last + 1);
    const trimCounts = counts.slice(first, last + 1);
    const enactedTrimBin = enactedBin - first;

    // p5/p95 bin indices for neutral-band shading
    const sortedVals = [...drawVals].map(v => Math.min(Math.max(Math.round(v), 0), N)).sort((a,b)=>a-b);
    const p5bin  = sortedVals[Math.floor(sortedVals.length * 0.05)] - first;
    const p95bin = sortedVals[Math.floor(sortedVals.length * 0.95)] - first;

    chart = new Chart(canvas, {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          data: trimCounts,
          backgroundColor: col + '88',
          borderColor: col,
          borderWidth: 0,
          borderRadius: 2,
          barPercentage: 0.85,
          categoryPercentage: 0.9,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: (items: any[]) => `${items[0].label} districts`,
              label: (item: any) => `${(item.raw as number).toLocaleString()} maps`,
            },
          },
        },
        scales: {
          x: {
            display: true,
            ticks: { font: { size: 8 }, color: '#888' },
            grid: { display: false },
            border: { display: true, color: 'rgba(0,0,0,0.15)' },
          },
          y: {
            display: true,
            ticks: { display: false },
            grid: { color: 'rgba(0,0,0,0.05)', drawTicks: false },
            border: { display: false },
          },
        },
      },
      plugins: [{
        id: 'neutral-band',
        beforeDatasetsDraw(ch: any) {
          const xScale = ch.scales.x;
          const { ctx, chartArea: { top, bottom, left, right } } = ch;
          const bw = labels.length > 1 ? Math.abs(xScale.getPixelForValue(1) - xScale.getPixelForValue(0)) : 10;
          const xLeft  = p5bin  > 0              ? xScale.getPixelForValue(p5bin)  - bw / 2 : left;
          const xRight = p95bin < labels.length - 1 ? xScale.getPixelForValue(p95bin) + bw / 2 : right;
          ctx.save();
          ctx.fillStyle = 'rgba(61, 119, 187, 0.08)';
          ctx.fillRect(xLeft, top, xRight - xLeft, bottom - top);
          ctx.restore();
        },
      }, {
        id: 'enacted-line',
        afterDraw(ch: any) {
          const xScale = ch.scales.x;
          const { ctx, chartArea: { top, bottom, right } } = ch;
          const x = xScale.getPixelForValue(enactedTrimBin);
          ctx.save();
          ctx.strokeStyle = '#d32f2f';
          ctx.lineWidth = 2.5;
          ctx.setLineDash([]);
          ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, bottom); ctx.stroke();
          const labelText = `Enacted (${enactedBin})`;
          ctx.font = 'bold 8px -apple-system, BlinkMacSystemFont, sans-serif';
          ctx.fillStyle = '#d32f2f';
          const lw = ctx.measureText(labelText).width;
          const lx = (x + lw + 6 < right) ? x + 4 : x - lw - 4;
          ctx.fillText(labelText, lx, top + 9);
          ctx.restore();
        },
      }],
    });
  }

  async function buildChart() {
    const { Chart, BarController, BarElement, CategoryScale, LinearScale, Tooltip } = await import('chart.js');
    Chart.register(BarController, BarElement, CategoryScale, LinearScale, Tooltip);

    if (chart) { chart.destroy(); chart = null; }

    const snap     = $state.snapshot(metric);
    const planSnap = planMetric ? $state.snapshot(planMetric) : null;
    const h        = snap.histogram;
    const edges    = Array.from(h.edges);
    const allLabels = edges.slice(0, -1).map((e: number, i: number) => ((e + edges[i + 1]) / 2).toFixed(2));
    const col      = categoryColor[snap.category] ?? '#888';
    const barCounts = Array.from(h.counts);

    // Use activeEnacted for the enacted vertical line when threshold is active
    const enactedLineVal = (demoThresholdKey && (metric as any).enacted_by_threshold)
      ? activeEnacted
      : (h.enacted ?? null);

    const aRange = snap.a_grade_range ?? null;

    // Trim to populated range — removes dead space on left/right tails
    let lo = 0, hi = barCounts.length - 1;
    while (lo < hi && barCounts[lo] === 0) lo++;
    while (hi > lo && barCounts[hi] === 0) hi--;
    lo = Math.max(0, lo - 1);
    hi = Math.min(barCounts.length - 1, hi + 1);
    // Ensure enacted and plan values are within the visible window
    if (enactedLineVal != null) {
      const ei = binIndex(Array.from(h.edges), enactedLineVal);
      if (ei >= 0) {
        lo = Math.min(lo, Math.max(0, ei - 1));
        hi = Math.max(hi, Math.min(barCounts.length - 1, ei + 1));
      }
    }
    if (planSnap) {
      const pi = binIndex(Array.from(h.edges), planSnap.value);
      if (pi >= 0) {
        lo = Math.min(lo, Math.max(0, pi - 1));
        hi = Math.max(hi, Math.min(barCounts.length - 1, pi + 1));
      }
    }
    const labels     = allLabels.slice(lo, hi + 1);
    const trimCounts = barCounts.slice(lo, hi + 1);

    // Map original bin index to trimmed index (offset by lo)
    const toTrimIdx = (val: number) => binIndex(Array.from(h.edges), val) - lo;

    chart = new Chart(canvas, {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          data:            trimCounts,
          backgroundColor: col + '88',
          borderColor:     col,
          borderWidth:     0,
          borderRadius:    2,
          barPercentage:   0.85,
          categoryPercentage: 0.9,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: (items: any[]) => `~${labels[items[0].dataIndex]}`,
              label: (item: any) => `${(item.raw as number).toLocaleString()} plans`,
            },
          },
        },
        scales: {
          x: {
            display: true,
            ticks: { display: false },
            grid: { display: false },
            border: { display: true, color: 'rgba(0,0,0,0.15)' },
          },
          y: {
            display: true,
            ticks: { display: false },
            grid: { color: 'rgba(0,0,0,0.05)', drawTicks: false },
            border: { display: false },
          },
        },
      },
      plugins: [{
        id: 'a-grade-band',
        beforeDatasetsDraw(ch: any) {
          if (!aRange) return;
          const { lo: grLo, hi: grHi } = aRange;
          if (grLo == null && grHi == null) return;
          const xScale = ch.scales.x;
          const { ctx, chartArea: { top, bottom, left, right } } = ch;
          const bw = edges.length > 2 ? Math.abs(xScale.getPixelForValue(1) - xScale.getPixelForValue(0)) : 10;
          const edgesArr = Array.from(h.edges);
          const loOrigIdx = grLo != null ? binIndex(edgesArr, grLo) : 0;
          const hiOrigIdx = grHi != null ? binIndex(edgesArr, grHi) : allLabels.length - 1;
          const loTrimIdx = loOrigIdx - lo;
          const hiTrimIdx = hiOrigIdx - lo;
          const xLeft  = loTrimIdx > 0 ? xScale.getPixelForValue(loTrimIdx) - bw / 2 : left;
          const xRight = hiTrimIdx < labels.length - 1 ? xScale.getPixelForValue(hiTrimIdx) + bw / 2 : right;
          ctx.save();
          ctx.fillStyle = 'rgba(39, 174, 96, 0.13)';
          ctx.fillRect(xLeft, top, xRight - xLeft, bottom - top);
          ctx.restore();
        },
      }, {
        id: 'neutral-band',
        beforeDatasetsDraw(ch: any) {
          if (h.p5 == null || h.p95 == null) return;
          const xScale = ch.scales.x;
          const { ctx, chartArea: { top, bottom, left, right } } = ch;
          const edgesArr = Array.from(h.edges);
          const bw = labels.length > 1 ? Math.abs(xScale.getPixelForValue(1) - xScale.getPixelForValue(0)) : 10;
          const p5TrimIdx  = binIndex(edgesArr, h.p5)  - lo;
          const p95TrimIdx = binIndex(edgesArr, h.p95) - lo;
          const xLeft  = p5TrimIdx  > 0              ? xScale.getPixelForValue(p5TrimIdx)  - bw / 2 : left;
          const xRight = p95TrimIdx < labels.length - 1 ? xScale.getPixelForValue(p95TrimIdx) + bw / 2 : right;
          ctx.save();
          ctx.fillStyle = 'rgba(61, 119, 187, 0.08)';
          ctx.fillRect(xLeft, top, xRight - xLeft, bottom - top);
          ctx.restore();
        },
      }, {
        id: 'value-lines',
        afterDraw(ch: any) {
          const xScale = ch.scales.x;
          const { ctx, chartArea: { top, bottom, right } } = ch;

          // Enacted line — crimson hero, with direct label
          if (enactedLineVal != null) {
            const trimIdx = toTrimIdx(enactedLineVal);
            if (trimIdx >= 0 && trimIdx < labels.length) {
              const x = xScale.getPixelForValue(trimIdx);
              ctx.save();
              ctx.strokeStyle = '#d32f2f';
              ctx.lineWidth   = 2.5;
              ctx.setLineDash([]);
              ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, bottom); ctx.stroke();
              const fmt = (v: number) => Number.isInteger(v) ? String(v) : v.toFixed(2);
              const labelText = `Enacted (${fmt(enactedLineVal)})`;
              ctx.font = 'bold 8px -apple-system, BlinkMacSystemFont, sans-serif';
              ctx.fillStyle = '#d32f2f';
              const lw = ctx.measureText(labelText).width;
              const lx = (x + lw + 6 < right) ? x + 4 : x - lw - 4;
              ctx.fillText(labelText, lx, top + 9);
              ctx.restore();
            }
          }

          // Plan overlay — orange solid line
          if (planSnap && (enactedLineVal == null || Math.abs(planSnap.value - enactedLineVal) > 1e-6)) {
            const trimIdx = toTrimIdx(planSnap.value);
            if (trimIdx >= 0 && trimIdx < labels.length) {
              const x = xScale.getPixelForValue(trimIdx);
              ctx.save();
              ctx.strokeStyle = '#e67e22';
              ctx.lineWidth   = 2.5;
              ctx.setLineDash([]);
              ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, bottom); ctx.stroke();
              ctx.restore();
            }
          }
        },
      }],
    });
  }

  // Rebuild chart whenever metric, planMetric, demoThresholdKey, or activeDrawValues change.
  // When threshold data is active, use buildIntegerChart (correct integer bins 0–nDistricts).
  // Otherwise use buildChart with the original histogram.
  $effect(() => {
    const m   = metric;
    const pm  = planMetric;
    const tk  = demoThresholdKey;
    const adv = activeDrawValues;   // reactive — changes when threshold key changes
    const ae  = activeEnacted;      // reactive — changes when threshold key changes
    tick().then(() => {
      if (!canvas || !m) return;
      if (tk && adv && adv.length) {
        buildIntegerChart(adv, ae);
      } else {
        buildChart();
      }
    });
    return () => { if (chart) { chart.destroy(); chart = null; } };
  });
</script>

<!-- ── Full-width layout ─────────────────────────────────────────────────── -->
  <div class="metric-card" bind:this={cardEl}>

    <!-- Headline -->
    <div class="headline" style="border-bottom:1px solid var(--border);padding:.55rem 1rem;
         background:var(--light);
         display:flex;align-items:center;justify-content:space-between;gap:.5rem;">
      <div style="display:flex;align-items:center;gap:.4rem;min-width:0;flex:1;">
        <span style="font-size:.72rem;font-weight:600;text-transform:uppercase;letter-spacing:.05em;
                     color:var(--gray);white-space:nowrap;">{metric.label}</span>
        <span style="font-size:.82rem;font-weight:700;color:var(--blue);white-space:nowrap;">{metric.headline ?? metric.label}</span>
        {#if metric.description}
          <span class="info-tip">
            <span class="info-tip-icon">ⓘ</span>
            <span class="info-tip-box">{metric.description}</span>
          </span>
        {/if}
      </div>
      <button class="capture-btn" onclick={doCapture} disabled={capturing} title="Save as PNG">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="7,10 12,15 17,10"/>
          <line x1="12" y1="15" x2="12" y2="3"/>
        </svg>
        {capturing ? 'Saving…' : 'PNG'}
      </button>
    </div>

    <!-- Body: grade info + histogram + finding -->
    <div class="metric-body">

      <!-- Left: grade + numbers -->
      <div style="padding:.7rem .9rem;border-right:1px solid var(--border);display:flex;flex-direction:column;gap:.3rem;">
        {#if planMetric}
          <!-- Plan overlay mode -->
          <div style="display:flex;align-items:center;gap:.3rem;">
            <span style="font-size:.95rem;font-weight:800;color:var(--blue);">{planMetric.pct_rank}</span><span style="font-size:.65rem;color:var(--gray);">th pctile</span>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:.15rem .5rem;margin-top:.2rem;">
            <div>
              <div style="font-size:.58rem;text-transform:uppercase;letter-spacing:.04em;color:#e67e22;">This Plan</div>
              <div style="font-weight:700;font-size:.85rem;color:#e67e22;">{planMetric.value.toFixed(2)}</div>
            </div>
            <div>
              <div style="font-size:.58rem;text-transform:uppercase;letter-spacing:.04em;color:var(--gray);">Enacted</div>
              <div style="font-size:.85rem;">{metric.enacted.toFixed(2)}</div>
            </div>
            <div>
              <div style="font-size:.58rem;text-transform:uppercase;letter-spacing:.04em;color:var(--gray);">Neutral median</div>
              <div style="font-size:.85rem;">{metric.histogram.p50.toFixed(2)}</div>
            </div>
            <div>
              <div style="font-size:.58rem;text-transform:uppercase;letter-spacing:.04em;color:var(--gray);">5th–95th range</div>
              <div style="font-size:.78rem;font-weight:600;">{metric.histogram.p5.toFixed(2)} – {metric.histogram.p95.toFixed(2)}</div>
            </div>
            {#if metric.histogram.p25 != null && metric.histogram.p75 != null}
            <div style="grid-column:span 2;">
              <div style="font-size:.58rem;text-transform:uppercase;letter-spacing:.04em;color:#27ae60;">Most representative (25th–75th)</div>
              <div style="font-size:.78rem;font-weight:600;color:#27ae60;">{metric.histogram.p25.toFixed(2)} – {metric.histogram.p75.toFixed(2)}</div>
            </div>
            {/if}
          </div>
        {:else}
          <!-- Default: enacted percentile rank -->
          <div style="display:flex;align-items:center;gap:.3rem;">
            <span style="font-size:.95rem;font-weight:800;color:var(--blue);">{Math.round(displayedPctRank)}</span><span style="font-size:.65rem;color:var(--gray);">th pctile</span>
            {#if demoThresholdKey}
              <span style="font-size:.6rem;color:#8e44ad;font-style:italic;">@{Math.round(+demoThresholdKey*100)}%</span>
            {/if}
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:.15rem .5rem;margin-top:.2rem;">
            <div>
              <div style="font-size:.58rem;text-transform:uppercase;letter-spacing:.04em;color:var(--gray);">Enacted</div>
              <div style="font-weight:700;font-size:.85rem;">{metric.enacted.toFixed(2)}</div>
            </div>
            <div>
              <div style="font-size:.58rem;text-transform:uppercase;letter-spacing:.04em;color:var(--gray);">Neutral median</div>
              <div style="font-size:.85rem;">{metric.histogram.p50.toFixed(2)}</div>
            </div>
            <div style="grid-column:span 2;">
              <div style="font-size:.58rem;text-transform:uppercase;letter-spacing:.04em;color:var(--gray);">Neutral 5th–95th range</div>
              <div style="font-size:.78rem;font-weight:600;">{metric.histogram.p5.toFixed(2)} – {metric.histogram.p95.toFixed(2)}</div>
            </div>
            {#if metric.histogram.p25 != null && metric.histogram.p75 != null}
            <div style="grid-column:span 2;">
              <div style="font-size:.58rem;text-transform:uppercase;letter-spacing:.04em;color:#27ae60;">Most representative (25th–75th)</div>
              <div style="font-size:.78rem;font-weight:600;color:#27ae60;">{metric.histogram.p25.toFixed(2)} – {metric.histogram.p75.toFixed(2)}</div>
            </div>
            {/if}
          </div>
        {/if}
      </div>

      <!-- Histogram -->
      <div style="padding:.6rem .7rem;display:flex;flex-direction:column;justify-content:center;border-right:1px solid var(--border);">
        <div style="height:115px;position:relative;">
          <canvas bind:this={canvas}></canvas>
        </div>
        <div style="font-size:.58rem;color:var(--gray);margin-top:.25rem;text-align:center;">
          {#if planMetric}
            <span style="color:#e67e22;font-weight:700;">—</span> this plan &nbsp;
            <span style="color:#d32f2f;">—</span> enacted &nbsp;|&nbsp; {metric.histogram.counts.reduce((a:number,b:number)=>a+b,0).toLocaleString()} neutral maps
          {:else}
            <span style="color:#d32f2f;">—</span> enacted &nbsp;|&nbsp; {metric.histogram.counts.reduce((a:number,b:number)=>a+b,0).toLocaleString()} neutral maps
            {#if demoThresholdKey}&nbsp;<span style="color:#8e44ad;font-weight:600;">≥{Math.round(+demoThresholdKey*100)}% BVAP</span>{/if}
          {/if}
          {#if metric.a_grade_range}
            &nbsp;|&nbsp; <span style="color:#27ae60;">█</span> A zone
            <span
              title="The green band marks the A-grade threshold — what excellent looks like. For this metric, earning an A means the enacted map performs better than roughly 95% of randomly drawn fair maps. The crimson line shows where the enacted map falls relative to that standard."
              style="cursor:help;color:#27ae60;font-size:.68rem;vertical-align:super;margin-left:1px;line-height:1;">ⓘ</span>
          {/if}
        </div>
      </div>

      <!-- Finding — right column -->
      <div style="padding:.8rem 1rem;display:flex;flex-direction:column;justify-content:center;background:#f8f9fb;">
        {#if metric.takeaway}
          <div style="font-size:.62rem;font-weight:800;text-transform:uppercase;letter-spacing:.08em;
                      color:var(--gray);margin-bottom:.35rem;">Finding →</div>
          <div style="font-size:.88rem;color:#1a1a1a;line-height:1.55;font-weight:500;">{metric.takeaway}</div>
        {/if}
      </div>

    </div>
  </div>

<style>
  .metric-card {
    background: var(--card);
    border-radius: 8px;
    border: 1.5px solid var(--border);
    box-shadow: var(--shadow);
    overflow: hidden;
  }
.capture-btn {
    display: flex;
    align-items: center;
    gap: .25rem;
    padding: .2rem .45rem;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: transparent;
    cursor: pointer;
    font-size: .66rem;
    color: var(--gray);
    flex-shrink: 0;
  }
  .capture-btn:hover { background: var(--light); }

  /* ── Inline tooltip ─────────────────────────────────────────────────── */
  .info-tip {
    position: relative;
    display: inline-flex;
    align-items: center;
  }
  .info-tip-icon {
    font-size: .68rem;
    color: var(--gray);
    cursor: help;
    padding: 0 .15rem;
    line-height: 1;
    white-space: nowrap;
  }
  .info-tip-box {
    visibility: hidden;
    opacity: 0;
    transition: opacity .12s;
    position: absolute;
    top: calc(100% + 5px);
    left: 0;
    width: 300px;
    background: #1e2226;
    color: #eee;
    font-size: .7rem;
    line-height: 1.55;
    padding: .6rem .75rem;
    border-radius: 6px;
    z-index: 300;
    pointer-events: none;
    white-space: normal;
    box-shadow: 0 4px 14px rgba(0,0,0,.3);
    font-weight: 400;
  }
  .info-tip:hover .info-tip-box {
    visibility: visible;
    opacity: 1;
  }

  .metric-body {
    display: grid;
    grid-template-columns: 150px minmax(0, 1fr) minmax(0, 1.15fr);
    min-width: 0;
  }

  @media (max-width: 700px) {
    .metric-body {
      grid-template-columns: 1fr;
    }
  }
</style>
