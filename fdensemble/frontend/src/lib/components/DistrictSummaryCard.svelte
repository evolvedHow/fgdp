<script lang="ts">
  import type { DistrictResult } from '../types.js';

  interface PlanSide { label: string; district: DistrictResult | null; }
  interface Props { districtId: string; planA: PlanSide; planB: PlanSide; }
  let { districtId, planA, planB }: Props = $props();

  const a = $derived(planA.district);
  const b = $derived(planB.district);

  function pct(v: number | undefined) { return v == null ? '—' : (v * 100).toFixed(1) + '%'; }
  function num(v: number | undefined)  { return v == null ? '—' : v.toLocaleString(); }

  function delta(bv: number | undefined, av: number | undefined) {
    if (bv == null || av == null) return null;
    return bv - av;
  }
  function pp(d: number | null, dec = 1) {
    if (d == null) return '—';
    return `${d > 0 ? '+' : ''}${(d * 100).toFixed(dec)}pp`;
  }
  function signed(d: number | null) {
    if (d == null) return '—';
    return `${d > 0 ? '+' : ''}${Math.round(d).toLocaleString()}`;
  }

  const leanFlip   = $derived(a && b && (a.dem_2pv >= 0.5) !== (b.dem_2pv >= 0.5));
  const hasDemog   = $derived((a?.pct_black != null) || (b?.pct_black != null));
  const dLean      = $derived(delta(b?.dem_2pv,     a?.dem_2pv));
  const dVAP       = $derived(delta(b?.total_vap,   a?.total_vap));
  const dPop       = $derived(delta(b?.total_pop,   a?.total_pop));
  const dBlack     = $derived(delta(b?.pct_black,   a?.pct_black));
  const dHisp      = $derived(delta(b?.pct_hisp,    a?.pct_hisp));
  const dMinority  = $derived(delta(b?.pct_minority, a?.pct_minority));
  const dWhite     = $derived(delta(b?.pct_white,   a?.pct_white));
  const dAian      = $derived(delta(b?.pct_aian,    a?.pct_aian));
  const dAsian     = $derived(delta(b?.pct_asian,   a?.pct_asian));
</script>

<div style="background:var(--card);border:1.5px solid {leanFlip ? '#555' : 'var(--border)'};
            border-radius:10px;margin-bottom:1rem;overflow:hidden;">

  <!-- Header -->
  <div style="background:var(--light);border-bottom:1px solid var(--border);
              padding:.6rem 1rem;display:flex;align-items:center;gap:.6rem;flex-wrap:wrap;">
    <span style="font-size:.8rem;font-weight:700;">District {districtId}</span>
    {#if leanFlip}
      <span style="background:#555;color:#fff;border-radius:3px;
                   padding:.1rem .4rem;font-size:.66rem;font-weight:700;">
        PARTISAN LEAN CHANGED
      </span>
    {/if}
    <span style="margin-left:auto;font-size:.67rem;color:var(--gray);
                 overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:320px;">
      All Δ = Map B − Map A
    </span>
  </div>

  <div style="padding:.8rem 1rem;display:grid;gap:.7rem;">

    <!-- Partisan lean -->
    <div>
      <div style="font-size:.65rem;font-weight:700;text-transform:uppercase;
                  letter-spacing:.05em;color:var(--gray);margin-bottom:.35rem;">
        Partisan Lean (two-party vote share)
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:.4rem;">
        <div style="background:var(--light);border-radius:6px;padding:.45rem .6rem;">
          <div style="font-size:.63rem;color:var(--gray);margin-bottom:.15rem;">Map A (reference)</div>
          <div style="font-size:.9rem;font-weight:700;">{pct(a?.dem_2pv)} Dem-lean</div>
          <div style="font-size:.76rem;color:#555;">{pct(a ? 1 - a.dem_2pv : undefined)} Rep-lean</div>
        </div>
        <div style="background:var(--light);border-radius:6px;padding:.45rem .6rem;">
          <div style="font-size:.63rem;color:var(--gray);margin-bottom:.15rem;">Map B (proposed)</div>
          <div style="font-size:.9rem;font-weight:700;">{pct(b?.dem_2pv)} Dem-lean</div>
          <div style="font-size:.76rem;color:#555;">{pct(b ? 1 - b.dem_2pv : undefined)} Rep-lean</div>
        </div>
        <div style="background:var(--light);border-radius:6px;padding:.45rem .6rem;">
          <div style="font-size:.63rem;color:var(--gray);margin-bottom:.15rem;">Δ (B minus A)</div>
          <div style="font-size:.9rem;font-weight:700;">{pp(dLean)} Dem-lean</div>
          <div style="font-size:.76rem;color:#555;">{dLean == null ? '—' : pp(-dLean)} Rep-lean</div>
        </div>
      </div>
    </div>

    <!-- Population -->
    <div>
      <div style="font-size:.65rem;font-weight:700;text-transform:uppercase;
                  letter-spacing:.05em;color:var(--gray);margin-bottom:.35rem;">
        Constituency Size
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:.4rem;">
        {#each [
          ['Voting Age Pop.', num(a?.total_vap), num(b?.total_vap), signed(dVAP)],
          ['Total Population', num(a?.total_pop), num(b?.total_pop), signed(dPop)],
        ] as [lbl, va, vb, dv]}
          <div style="background:var(--light);border-radius:6px;padding:.45rem .6rem;">
            <div style="font-size:.63rem;color:var(--gray);margin-bottom:.15rem;">{lbl}</div>
            <div style="font-size:.74rem;"><b>A:</b> {va}</div>
            <div style="font-size:.74rem;"><b>B:</b> {vb}</div>
            {#if dv !== '—'}
              <div style="font-size:.72rem;font-weight:700;margin-top:.1rem;">Δ {dv}</div>
            {/if}
          </div>
        {/each}
      </div>
    </div>

    <!-- Demographics -->
    {#if hasDemog}
      <div>
        <div style="font-size:.65rem;font-weight:700;text-transform:uppercase;
                    letter-spacing:.05em;color:var(--gray);margin-bottom:.35rem;">
          Demographic Composition — % of Voting Age Population  (Δ = B minus A)
        </div>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:.4rem;">
          {#each [
            ['Black / African Am.',  a?.pct_black,   b?.pct_black,   dBlack],
            ['Hispanic / Latino',    a?.pct_hisp,    b?.pct_hisp,    dHisp],
            ['Minority Coalition',   a?.pct_minority, b?.pct_minority, dMinority],
            ['White',                a?.pct_white,   b?.pct_white,   dWhite],
            ['Am. Indian / AN',      a?.pct_aian,    b?.pct_aian,    dAian],
            ['Asian American',       a?.pct_asian,   b?.pct_asian,   dAsian],
          ] as [lbl, va, vb, dv]}
            {#if va != null || vb != null}
              <div style="background:var(--light);border-radius:6px;padding:.45rem .6rem;">
                <div style="font-size:.62rem;color:var(--gray);margin-bottom:.2rem;line-height:1.3;">{lbl}</div>
                <div style="display:flex;justify-content:space-between;font-size:.72rem;">
                  <span><b>A:</b> {pct(va)}</span><span><b>B:</b> {pct(vb)}</span>
                </div>
                <div style="font-size:.72rem;font-weight:700;margin-top:.05rem;">
                  Δ {dv == null ? '—' : pp(dv)}
                </div>
              </div>
            {/if}
          {/each}
        </div>
      </div>
    {:else}
      <div style="font-size:.71rem;color:var(--gray);font-style:italic;">
        Demographic breakdown available for maps scored via the map library.
      </div>
    {/if}

  </div>
</div>
