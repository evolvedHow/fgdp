<script lang="ts">
  /**
   * DemoMetricCard — frequency histogram for Black / White / Minority Coalition
   * majority-district counts across the 99K ensemble.
   *
   * Each bar answers: "Out of 99,001 maps drawn at random, X districts
   * qualified Y times." The enacted map value is highlighted in grade colour.
   * Fixed at the VRA §2 50% majority threshold — no slider.
   */
  import type { MetricGrade } from '../types.js';

  interface Props {
    metric: MetricGrade;
    nDistricts?: number;   // total districts (default 14)
  }
  let { metric, nDistricts = 14 }: Props = $props();

  // ── Fixed threshold: VRA 50% majority standard ───────────────────────────
  const THRESHOLD = '0.50';

  // ── Data from scorecard ──────────────────────────────────────────────────
  const drawValues = $derived.by((): number[] => {
    const dbt = (metric as any).draw_values_by_threshold as Record<string, number[]> | undefined;
    return dbt?.[THRESHOLD] ?? (metric as any).draw_values ?? [];
  });

  const enactedVal = $derived.by((): number => {
    const ebt = (metric as any).enacted_by_threshold as Record<string, number> | undefined;
    if (ebt?.[THRESHOLD] !== undefined) return ebt[THRESHOLD];
    return Math.round(metric.enacted);
  });

  // ── Integer frequency map (0 … nDistricts) ───────────────────────────────
  const countMap = $derived.by((): number[] => {
    const arr = new Array(nDistricts + 1).fill(0);
    for (const v of drawValues) if (v >= 0 && v <= nDistricts) arr[v]++;
    return arr;
  });
  const total    = $derived(drawValues.length);
  const maxCount = $derived(Math.max(...countMap, 1));

  // ── Percentile stats ──────────────────────────────────────────────────────
  const stats = $derived.by(() => {
    if (!drawValues.length) return { p25: 0, p50: 0, p75: 0 };
    const sorted = [...drawValues].sort((a, b) => a - b);
    const n = sorted.length;
    const at = (p: number) => sorted[Math.min(Math.floor(p / 100 * n), n - 1)];
    return { p25: at(25), p50: at(50), p75: at(75) };
  });

  // ── Grade from percentile rank ────────────────────────────────────────────
  const pctRank = $derived.by((): number => {
    if (!drawValues.length) return metric.pct_rank;
    return (drawValues.filter(v => v <= enactedVal).length / drawValues.length) * 100;
  });

  const grade = $derived.by((): string => {
    const gradeFn = (metric as any).grade_fn as string || 'simple';
    const hib     = (metric as any).higher_is_better as boolean | null;
    const pct     = pctRank;
    if (gradeFn === 'seats') return pct >= 50 ? 'A' : pct >= 20 ? 'B' : pct >= 5 ? 'C' : 'F';
    if (gradeFn === 'comp')  return pct >= 95 ? 'A' : pct >= 64 ? 'B' : pct >= 5 ? 'C' : 'F';
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
  const catColor = $derived(categoryColor[(metric as any).category as string] ?? '#8e44ad');
  const gcol     = $derived(gradeColor[grade] ?? '#888');

  // ── SVG bar chart geometry ────────────────────────────────────────────────
  // Adapts to nDistricts: congress(14)=15 slots, senate(56)=57 slots, etc.
  const PAD_L   = 12;
  const PAD_R   = 12;
  const SVG_W   = 260;
  const SVG_H   = 108;
  const TW      = SVG_W - PAD_L - PAD_R;   // 236px usable
  const CHART_B = 76;    // y of baseline
  const CHART_T = 14;    // y of chart top
  const CHART_H = CHART_B - CHART_T;        // 62px bar area
  const N_SLOTS = $derived(nDistricts + 1); // integers 0–nDistricts
  const SLOT_W  = $derived(TW / N_SLOTS);
  const BAR_W   = $derived(Math.max(SLOT_W - 1, 1.5)); // min 1.5px for large chambers

  // X-axis label step: show fewer labels when districts are many
  const LABEL_STEP = $derived(
    nDistricts <= 15  ? 2  :
    nDistricts <= 30  ? 5  :
    nDistricts <= 60  ? 10 :
    nDistricts <= 120 ? 20 : 30
  );

  // Peak bar index: the largest bar that is NOT the enacted value
  const peakIdx = $derived.by((): number => {
    let best = -1, bestN = 0;
    for (let i = 0; i <= nDistricts; i++) {
      if (i !== enactedVal && countMap[i] > bestN) { bestN = countMap[i]; best = i; }
    }
    return best;
  });

  // Pre-computed label positions (avoids {@const} outside block boundaries in SVG)
  const enactedBarH = $derived((countMap[enactedVal] ?? 0) / maxCount * CHART_H);
  const enactedBarX = $derived(PAD_L + enactedVal * SLOT_W + BAR_W / 2);
</script>

<div style="background:var(--card);border-radius:8px;overflow:hidden;
            border:1.5px solid var(--border);
            box-shadow:var(--shadow);">

  <!-- ── Header: metric name + grade ──────────────────────────────────────── -->
  <div style="padding:.5rem .8rem;
       background:var(--light);
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
        <div style="font-size:.85rem;font-weight:800;color:var(--blue);">{Math.round(pctRank)}<sup style="font-size:.5rem;font-weight:700;">th</sup></div>
        <div style="font-size:.58rem;color:var(--gray);">percentile</div>
        <div style="font-size:.58rem;color:#8e44ad;">≥{Math.round(+THRESHOLD * 100)}% threshold</div>
      </div>
    </div>
  </div>

  <!-- ── Integer frequency histogram ─────────────────────────────────────── -->
  <div style="padding:.55rem .8rem .4rem;">
    {#if total > 0}
      <svg viewBox="0 0 {SVG_W} {SVG_H}" width="100%"
           style="display:block;overflow:visible;" aria-hidden="true">

        <!-- ── Baseline ── -->
        <line x1={PAD_L} y1={CHART_B} x2={SVG_W - PAD_R} y2={CHART_B}
          stroke="#e0e0e0" stroke-width="1"/>

        <!-- ── All bars ── -->
        {#each Array.from({length: nDistricts + 1}, (_, i) => i) as i}
          {@const bh = (countMap[i] / maxCount) * CHART_H}
          {@const bx = PAD_L + i * SLOT_W}
          {#if countMap[i] > 0}
            <rect
              x={bx} y={CHART_B - bh}
              width={BAR_W} height={bh}
              fill={i === enactedVal ? catColor : catColor + '66'}
              rx="1"
            />
          {/if}
        {/each}

        <!-- ── Enacted position marker (always visible, even if no ensemble bar) ── -->
        <rect x={PAD_L + enactedVal * SLOT_W} y={CHART_B - Math.max(enactedBarH, 5)}
          width={BAR_W} height={Math.max(enactedBarH, 5)}
          fill={catColor} rx="1"/>

        <!-- ── Enacted bar label ── -->
        <text x={enactedBarX} y={CHART_B - Math.max(enactedBarH, 5) - 4}
          text-anchor="middle" font-size="10" font-weight="bold"
          fill={catColor}>{enactedVal}</text>

        <!-- peak bar label removed — bar height conveys frequency visually -->

        <!-- ── X-axis integer labels (step adapts to district count) ── -->
        {#each Array.from({length: nDistricts + 1}, (_, i) => i) as i}
          {#if i % LABEL_STEP === 0}
            <text x={PAD_L + i * SLOT_W + BAR_W / 2} y={CHART_B + 13}
              text-anchor="middle" font-size="8" fill="#bbb">{i}</text>
          {/if}
        {/each}

        <!-- ── X-axis title ── -->
        <text x={SVG_W / 2} y={SVG_H - 1}
          text-anchor="middle" font-size="7.5" fill="#aaa">
          districts with ≥{Math.round(+THRESHOLD * 100)}% majority
        </text>

      </svg>

      <!-- Legend row -->
      <div style="display:flex;gap:.45rem;font-size:.57rem;color:var(--gray);
                  flex-wrap:wrap;margin-top:.05rem;align-items:center;">
        <span>enacted: <b style="color:{gcol};">{enactedVal}</b></span>
        <span style="color:#ccc;">·</span>
        <span>typical: {stats.p25}–{stats.p75}</span>
        <span style="color:#ccc;">·</span>
        <span>{total.toLocaleString()} maps</span>
      </div>
    {:else}
      <div style="font-size:.7rem;color:var(--gray);padding:.5rem 0;">
        No distribution data available.
      </div>
    {/if}
  </div>

  <!-- ── Takeaway ──────────────────────────────────────────────────────── -->
  {#if metric.takeaway}
    <div style="border-top:1px solid var(--border);padding:.4rem .8rem;
         background:#f8f9fb;
         font-size:.67rem;color:#333;line-height:1.45;">
      <span style="font-size:.59rem;font-weight:700;text-transform:uppercase;
                   letter-spacing:.04em;color:var(--gray);margin-right:.3rem;">Finding →</span>{metric.takeaway}
    </div>
  {/if}
</div>
