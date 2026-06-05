<script lang="ts">
  import type { DistrictResult, VtdDetail } from '../types.js';
  import VtdSubTable from './VtdSubTable.svelte';

  interface Props {
    planA: { label: string; districts: DistrictResult[]; vtd_assignments?: Record<string, number>; vtd_details?: Record<string, VtdDetail> };
    planB: { label: string; districts: DistrictResult[]; vtd_assignments?: Record<string, number> };
    highlightDistrictId?: string;
    onDistrictClick?: (districtId: string) => void;
  }
  let { planA, planB, highlightDistrictId, onDistrictClick }: Props = $props();

  type SortKey = 'district' | 'demLeanDelta' | 'popDelta' | 'vtdsMoved';
  let sortKey: SortKey = $state('district');
  let sortDesc = $state(false);
  let expandedDistrictId = $state('');

  $effect(() => { if (highlightDistrictId) expandedDistrictId = highlightDistrictId; });

  const hasVtdData = $derived(!!(planA.vtd_assignments && planB.vtd_assignments));

  function dist2(a: DistrictResult, b: DistrictResult) {
    return (a.centroid_lat - b.centroid_lat) ** 2 + (a.centroid_lon - b.centroid_lon) ** 2;
  }

  interface MatchedRow {
    aIdx:       number;
    aDistrict:  DistrictResult;
    bDistrict:  DistrictResult | null;
    demDelta:   number | null;   // B dem_2pv - A dem_2pv (pp)
    popDelta:   number | null;   // B total_pop - A total_pop
    vapDelta:   number | null;   // B total_vap - A total_vap
    vtdsMoved:  number;          // VTDs that left this district (if vtd data available)
    leanFlip:   boolean;         // district changed partisan lean direction
  }

  function countVtdsMoved(aNum: number, bNum: number): number {
    if (!planA.vtd_assignments || !planB.vtd_assignments) return 0;
    let moved = 0;
    for (const [geoid, dist] of Object.entries(planA.vtd_assignments)) {
      if (dist === aNum && planB.vtd_assignments[geoid] !== bNum) moved++;
    }
    return moved;
  }

  const rows: MatchedRow[] = $derived.by(() => {
    const a = planA.districts;
    const b = planB.districts;
    return a.map((da, aIdx) => {
      if (!b.length) return { aIdx, aDistrict: da, bDistrict: null, demDelta: null, popDelta: null, vapDelta: null, vtdsMoved: 0, leanFlip: false };
      let best = b[0]; let bestD = dist2(da, b[0]);
      for (let i = 1; i < b.length; i++) {
        const d = dist2(da, b[i]);
        if (d < bestD) { bestD = d; best = b[i]; }
      }
      const demDelta  = best.dem_2pv - da.dem_2pv;
      const popDelta  = (best.total_pop != null && da.total_pop != null) ? best.total_pop - da.total_pop : null;
      const vapDelta  = best.total_vap - da.total_vap;
      const leanFlip  = (da.dem_2pv >= 0.5) !== (best.dem_2pv >= 0.5);
      const vtdsMoved = hasVtdData ? countVtdsMoved(da.district_num, best.district_num) : 0;
      return { aIdx, aDistrict: da, bDistrict: best, demDelta, popDelta, vapDelta, vtdsMoved, leanFlip };
    });
  });

  const sortedRows = $derived.by(() => {
    const r = [...rows];
    r.sort((x, y) => {
      let d = 0;
      if (sortKey === 'district')    d = x.aIdx - y.aIdx;
      else if (sortKey === 'demLeanDelta') d = (x.demDelta ?? 0) - (y.demDelta ?? 0);
      else if (sortKey === 'popDelta')    d = (x.vapDelta ?? 0) - (y.vapDelta ?? 0);
      else if (sortKey === 'vtdsMoved')   d = x.vtdsMoved - y.vtdsMoved;
      return sortDesc ? -d : d;
    });
    return r;
  });

  // Plan-level summary stats
  const demLeansA = $derived(planA.districts.filter(d => d.dem_2pv >= 0.5).length);
  const demLeansB = $derived(planB.districts.filter(d => d.dem_2pv >= 0.5).length);
  const netDemChange = $derived(demLeansB - demLeansA);
  const leanFlipCount = $derived(rows.filter(r => r.leanFlip).length);
  const distChangedCount = $derived(rows.filter(r => r.demDelta != null && Math.abs(r.demDelta * 100) >= 3).length);

  function pp(v: number | null, decimals = 1) {
    if (v == null) return '—';
    const s = v > 0 ? '+' : '';
    return `${s}${(v * 100).toFixed(decimals)}pp`;
  }
  function signed(v: number | null) {
    if (v == null) return '—';
    const s = v > 0 ? '+' : '';
    return `${s}${Math.round(v).toLocaleString()}`;
  }
  function toggleSort(k: SortKey) {
    if (sortKey === k) sortDesc = !sortDesc;
    else { sortKey = k; sortDesc = true; }
  }
  function chevron(k: SortKey) {
    return sortKey === k ? (sortDesc ? ' ▼' : ' ▲') : '';
  }
  function isHighlighted(id: string) { return highlightDistrictId === id; }
</script>

<!-- Delta note -->
<div style="font-size:.72rem;color:var(--gray);margin-bottom:.6rem;font-style:italic;">
  All Δ values = Map B minus Map A. Positive = Map B is higher.
</div>

<!-- Summary banner -->
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:.5rem;margin-bottom:.8rem;">
  {#each [
    ['Dem-Lean Districts', `${demLeansA} → ${demLeansB}`, netDemChange === 0 ? 'No change' : `${netDemChange > 0 ? '+' : ''}${netDemChange}`, Math.abs(netDemChange)],
    ['Districts Shifted ≥3pp', distChangedCount.toString(), '', 0],
    ['Partisan Control Flips', leanFlipCount.toString(), leanFlipCount > 0 ? `${leanFlipCount} district${leanFlipCount > 1 ? 's' : ''} flipped` : '', leanFlipCount],
  ] as [label, value, sub, magnitude]}
    <div style="background:var(--card);border:1.5px solid var(--border);border-radius:8px;padding:.6rem .8rem;">
      <div style="font-size:.62rem;text-transform:uppercase;letter-spacing:.05em;color:var(--gray);margin-bottom:.2rem;">{label}</div>
      <div style="font-weight:700;font-size:1rem;">{value}</div>
      {#if sub}<div style="font-size:.68rem;color:var(--gray);">{sub}</div>{/if}
    </div>
  {/each}
</div>

<!-- Table -->
<div style="background:var(--card);border:1.5px solid var(--border);border-radius:8px;overflow:hidden;">
  <div style="overflow-x:auto;">
    <table style="width:100%;border-collapse:collapse;font-size:.76rem;">
      <thead>
        <tr style="background:var(--light);border-bottom:1.5px solid var(--border);">
          {#if hasVtdData}
            <th style="padding:.45rem .4rem;width:24px;"></th>
          {/if}
          <th onclick={() => toggleSort('district')}
              style="padding:.45rem .8rem;text-align:left;font-size:.64rem;text-transform:uppercase;
                     letter-spacing:.05em;color:var(--gray);cursor:pointer;white-space:nowrap;">
            District (Map A){chevron('district')}
          </th>
          <th onclick={() => toggleSort('demLeanDelta')}
              style="padding:.45rem .7rem;text-align:right;font-size:.64rem;text-transform:uppercase;
                     letter-spacing:.05em;color:var(--gray);cursor:pointer;white-space:nowrap;">
            Δ Dem-Lean%{chevron('demLeanDelta')}
          </th>
          <th style="padding:.45rem .7rem;text-align:right;font-size:.64rem;text-transform:uppercase;
                     letter-spacing:.05em;color:var(--gray);white-space:nowrap;">
            Δ Rep-Lean%
          </th>
          <th onclick={() => toggleSort('popDelta')}
              style="padding:.45rem .7rem;text-align:right;font-size:.64rem;text-transform:uppercase;
                     letter-spacing:.05em;color:var(--gray);cursor:pointer;white-space:nowrap;">
            Δ Population{chevron('popDelta')}
          </th>
          {#if hasVtdData}
            <th onclick={() => toggleSort('vtdsMoved')}
                style="padding:.45rem .7rem;text-align:right;font-size:.64rem;text-transform:uppercase;
                       letter-spacing:.05em;color:var(--gray);cursor:pointer;white-space:nowrap;">
              VTDs Moved{chevron('vtdsMoved')}
            </th>
          {/if}
        </tr>
      </thead>
      <tbody>
        {#each sortedRows as row, i}
          {@const distId = row.aDistrict.id}
          {@const isExpanded = expandedDistrictId === distId}
          {@const highlighted = isHighlighted(distId)}
          {@const rowBg = highlighted ? '#e8f4fd' : row.leanFlip ? (i % 2 === 0 ? '#fff8e1' : '#fff3cd') : (i % 2 === 0 ? 'var(--card)' : 'var(--light)')}

          <tr
            style="border-bottom:{isExpanded ? 'none' : '1px solid var(--border)'};
                   background:{rowBg};
                   outline:{highlighted ? '2px solid var(--blue)' : 'none'};outline-offset:-1px;
                   cursor:{hasVtdData || onDistrictClick ? 'pointer' : 'default'};"
            onclick={() => { if (hasVtdData) expandedDistrictId = isExpanded ? '' : distId; onDistrictClick?.(distId); }}
          >
            {#if hasVtdData}
              <td style="padding:.4rem .4rem;text-align:center;color:var(--gray);font-size:.7rem;">
                {isExpanded ? '▾' : '▸'}
              </td>
            {/if}

            <!-- District ID -->
            <td style="padding:.4rem .8rem;font-weight:600;">
              {row.aDistrict.id}
              {#if row.leanFlip}
                <span style="margin-left:.3rem;font-size:.6rem;background:#555;color:#fff;
                             border-radius:2px;padding:.05rem .2rem;font-weight:700;">FLIP</span>
              {/if}
            </td>

            <!-- Δ Dem-Lean% -->
            <td style="padding:.4rem .7rem;text-align:right;font-family:monospace;font-weight:600;
                       color:{row.demDelta == null ? 'var(--gray)' : 'inherit'};">
              {pp(row.demDelta)}
            </td>

            <!-- Δ Rep-Lean% (mirror of dem delta) -->
            <td style="padding:.4rem .7rem;text-align:right;font-family:monospace;font-weight:600;
                       color:{row.demDelta == null ? 'var(--gray)' : 'inherit'};">
              {row.demDelta == null ? '—' : pp(-row.demDelta)}
            </td>

            <!-- Δ Population (VAP if total_pop unavailable) -->
            <td style="padding:.4rem .7rem;text-align:right;font-family:monospace;
                       color:{row.popDelta == null && row.vapDelta == null ? 'var(--gray)' : 'inherit'};">
              {row.popDelta != null ? signed(row.popDelta) : row.vapDelta != null ? signed(row.vapDelta) + ' vap' : '—'}
            </td>

            {#if hasVtdData}
              <td style="padding:.4rem .7rem;text-align:right;font-family:monospace;color:var(--gray);">
                {row.vtdsMoved > 0 ? row.vtdsMoved.toLocaleString() : '—'}
              </td>
            {/if}
          </tr>

          {#if isExpanded && hasVtdData && planA.vtd_assignments && planB.vtd_assignments && row.bDistrict}
            <tr style="border-bottom:1px solid var(--border);">
              <td colspan="10" style="padding:0;">
                <VtdSubTable
                  districtNumA={row.aDistrict.district_num}
                  districtNumB={row.bDistrict.district_num}
                  vtdAssignmentsA={planA.vtd_assignments}
                  vtdAssignmentsB={planB.vtd_assignments}
                  vtdDetails={planA.vtd_details ?? {}}
                />
              </td>
            </tr>
          {/if}
        {/each}
      </tbody>
    </table>
  </div>
  <div style="padding:.35rem .8rem;font-size:.64rem;color:var(--gray);border-top:1px solid var(--border);background:var(--light);">
    Districts matched by nearest geographic centroid. Click headers to sort.
    {#if hasVtdData}· Click a row to expand precinct-level breakdown.{/if}
    {#if leanFlipCount > 0}· Yellow = district changed partisan lean direction.{/if}
  </div>
</div>
