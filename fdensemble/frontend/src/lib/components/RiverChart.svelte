<script lang="ts">
  import { tick } from 'svelte';
  import type { RiverData } from '../types.js';

  interface Props {
    river: RiverData;
    enactedShares: number[] | null;
  }
  let { river, enactedShares }: Props = $props();

  // Plain let — NOT $state(). Chart.js uses Object.defineProperty on canvas.
  let canvas: HTMLCanvasElement;
  let chart: any;

  async function buildChart() {
    const { Chart, LineController, LineElement, PointElement, Filler,
            CategoryScale, LinearScale, Tooltip, Legend } = await import('chart.js');
    Chart.register(LineController, LineElement, PointElement, Filler,
                   CategoryScale, LinearScale, Tooltip, Legend);

    if (chart) { chart.destroy(); chart = null; }

    // $state.snapshot() converts reactive prop → plain JS so Chart.js can
    // safely call Object.defineProperty on data arrays internally.
    const r = $state.snapshot(river);
    const labels = r.p50.map((_: number, i: number) => `District ${i + 1}`);
    const dem = '#3D77BB';

    const datasets: any[] = [
      {
        label: '5th–95th %ile',
        data: r.p95,
        borderColor: 'transparent',
        backgroundColor: dem + '25',
        fill: '+1',
        pointRadius: 0,
        tension: 0.3,
      },
      {
        label: '_lower',
        data: r.p5,
        borderColor: 'transparent',
        backgroundColor: dem + '25',
        fill: false,
        pointRadius: 0,
        tension: 0.3,
      },
      {
        label: 'Median',
        data: r.p50,
        borderColor: dem,
        borderWidth: 2,
        backgroundColor: 'transparent',
        fill: false,
        pointRadius: 0,
        tension: 0.3,
      },
    ];

    // Enacted overlay: use pre-sorted data from scorecard (river.enacted),
    // or fall back to enactedShares prop (ALARM CSV path, sorted here)
    const enactedData = r.enacted
      ? r.enacted
      : enactedShares
        ? [...enactedShares].sort((a, b) => a - b)
        : null;

    if (enactedData) {
      datasets.push({
        label: 'Enacted',
        data: enactedData,
        borderColor: '#111',
        borderWidth: 2.5,
        backgroundColor: 'transparent',
        fill: false,
        pointRadius: 0,
        tension: 0.3,
        borderDash: [],
      });
    }

    chart = new Chart(canvas, {
      type: 'line',
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: {
            labels: {
              filter: (item: any) => !item.text.startsWith('_'),
              font: { size: 11 },
            },
          },
          tooltip: { mode: 'index', intersect: false },
        },
        scales: {
          x: { ticks: { font: { size: 10 } } },
          y: {
            min: 0, max: 1,
            ticks: {
              font: { size: 10 },
              callback: (v: any) => `${(v * 100).toFixed(0)}%`,
            },
            title: { display: true, text: 'Dem two-party share', font: { size: 11 } },
          },
        },
      },
      plugins: [{
        id: '50pct-line',
        afterDraw(ch: any) {
          const { ctx, chartArea: { left, right }, scales: { y } } = ch;
          const yPx = y.getPixelForValue(0.5);
          ctx.save();
          ctx.strokeStyle = '#bbb';
          ctx.lineWidth   = 1;
          ctx.setLineDash([4, 4]);
          ctx.beginPath();
          ctx.moveTo(left, yPx);
          ctx.lineTo(right, yPx);
          ctx.stroke();
          ctx.restore();
        },
      }],
    });
  }

  $effect(() => {
    const r = river; // track river so chart rebuilds when election switches
    tick().then(() => {
      if (canvas && r) buildChart();
    });
    return () => { if (chart) { chart.destroy(); chart = null; } };
  });
</script>

<div style="background:var(--card);border-radius:10px;padding:1rem 1.2rem;box-shadow:var(--shadow);border:1.5px solid var(--border);">
  <div style="font-size:.74rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--gray);margin-bottom:.7rem;">
    Partisan Lean by District Rank
  </div>
  <div style="height:280px;position:relative;">
    <canvas bind:this={canvas}></canvas>
  </div>
  <div style="font-size:.68rem;color:var(--gray);margin-top:.4rem;">
    Districts sorted by partisan lean (least to most Democratic).
    Shaded band = 5th–95th percentile of {river.n_sample.toLocaleString()} plans.
    Dashed reference line at 50%.
  </div>
</div>
