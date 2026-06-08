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
    planMetric?: PlanMetricOverlay | null;
    filterPct?: number;
  }
  let { metric, planMetric = null, filterPct = 0 }: Props = $props();

  // ── Ensemble quality filter logic ─────────────────────────────────────────
  // When filterPct > 0, remove the bottom X% worst-performing ensemble plans
  // and recompute the enacted map's percentile rank + grade in real-time.

  function computeGrade(pctRank: number, gradeFn: string, higherIsBetter: boolean | null): string {
    if (gradeFn === 'seats') {
      if (pctRank >= 50) return 'A';
      if (pctRank >= 20) return 'B';
      if (pctRank >= 5)  return 'C';
      return 'F';
    }
    if (gradeFn === 'comp') {
      if (pctRank >= 95) return 'A';
      if (pctRank >= 64) return 'B';
      if (pctRank >= 5)  return 'C';
      return 'F';
    }
    if (gradeFn === 'simple' || higherIsBetter === null || higherIsBetter === undefined) {
      const dist = Math.abs(pctRank - 50);
      if (dist <= 10) return 'A';
      if (dist <= 30) return 'B';
      if (dist <= 45) return 'C';
      return 'F';
    }
    // directional
    const rank = higherIsBetter ? pctRank : (100 - pctRank);
    if (rank >= 95) return 'A';
    if (rank >= 64) return 'B';
    if (rank >= 5)  return 'C';
    return 'F';
  }

  function rebucket(values: number[], edges: number[]): number[] {
    const n = edges.length - 1;
    const counts = new Array(n).fill(0);
    for (const v of values) {
      let idx = edges.findIndex((e: number, i: number) => v >= e && v < edges[i + 1]);
      if (idx < 0) {
        if (v >= edges[0]) idx = n - 1;
        else idx = 0;
      }
      if (idx >= 0 && idx < n) counts[idx]++;
    }
    return counts;
  }

  const filteredDrawValues = $derived.by((): number[] | null => {
    const dv = (metric as any).draw_values as number[] | undefined;
    const hib = (metric as any).higher_is_better as boolean | null | undefined;
    if (!dv || filterPct <= 0) return null;
    const sorted = [...dv].sort((a: number, b: number) => a - b);
    const n = sorted.length;
    const cutN = Math.floor(filterPct / 100 * n);
    if (hib === true) {
      return sorted.slice(cutN);           // keep top (100 - filterPct)%
    } else if (hib === false) {
      return sorted.slice(0, n - cutN);    // keep bottom (100 - filterPct)%
    } else {
      // Symmetric: remove cutN/2 from each tail (both extremes are "worst")
      const halfCut = Math.floor(cutN / 2);
      return sorted.slice(halfCut, n - halfCut);
    }
  });

  const displayedPctRank = $derived.by((): number => {
    if (!filteredDrawValues || !filteredDrawValues.length) return metric.pct_rank;
    const enacted = metric.enacted;
    return (filteredDrawValues.filter((v: number) => v <= enacted).length / filteredDrawValues.length) * 100;
  });

  const displayedGrade = $derived.by((): string => {
    if (!filteredDrawValues) return metric.grade;
    const gradeFn = (metric as any).grade_fn as string || 'simple';
    const hib = (metric as any).higher_is_better as boolean | null;
    return computeGrade(displayedPctRank, gradeFn, hib);
  });

  const filteredHistCounts = $derived.by((): number[] | null => {
    if (!filteredDrawValues) return null;
    return rebucket(filteredDrawValues, Array.from(metric.histogram.edges));
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

  function barColor() {
    return categoryColor[metric.category] ?? '#888';
  }

  function binIndex(edges: number[], val: number): number {
    let idx = edges.findIndex((e: number, i: number) => val >= e && val < edges[i + 1]);
    if (idx < 0) {
      if (val >= edges[0]) idx = edges.length - 2;
      else idx = 0;
    }
    return idx;
  }

  async function buildChart(filteredCounts: number[] | null = null) {
    const { Chart, BarController, BarElement, CategoryScale, LinearScale, Tooltip } = await import('chart.js');
    Chart.register(BarController, BarElement, CategoryScale, LinearScale, Tooltip);

    if (chart) { chart.destroy(); chart = null; }

    // $state.snapshot() converts reactive proxy → plain JS object so Chart.js
    // can safely call Object.defineProperty on the data arrays internally.
    const snap    = $state.snapshot(metric);
    const planSnap = planMetric ? $state.snapshot(planMetric) : null;
    const h       = snap.histogram;
    const edges   = Array.from(h.edges);
    const labels  = edges.slice(0, -1).map((e: number, i: number) => ((e + edges[i + 1]) / 2).toFixed(2));
    const col     = categoryColor[snap.category] ?? '#888';
    const barCounts = filteredCounts ?? Array.from(h.counts);

    const aRange = snap.a_grade_range ?? null;

    chart = new Chart(canvas, {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          data:            barCounts,
          backgroundColor: col + '88',
          borderColor:     col,
          borderWidth:     0.5,
          borderRadius:    1,
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
              label: (item: any) => `${item.raw} plans`,
            },
          },
        },
        scales: {
          x: { display: false },
          y: { display: false },
        },
      },
      plugins: [{
        id: 'a-grade-band',
        beforeDatasetsDraw(ch: any) {
          if (!aRange) return;
          const { lo, hi } = aRange;
          if (lo == null && hi == null) return;
          const xScale = ch.scales.x;
          const { ctx, chartArea: { top, bottom, left, right } } = ch;
          const bw = edges.length > 2 ? Math.abs(xScale.getPixelForValue(1) - xScale.getPixelForValue(0)) : 10;
          const edgesArr = Array.from(h.edges);
          const xLeft  = lo != null ? xScale.getPixelForValue(binIndex(edgesArr, lo)) - bw / 2 : left;
          const xRight = hi != null ? xScale.getPixelForValue(binIndex(edgesArr, hi)) + bw / 2 : right;
          ctx.save();
          ctx.fillStyle = 'rgba(39, 174, 96, 0.13)';
          ctx.fillRect(xLeft, top, xRight - xLeft, bottom - top);
          ctx.restore();
        },
      }, {
        id: 'value-lines',
        afterDraw(ch: any) {
          const xScale = ch.scales.x;
          const { ctx, chartArea: { top, bottom } } = ch;

          // Enacted black dashed line
          if (h.enacted != null) {
            const idx = binIndex(Array.from(h.edges), h.enacted);
            if (idx >= 0) {
              const x = xScale.getPixelForValue(idx);
              ctx.save();
              ctx.strokeStyle = '#111';
              ctx.lineWidth   = 2;
              ctx.setLineDash([4, 3]);
              ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, bottom); ctx.stroke();
              ctx.restore();
            }
          }

          // Plan overlay — orange solid line (only when different from enacted)
          if (planSnap && (h.enacted == null || Math.abs(planSnap.value - h.enacted) > 1e-6)) {
            const idx = binIndex(Array.from(h.edges), planSnap.value);
            if (idx >= 0) {
              const x = xScale.getPixelForValue(idx);
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

  // Track metric + planMetric + filterPct changes so chart rebuilds when any change.
  $effect(() => {
    const m  = metric;
    const pm = planMetric;    // declare dependency
    const fc = filteredHistCounts;  // declare dependency — triggers on filterPct change
    tick().then(() => {
      if (canvas && m) buildChart(fc);
    });
    return () => { if (chart) { chart.destroy(); chart = null; } };
  });
</script>

<div class="metric-card" class:is-outlier={metric.grade === 'F'} bind:this={cardEl}>

  <!-- Headline -->
  <div class="headline" style="border-bottom:1px solid var(--border);padding:.55rem 1rem;
       background:{metric.grade === 'F' ? '#fff5f5' : metric.grade === 'A' ? '#f5fdf8' : 'var(--light)'};
       display:flex;align-items:center;justify-content:space-between;gap:.5rem;">
    <div>
      <span style="font-size:.72rem;font-weight:600;text-transform:uppercase;letter-spacing:.05em;
                   color:var(--gray);margin-right:.5rem;">{metric.label}</span>
      <span style="font-size:.82rem;font-weight:700;color:var(--blue);">{metric.headline ?? metric.label}</span>
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

  <!-- Body: grade info + histogram + description -->
  <div style="display:grid;grid-template-columns:190px 200px 1fr;min-width:0;">

    <!-- Left: grade + numbers -->
    <div style="padding:.7rem .9rem;border-right:1px solid var(--border);display:flex;flex-direction:column;gap:.3rem;">
      {#if planMetric}
        <!-- Plan overlay mode -->
        <div style="display:flex;align-items:center;gap:.4rem;">
          <span style="display:inline-flex;align-items:center;justify-content:center;
                       width:1.7rem;height:1.7rem;border-radius:50%;
                       background:{gradeColor[planMetric.grade] ?? '#888'};
                       color:#fff;font-weight:800;font-size:.85rem;flex-shrink:0;">{planMetric.grade}</span>
          <span style="font-size:.7rem;color:var(--gray);">{planMetric.pct_rank}th percentile</span>
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
        <!-- Default: enacted grades -->
        {#if (metric as any).grade_symmetric !== undefined && (metric as any).grade_symmetric !== metric.grade}
          <!-- Dual grade: VRA floor + symmetric side by side -->
          <div style="display:flex;align-items:center;gap:.5rem;">
            <div style="display:flex;flex-direction:column;align-items:center;gap:.1rem;">
              <span style="font-size:.5rem;font-weight:700;letter-spacing:.04em;text-transform:uppercase;
                           color:{gradeColor[displayedGrade] ?? '#888'};">VRA Floor</span>
              <span style="display:inline-flex;align-items:center;justify-content:center;
                           width:1.7rem;height:1.7rem;border-radius:50%;
                           background:{gradeColor[displayedGrade] ?? '#888'};
                           color:#fff;font-weight:800;font-size:.85rem;flex-shrink:0;">{displayedGrade}</span>
            </div>
            <div style="display:flex;flex-direction:column;align-items:center;gap:.1rem;opacity:.55;">
              <span style="font-size:.5rem;font-weight:700;letter-spacing:.04em;text-transform:uppercase;
                           color:var(--gray);">Symmetric</span>
              <span style="display:inline-flex;align-items:center;justify-content:center;
                           width:1.7rem;height:1.7rem;border-radius:50%;
                           background:{gradeColor[(metric as any).grade_symmetric] ?? '#888'};
                           color:#fff;font-weight:800;font-size:.85rem;flex-shrink:0;">{(metric as any).grade_symmetric}</span>
            </div>
          </div>
          <span style="font-size:.7rem;color:var(--gray);">{Math.round(displayedPctRank)}th percentile
            {#if filterPct > 0}<span style="font-size:.6rem;color:var(--blue);font-style:italic;"> filtered</span>{/if}
          </span>
        {:else}
          <!-- Single grade (no grade_symmetric, or both grades match) -->
          <div style="display:flex;align-items:center;gap:.4rem;">
            <span style="display:inline-flex;align-items:center;justify-content:center;
                         width:1.7rem;height:1.7rem;border-radius:50%;
                         background:{gradeColor[displayedGrade] ?? '#888'};
                         color:#fff;font-weight:800;font-size:.85rem;flex-shrink:0;">{displayedGrade}</span>
            <span style="font-size:.7rem;color:var(--gray);">{Math.round(displayedPctRank)}th percentile</span>
            {#if filterPct > 0}
              <span style="font-size:.6rem;color:var(--blue);font-style:italic;" title="Grade recomputed against the top {100-filterPct}% of ensemble plans">filtered</span>
            {/if}
          </div>
        {/if}
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
        {#if !planMetric && (metric as any).grade_symmetric !== undefined}
          <div style="font-size:.62rem;color:var(--gray);margin-top:.4rem;padding:.3rem .5rem;
                      background:#f8f4ff;border-radius:4px;border-left:2.5px solid #8e44ad;line-height:1.45;">
            <b style="color:#8e44ad;">VRA Floor Grade</b>: Minority representation uses a one-sided test —
            having more minority-opportunity districts than neutral maps is never penalized.
            Grade F = below the race-neutral VRA floor (10th pct). Symmetric grade shown for reference.
          </div>
        {/if}
      {/if}
    </div>

    <!-- Middle: histogram -->
    <div style="padding:.6rem .8rem;border-right:1px solid var(--border);display:flex;flex-direction:column;justify-content:center;">
      <div style="height:90px;position:relative;">
        <canvas bind:this={canvas}></canvas>
      </div>
      <div style="font-size:.58rem;color:var(--gray);margin-top:.25rem;text-align:center;">
        {#if planMetric}
          <span style="color:#e67e22;font-weight:700;">—</span> this plan &nbsp;
          <span style="color:#111;">‒‒</span> enacted &nbsp;|&nbsp; {(filterPct > 0 ? (filteredHistCounts?.reduce((a:number,b:number)=>a+b,0) ?? 0) : metric.histogram.counts.reduce((a,b)=>a+b,0)).toLocaleString()} {filterPct > 0 ? 'filtered' : 'neutral'} maps
        {:else}
          ‒‒ enacted &nbsp;|&nbsp; {(filterPct > 0 ? (filteredHistCounts?.reduce((a:number,b:number)=>a+b,0) ?? 0) : metric.histogram.counts.reduce((a,b)=>a+b,0)).toLocaleString()} {filterPct > 0 ? 'filtered' : 'neutral'} maps
        {/if}
        {#if metric.a_grade_range}
          &nbsp;|&nbsp; <span style="color:#27ae60;">█</span> A zone
          <span
            title="The green band marks the A-grade threshold — what excellent looks like. For this metric, earning an A means the enacted map performs better than roughly 95% of randomly drawn fair maps. The black dashed line shows where the enacted map falls relative to that standard."
            style="cursor:help;color:#27ae60;font-size:.68rem;vertical-align:super;margin-left:1px;line-height:1;">ⓘ</span>
        {/if}
      </div>
    </div>

    <!-- Right: what this metric measures -->
    <div style="padding:.7rem 1rem;display:flex;flex-direction:column;justify-content:center;">
      <div style="font-size:.72rem;font-weight:600;color:var(--gray);text-transform:uppercase;
                  letter-spacing:.04em;margin-bottom:.3rem;">What this measures</div>
      <div style="font-size:.73rem;color:#444;line-height:1.6;">{metric.description}</div>
    </div>
  </div>

  <!-- Takeaway -->
  {#if metric.takeaway}
    <div style="border-top:1px solid var(--border);padding:.5rem 1rem;
         background:{metric.grade === 'F' ? '#fff0f0' : metric.grade === 'A' ? '#f0faf4' : '#f8f9fb'};
         display:flex;align-items:baseline;gap:.5rem;">
      <span style="font-size:.65rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;
                   color:{gradeColor[metric.grade] ?? '#888'};white-space:nowrap;flex-shrink:0;">Finding →</span>
      <span style="font-size:.74rem;color:#333;line-height:1.5;font-weight:500;">{metric.takeaway}</span>
    </div>
  {/if}
</div>

<style>
  .metric-card {
    background: var(--card);
    border-radius: 8px;
    border: 1.5px solid var(--border);
    box-shadow: var(--shadow);
    overflow: hidden;
  }
  .is-outlier {
    border-color: #e8a0a0;
  }
  @media (max-width: 860px) {
    div[style*="grid-template-columns:190px"] {
      grid-template-columns: 1fr !important;
    }
  }
</style>
