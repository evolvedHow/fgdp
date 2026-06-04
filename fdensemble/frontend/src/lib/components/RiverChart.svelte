<script lang="ts">
  import { tick } from 'svelte';
  import type { RiverData } from '../types.js';
  import { captureElement } from '../capture.js';

  interface Props {
    river: RiverData;
    enactedShares: number[] | null;
  }
  let { river, enactedShares }: Props = $props();

  // Plain let — NOT $state(). Chart.js uses Object.defineProperty on canvas.
  let canvas: HTMLCanvasElement;
  let chart: any;
  let cardEl: HTMLElement;
  let capturing = $state(false);

  async function doCapture() {
    if (capturing || !cardEl) return;
    capturing = true;
    try { await captureElement(cardEl, 'river-chart'); }
    finally { capturing = false; }
  }

  async function buildChart() {
    const { Chart, LineController, LineElement, PointElement, Filler,
            CategoryScale, LinearScale, Tooltip, Legend } = await import('chart.js');
    Chart.register(LineController, LineElement, PointElement, Filler,
                   CategoryScale, LinearScale, Tooltip, Legend);

    if (chart) { chart.destroy(); chart = null; }

    // $state.snapshot() converts reactive prop → plain JS so Chart.js can
    // safely call Object.defineProperty on data arrays internally.
    const r = $state.snapshot(river);
    const distIds: number[] | null = r.enacted_district_ids ?? null;
    const labels = r.p50.map((_: number, i: number) => `#${i + 1}`);
    // Pure neutral grey — no blue tint
    const neutral = '#606060';

    const datasets: any[] = [
      {
        label: '5th–95th %ile',
        data: r.p95,
        borderColor: 'transparent',
        backgroundColor: 'rgba(110,110,110,0.20)',
        fill: '+1',
        pointRadius: 0,
        tension: 0.3,
      },
      {
        label: '_lower',
        data: r.p5,
        borderColor: 'transparent',
        backgroundColor: 'rgba(110,110,110,0.20)',
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
        layout: { padding: { bottom: 60 } },  // room for party anchor labels
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
              title: (items: any[]) => {
                const i = items[0]?.dataIndex ?? 0;
                const distId = distIds?.[i];
                const distLabel = distId != null ? `GA-${String(distId).padStart(2, '0')}` : null;
                const rankLabel = `Partisan rank #${i + 1} of ${r.n_districts}`;
                return distLabel ? `${distLabel}  ·  ${rankLabel}` : rankLabel;
              },
              label: (ctx: any) => {
                if (ctx.dataset.label?.startsWith('_')) return null;
                const v: number = ctx.raw;
                if (ctx.dataset.label === 'Enacted') {
                  const demPct    = Math.round(v * 100);
                  const repPct    = 100 - demPct;
                  const winner    = v >= 0.5 ? 'Dem' : 'Rep';
                  const winMargin = Math.round(Math.abs(v - 0.5) * 200);
                  return `Enacted:  Dem ${demPct}%  ·  Rep ${repPct}%  (${winner} +${winMargin}pp)`;
                }
                return `${ctx.dataset.label}: ${(v * 100).toFixed(1)}%`;
              },
            },
          },
        },
        scales: {
          x: {
            ticks: {
              font: { size: 9 },
              maxTicksLimit: 8,
              callback: (_: any, i: number) => {
                const distId = distIds?.[i];
                return distId != null ? `GA-${String(distId).padStart(2, '0')}` : `#${i + 1}`;
              },
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
            // cvs.height is physical pixels; ctx is pre-scaled by devicePixelRatio so coords are CSS px
            const dpr = window.devicePixelRatio || 1;
            const yPos = cvs.height / dpr - 10;
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
              const margin = Math.abs(v - 0.5);
              const isDem = v >= 0.5;
              // Only draw filled bubbles for safe seats (>12pp margin); skip close races
              if (margin < 0.12) return;
              const r = 4 + (margin - 0.12) * 22;        // starts at 4px at 12pp, ~15px at 50pp
              const fill   = isDem ? 'rgba(36,113,163,0.50)' : 'rgba(192,57,43,0.50)';
              const stroke = isDem ? '#1a5276' : '#922b21';
              ctx.beginPath();
              ctx.arc(px, py, r, 0, Math.PI * 2);
              ctx.fillStyle = fill;
              ctx.fill();
              ctx.strokeStyle = stroke;
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

<div style="background:var(--card);border-radius:10px;padding:1rem 1.2rem;box-shadow:var(--shadow);border:1.5px solid var(--border);" bind:this={cardEl}>
  <div style="display:flex;align-items:center;justify-content:space-between;gap:.5rem;margin-bottom:.4rem;">
    <div style="font-size:.74rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--gray);">
      District Partisan Lean — Enacted vs. Neutral Ensemble
    </div>
    <button class="capture-btn" onclick={doCapture} disabled={capturing} title="Save chart as PNG">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
        <polyline points="7,10 12,15 17,10"/>
        <line x1="12" y1="15" x2="12" y2="3"/>
      </svg>
      {capturing ? 'Saving…' : 'PNG'}
    </button>
  </div>
  <div style="font-size:.7rem;color:var(--gray);margin-bottom:.6rem;">
    Each position is a <b>partisan-lean rank</b>, not a geographic district number — the leftmost is always the most Republican district in a given plan, the rightmost always the most Democratic.
    X-axis labels show the actual enacted district (GA-XX). Hover for district and margin detail.
    Enacted plan bubbles:
    <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:rgba(36,113,163,0.55);vertical-align:middle;border:1.5px solid #1a5276;"></span> Democratic-won &nbsp;
    <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:rgba(192,57,43,0.55);vertical-align:middle;border:1.5px solid #922b21;"></span> Republican-won.
    Bubble size = margin of victory. Grey band = neutral ensemble range.
  </div>
  <div style="height:380px;position:relative;">
    <canvas bind:this={canvas}></canvas>
  </div>
  <div style="font-size:.65rem;color:var(--gray);margin-top:.3rem;">
    Shaded band = 5th–95th percentile of {river.n_sample.toLocaleString()} neutral-drawn plans.
    Median = grey line. Dashed = 50% threshold.
  </div>
</div>
