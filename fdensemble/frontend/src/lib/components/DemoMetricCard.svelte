<script lang="ts">
  /**
   * DemoMetricCard — compact card for Black / White / Minority Coalition
   * threshold metrics.  Shows a horizontal ruler visualisation (not a
   * histogram) and has its own independent 20%–50% threshold slider.
   *
   * The distribution is drawn as:
   *   • light band  = p5–p95 (outer ensemble range)
   *   • dark band   = p25–p75 (typical / IQR)
   *   • filled dot  = median
   *   • grade-coloured circle with dashed stem = enacted map value
   */
  import type { MetricGrade } from '../types.js';

  interface Props {
    metric: MetricGrade;
    nDistricts?: number;   // max possible district count (default 14)
  }
  let { metric, nDistricts = 14 }: Props = $props();

  // ── Independent threshold slider ─────────────────────────────────────────
  let thresholdPct = $state(50);
  const thresholdKey = $derived((thresholdPct / 100).toFixed(2)); // "0.50" … "0.20"

  // ── Data from scorecard ──────────────────────────────────────────────────
  const drawValues = $derived.by((): number[] => {
    const dbt = (metric as any).draw_values_by_threshold as Record<string, number[]> | undefined;
    return (dbt && dbt[thresholdKey]) ? dbt[thresholdKey] : [];
  });

  const enactedVal = $derived.by((): number => {
    const ebt = (metric as any).enacted_by_threshold as Record<string, number> | undefined;
    if (ebt && ebt[thresholdKey] !== undefined) return ebt[thresholdKey];
    return Math.round(metric.enacted);
  });

  // ── Stats from draw distribution ─────────────────────────────────────────
  const stats = $derived.by(() => {
    const dv = drawValues;
    if (!dv.length) return { p5: 0, p25: 0, p50: 0, p75: 0, p95: 0, total: 0 };
    const sorted = [...dv].sort((a, b) => a - b);
    const n = sorted.length;
    const at = (pct: number) => sorted[Math.min(Math.floor(pct / 100 * n), n - 1)];
    return { p5: at(5), p25: at(25), p50: at(50), p75: at(75), p95: at(95), total: n };
  });

  // ── Grade from percentile rank ────────────────────────────────────────────
  const pctRank = $derived.by((): number => {
    const dv = drawValues;
    if (!dv.length) return metric.pct_rank;
    const ev = enactedVal;
    return (dv.filter(v => v <= ev).length / dv.length) * 100;
  });

  const grade = $derived.by((): string => {
    const gradeFn = (metric as any).grade_fn as string || 'directional';
    const hib     = (metric as any).higher_is_better as boolean | null;
    const pct     = pctRank;
    if (gradeFn === 'seats') {
      return pct >= 50 ? 'A' : pct >= 20 ? 'B' : pct >= 5 ? 'C' : 'F';
    }
    if (gradeFn === 'comp') {
      return pct >= 95 ? 'A' : pct >= 64 ? 'B' : pct >= 5 ? 'C' : 'F';
    }
    if (gradeFn === 'simple' || hib === null || hib === undefined) {
      const d = Math.abs(pct - 50);
      return d <= 10 ? 'A' : d <= 30 ? 'B' : d <= 45 ? 'C' : 'F';
    }
    const rank = hib ? pct : 100 - pct;
    return rank >= 95 ? 'A' : rank >= 64 ? 'B' : rank >= 5 ? 'C' : 'F';
  });

  // ── Colour helpers ────────────────────────────────────────────────────────
  const gradeColor: Record<string, string> = {
    A: '#27ae60', B: '#2980b9', C: '#d68910', D: '#e67e22', F: '#c0392b',
  };
  const categoryColor: Record<string, string> = {
    partisan: '#3D77BB', competitive: '#17a589',
    geographic: '#7f8c8d', minority: '#8e44ad',
  };
  const catColor = $derived(categoryColor[(metric as any).category as string] ?? '#888');
  const gcol     = $derived(gradeColor[grade] ?? '#888');

  // ── SVG ruler geometry ────────────────────────────────────────────────────
  const SVG_W   = 260;
  const SVG_H   = 72;
  const PAD     = 18;          // left & right padding
  const TW      = SVG_W - PAD * 2;   // usable track width
  const TY      = 36;          // y-centre of ruler track

  function xPos(v: number): number {
    return PAD + Math.max(0, Math.min(1, v / nDistricts)) * TW;
  }
</script>

<div style="background:var(--card);border-radius:8px;overflow:hidden;
            border:1.5px solid {grade === 'F' ? '#e8a0a0' : 'var(--border)'};
            box-shadow:var(--shadow);">

  <!-- ── Header: metric name + live grade ─────────────────────────────── -->
  <div style="padding:.5rem .8rem;
       background:{grade === 'F' ? '#fff5f5' : grade === 'A' ? '#f5fdf8' : 'var(--light)'};
       border-bottom:1px solid var(--border);
       display:flex;align-items:center;justify-content:space-between;gap:.5rem;">
    <div style="min-width:0;">
      <div style="font-size:.63rem;font-weight:700;text-transform:uppercase;
                  letter-spacing:.05em;color:var(--gray);">{metric.label}</div>
      <div style="font-size:.76rem;font-weight:700;color:var(--blue);
                  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
        {metric.headline ?? metric.label}
      </div>
    </div>
    <div style="display:flex;align-items:center;gap:.35rem;flex-shrink:0;">
      <div style="text-align:right;line-height:1.3;">
        <div style="font-size:.62rem;color:var(--gray);">{Math.round(pctRank)}th pctile</div>
        <div style="font-size:.59rem;color:#8e44ad;font-weight:600;">≥{thresholdPct}% BVAP</div>
      </div>
      <span style="display:inline-flex;align-items:center;justify-content:center;
                   width:2.1rem;height:2.1rem;border-radius:50%;flex-shrink:0;
                   background:{gcol};color:#fff;font-weight:800;font-size:.95rem;">{grade}</span>
    </div>
  </div>

  <!-- ── Individual threshold slider ──────────────────────────────────── -->
  <div style="padding:.4rem .8rem .3rem;border-bottom:1px solid var(--border);background:#faf7ff;">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.15rem;">
      <span style="font-size:.58rem;color:var(--gray);">
        {thresholdPct === 50 ? 'True majority — VRA §2 standard' :
         thresholdPct === 20 ? 'Influence threshold' :
         'Between influence & majority'}
      </span>
      <span style="font-size:.67rem;font-weight:700;color:#8e44ad;">≥{thresholdPct}%</span>
    </div>
    <input type="range" min=20 max=50 step=5 bind:value={thresholdPct}
      style="width:100%;accent-color:#8e44ad;cursor:pointer;margin:.1rem 0 .05rem;" />
    <div style="display:flex;justify-content:space-between;font-size:.52rem;color:#bbb;
                padding:0 1px;">
      {#each [20,25,30,35,40,45,50] as t}
        <span>{t}%</span>
      {/each}
    </div>
  </div>

  <!-- ── Distribution ruler ────────────────────────────────────────────── -->
  <div style="padding:.55rem .8rem .45rem;">
    {#if drawValues.length > 0}
      {@const bx1 = xPos(stats.p5)}
      {@const bx2 = Math.max(xPos(stats.p95), bx1 + 4)}
      {@const ix1 = xPos(stats.p25)}
      {@const ix2 = Math.max(xPos(stats.p75), ix1 + 2)}
      {@const ex  = xPos(enactedVal)}
      {@const mx  = xPos(stats.p50)}

      <svg viewBox="0 0 {SVG_W} {SVG_H}" width="100%"
           style="display:block;overflow:visible;" aria-hidden="true">

        <!-- ── Base track ── -->
        <rect x={PAD} y={TY - 2} width={TW} height="4" rx="2" fill="#e4e4e4"/>

        <!-- ── P5–P95 outer band ── -->
        <rect x={bx1} y={TY - 10} width={bx2 - bx1} height="20" rx="5"
          fill="{catColor}28" stroke="{catColor}50" stroke-width="1"/>

        <!-- ── P25–P75 inner band ── -->
        <rect x={ix1} y={TY - 6} width={ix2 - ix1} height="12" rx="3"
          fill="{catColor}66"/>

        <!-- ── Median marker (filled dot) ── -->
        <circle cx={mx} cy={TY} r="5" fill={catColor}/>

        <!-- ── Enacted dashed stem ── -->
        <line x1={ex} y1={TY - 22} x2={ex} y2={TY + 18}
          stroke="#333" stroke-width="1.5" stroke-dasharray="3,2"/>

        <!-- ── Enacted circle (grade colour, on top of median if coincident) ── -->
        <circle cx={ex} cy={TY} r="7" fill={gcol} stroke="white" stroke-width="2"/>

        <!-- ── Tick marks at each integer ── -->
        {#each Array.from({length: nDistricts + 1}, (_, i) => i) as i}
          <line x1={xPos(i)} y1={TY + 12} x2={xPos(i)} y2={TY + 17}
            stroke="#ccc" stroke-width="1"/>
        {/each}

        <!-- ── Integer labels (even numbers only) ── -->
        {#each Array.from({length: nDistricts + 1}, (_, i) => i) as i}
          {#if i % 2 === 0}
            <text x={xPos(i)} y={SVG_H - 2} font-size="9" fill="#aaa"
              text-anchor="middle">{i}</text>
          {/if}
        {/each}

        <!-- ── Enacted value label (above stem) ── -->
        <text x={ex} y={TY - 26} font-size="10" font-weight="bold"
          fill="#222" text-anchor="middle">{enactedVal}</text>

      </svg>

      <!-- Legend row -->
      <div style="display:flex;gap:.5rem;font-size:.57rem;color:var(--gray);
                  flex-wrap:wrap;margin-top:.1rem;align-items:center;">
        <span>enacted: <b style="color:{gcol};">{enactedVal}</b></span>
        <span style="color:#ccc;">·</span>
        <span>median: <b>{stats.p50}</b></span>
        <span style="color:#ccc;">·</span>
        <span>typical: {stats.p25}–{stats.p75}</span>
        <span style="color:#ccc;">·</span>
        <span>{stats.total.toLocaleString()} maps</span>
      </div>
    {:else}
      <div style="font-size:.7rem;color:var(--gray);padding:.5rem 0;">
        No threshold data available for this metric.
      </div>
    {/if}
  </div>

  <!-- ── Takeaway ──────────────────────────────────────────────────────── -->
  {#if metric.takeaway}
    <div style="border-top:1px solid var(--border);padding:.4rem .8rem;
         background:{grade === 'F' ? '#fff0f0' : grade === 'A' ? '#f0faf4' : '#f8f9fb'};
         font-size:.67rem;color:#333;line-height:1.45;">
      <span style="font-size:.59rem;font-weight:700;text-transform:uppercase;
                   letter-spacing:.04em;color:{gcol};margin-right:.3rem;">Finding →</span>{metric.takeaway}
    </div>
  {/if}
</div>
