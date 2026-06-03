<script lang="ts">
  // onMount/onDestroy not needed — using $effect with cleanup instead
  import type { MetricGrade } from '../types.js';

  interface Props { metric: MetricGrade; }
  let { metric }: Props = $props();

  let canvas: HTMLCanvasElement | undefined = $state();
  let chart: any;

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

    const h = metric.histogram;
    const labels = h.edges.slice(0, -1).map((e, i) => ((e + h.edges[i + 1]) / 2).toFixed(2));
    const col    = barColor();

    chart = new Chart(canvas, {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          data:            h.counts,
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

  // In Svelte 5 runes mode, canvas must be $state() for $effect to track it.
  // onMount/onDestroy replaced by $effect with cleanup return.
  $effect(() => {
    if (!canvas) return;
    buildChart();
    return () => { if (chart) { chart.destroy(); chart = null; } };
  });
</script>

<div style="background:var(--card);border-radius:8px;border:1.5px solid var(--border);
            box-shadow:var(--shadow);display:grid;
            grid-template-columns:200px 200px 1fr;min-width:0;overflow:hidden;"
     class:is-outlier={metric.grade === 'F'}>

  <!-- Left: label + numbers -->
  <div style="padding:.75rem .9rem;border-right:1px solid var(--border);display:flex;flex-direction:column;gap:.35rem;">
    <div style="font-weight:700;font-size:.78rem;color:var(--blue);line-height:1.2;">{metric.label}</div>
    <div style="display:flex;align-items:center;gap:.4rem;margin-top:.1rem;">
      <span style="display:inline-flex;align-items:center;justify-content:center;
                   width:1.55rem;height:1.55rem;border-radius:50%;
                   background:{gradeColor[metric.grade] ?? '#888'};
                   color:#fff;font-weight:800;font-size:.8rem;flex-shrink:0;">{metric.grade}</span>
      <span style="font-size:.68rem;color:var(--gray);">{metric.pct_rank}th %ile</span>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:.15rem .4rem;margin-top:.1rem;">
      <div>
        <div style="font-size:.6rem;color:var(--gray);">Enacted</div>
        <div style="font-weight:700;font-size:.82rem;">{metric.enacted.toFixed(2)}</div>
      </div>
      <div>
        <div style="font-size:.6rem;color:var(--gray);">Median</div>
        <div style="font-size:.82rem;">{metric.histogram.p50.toFixed(2)}</div>
      </div>
      <div style="grid-column:span 2;">
        <div style="font-size:.6rem;color:var(--gray);">5th–95th %ile range</div>
        <div style="font-size:.76rem;font-weight:600;">{metric.histogram.p5.toFixed(2)} – {metric.histogram.p95.toFixed(2)}</div>
      </div>
    </div>
  </div>

  <!-- Middle: histogram -->
  <div style="padding:.6rem .8rem;border-right:1px solid var(--border);display:flex;flex-direction:column;justify-content:center;">
    <div style="height:90px;position:relative;">
      <canvas bind:this={canvas}></canvas>
    </div>
    <div style="font-size:.6rem;color:var(--gray);margin-top:.2rem;text-align:center;">
      — enacted &nbsp;|&nbsp; distribution of {(metric.histogram.counts.reduce((a,b)=>a+b,0)).toLocaleString()} plans
    </div>
  </div>

  <!-- Right: description -->
  <div style="padding:.75rem 1rem;display:flex;flex-direction:column;justify-content:center;gap:.3rem;">
    <div style="font-size:.75rem;color:#444;line-height:1.55;">{metric.description}</div>
  </div>
</div>

<style>
  .is-outlier { border-color: #f5a9a9; }
  .is-outlier :global([style*="color:var(--blue)"]) { color: var(--red) !important; }

  @media (max-width: 860px) {
    div[style*="grid-template-columns:200px"] {
      grid-template-columns: 1fr !important;
    }
  }
</style>
