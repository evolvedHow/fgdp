<script lang="ts">
  import { tick } from 'svelte';
  import type { ScatterPair } from '../types.js';

  interface Props {
    pair: ScatterPair;
    xlabel: string;
    ylabel: string;
    color?: string;
    title?: string;
  }
  let { pair, xlabel, ylabel, color = '#3D77BB', title = '' }: Props = $props();

  let canvas: HTMLCanvasElement;
  let chart: any;

  // Linear regression helpers
  function linreg(xs: number[], ys: number[]): { m: number; b: number } {
    const n = xs.length;
    let sx = 0, sy = 0, sxy = 0, sx2 = 0;
    for (let i = 0; i < n; i++) { sx += xs[i]; sy += ys[i]; sxy += xs[i] * ys[i]; sx2 += xs[i] * xs[i]; }
    const denom = n * sx2 - sx * sx;
    if (Math.abs(denom) < 1e-10) return { m: 0, b: sy / n };
    const m = (n * sxy - sx * sy) / denom;
    const b = (sy - m * sx) / n;
    return { m, b };
  }

  async function buildChart() {
    const { Chart, ScatterController, PointElement, LinearScale, Tooltip, Legend }
      = await import('chart.js');
    Chart.register(ScatterController, PointElement, LinearScale, Tooltip, Legend);

    if (chart) { chart.destroy(); chart = null; }

    const snap = $state.snapshot(pair);
    const xs = Array.from(snap.x);
    const ys = Array.from(snap.y);
    const { m, b } = linreg(xs, ys);

    const datasets: any[] = [
      {
        label:           'Ensemble plans',
        data:            xs.map((x, i) => ({ x, y: ys[i] })),
        backgroundColor: color + '55',
        borderColor:     color + '99',
        borderWidth:     0.5,
        pointRadius:     2.5,
        pointHoverRadius: 4,
      },
    ];

    if (snap.enacted_x != null && snap.enacted_y != null) {
      datasets.push({
        label:           'Enacted',
        data:            [{ x: snap.enacted_x, y: snap.enacted_y }],
        backgroundColor: '#e74c3c',
        borderColor:     '#fff',
        borderWidth:     2,
        pointRadius:     9,
        pointStyle:      'star',
        pointHoverRadius: 11,
      });
    }

    const r    = snap.r ?? 0;
    const r2   = r * r;
    const rLabel = `r = ${r.toFixed(2)}  R² = ${r2.toFixed(2)}`;

    chart = new Chart(canvas, {
      type: 'scatter',
      data: { datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: {
            display: snap.enacted_x != null,
            position: 'top',
            labels: { font: { size: 10 }, boxWidth: 10, padding: 8 },
          },
          tooltip: {
            callbacks: {
              label: (item: any) => {
                const d = item.raw as { x: number; y: number };
                return `${xlabel}: ${d.x.toFixed(2)}, ${ylabel}: ${d.y.toFixed(4)}`;
              },
            },
          },
        },
        scales: {
          x: {
            title: { display: true, text: xlabel, font: { size: 10 }, color: '#555' },
            ticks: { font: { size: 9 } },
          },
          y: {
            title: { display: true, text: ylabel, font: { size: 10 }, color: '#555' },
            ticks: { font: { size: 9 } },
          },
        },
      },
      plugins: [{
        id: 'regression-line',
        beforeDatasetsDraw(ch: any) {
          if (xs.length < 3) return;
          const xScale = ch.scales.x;
          const yScale = ch.scales.y;
          const xMin = xScale.min;
          const xMax = xScale.max;
          const { ctx } = ch;
          ctx.save();
          ctx.strokeStyle = '#e67e22';
          ctx.lineWidth   = 1.8;
          ctx.setLineDash([5, 4]);
          ctx.beginPath();
          ctx.moveTo(xScale.getPixelForValue(xMin), yScale.getPixelForValue(m * xMin + b));
          ctx.lineTo(xScale.getPixelForValue(xMax), yScale.getPixelForValue(m * xMax + b));
          ctx.stroke();
          ctx.restore();
        },
        afterDraw(ch: any) {
          const { ctx, chartArea: { right, top } } = ch;
          ctx.save();
          ctx.font      = '10px system-ui, sans-serif';
          ctx.fillStyle = '#555';
          ctx.textAlign = 'right';
          ctx.fillText(rLabel, right - 4, top + 14);
          ctx.restore();
        },
      }],
    });
  }

  $effect(() => {
    const p = pair;
    tick().then(() => { if (canvas && p) buildChart(); });
    return () => { if (chart) { chart.destroy(); chart = null; } };
  });
</script>

<div style="background:var(--card);border:1.5px solid var(--border);border-radius:8px;
            padding:.6rem .8rem;display:flex;flex-direction:column;gap:.3rem;">
  {#if title}
    <div style="font-size:.66rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--gray);">
      {title}
    </div>
  {/if}
  <div style="height:200px;position:relative;">
    <canvas bind:this={canvas}></canvas>
  </div>
  {#if pair.r != null}
    <div style="font-size:.62rem;color:var(--gray);text-align:center;">
      {Math.abs(pair.r) >= 0.5 ? '⚠' : ''}
      {Math.abs(pair.r) >= 0.7 ? 'Strong' : Math.abs(pair.r) >= 0.4 ? 'Moderate' : 'Weak'}
      {pair.r > 0 ? 'positive' : 'negative'} correlation
      — <span style="color:#e67e22;">— —</span> regression line
    </div>
  {/if}
</div>
