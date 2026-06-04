<script lang="ts">
  import { tick } from 'svelte';
  import type { MetricGrade } from '../types.js';
  import { captureElement } from '../capture.js';

  interface Props { metric: MetricGrade; }
  let { metric }: Props = $props();

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

  async function buildChart() {
    const { Chart, BarController, BarElement, CategoryScale, LinearScale, Tooltip } = await import('chart.js');
    Chart.register(BarController, BarElement, CategoryScale, LinearScale, Tooltip);

    if (chart) { chart.destroy(); chart = null; }

    // $state.snapshot() converts reactive proxy → plain JS object so Chart.js
    // can safely call Object.defineProperty on the data arrays internally.
    const snap  = $state.snapshot(metric);
    const h     = snap.histogram;
    const edges = Array.from(h.edges);
    const labels = edges.slice(0, -1).map((e: number, i: number) => ((e + edges[i + 1]) / 2).toFixed(2));
    const col    = categoryColor[snap.category] ?? '#888';

    chart = new Chart(canvas, {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          data:            Array.from(h.counts),
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
        id: 'enacted-line',
        afterDraw(ch: any) {
          if (h.enacted == null) return;
          const xScale = ch.scales.x;
          const { ctx, chartArea: { top, bottom } } = ch;
          // find bin index for enacted value
          const idx = h.edges.findIndex((e, i) => h.enacted! >= e && h.enacted! < h.edges[i + 1]);
          if (idx < 0) return;
          const x = xScale.getPixelForValue(idx);
          ctx.save();
          ctx.strokeStyle = '#111';
          ctx.lineWidth   = 2;
          ctx.setLineDash([4, 3]);
          ctx.beginPath();
          ctx.moveTo(x, top);
          ctx.lineTo(x, bottom);
          ctx.stroke();
          ctx.restore();
        },
      }],
    });
  }

  // Track metric changes so chart rebuilds when election switches.
  // tick() ensures the canvas DOM element is mounted before Chart.js runs.
  $effect(() => {
    const m = metric; // declare dependency so effect re-runs on metric change
    tick().then(() => {
      if (canvas && m) buildChart();
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
      <div style="display:flex;align-items:center;gap:.4rem;">
        <span style="display:inline-flex;align-items:center;justify-content:center;
                     width:1.7rem;height:1.7rem;border-radius:50%;
                     background:{gradeColor[metric.grade] ?? '#888'};
                     color:#fff;font-weight:800;font-size:.85rem;flex-shrink:0;">{metric.grade}</span>
        <span style="font-size:.7rem;color:var(--gray);">{metric.pct_rank}th percentile</span>
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
      </div>
    </div>

    <!-- Middle: histogram -->
    <div style="padding:.6rem .8rem;border-right:1px solid var(--border);display:flex;flex-direction:column;justify-content:center;">
      <div style="height:90px;position:relative;">
        <canvas bind:this={canvas}></canvas>
      </div>
      <div style="font-size:.58rem;color:var(--gray);margin-top:.25rem;text-align:center;">
        ‒‒ enacted &nbsp;|&nbsp; distribution of {(metric.histogram.counts.reduce((a,b)=>a+b,0)).toLocaleString()} neutral maps
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
