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

  const a = $derived(planA.district);
  const b = $derived(planB.district);

  function pct(v: number | undefined) {
    return v == null ? '—' : (v * 100).toFixed(1) + '%';
  }
  function num(v: number | undefined) {
    return v == null ? '—' : v.toLocaleString();
  }
  function delta(bv: number | undefined, av: number | undefined, isPct = false) {
    if (bv == null || av == null) return null;
    const d = bv - av;
    return isPct ? d * 100 : d;
  }
  function deltaStr(d: number | null, isPct = false, decimals = 1) {
    if (d == null) return '—';
    const s = d > 0 ? '+' : '';
    return isPct ? `${s}${d.toFixed(decimals)}pp` : `${s}${Math.round(d).toLocaleString()}`;
  }
  function deltaColor(d: number | null) {
    if (d == null || Math.abs(d) < 0.0001) return 'var(--gray)';
    return d > 0 ? '#27ae60' : '#c0392b';
  }

  // Derived deltas
  const dLean    = $derived(delta(b?.dem_2pv, a?.dem_2pv));
  const dVAP     = $derived(delta(b?.total_vap, a?.total_vap));
  const dPop     = $derived(delta(b?.total_pop, a?.total_pop));
  const dBlack   = $derived(delta(b?.pct_black, a?.pct_black, true));
  const dHisp    = $derived(delta(b?.pct_hisp, a?.pct_hisp, true));
  const dMinority= $derived(delta(b?.pct_minority, a?.pct_minority, true));
  const dWhite   = $derived(delta(b?.pct_white, a?.pct_white, true));
  const dAian    = $derived(delta(b?.pct_aian, a?.pct_aian, true));
  const dAsian   = $derived(delta(b?.pct_asian, a?.pct_asian, true));

  const seatFlip = $derived(
    a && b && ((a.dem_2pv >= 0.5) !== (b.dem_2pv >= 0.5))
  );

  const hasDemographics = $derived(
    (a?.pct_black != null) || (b?.pct_black != null)
  );
</script>

<div style="background:var(--card);border:1.5px solid {seatFlip ? '#e67e22' : 'var(--border)'};
            border-radius:10px;margin-bottom:1rem;overflow:hidden;">

  <!-- Header -->
  <div style="background:var(--light);border-bottom:1px solid var(--border);padding:.6rem 1rem;
              display:flex;align-items:center;gap:.6rem;">
    <span style="font-size:.78rem;font-weight:700;">District {districtId}</span>
    {#if seatFlip}
      <span style="background:#e67e22;color:#fff;border-radius:3px;padding:.1rem .4rem;
                   font-size:.66rem;font-weight:700;">SEAT FLIP</span>
    {/if}
    <span style="margin-left:auto;font-size:.68rem;color:var(--gray);">
      Map A: {planA.label} → Map B: {planB.label}
    </span>
  </div>

  <div style="padding:.8rem 1rem;display:grid;gap:.5rem;">

    <!-- ── Partisan lean ─────────────────────────────────────────────────────── -->
    <div style="font-size:.66rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;
                color:var(--gray);margin-bottom:.1rem;">Partisan Lean</div>
    <div style="display:grid;grid-template-columns:1fr auto 1fr auto;gap:.4rem .8rem;
                align-items:center;margin-bottom:.4rem;">
      <!-- Map A -->
      {#if a}
        <div>
          <span style="font-size:1.2rem;font-weight:800;
                       color:{a.dem_2pv >= 0.5 ? 'var(--blue)' : '#c0392b'};">
            {pct(a.dem_2pv)} {a.dem_2pv >= 0.5 ? 'Dem' : 'Rep'}
          </span>
        </div>
      {:else}
        <div style="color:var(--gray);">—</div>
      {/if}
      <!-- Delta arrow -->
      <div style="text-align:center;font-size:.78rem;font-weight:700;
                  color:{deltaColor(dLean != null ? dLean! * 100 : null)};">
        {deltaStr(dLean != null ? dLean! * 100 : null, true)}
      </div>
      <!-- Map B -->
      {#if b}
        <div>
          <span style="font-size:1.2rem;font-weight:800;
                       color:{b.dem_2pv >= 0.5 ? 'var(--blue)' : '#c0392b'};">
            {pct(b.dem_2pv)} {b.dem_2pv >= 0.5 ? 'Dem' : 'Rep'}
          </span>
        </div>
      {:else}
        <div style="color:var(--gray);">—</div>
      {/if}
      <div></div>
    </div>

    <!-- ── Population & VAP ──────────────────────────────────────────────────── -->
    <div style="font-size:.66rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;
                color:var(--gray);margin-bottom:.1rem;">Constituency Size</div>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:.4rem;margin-bottom:.4rem;">
      {#each [
        ['Voting Age Pop (VAP)', num(a?.total_vap), num(b?.total_vap), deltaStr(dVAP)],
        ['Total Population',     num(a?.total_pop), num(b?.total_pop), deltaStr(dPop)],
      ] as [label, va, vb, dv]}
        <div style="background:var(--light);border-radius:6px;padding:.45rem .6rem;">
          <div style="font-size:.64rem;color:var(--gray);margin-bottom:.15rem;">{label}</div>
          <div style="font-size:.76rem;"><b>A:</b> {va}</div>
          <div style="font-size:.76rem;"><b>B:</b> {vb}</div>
          {#if dv !== '—'}
            <div style="font-size:.72rem;font-weight:700;color:{deltaColor(dVAP)};">
              Δ {dv}
            </div>
          {/if}
        </div>
      {/each}
    </div>

    <!-- ── Demographics ─────────────────────────────────────────────────────── -->
    {#if hasDemographics}
      <div style="font-size:.66rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;
                  color:var(--gray);margin-bottom:.1rem;">Demographic Composition (% of VAP)</div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:.4rem;">

        {#each [
          ['Black / African American', a?.pct_black, b?.pct_black, dBlack],
          ['Hispanic / Latino',        a?.pct_hisp,  b?.pct_hisp,  dHisp],
          ['Minority Coalition',        a?.pct_minority, b?.pct_minority, dMinority],
          ['White',                     a?.pct_white, b?.pct_white, dWhite],
          ['Am. Indian / AK Native',   a?.pct_aian,  b?.pct_aian,  dAian],
          ['Asian American',            a?.pct_asian, b?.pct_asian, dAsian],
        ] as [label, va, vb, dv]}
          {#if va != null || vb != null}
            <div style="background:var(--light);border-radius:6px;padding:.45rem .6rem;">
              <div style="font-size:.63rem;color:var(--gray);margin-bottom:.2rem;line-height:1.3;">
                {label}
              </div>
              <div style="display:flex;justify-content:space-between;font-size:.74rem;margin-bottom:.05rem;">
                <span><b>A:</b> {pct(va)}</span>
                <span><b>B:</b> {pct(vb)}</span>
              </div>
              {#if dv != null && Math.abs(dv) >= 0.05}
                <div style="font-size:.72rem;font-weight:700;color:{deltaColor(dv)};">
                  Δ {deltaStr(dv, true)}
                </div>
              {:else}
                <div style="font-size:.67rem;color:var(--gray);">No significant change</div>
              {/if}
            </div>
          {/if}
        {/each}

      </div>
    {:else}
      <div style="font-size:.72rem;color:var(--gray);font-style:italic;padding:.3rem 0;">
        Demographic data available for library maps scored via the scoring pipeline.
        Enacted plans do not yet include VTD-level racial breakdowns.
      </div>
    {/if}

  </div>
</div>
