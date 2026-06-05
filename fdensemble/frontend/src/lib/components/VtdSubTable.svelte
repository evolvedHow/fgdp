<script lang="ts">
  import type { VtdDetail } from '../types.js';

  interface Props {
    districtNumA: number;
    districtNumB: number;
    vtdAssignmentsA: Record<string, number>;
    vtdAssignmentsB: Record<string, number>;
    vtdDetails: Record<string, VtdDetail>;
  }
  let { districtNumA, districtNumB, vtdAssignmentsA, vtdAssignmentsB, vtdDetails }: Props = $props();

  interface VtdRow {
    geoid: string;
    dem_2pv: number;
    total_vap: number;
    distA: number | null;
    distB: number | null;
    moved: boolean;
    inA: boolean;
    inB: boolean;
  }

  const rows: VtdRow[] = $derived.by(() => {
    const geoids = new Set<string>();
    for (const [g, d] of Object.entries(vtdAssignmentsA)) {
      if (d === districtNumA) geoids.add(g);
    }
    for (const [g, d] of Object.entries(vtdAssignmentsB)) {
      if (d === districtNumB) geoids.add(g);
    }

    return [...geoids].map(geoid => {
      const dA = vtdAssignmentsA[geoid] ?? null;
      const dB = vtdAssignmentsB[geoid] ?? null;
      const detail = vtdDetails[geoid];
      const inA = dA === districtNumA;
      const inB = dB === districtNumB;
      return {
        geoid,
        dem_2pv: detail?.dem_2pv ?? 0,
        total_vap: detail?.total_vap ?? 0,
        distA: dA,
        distB: dB,
        moved: inA !== inB,
        inA,
        inB,
      };
    }).sort((a, b) => b.total_vap - a.total_vap);
  });

  const movedCount = $derived(rows.filter(r => r.moved).length);

  function pct(v: number) { return (v * 100).toFixed(1) + '%'; }
</script>

<div style="background:var(--light);border-top:1px solid var(--border);padding:.5rem .7rem;">
  <div style="font-size:.68rem;color:var(--gray);margin-bottom:.4rem;font-weight:600;">
    VTD breakdown — {rows.length} precincts
    {#if movedCount > 0}
      · <span style="color:#e67e22;">{movedCount} moved between plans</span>
    {/if}
  </div>

  {#if rows.length === 0}
    <div style="font-size:.72rem;color:var(--gray);padding:.4rem;">
      No VTD data available for this district (plans without uploaded shapefiles do not have VTD assignments).
    </div>
  {:else}
    <div style="overflow-x:auto;max-height:260px;overflow-y:auto;">
      <table style="width:100%;border-collapse:collapse;font-size:.7rem;">
        <thead>
          <tr style="background:var(--card);position:sticky;top:0;z-index:1;">
            <th style="padding:.3rem .5rem;text-align:left;font-size:.62rem;text-transform:uppercase;letter-spacing:.04em;color:var(--gray);white-space:nowrap;">GEOID</th>
            <th style="padding:.3rem .5rem;text-align:right;font-size:.62rem;text-transform:uppercase;letter-spacing:.04em;color:var(--gray);">Dem%</th>
            <th style="padding:.3rem .5rem;text-align:right;font-size:.62rem;text-transform:uppercase;letter-spacing:.04em;color:var(--gray);">VAP</th>
            <th style="padding:.3rem .5rem;text-align:center;font-size:.62rem;text-transform:uppercase;letter-spacing:.04em;color:var(--gray);">Plan A</th>
            <th style="padding:.3rem .5rem;text-align:center;font-size:.62rem;text-transform:uppercase;letter-spacing:.04em;color:var(--gray);">Plan B</th>
          </tr>
        </thead>
        <tbody>
          {#each rows as row}
            <tr style="border-bottom:1px solid var(--border);
                        background:{row.moved ? '#fff3cd' : 'transparent'};">
              <td style="padding:.25rem .5rem;font-family:monospace;font-size:.67rem;color:var(--gray);">
                {row.geoid}
                {#if row.moved}
                  <span style="background:#e67e22;color:#fff;border-radius:2px;padding:.02rem .2rem;font-size:.6rem;margin-left:.2rem;font-family:sans-serif;">moved</span>
                {/if}
              </td>
              <td style="padding:.25rem .5rem;text-align:right;font-family:monospace;
                          color:{row.dem_2pv >= 0.5 ? 'var(--blue)' : '#c0392b'};">
                {pct(row.dem_2pv)}
              </td>
              <td style="padding:.25rem .5rem;text-align:right;color:var(--gray);">
                {row.total_vap.toLocaleString()}
              </td>
              <td style="padding:.25rem .5rem;text-align:center;font-weight:{row.inA ? '700' : '400'};
                          color:{row.inA ? 'inherit' : 'var(--gray)'};">
                {row.distA ?? '—'}
              </td>
              <td style="padding:.25rem .5rem;text-align:center;font-weight:{row.inB ? '700' : '400'};
                          color:{row.inB ? 'inherit' : 'var(--gray)'};">
                {row.distB ?? '—'}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>
