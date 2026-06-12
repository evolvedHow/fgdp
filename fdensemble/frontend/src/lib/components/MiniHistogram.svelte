<script lang="ts">
  interface Props {
    counts:     number[];   // bin counts (or draw_values if isDrawValues=true)
    edges:      number[];   // bin edges (length = counts.length + 1)
    enacted:    number | null;
    p25?:       number | null;
    p50?:       number | null;
    p75?:       number | null;
    aGradeRange?: { lo: number | null; hi: number | null } | null;
    xMin?:      number;   // external scale override (for shared axis)
    xMax?:      number;   // external scale override
    color?:     string;
  }

  const {
    counts, edges, enacted,
    p25 = null, p50 = null, p75 = null,
    aGradeRange = null,
    xMin: xMinProp, xMax: xMaxProp,
    color = '#3D77BB',
  }: Props = $props();

  const W  = 280;
  const H  = 76;
  const PL = 4;   // pad left
  const PR = 4;   // pad right
  const PT = 4;   // pad top
  const PB = 16;  // pad bottom (for axis labels)
  const IW = W - PL - PR;
  const IH = H - PT - PB;

  // Trim empty edge bins
  const trimmed = $derived.by(() => {
    let lo = 0, hi = counts.length - 1;
    while (lo < counts.length && counts[lo] === 0) lo++;
    while (hi > lo && counts[hi] === 0) hi--;
    return {
      counts: counts.slice(lo, hi + 1),
      edges:  edges.slice(lo, hi + 2),
    };
  });

  const xMin = $derived(xMinProp ?? trimmed.edges[0] ?? 0);
  const xMax = $derived(xMaxProp ?? trimmed.edges.at(-1) ?? 1);
  const xRange = $derived(Math.max(xMax - xMin, 1e-9));
  const totalCount = $derived(trimmed.counts.reduce((s, c) => s + c, 0) || 1);

  function xSvg(v: number): number {
    return PL + ((v - xMin) / xRange) * IW;
  }

  // Bars
  const barPaths = $derived(
    trimmed.counts.map((c, i) => {
      const x0 = xSvg(trimmed.edges[i]);
      const x1 = xSvg(trimmed.edges[i + 1]);
      const pct = c / totalCount;
      const bh  = pct * IH * 5;   // 5× scale so full bars are tall enough
      const bh2 = Math.min(bh, IH);
      return { x: x0, w: Math.max(0, x1 - x0 - 0.4), h: bh2, y: PT + IH - bh2 };
    })
  );

  // A-grade zone
  const aZone = $derived.by(() => {
    if (!aGradeRange) return null;
    const { lo, hi } = aGradeRange;
    const x0 = lo != null ? Math.max(xSvg(lo), PL) : PL;
    const x1 = hi != null ? Math.min(xSvg(hi), PL + IW) : PL + IW;
    if (x1 <= x0) return null;
    return { x: x0, w: x1 - x0 };
  });

  // IQR band
  const iqr = $derived.by(() => {
    if (p25 == null || p75 == null) return null;
    const x0 = Math.max(xSvg(p25), PL);
    const x1 = Math.min(xSvg(p75), PL + IW);
    if (x1 <= x0) return null;
    return { x: x0, w: x1 - x0 };
  });

  function fmt(v: number): string {
    if (Number.isInteger(v)) return String(v);
    if (Math.abs(v) >= 10) return v.toFixed(1);
    return v.toFixed(2);
  }

  const axisTicks = $derived.by(() => {
    const pts: number[] = [];
    if (p25 != null && p25 >= xMin && p25 <= xMax) pts.push(p25);
    if (p50 != null && p50 >= xMin && p50 <= xMax && (pts.length === 0 || Math.abs(p50 - p25!) > xRange * 0.1)) pts.push(p50);
    if (p75 != null && p75 >= xMin && p75 <= xMax && (pts.length === 0 || Math.abs(p75 - pts.at(-1)!) > xRange * 0.1)) pts.push(p75);
    return pts;
  });
</script>

<svg viewBox="0 0 {W} {H}" style="width:100%;height:100%;overflow:visible;" role="img" aria-label="distribution histogram">

  <!-- A-grade zone -->
  {#if aZone}
    <rect x={aZone.x} y={PT} width={aZone.w} height={IH} fill="#27ae60" opacity="0.13" />
  {/if}

  <!-- IQR band (p25–p75) -->
  {#if iqr}
    <rect x={iqr.x} y={PT} width={iqr.w} height={IH} fill={color} opacity="0.07" />
  {/if}

  <!-- Bars -->
  {#each barPaths as b}
    <rect x={b.x} y={b.y} width={b.w} height={b.h} fill={color} opacity="0.72" rx="0.5" />
  {/each}

  <!-- Axis baseline -->
  <line x1={PL} y1={PT + IH} x2={PL + IW} y2={PT + IH} stroke="#ccc" stroke-width="0.6" />

  <!-- Median line -->
  {#if p50 != null && p50 >= xMin && p50 <= xMax}
    {@const mx = xSvg(p50)}
    <line x1={mx} y1={PT} x2={mx} y2={PT + IH} stroke="#aaa" stroke-width="0.8" stroke-dasharray="3,2" />
  {/if}

  <!-- Enacted line -->
  {#if enacted != null && enacted >= xMin && enacted <= xMax}
    {@const ex = xSvg(enacted)}
    <line x1={ex} y1={PT} x2={ex} y2={PT + IH} stroke="#e74c3c" stroke-width="2" stroke-dasharray="4,2.5" />
  {/if}

  <!-- Tick labels -->
  {#each axisTicks as v}
    {@const tx = xSvg(v)}
    <line x1={tx} y1={PT + IH} x2={tx} y2={PT + IH + 3} stroke="#bbb" stroke-width="0.7" />
    <text x={tx} y={H - 3} text-anchor="middle" font-size="7" fill="#999">{fmt(v)}</text>
  {/each}

</svg>
