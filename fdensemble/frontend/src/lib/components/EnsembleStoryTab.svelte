<script lang="ts">
  import type { Analysis, Histogram, MetricGrade } from '../types.js';
  import StatCallout from './StatCallout.svelte';
  import BenchmarkMethodology from './BenchmarkMethodology.svelte';

  interface Props {
    analysis: Analysis;
  }
  let { analysis }: Props = $props();

  const summary = $derived(analysis.summary);
  const grades  = $derived(analysis.grades);

  // Find the modal value in a histogram (bin center with highest count)
  function modalValue(hist: Histogram): number {
    const maxIdx = hist.counts.indexOf(Math.max(...hist.counts));
    return Math.round((hist.edges[maxIdx] + hist.edges[maxIdx + 1]) / 2);
  }

  const demSeatsGrade = $derived(grades['dem_seats'] as MetricGrade | undefined);
  const overallGrade  = $derived((grades['_overall'] as any)?.grade ?? '—');

  const modalSeats    = $derived(demSeatsGrade?.histogram ? modalValue(demSeatsGrade.histogram) : null);
  const enactedSeats  = $derived(demSeatsGrade?.enacted ?? null);
  const enactedPctRank = $derived(demSeatsGrade?.pct_rank ?? null);

  const gradeColor: Record<string, string> = {
    A: '#27ae60', B: '#2980b9', C: '#d68910', F: '#c0392b',
  };
</script>

<div>
  <!-- Story HTML panel -->
  {#if summary?.story_html}
    <div style="background:var(--card);border:1.5px solid var(--border);border-radius:10px;
                padding:1.4rem 1.6rem;margin-bottom:1.2rem;line-height:1.72;font-size:.84rem;
                color:#222;">
      <!-- eslint-disable-next-line svelte/no-at-html-tags -->
      {@html summary.story_html}
    </div>
  {:else}
    <div style="background:var(--light);border:1.5px dashed var(--border);border-radius:10px;
                padding:1.2rem 1.4rem;margin-bottom:1.2rem;text-align:center;color:var(--gray);
                font-size:.82rem;">
      <div style="font-size:1.1rem;margin-bottom:.4rem;">📊</div>
      <div style="font-weight:600;margin-bottom:.3rem;">Ensemble narrative coming soon</div>
      <div>After each ensemble run, an LLM-generated narrative summarizing the key findings
           will appear here in plain English.</div>
    </div>
  {/if}

  <!-- Key stat callouts -->
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
              gap:.75rem;margin-bottom:1.2rem;">
    <StatCallout
      value={summary?.n_plans?.toLocaleString() ?? '—'}
      label="Neutral maps generated"
      sublabel="Each drawn without partisan intent, satisfying all legal constraints"
    />
    {#if modalSeats !== null}
      <StatCallout
        value={`${modalSeats} Dem seats`}
        label="Most common outcome in neutral maps"
        sublabel={`The single most frequent result among ${summary?.n_plans?.toLocaleString() ?? ''} neutral alternatives`}
      />
    {/if}
    {#if enactedSeats !== null && enactedPctRank !== null}
      <StatCallout
        value={`${enactedSeats} Dem seats`}
        label="Enacted map — {Math.round(enactedPctRank)}th percentile"
        sublabel={`${Math.round(enactedPctRank) <= 50 ? 'Below' : 'Above'} ${Math.abs(50 - Math.round(enactedPctRank))}pp from the neutral median`}
        accent={enactedPctRank <= 15 ? '#c0392b' : enactedPctRank >= 85 ? '#27ae60' : 'var(--blue)'}
      />
    {/if}
    {#if overallGrade !== '—'}
      <StatCallout
        value={overallGrade}
        label="Overall Princeton grade"
        sublabel="Based on the Princeton Gerrymandering Project dual-test methodology"
        accent={gradeColor[overallGrade] ?? 'var(--blue)'}
      />
    {/if}
  </div>

  <!-- Methodology accordion -->
  {#if summary?.run}
    <BenchmarkMethodology run={summary.run} />
  {/if}
</div>
