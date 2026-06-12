<script lang="ts">
  import type { RunMeta, Analysis } from '../types.js';
  import CityIntegrityPanel from './CityIntegrityPanel.svelte';

  interface Props {
    runs: RunMeta[];
    selectedRunId: string;
    analysis: Analysis;
    onRunChange?: (id: string) => void;
  }
  let { runs, selectedRunId, analysis, onRunChange }: Props = $props();

  const summary     = $derived(analysis?.summary ?? null);
  const selectedRun = $derived(runs.find(r => r.id === selectedRunId) ?? null);
  const selectedSource = $derived(selectedRun?.source ?? 'gerrychain');

  // Per-algorithm display helpers (registry table only)
  const ALGO_DETAIL: Record<string, { chains: string; popTol: string; constraints: string }> = {
    alarm: {
      chains:      'Independent SMC chains',
      popTol:      '±1%',
      constraints: 'Equal population, contiguity',
    },
    gerrychain: {
      chains:      'Single ReCom chain',
      popTol:      '±1%',
      constraints: 'Equal population, contiguity, compactness (soft)',
    },
  };

  function detail(run: RunMeta) {
    const base = ALGO_DETAIL[run.source ?? ''] ?? ALGO_DETAIL.gerrychain;
    const popTol = base.popTol;
    const chains = (run.source === 'alarm' && run.n_plans)
      ? `${run.n_plans.toLocaleString()} plans, independent SMC`
      : base.chains;
    return { ...base, popTol, chains };
  }

  function chamberLabel(c: string | undefined) {
    return ({ congress: 'U.S. Congress', senate: 'GA Senate', house: 'GA House' })[c ?? ''] ?? (c ?? '—');
  }

  function sourceLabel(s: string | undefined) {
    return s === 'alarm' ? 'ALARM' : 'GerryChain';
  }

  function sourceBadgeColor(s: string | undefined) {
    return s === 'alarm' ? '#8e44ad' : '#2471a3';
  }

  function electionsList(run: RunMeta) {
    if (run.elections && run.elections.length > 0) {
      return run.elections.map(e => e.label).join(', ');
    }
    return run.description ?? 'Multi-election composite';
  }
</script>

<div>
  <!-- Story panel (LLM-generated narrative; shows placeholder until populated) -->
  {#if summary?.story_html}
    <div style="background:var(--card);border:1.5px solid var(--border);border-radius:10px;
                padding:1.4rem 1.6rem;margin-bottom:1.2rem;line-height:1.72;font-size:.84rem;
                color:#222;">
      <!-- eslint-disable-next-line svelte/no-at-html-tags -->
      {@html summary.story_html}
    </div>
  {/if}

  <!-- Benchmark registry -->
  <div style="margin-bottom:1.2rem;">
    <div style="font-size:.74rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;
                color:var(--gray);margin-bottom:.55rem;">
      Available Benchmarks
    </div>

    <div style="background:var(--card);border:1.5px solid var(--border);border-radius:8px;overflow:hidden;">
      <table style="width:100%;border-collapse:collapse;font-size:.76rem;">
        <thead>
          <tr style="background:var(--light);border-bottom:1.5px solid var(--border);">
            <th style="padding:.45rem .8rem;text-align:left;font-size:.64rem;text-transform:uppercase;
                       letter-spacing:.05em;color:var(--gray);">Benchmark</th>
            <th style="padding:.45rem .8rem;text-align:left;font-size:.64rem;text-transform:uppercase;
                       letter-spacing:.05em;color:var(--gray);">Chamber</th>
            <th style="padding:.45rem .8rem;text-align:left;font-size:.64rem;text-transform:uppercase;
                       letter-spacing:.05em;color:var(--gray);">Algorithm</th>
            <th style="padding:.45rem .8rem;text-align:right;font-size:.64rem;text-transform:uppercase;
                       letter-spacing:.05em;color:var(--gray);">Plans</th>
            <th style="padding:.45rem .8rem;text-align:left;font-size:.64rem;text-transform:uppercase;
                       letter-spacing:.05em;color:var(--gray);">Date</th>
            <th style="padding:.45rem .8rem;text-align:left;font-size:.64rem;text-transform:uppercase;
                       letter-spacing:.05em;color:var(--gray);">Electoral Basis</th>
            <th style="padding:.45rem .8rem;text-align:left;font-size:.64rem;text-transform:uppercase;
                       letter-spacing:.05em;color:var(--gray);">Key Constraints</th>
          </tr>
        </thead>
        <tbody>
          {#each runs as run, i}
            {@const isSelected = run.id === selectedRunId}
            {@const d = detail(run)}
            <tr
              onclick={() => onRunChange?.(run.id)}
              style="border-bottom:{i < runs.length - 1 ? '1px solid var(--border)' : 'none'};
                     background:{isSelected ? '#eaf3fb' : i % 2 === 0 ? 'var(--card)' : 'var(--light)'};
                     cursor:{onRunChange ? 'pointer' : 'default'};
                     outline:{isSelected ? '2px solid var(--blue)' : 'none'};outline-offset:-1px;"
            >
              <!-- Name + source badge -->
              <td style="padding:.5rem .8rem;">
                <div style="display:flex;align-items:center;gap:.4rem;flex-wrap:wrap;">
                  {#if isSelected}
                    <span style="font-size:.6rem;font-weight:700;background:var(--blue);color:#fff;
                                 border-radius:3px;padding:.1rem .35rem;white-space:nowrap;">
                      ● current
                    </span>
                  {/if}
                  <span style="font-size:.64rem;font-weight:700;
                               background:{sourceBadgeColor(run.source)};color:#fff;
                               border-radius:3px;padding:.1rem .35rem;white-space:nowrap;">
                    {sourceLabel(run.source)}
                  </span>
                </div>
                <div style="margin-top:.2rem;font-size:.72rem;color:#333;font-weight:{isSelected ? '700' : '500'};">
                  {run.name ?? run.id}
                </div>
              </td>

              <!-- Chamber -->
              <td style="padding:.5rem .8rem;font-size:.76rem;white-space:nowrap;">
                {chamberLabel(run.chamber)}
              </td>

              <!-- Algorithm -->
              <td style="padding:.5rem .8rem;">
                <div style="font-size:.74rem;font-weight:600;">{run.algorithm}</div>
                <div style="font-size:.67rem;color:var(--gray);margin-top:.1rem;line-height:1.35;">
                  {d.chains}
                </div>
              </td>

              <!-- Plans -->
              <td style="padding:.5rem .8rem;text-align:right;font-weight:700;font-size:.8rem;
                         white-space:nowrap;">
                {run.n_plans?.toLocaleString()}
              </td>

              <!-- Date -->
              <td style="padding:.5rem .8rem;font-size:.73rem;color:var(--gray);white-space:nowrap;">
                {run.date}
              </td>

              <!-- Electoral basis -->
              <td style="padding:.5rem .8rem;font-size:.72rem;line-height:1.35;">
                {electionsList(run)}
                {#if run.source === 'alarm' && run.chamber === 'congress'}
                  <div style="font-size:.65rem;color:var(--gray);font-style:italic;">
                    re-scored from original 2016–2020 composite
                  </div>
                {/if}
              </td>

              <!-- Constraints -->
              <td style="padding:.5rem .8rem;font-size:.70rem;color:#444;line-height:1.4;">
                {d.constraints}
                <div style="color:var(--gray);margin-top:.1rem;">Pop. tol. {d.popTol}</div>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
      {#if onRunChange}
        <div style="padding:.3rem .8rem;font-size:.64rem;color:var(--gray);border-top:1px solid var(--border);
                    background:var(--light);">
          Click a row to switch the active benchmark.
        </div>
      {/if}
    </div>
  </div>

  <!-- City integrity panel — unnecessary municipal splits in the enacted map -->
  <CityIntegrityPanel runId={selectedRunId} source={selectedSource} chamber={selectedRun?.chamber ?? ''} />

</div>
