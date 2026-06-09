<script lang="ts">
  import type { RunMeta, Analysis, ScoredPlan } from '../types.js';
  import ScoreTab  from './ScoreTab.svelte';
  import CompareTab from './CompareTab.svelte';

  interface Props {
    runs:               RunMeta[];
    analysis:           Analysis;
    companionAnalysis:  Analysis | null;
    companionRunId:     string | null;
    selectedRunId:      string;
    selectedElectionIdx: number;
    onSwitchElection:  (idx: number) => void;
    onAddPlan:         (plan: ScoredPlan) => void;
  }

  let {
    runs, analysis, companionAnalysis, companionRunId,
    selectedRunId, selectedElectionIdx, onSwitchElection, onAddPlan,
  }: Props = $props();

  type Mode = 'benchmark' | 'compare';
  let mode: Mode = $state('benchmark');

  const MODES: { value: Mode; label: string; desc: string }[] = [
    {
      value: 'benchmark',
      label: 'Score a Plan',
      desc:  'Pick any map and see how it scores relative to thousands of neutral plans — Princeton grades, histograms, district breakdown.',
    },
    {
      value: 'compare',
      label: 'Compare Two Plans',
      desc:  'Pick any two maps (enacted, benchmark reference, or proposed) and see district-by-district differences — lean changes, population shifts, demographic deltas.',
    },
  ];
</script>

<!-- Mode selector -->
<div style="background:var(--card);border:1.5px solid var(--border);border-radius:8px;
            padding:.75rem 1rem;margin-bottom:.9rem;display:flex;gap:1.2rem;flex-wrap:wrap;">
  {#each MODES as m}
    <label style="display:flex;align-items:flex-start;gap:.5rem;cursor:pointer;flex:1;min-width:220px;">
      <input
        type="radio"
        name="analysis-mode"
        value={m.value}
        checked={mode === m.value}
        onchange={() => mode = m.value}
        style="margin-top:.2rem;flex-shrink:0;cursor:pointer;"
      />
      <div>
        <div style="font-size:.8rem;font-weight:700;color:{mode === m.value ? 'var(--blue)' : '#333'};">
          {m.label}
        </div>
        <div style="font-size:.7rem;color:var(--gray);line-height:1.4;margin-top:.1rem;">
          {m.desc}
        </div>
      </div>
    </label>
  {/each}
</div>

<!-- Content -->
{#if mode === 'benchmark'}
  <!-- Benchmark mode: Map A = active benchmark (header selector), Map B = any map to score -->
  <ScoreTab
    {analysis}
    {companionAnalysis}
    {companionRunId}
    {selectedRunId}
    {selectedElectionIdx}
    {onSwitchElection}
    {onAddPlan}
  />
{:else}
  <!-- Compare mode: pick any two maps — enacted, benchmark reference, or proposed -->
  <CompareTab {runs} />
{/if}
