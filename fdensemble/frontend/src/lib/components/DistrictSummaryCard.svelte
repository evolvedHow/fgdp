<script lang="ts">
  import type { DistrictResult } from '../types.js';

  interface PlanSide {
    label: string;
    district: DistrictResult | null;
  }

  interface Props {
    districtId: string;
    planA: PlanSide;
    planB: PlanSide;
  }
  let { districtId, planA, planB }: Props = $props();

  function pct(v: number) { return (v * 100).toFixed(1) + '%'; }
  function partyLabel(dem_2pv: number) { return dem_2pv >= 0.5 ? 'Dem' : 'Rep'; }
  function partyColor(dem_2pv: number) { return dem_2pv >= 0.5 ? 'var(--blue)' : '#c0392b'; }

  const seatFlip = $derived(
    planA.district && planB.district &&
    ((planA.district.dem_2pv >= 0.5) !== (planB.district.dem_2pv >= 0.5))
  );

  const delta = $derived(
    planA.district && planB.district
      ? planB.district.dem_2pv - planA.district.dem_2pv
      : null
  );
</script>

<div style="background:var(--card);border:1.5px solid {seatFlip ? '#e67e22' : 'var(--border)'};
            border-radius:10px;padding:1rem 1.2rem;margin-bottom:1rem;">
  <div style="font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;
              color:var(--gray);margin-bottom:.7rem;">
    District {districtId} — Comparison
    {#if seatFlip}
      <span style="background:#e67e22;color:#fff;border-radius:3px;padding:.1rem .35rem;
                   font-size:.65rem;margin-left:.4rem;vertical-align:middle;">SEAT FLIP</span>
    {/if}
  </div>

  <div style="display:grid;grid-template-columns:1fr auto 1fr;gap:.8rem;align-items:center;">
    <!-- Plan A -->
    <div style="text-align:center;">
      <div style="font-size:.65rem;color:var(--gray);margin-bottom:.3rem;">{planA.label}</div>
      {#if planA.district}
        <div style="font-size:1.5rem;font-weight:800;color:{partyColor(planA.district.dem_2pv)};">
          {pct(planA.district.dem_2pv)}
        </div>
        <div style="font-size:.72rem;font-weight:600;color:{partyColor(planA.district.dem_2pv)};">
          {partyLabel(planA.district.dem_2pv)}
        </div>
        <div style="font-size:.67rem;color:var(--gray);margin-top:.2rem;">
          VAP: {planA.district.total_vap.toLocaleString()}
        </div>
      {:else}
        <div style="color:var(--gray);font-size:.8rem;">—</div>
      {/if}
    </div>

    <!-- Delta arrow -->
    <div style="text-align:center;min-width:60px;">
      {#if delta !== null}
        <div style="font-size:.75rem;font-weight:700;
                    color:{delta > 0.001 ? '#27ae60' : delta < -0.001 ? '#c0392b' : 'var(--gray)'};">
          {delta > 0.001 ? '+' : ''}{(delta * 100).toFixed(1)}pp
        </div>
        <div style="font-size:1.1rem;color:var(--gray);">→</div>
        <div style="font-size:.65rem;color:var(--gray);">change</div>
      {:else}
        <div style="color:var(--gray);">→</div>
      {/if}
    </div>

    <!-- Plan B -->
    <div style="text-align:center;">
      <div style="font-size:.65rem;color:var(--gray);margin-bottom:.3rem;">{planB.label}</div>
      {#if planB.district}
        <div style="font-size:1.5rem;font-weight:800;color:{partyColor(planB.district.dem_2pv)};">
          {pct(planB.district.dem_2pv)}
        </div>
        <div style="font-size:.72rem;font-weight:600;color:{partyColor(planB.district.dem_2pv)};">
          {partyLabel(planB.district.dem_2pv)}
        </div>
        <div style="font-size:.67rem;color:var(--gray);margin-top:.2rem;">
          VAP: {planB.district.total_vap.toLocaleString()}
        </div>
      {:else}
        <div style="color:var(--gray);font-size:.8rem;">—</div>
      {/if}
    </div>
  </div>
</div>
