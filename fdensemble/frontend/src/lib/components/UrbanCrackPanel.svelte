<script lang="ts">
  import type { CorrelationData } from '../types.js';
  import CrossMetricScatter from './CrossMetricScatter.svelte';
  import CorrelationHeatmap from './CorrelationHeatmap.svelte';
  import { apiGet } from '../api.js';

  interface Props {
    runId: string;
  }
  let { runId }: Props = $props();

  let data:      CorrelationData | null = $state(null);
  let loading    = $state(false);
  let expanded   = $state(false);
  let activePair = $state<string | null>(null);  // selected scatter pair key

  // Friendly labels for each scatter pair key
  const PAIR_META: Record<string, { xlabel: string; ylabel: string; title: string; color: string }> = {
    'muni_splits_vs_dem_seats':      { xlabel: 'City Splits',   ylabel: 'Dem-Lean Seats',  title: 'City Splits → Dem Seat Count',           color: '#3D77BB' },
    'muni_splits_vs_efficiency_gap': { xlabel: 'City Splits',   ylabel: 'Efficiency Gap',  title: 'City Splits → Wasted-Vote Imbalance',    color: '#17a589' },
    'muni_splits_vs_comp_seats':     { xlabel: 'City Splits',   ylabel: 'Competitive Seats', title: 'City Splits → Competitive Seat Count', color: '#8e44ad' },
    'dem_seats_vs_efficiency_gap':   { xlabel: 'Dem-Lean Seats', ylabel: 'Efficiency Gap', title: 'Dem Seats vs. Vote-Waste Imbalance',     color: '#3D77BB' },
  };

  const availablePairKeys = $derived(
    data?.scatter ? Object.keys(data.scatter).filter(k => k in PAIR_META) : []
  );

  async function load() {
    if (loading || data) return;
    loading = true;
    try {
      data = await apiGet<CorrelationData>('/analysis/correlations', { run: runId });
      // Auto-select first scatter pair
      if (data.available && data.scatter) {
        const firstKey = Object.keys(data.scatter).find(k => k in PAIR_META) ?? null;
        activePair = firstKey;
      }
    } catch {
      data = { available: false };
    } finally {
      loading = false;
    }
  }

  function toggleExpanded() {
    expanded = !expanded;
    if (expanded) load();
  }
</script>

<div style="background:var(--card);border:1.5px solid var(--border);border-radius:8px;
            overflow:hidden;margin-top:.9rem;">

  <!-- Collapsible header -->
  <button
    onclick={toggleExpanded}
    style="width:100%;padding:.65rem 1rem;background:var(--light);border:none;cursor:pointer;
           display:flex;align-items:center;justify-content:space-between;gap:.6rem;
           font-size:.74rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;
           color:var(--gray);border-bottom:{expanded ? '1.5px solid var(--border)' : 'none'};"
  >
    <div style="display:flex;align-items:center;gap:.5rem;">
      <span style="font-size:.9rem;">🔗</span>
      Geographic Cracking &amp; Partisan Outcomes
      <span style="font-size:.62rem;font-weight:400;text-transform:none;letter-spacing:0;color:var(--gray);">
        — how city splits correlate with vote efficiency and seat counts
      </span>
    </div>
    <span style="font-size:.9rem;color:var(--gray);">{expanded ? '▲' : '▼'}</span>
  </button>

  {#if expanded}
    <div style="padding:.8rem 1rem;">

      {#if loading}
        <div style="display:flex;align-items:center;gap:.5rem;font-size:.76rem;color:var(--gray);padding:.6rem 0;">
          <span style="display:inline-block;width:10px;height:10px;border:2px solid var(--blue);
                       border-top-color:transparent;border-radius:50%;animation:spin 0.7s linear infinite;"></span>
          Loading correlation data…
        </div>

      {:else if !data?.available}
        <div style="font-size:.76rem;color:var(--gray);padding:.4rem 0;line-height:1.6;">
          <b>Correlation data not yet computed.</b> Re-run the scorecard builder to enable this panel:<br>
          <code style="font-size:.7rem;background:#f0f2f5;padding:.1rem .3rem;border-radius:3px;">
            uv run --project fdp python fdp/scripts/build_scorecard.py --run-name {runId} …
          </code>
        </div>

      {:else}
        <!-- Insight narrative — data-driven summary after load -->
        {@const muniDemR = data.scatter?.['muni_splits_vs_dem_seats']?.r ?? null}
        {@const muniEgapR = data.scatter?.['muni_splits_vs_efficiency_gap']?.r ?? null}
        {@const nDraws = data.scatter && Object.values(data.scatter)[0]?.x?.length}
        {@const strongCorr = (Math.abs(muniDemR ?? 0) + Math.abs(muniEgapR ?? 0)) / 2 > 0.3}
        <div style="background:{strongCorr ? '#f8fdf9' : '#f8f9fb'};
                    border-left:3px solid {strongCorr ? '#27ae60' : '#888'};
                    border-radius:0 4px 4px 0;
                    padding:.6rem .9rem;margin-bottom:.9rem;font-size:.74rem;line-height:1.7;color:#333;">
          <b>Testing the Urban Cracking Hypothesis:</b>
          When cities are split across multiple districts, concentrated urban votes are diluted —
          each district picks up only a thin slice, converting competitive precincts into safe-partisan seats
          and wasting more Democratic votes (higher efficiency gap).
          The scatter plots below test whether this mechanism appears across {nDraws ?? '…'} neutral ensemble draws.
          {#if muniDemR != null}
            {#if strongCorr}
              <br><b style="color:#27ae60;">Finding:</b> The ensemble confirms the hypothesis —
              city splits strongly correlate with partisan outcomes (r = {muniDemR?.toFixed(2)}).
            {:else}
              <br><b style="color:#888;">Finding:</b> In this neutral ensemble, city-split count
              is not a strong predictor of partisan outcomes (r ≈ {muniDemR?.toFixed(2)}).
              The enacted map's partisan profile may reflect sub-municipal VTD manipulation or
              packing rather than visible city-boundary cracking.
              The enacted plan's individual position on each axis (red star) tells the fuller story.
            {/if}
          {/if}
        </div>

        <!-- Scatter pair tabs -->
        {#if availablePairKeys.length > 1}
          <div style="display:flex;gap:.4rem;flex-wrap:wrap;margin-bottom:.6rem;">
            {#each availablePairKeys as k}
              {@const meta = PAIR_META[k]}
              <button
                onclick={() => activePair = k}
                style="padding:.25rem .6rem;border:1.5px solid {activePair === k ? 'var(--blue)' : 'var(--border)'};
                       border-radius:4px;font-size:.68rem;cursor:pointer;
                       background:{activePair === k ? 'var(--blue)' : 'transparent'};
                       color:{activePair === k ? '#fff' : 'var(--gray)'};"
              >
                {meta.title}
              </button>
            {/each}
          </div>
        {/if}

        <!-- Active scatter + heatmap side by side -->
        <div style="display:grid;grid-template-columns:1fr 280px;gap:.8rem;align-items:start;">

          <!-- Scatter chart -->
          <div>
            {#if activePair && data.scatter?.[activePair]}
              {@const meta = PAIR_META[activePair]}
              <CrossMetricScatter
                pair={data.scatter[activePair]}
                xlabel={meta.xlabel}
                ylabel={meta.ylabel}
                color={meta.color}
                title={meta.title}
              />
            {:else}
              <div style="background:var(--light);border:1.5px dashed var(--border);border-radius:8px;
                          height:200px;display:flex;align-items:center;justify-content:center;
                          font-size:.76rem;color:var(--gray);">
                Select a pair above to see the scatter
              </div>
            {/if}

            <!-- Interpretation callout for selected pair -->
            {#if activePair && data.scatter?.[activePair]}
              {@const sp = data.scatter[activePair]}
              {@const r = sp.r ?? 0}
              {@const r2 = r * r}
              {@const nearZero = Math.abs(r) < 0.2}
              {@const ex = sp.enacted_x}
              {@const ey = sp.enacted_y}
              <div style="margin-top:.5rem;font-size:.72rem;color:#333;line-height:1.6;
                          background:#f8f9fb;border-radius:4px;padding:.5rem .7rem;">
                {#if activePair === 'muni_splits_vs_dem_seats'}
                  {#if !nearZero && r < 0}
                    Plans with more city splits produce <b>fewer Democratic-leaning seats</b>
                    (r = {r.toFixed(2)}, R² = {r2.toFixed(2)}).
                    City-split count explains {(r2*100).toFixed(0)}% of Dem-seat variation across
                    {sp.x.length} ensemble draws.
                    {#if ex != null && ey != null}
                      The enacted map ({ex} splits → {ey} seats) confirms the pattern.
                    {/if}
                  {:else if nearZero}
                    r ≈ {r.toFixed(2)} — city splits and Dem seat count vary <b>independently</b>
                    in the neutral ensemble.
                    {#if ex != null && ey != null}
                      <b>Key insight (red star):</b> the enacted map uses only <b>{ex} city splits</b>
                      — fewer than nearly all neutral plans — yet still delivers only <b>{ey} Dem-leaning seats</b>,
                      sitting below the neutral median. The partisan skew exists without visible city-boundary cracking,
                      suggesting sub-municipal or county-level manipulation instead.
                    {/if}
                  {:else}
                    r = {r.toFixed(2)} — weak positive association in this ensemble.
                    {#if ex != null && ey != null}The enacted map: {ex} splits, {ey} Dem seats (red star).{/if}
                  {/if}

                {:else if activePair === 'muni_splits_vs_efficiency_gap'}
                  {#if !nearZero && r > 0}
                    Plans with more city splits produce a <b>higher efficiency gap</b>
                    (r = {r.toFixed(2)}) — Democratic votes are wasted at a greater rate when cities are cracked.
                    City-split count explains {(r2*100).toFixed(0)}% of vote-waste variation across {sp.x.length} draws.
                    {#if ex != null && ey != null}
                      Enacted: {ex} splits, efficiency gap {ey?.toFixed ? ey.toFixed(3) : ey}.
                    {/if}
                  {:else if nearZero}
                    r ≈ {r.toFixed(2)} — city splits and efficiency gap are largely independent here.
                    {#if ex != null && ey != null}
                      <b>Enacted (red star):</b> {ex} city splits with efficiency gap {ey?.toFixed ? ey.toFixed(3) : ey}.
                      Despite low city splits, check whether the efficiency gap sits within or outside the neutral cloud.
                    {/if}
                  {:else}
                    r = {r.toFixed(2)} — {r < 0 ? 'fewer city splits correlate with lower efficiency gap' : 'weak association'} in this ensemble.
                  {/if}

                {:else if activePair === 'muni_splits_vs_comp_seats'}
                  {#if !nearZero && r < 0}
                    More city splits → <b>fewer competitive seats</b> (r = {r.toFixed(2)}).
                    Cracking converts competitive urban precincts into diluted, safe-partisan districts.
                    {#if ex != null && ey != null}
                      Enacted (red star): {ex} city splits, {ey} competitive seats.
                    {/if}
                  {:else if nearZero}
                    r ≈ {r.toFixed(2)} — city splits and competitive seat count are largely independent in this ensemble.
                    {#if ex != null && ey != null}
                      {#if ey === 0}
                        <b style="color:#c0392b;">Enacted (red star): 0 competitive seats</b>
                        — every district is a safe seat for one party, with only {ex} city splits.
                        The neutral ensemble typically produces 2–4 competitive seats; the enacted map sits at the extreme low end.
                      {:else}
                        Enacted (red star): {ex} city splits, {ey} competitive seats.
                      {/if}
                    {/if}
                  {:else}
                    r = {r.toFixed(2)} — weak association between city splits and competitive seat count.
                    {#if ex != null && ey != null}Enacted: {ex} splits, {ey} competitive seats.{/if}
                  {/if}

                {:else if activePair === 'dem_seats_vs_efficiency_gap'}
                  {#if Math.abs(r) > 0.5}
                    r = {r.toFixed(2)} — near-perfect relationship between seat count and vote-waste imbalance.
                    More Dem seats → lower efficiency gap (fewer Democratic votes wasted relative to Republican votes).
                    This tight line is expected: both metrics measure the same underlying partisan tilt.
                    {#if ex != null && ey != null}
                      <b>Enacted (red star):</b> {ex} Dem-leaning seats with an efficiency gap of
                      <b>{ey?.toFixed ? ey.toFixed(3) : ey}</b>
                      ({ey > 0 ? 'positive = Democratic votes wasted at higher rate' : 'negative = Republican votes wasted at higher rate'}).
                      Compare its position to the neutral ensemble cloud to see where it falls on the fairness spectrum.
                    {/if}
                  {:else}
                    r = {r.toFixed(2)} between Dem seats and efficiency gap.
                    {#if ex != null && ey != null}
                      Enacted: {ex} Dem seats, efficiency gap {ey?.toFixed ? ey.toFixed(3) : ey}.
                    {/if}
                  {/if}

                {:else}
                  r = {r.toFixed(2)}, R² = {r2.toFixed(2)} across {sp.x.length} sample draws.
                  {#if ex != null && ey != null}Enacted (red star): ({ex}, {ey?.toFixed ? ey.toFixed(3) : ey}).{/if}
                {/if}
              </div>
            {/if}
          </div>

          <!-- Correlation matrix -->
          <div>
            <div style="font-size:.66rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;
                        color:var(--gray);margin-bottom:.35rem;">Correlation Matrix</div>
            {#if data.matrix}
              <CorrelationHeatmap
                matrix={data.matrix}
                onCellClick={(x, y) => {
                  const k = `${x}_vs_${y}`;
                  const k2 = `${y}_vs_${x}`;
                  if (data?.scatter?.[k]) activePair = k;
                  else if (data?.scatter?.[k2]) activePair = k2;
                }}
              />
            {/if}
            <div style="margin-top:.7rem;font-size:.62rem;color:var(--gray);line-height:1.5;">
              <b>Reading the heatmap:</b><br>
              Green = positive r (both metrics rise together).<br>
              Red = negative r (as one rises, the other falls).<br>
              Click a cell to view its scatter plot.
            </div>
          </div>
        </div>
      {/if}
    </div>
  {/if}
</div>

<style>
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
