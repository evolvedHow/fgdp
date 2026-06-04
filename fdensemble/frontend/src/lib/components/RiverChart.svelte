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
    const labels = r.p50.map((_: number, i: number) => `D${i + 1}`);
    // Neutral slate — avoids any perceived partisan color bias in the ensemble band
    const neutral = '#475569';

    const datasets: any[] = [
      {
        label: '5th–95th %ile',
        data: r.p95,
        borderColor: 'transparent',
        backgroundColor: 'rgba(71,85,105,0.22)',
        fill: '+1',
        pointRadius: 0,
        tension: 0.3,
      },
      {
        label: '_lower',
        data: r.p5,
        borderColor: 'transparent',
        backgroundColor: 'rgba(71,85,105,0.22)',
        fill: false,
        pointRadius: 0,
        tension: 0.3,
      },
      {
        label: 'Neutral median',
        data: r.p50,
        borderColor: neutral,
        borderWidth: 2,
        backgroundColor: 'transparent',
        fill: false,
        pointRadius: 0,
        tension: 0.3,
      },
    ];

    // Enacted overlay: pre-sorted from scorecard or fallback from ALARM CSV
    const enactedData: number[] | null = r.enacted
      ? r.enacted
      : enactedShares
        ? [...enactedShares].sort((a, b) => a - b)
        : null;

    // Thin ghost line connecting enacted districts (visual guide)
    if (enactedData) {
      datasets.push({
        label: 'Enacted',
        data: enactedData,
        borderColor: 'rgba(51,65,85,0.30)',
        borderWidth: 1,
        backgroundColor: 'transparent',
        fill: false,
        pointRadius: 0,
        tension: 0.3,
      });
    }

    chart = new Chart(canvas, {
      type: 'line',
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        layout: { padding: { bottom: 30 } },  // room for party anchor labels
        plugins: {
          legend: {
            position: 'top',
            align: 'center',
            labels: {
              filter: (item: any) => !item.text.startsWith('_'),
              font: { size: 10 },
              boxWidth: 14,
              padding: 10,
            },
          },
          tooltip: {
            mode: 'index',
            intersect: false,
            callbacks: {
              label: (ctx: any) => {
                if (ctx.dataset.label === 'Enacted' && enactedData) {
                  const v = enactedData[ctx.dataIndex];
                  const pct = (v * 100).toFixed(1);
                  return v >= 0.5
                    ? `Enacted: ${pct}% Dem (+${((v - 0.5) * 200).toFixed(1)}pp)`
                    : `Enacted: ${pct}% Dem (${((v - 0.5) * 200).toFixed(1)}pp)`;
                }
                return `${ctx.dataset.label}: ${(ctx.raw * 100).toFixed(1)}%`;
              },
            },
          },
        },
        scales: {
          x: {
            ticks: {
              font: { size: 9 },
              maxTicksLimit: 8,
              callback: (_: any, i: number) => `D${i + 1}`,
            },
          },
          y: {
            min: 0, max: 1,
            ticks: {
              font: { size: 10 },
              callback: (v: any) => `${(v * 100).toFixed(0)}%`,
            },
            title: { display: true, text: 'Two-party vote share', font: { size: 11 } },
          },
        },
      },
      plugins: [
        // 50% reference line
        {
          id: '50pct-line',
          afterDraw(ch: any) {
            const { ctx, chartArea: { left, right }, scales: { y } } = ch;
            const yPx = y.getPixelForValue(0.5);
            ctx.save();
            ctx.strokeStyle = '#aaa';
            ctx.lineWidth   = 1;
            ctx.setLineDash([4, 4]);
            ctx.beginPath();
            ctx.moveTo(left, yPx);
            ctx.lineTo(right, yPx);
            ctx.stroke();
            // "50%" label at the line
            ctx.setLineDash([]);
            ctx.fillStyle = '#999';
            ctx.font = '9px sans-serif';
            ctx.textAlign = 'right';
            ctx.fillText('50%', left - 2, yPx + 3);
            ctx.restore();
          },
        },
        // Party anchor labels drawn inside the layout padding below x-axis ticks
        {
          id: 'party-anchors',
          afterDraw(ch: any) {
            const { ctx, canvas: cvs, chartArea: { left, right, bottom } } = ch;
            // Draw in the padding zone below the chart area (guaranteed space via layout.padding.bottom)
            const yPos = cvs.height - 10;
            ctx.save();
            ctx.font = 'bold 10px sans-serif';
            // Left: Republican
            ctx.textAlign = 'left';
            ctx.fillStyle = '#c0392b';
            ctx.fillText('R ←', left, yPos);
            ctx.font = '9px sans-serif';
            ctx.fillStyle = '#888';
            ctx.fillText(' More Republican', left + 18, yPos);
            // Right: Democratic
            ctx.font = 'bold 10px sans-serif';
            ctx.textAlign = 'right';
            ctx.fillStyle = '#2471a3';
            ctx.fillText('→ D', right, yPos);
            ctx.font = '9px sans-serif';
            ctx.fillStyle = '#888';
            ctx.textAlign = 'right';
            ctx.fillText('More Democratic ', right - 20, yPos);
            ctx.restore();
          },
        },
        // Enacted district bubbles — sized by margin, colored by winning party
        {
          id: 'enacted-bubbles',
          afterDatasetsDraw(ch: any) {
            if (!enactedData) return;
            const { ctx, scales: { x, y } } = ch;
            ctx.save();
            enactedData.forEach((v: number, i: number) => {
              const px = x.getPixelForValue(i);
              const py = y.getPixelForValue(v);
              const margin = Math.abs(v - 0.5);          // 0 = toss-up, 0.5 = landslide
              const r = 3.5 + margin * 26;               // 3.5px min, ~16.5px at +50pp margin
              ctx.beginPath();
              ctx.arc(px, py, r, 0, Math.PI * 2);
              ctx.fillStyle = 'rgba(71,85,105,0.50)';
              ctx.fill();
              ctx.strokeStyle = '#334155';
              ctx.lineWidth = 1.5;
              ctx.stroke();
            });
            ctx.restore();
          },
        },
      ],
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
  <div style="font-size:.74rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--gray);margin-bottom:.4rem;">
    District Partisan Lean — Enacted vs. Neutral Ensemble
  </div>
  <div style="font-size:.7rem;color:var(--gray);margin-bottom:.6rem;">
    Districts ranked left→right by partisan lean (most Republican → most Democratic).
    Enacted plan shown as neutral bubbles; bubble size = margin of victory.
    Grey band = neutral ensemble range.
  </div>
  <div style="height:310px;position:relative;">
    <canvas bind:this={canvas}></canvas>
  </div>
  <div style="font-size:.65rem;color:var(--gray);margin-top:.3rem;">
    Shaded band = 5th–95th percentile of {river.n_sample.toLocaleString()} neutral-drawn plans.
    Median = grey line. Dashed = 50% threshold.
  </div>
</div>
