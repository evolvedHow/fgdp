<script lang="ts">
  import { onMount } from 'svelte';
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
    } catch {
      data = { available: false };
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    // Force panel open + load data when the user prints, so all 4 scatters appear.
    const handler = () => {
      if (!expanded) { expanded = true; }
      if (!data) load();
    };
    window.addEventListener('beforeprint', handler);
    return () => window.removeEventListener('beforeprint', handler);
  });

  function toggleExpanded() {
    expanded = !expanded;
    if (expanded) load();
  }
</script>

<div class="urban-crack-panel" style="background:var(--card);border:1.5px solid var(--border);border-radius:8px;
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

        <!-- 2×2 grid of all scatter plots + correlation summary sidebar -->
        <div class="scatter-layout" style="display:grid;grid-template-columns:1fr 220px;gap:1rem;align-items:start;">

          <!-- Left: 2×2 scatter grid — all 4 always visible -->
          <div class="scatter-grid" style="display:grid;grid-template-columns:1fr 1fr;gap:.7rem;">
            {#each availablePairKeys as k}
              {@const meta = PAIR_META[k]}
              {#if data.scatter?.[k]}
                <CrossMetricScatter
                  pair={data.scatter[k]}
                  xlabel={meta.xlabel}
                  ylabel={meta.ylabel}
                  color={meta.color}
                  title={meta.title}
                  compact={true}
                />
              {/if}
            {/each}
          </div>

          <!-- Right: correlation summary sidebar -->
          <div>
            <div style="font-size:.68rem;font-weight:700;text-transform:uppercase;
                        letter-spacing:.05em;color:var(--gray);margin-bottom:.5rem;">
              Correlation summary
            </div>
            <div style="display:flex;flex-direction:column;gap:.35rem;">
              {#each availablePairKeys as k}
                {@const meta = PAIR_META[k]}
                {@const sp   = data.scatter?.[k]}
                {@const r    = sp?.r ?? null}
                {@const str  = rStrength(r)}
                <div
                  style="text-align:left;border:1.5px solid var(--border);
                         border-radius:6px;padding:.5rem .65rem;
                         background:var(--card);"
                >
                  <div style="font-size:.7rem;font-weight:700;color:{meta.color};margin-bottom:.1rem;">
                    {meta.title}
                  </div>
                  <div style="font-size:.64rem;color:var(--gray);margin-bottom:.2rem;line-height:1.35;">
                    {meta.question}
                  </div>
                  <div style="display:flex;align-items:center;gap:.5rem;">
                    <span style="font-family:monospace;font-size:.78rem;font-weight:800;color:#333;">
                      r = {r != null ? r.toFixed(2) : '—'}
                    </span>
                    <span style="font-size:.63rem;font-weight:600;color:{str.color};">
                      {str.label}
                    </span>
                  </div>
                </div>
              {/each}
            </div>
            <div style="margin-top:.6rem;font-size:.63rem;color:var(--gray);line-height:1.5;
                        padding:.4rem .5rem;background:var(--light);border-radius:4px;">
              <b>r (Pearson correlation)</b> measures how two metrics move together
              across all neutral ensemble plans. Near zero = independent.
              ±1 = perfectly linked. Red star = enacted map.
            </div>
          </div>

        </div>
      {/if}
    </div>
  {/if}
</div>

<style>
  @keyframes spin { to { transform: rotate(360deg); } }

  /* Narrow screens: stack 2×2 grid to single column */
  @media (max-width: 700px) {
    .scatter-grid {
      grid-template-columns: 1fr !important;
    }
    .scatter-layout {
      grid-template-columns: 1fr !important;
    }
  }
</style>
