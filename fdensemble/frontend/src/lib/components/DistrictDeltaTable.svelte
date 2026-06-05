<script lang="ts">
  import type { DistrictResult } from '../types.js';

  interface Props {
    planA: { label: string; districts: DistrictResult[] };
    planB: { label: string; districts: DistrictResult[] };
  }
  let { planA, planB }: Props = $props();

  type SortKey = 'aRank' | 'delta' | 'aLean' | 'bLean';
  let sortKey: SortKey = $state('aRank');
  let sortDesc = $state(true);

  function dist2(a: DistrictResult, b: DistrictResult): number {
    const dlat = a.centroid_lat - b.centroid_lat;
    const dlon = a.centroid_lon - b.centroid_lon;
    return dlat * dlat + dlon * dlon;
  }

  interface MatchedRow {
    aIdx: number;
    aDistrict: DistrictResult;
    bDistrict: DistrictResult | null;
    delta: number | null;
    seatFlip: boolean;
  }

  // Match Plan B districts to Plan A by nearest centroid
  const rows: MatchedRow[] = $derived.by(() => {
    const a = planA.districts;
    const b = planB.districts;
    const matched: MatchedRow[] = a.map((da, aIdx) => {
      if (b.length === 0) {
        return { aIdx, aDistrict: da, bDistrict: null, delta: null, seatFlip: false };
      }
      let best = b[0];
      let bestD = dist2(da, b[0]);
      for (let i = 1; i < b.length; i++) {
        const d = dist2(da, b[i]);
        if (d < bestD) { bestD = d; best = b[i]; }
      }
      const delta = best.dem_2pv - da.dem_2pv;
      const seatFlip =
        (da.dem_2pv >= 0.5 && best.dem_2pv < 0.5) ||
        (da.dem_2pv < 0.5 && best.dem_2pv >= 0.5);
      return { aIdx, aDistrict: da, bDistrict: best, delta, seatFlip };
    });
    return matched;
  });

  const sortedRows: MatchedRow[] = $derived.by(() => {
    const r = [...rows];
    r.sort((x, y) => {
      let diff = 0;
      if (sortKey === 'aRank')  diff = x.aIdx - y.aIdx;
      else if (sortKey === 'delta') diff = (x.delta ?? 0) - (y.delta ?? 0);
      else if (sortKey === 'aLean') diff = x.aDistrict.dem_2pv - y.aDistrict.dem_2pv;
      else if (sortKey === 'bLean') diff = (x.bDistrict?.dem_2pv ?? 0) - (y.bDistrict?.dem_2pv ?? 0);
      return sortDesc ? -diff : diff;
    });
    return r;
  });

  // Summary stats
  const demSeatsA: number = $derived(planA.districts.filter(d => d.dem_2pv >= 0.5).length);
  const demSeatsB: number = $derived(planB.districts.filter(d => d.dem_2pv >= 0.5).length);
  const flipCount: number = $derived(rows.filter(r => r.seatFlip).length);

  function pct(v: number) { return (v * 100).toFixed(1) + '%'; }
  function delta(v: number | null) {
    if (v === null) return '—';
    const sign = v > 0 ? '+' : '';
    return sign + (v * 100).toFixed(1) + 'pp';
  }
  function deltaColor(v: number | null) {
    if (v === null || Math.abs(v) < 0.001) return 'inherit';
    return v > 0 ? '#27ae60' : '#c0392b';
  }

  function toggleSort(key: SortKey) {
    if (sortKey === key) sortDesc = !sortDesc;
    else { sortKey = key; sortDesc = true; }
  }

  function chevron(key: SortKey) {
    if (sortKey !== key) return '';
    return sortDesc ? ' ▼' : ' ▲';
  }
</script>

<!-- Summary banner -->
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:.6rem;
            margin-bottom:.8rem;">
  <div style="background:var(--card);border:1.5px solid var(--border);border-radius:8px;
              padding:.6rem .8rem;font-size:.78rem;">
    <div style="font-size:.62rem;text-transform:uppercase;letter-spacing:.05em;color:var(--gray);margin-bottom:.2rem;">
      {planA.label}
    </div>
    <div style="font-weight:700;font-size:1rem;">{demSeatsA} Dem seats</div>
    <div style="color:var(--gray);font-size:.7rem;">{planA.districts.length - demSeatsA} Rep seats</div>
  </div>
  <div style="background:var(--card);border:1.5px solid var(--border);border-radius:8px;
              padding:.6rem .8rem;font-size:.78rem;">
    <div style="font-size:.62rem;text-transform:uppercase;letter-spacing:.05em;color:var(--gray);margin-bottom:.2rem;">
      {planB.label}
    </div>
    <div style="font-weight:700;font-size:1rem;">{demSeatsB} Dem seats</div>
    <div style="color:var(--gray);font-size:.7rem;">{planB.districts.length - demSeatsB} Rep seats</div>
  </div>
  <div style="background:var(--card);border:1.5px solid var(--border);border-radius:8px;
              padding:.6rem .8rem;font-size:.78rem;">
    <div style="font-size:.62rem;text-transform:uppercase;letter-spacing:.05em;color:var(--gray);margin-bottom:.2rem;">
      Net seat change
    </div>
    <div style="font-weight:700;font-size:1rem;color:{demSeatsB - demSeatsA > 0 ? '#27ae60' : demSeatsB - demSeatsA < 0 ? '#c0392b' : 'inherit'};">
      {demSeatsB - demSeatsA > 0 ? '+' : ''}{demSeatsB - demSeatsA} Dem
    </div>
    <div style="color:var(--gray);font-size:.7rem;">{flipCount} seat-flip district{flipCount !== 1 ? 's' : ''}</div>
  </div>
</div>

<!-- Table -->
<div style="background:var(--card);border:1.5px solid var(--border);border-radius:8px;overflow:hidden;">
  <div style="overflow-x:auto;">
    <table style="width:100%;border-collapse:collapse;font-size:.76rem;">
      <thead>
        <tr style="background:var(--light);border-bottom:1.5px solid var(--border);">
          <th style="padding:.45rem .7rem;text-align:left;font-size:.65rem;text-transform:uppercase;
                     letter-spacing:.05em;color:var(--gray);white-space:nowrap;cursor:pointer;"
              onclick={() => toggleSort('aRank')}>
            {planA.label} District{chevron('aRank')}
          </th>
          <th style="padding:.45rem .7rem;text-align:right;font-size:.65rem;text-transform:uppercase;
                     letter-spacing:.05em;color:var(--gray);white-space:nowrap;cursor:pointer;"
              onclick={() => toggleSort('aLean')}>
            Dem%{chevron('aLean')}
          </th>
          <th style="padding:.45rem .5rem;text-align:center;font-size:.65rem;color:var(--gray);">→</th>
          <th style="padding:.45rem .7rem;text-align:left;font-size:.65rem;text-transform:uppercase;
                     letter-spacing:.05em;color:var(--gray);white-space:nowrap;">
            {planB.label} District
          </th>
          <th style="padding:.45rem .7rem;text-align:right;font-size:.65rem;text-transform:uppercase;
                     letter-spacing:.05em;color:var(--gray);white-space:nowrap;cursor:pointer;"
              onclick={() => toggleSort('bLean')}>
            Dem%{chevron('bLean')}
          </th>
          <th style="padding:.45rem .7rem;text-align:right;font-size:.65rem;text-transform:uppercase;
                     letter-spacing:.05em;color:var(--gray);white-space:nowrap;cursor:pointer;"
              onclick={() => toggleSort('delta')}>
            Δ Lean{chevron('delta')}
          </th>
        </tr>
      </thead>
      <tbody>
        {#each sortedRows as row, i}
          {@const rowBg = row.seatFlip ? (i % 2 === 0 ? '#fff8e1' : '#fff3cd') : (i % 2 === 0 ? 'var(--card)' : 'var(--light)')}
          <tr style="border-bottom:1px solid var(--border);background:{rowBg};">
            <td style="padding:.4rem .7rem;font-weight:600;white-space:nowrap;">
              {row.aDistrict.id}
              {#if row.aDistrict.dem_2pv >= 0.5}
                <span style="font-size:.6rem;color:var(--blue);margin-left:.3rem;">Dem</span>
              {:else}
                <span style="font-size:.6rem;color:#c0392b;margin-left:.3rem;">Rep</span>
              {/if}
            </td>
            <td style="padding:.4rem .7rem;text-align:right;font-family:monospace;">
              {pct(row.aDistrict.dem_2pv)}
            </td>
            <td style="padding:.4rem .5rem;text-align:center;color:var(--gray);">→</td>
            <td style="padding:.4rem .7rem;font-weight:600;white-space:nowrap;">
              {row.bDistrict ? row.bDistrict.id : '—'}
              {#if row.bDistrict}
                {#if row.bDistrict.dem_2pv >= 0.5}
                  <span style="font-size:.6rem;color:var(--blue);margin-left:.3rem;">Dem</span>
                {:else}
                  <span style="font-size:.6rem;color:#c0392b;margin-left:.3rem;">Rep</span>
                {/if}
              {/if}
            </td>
            <td style="padding:.4rem .7rem;text-align:right;font-family:monospace;">
              {row.bDistrict ? pct(row.bDistrict.dem_2pv) : '—'}
            </td>
            <td style="padding:.4rem .7rem;text-align:right;font-family:monospace;
                       font-weight:700;color:{deltaColor(row.delta)};">
              {delta(row.delta)}
              {#if row.seatFlip}
                <span style="display:inline-block;margin-left:.3rem;font-size:.6rem;
                             background:#e67e22;color:#fff;border-radius:2px;padding:.05rem .2rem;
                             font-weight:700;vertical-align:middle;">FLIP</span>
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
  <div style="padding:.4rem .7rem;font-size:.65rem;color:var(--gray);border-top:1px solid var(--border);
              background:var(--light);">
    Districts matched by nearest centroid. Click column headers to sort.
    {#if flipCount > 0}
      <span style="color:#e67e22;font-weight:700;">Yellow rows = seat flips.</span>
    {/if}
  </div>
</div>
