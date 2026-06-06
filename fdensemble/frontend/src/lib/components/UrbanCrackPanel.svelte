<script lang="ts">
  import type { CorrelationData } from '../types.js';
  import CrossMetricScatter from './CrossMetricScatter.svelte';
  import { apiGet } from '../api.js';

  interface Props {
    runId: string;
  }
  let { runId }: Props = $props();

  let data:      CorrelationData | null = $state(null);
  let loading    = $state(false);
  let expanded   = $state(false);
  let activePair = $state<string | null>(null);

  // The 4 scatter pairs — order determines the summary table order
  const PAIR_META: Record<string, { xlabel: string; ylabel: string; title: string; color: string; question: string }> = {
    'muni_splits_vs_dem_seats':      {
      xlabel: 'City Splits', ylabel: 'Dem-Lean Seats',
      title:  'City splits → Dem seats',
      color:  '#3D77BB',
      question: 'Does cracking cities produce fewer Dem-leaning seats?',
    },
    'muni_splits_vs_efficiency_gap': {
      xlabel: 'City Splits', ylabel: 'Efficiency Gap',
      title:  'City splits → Vote waste',
      color:  '#17a589',
      question: 'Does cracking cities waste more Democratic votes?',
    },
    'muni_splits_vs_comp_seats':     {
      xlabel: 'City Splits', ylabel: 'Competitive Seats',
      title:  'City splits → Competitive seats',
      color:  '#8e44ad',
      question: 'Does cracking cities eliminate competitive races?',
    },
    'dem_seats_vs_efficiency_gap':   {
      xlabel: 'Dem-Lean Seats', ylabel: 'Efficiency Gap',
      title:  'Dem seats vs. vote waste',
      color:  '#c0392b',
      question: 'Are seat count and vote waste measuring the same thing?',
    },
  };

  const availablePairKeys = $derived(
    data?.scatter ? Object.keys(data.scatter).filter(k => k in PAIR_META) : []
  );

  function rStrength(r: number | null): { label: string; color: string } {
    if (r == null) return { label: 'No data', color: '#999' };
    const abs = Math.abs(r);
    if (abs < 0.15) return { label: 'Near zero — independent', color: '#27ae60' };
    if (abs < 0.4)  return { label: 'Weak association',        color: '#d68910' };
    if (abs < 0.7)  return { label: 'Moderate correlation',    color: '#e67e22' };
    return               { label: 'Strong correlation',         color: '#c0392b' };
  }

  async function load() {
    if (loading || data) return;
    loading = true;
    try {
      data = await apiGet<CorrelationData>('/analysis/correlations', { run: runId });
      if (data.available && data.scatter) {
        activePair = Object.keys(data.scatter).find(k => k in PAIR_META) ?? null;
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

        <!-- Layout: scatter left, summary table right -->
        <div style="display:grid;grid-template-columns:1fr 300px;gap:1rem;align-items:start;">

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
              <!-- Plain-English takeaway for the active pair -->
              {#if data.scatter[activePair].r != null}
                {@const r  = data.scatter[activePair].r ?? 0}
                {@const ex = data.scatter[activePair].enacted_x}
                {@const ey = data.scatter[activePair].enacted_y}
                {@const nearZero = Math.abs(r) < 0.2}
                <div style="margin-top:.5rem;font-size:.73rem;color:#333;line-height:1.65;
                            background:#f8f9fb;border-radius:4px;padding:.55rem .75rem;
                            border-left:3px solid {PAIR_META[activePair].color};">
                  {#if nearZero}
                    Each dot in the chart above is one neutral map. The flat orange trend line
                    (r = {r.toFixed(2)}) shows that across thousands of random maps, city-split count
                    has <b>almost no effect</b> on this outcome.
                    {#if ex != null && ey != null}
                      The <b style="color:#e74c3c;">enacted map (red marker)</b> is labelled directly
                      on the chart — notice where it sits relative to the blue cloud.
                    {/if}
                  {:else if Math.abs(r) > 0.8}
                    r = {r.toFixed(2)} — these two metrics are <b>nearly identical in what they measure</b>.
                    They both capture the same underlying partisan tilt, just calculated differently.
                    The tight diagonal line of dots shows they move in near-perfect lockstep across all neutral maps.
                  {:else}
                    r = {r.toFixed(2)} — a {Math.abs(r) < 0.4 ? 'weak' : 'moderate'} association
                    across neutral maps. The orange trend line shows the general direction.
                    {#if ex != null && ey != null}
                      Find the <b style="color:#e74c3c;">enacted map (red)</b> on the chart to see
                      where it falls relative to the neutral cloud.
                    {/if}
                  {/if}
                </div>
              {/if}
            {/if}
          </div>

          <!-- Simple correlation summary table (replaces heatmap) -->
          <div>
            <div style="font-size:.68rem;font-weight:700;text-transform:uppercase;
                        letter-spacing:.05em;color:var(--gray);margin-bottom:.5rem;">
              Click a row to see the scatter →
            </div>
            <div style="display:flex;flex-direction:column;gap:.35rem;">
              {#each availablePairKeys as k}
                {@const meta = PAIR_META[k]}
                {@const sp   = data.scatter?.[k]}
                {@const r    = sp?.r ?? null}
                {@const str  = rStrength(r)}
                {@const isActive = activePair === k}
                <button
                  onclick={() => activePair = k}
                  style="text-align:left;border:1.5px solid {isActive ? meta.color : 'var(--border)'};
                         border-radius:6px;padding:.5rem .65rem;cursor:pointer;
                         background:{isActive ? meta.color + '12' : 'var(--card)'};
                         transition:border-color .15s, background .15s;"
                >
                  <div style="font-size:.72rem;font-weight:700;color:{isActive ? meta.color : '#333'};
                              margin-bottom:.15rem;">
                    {meta.title}
                  </div>
                  <div style="font-size:.67rem;color:var(--gray);margin-bottom:.25rem;line-height:1.4;">
                    {meta.question}
                  </div>
                  <div style="display:flex;align-items:center;gap:.5rem;">
                    <span style="font-family:monospace;font-size:.8rem;font-weight:800;color:#333;">
                      r = {r != null ? r.toFixed(2) : '—'}
                    </span>
                    <span style="font-size:.65rem;font-weight:600;color:{str.color};">
                      {str.label}
                    </span>
                  </div>
                </button>
              {/each}
            </div>
            <div style="margin-top:.6rem;font-size:.64rem;color:var(--gray);line-height:1.5;
                        padding:.4rem .5rem;background:var(--light);border-radius:4px;">
              <b>r (Pearson correlation)</b> measures how two metrics move together
              across all neutral ensemble plans. Near zero = independent.
              ±1 = perfectly linked. Each button above selects a scatter plot.
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
