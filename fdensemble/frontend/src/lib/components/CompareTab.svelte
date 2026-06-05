<script lang="ts">
  import type { ScoredPlan } from '../types.js';
  import DistrictDeltaTable from './DistrictDeltaTable.svelte';

  interface Props {
    scoredPlans: ScoredPlan[];
  }
  let { scoredPlans }: Props = $props();

  let planAId: string = $state('');
  let planBId: string = $state('');

  // Auto-select defaults when plans become available
  $effect(() => {
    const plans = scoredPlans;
    if (plans.length >= 1 && !planAId) planAId = plans[0].id;
    if (plans.length >= 2 && !planBId) planBId = plans[1]?.id ?? '';
  });

  const planA: ScoredPlan | null = $derived(scoredPlans.find(p => p.id === planAId) ?? null);
  const planB: ScoredPlan | null = $derived(scoredPlans.find(p => p.id === planBId) ?? null);

  const canCompare: boolean = $derived(
    planA !== null && planB !== null &&
    planAId !== planBId &&
    planA.districts.length > 0 && planB.districts.length > 0
  );
</script>

<div>
  <!-- Plan selectors -->
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1rem;">
    <div style="background:var(--card);border:1.5px solid var(--border);border-radius:8px;padding:.7rem .9rem;">
      <label for="plan-a-select" style="font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;
                    color:var(--gray);display:block;margin-bottom:.35rem;">Plan A (baseline)</label>
      <select
        id="plan-a-select"
        value={planAId}
        onchange={(e) => planAId = (e.target as HTMLSelectElement).value}
        style="width:100%;padding:.35rem .5rem;font-size:.82rem;border:1px solid var(--border);
               border-radius:4px;background:var(--card);color:inherit;cursor:pointer;"
      >
        <option value="">— select a plan —</option>
        {#each scoredPlans as plan}
          <option value={plan.id}>{plan.label}</option>
        {/each}
      </select>
      {#if planA}
        <div style="font-size:.68rem;color:var(--gray);margin-top:.3rem;">
          {planA.districts.length} districts ·
          {planA.districts.filter(d => d.dem_2pv >= 0.5).length} Dem /
          {planA.districts.filter(d => d.dem_2pv < 0.5).length} Rep
        </div>
      {/if}
    </div>

    <div style="background:var(--card);border:1.5px solid var(--border);border-radius:8px;padding:.7rem .9rem;">
      <label for="plan-b-select" style="font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;
                    color:var(--gray);display:block;margin-bottom:.35rem;">Plan B (proposed)</label>
      <select
        id="plan-b-select"
        value={planBId}
        onchange={(e) => planBId = (e.target as HTMLSelectElement).value}
        style="width:100%;padding:.35rem .5rem;font-size:.82rem;border:1px solid var(--border);
               border-radius:4px;background:var(--card);color:inherit;cursor:pointer;"
      >
        <option value="">— select a plan —</option>
        {#each scoredPlans as plan}
          <option value={plan.id}>{plan.label}</option>
        {/each}
      </select>
      {#if planB}
        <div style="font-size:.68rem;color:var(--gray);margin-top:.3rem;">
          {planB.districts.length} districts ·
          {planB.districts.filter(d => d.dem_2pv >= 0.5).length} Dem /
          {planB.districts.filter(d => d.dem_2pv < 0.5).length} Rep
        </div>
      {/if}
    </div>
  </div>

  <!-- Comparison note -->
  {#if planAId === planBId && planAId}
    <div style="background:#fff8e1;border:1px solid #f9a825;border-radius:6px;padding:.5rem .8rem;
                font-size:.76rem;color:#e65100;margin-bottom:.8rem;">
      Plan A and Plan B are the same. Select two different plans to compare.
    </div>
  {/if}

  {#if scoredPlans.length < 2}
    <div style="text-align:center;padding:3rem;color:var(--gray);font-size:.85rem;
                background:var(--card);border:1.5px solid var(--border);border-radius:8px;">
      Upload a second plan in the <b>Evaluate</b> tab to enable comparison.
    </div>
  {:else if canCompare && planA && planB}
    <DistrictDeltaTable
      planA={{ label: planA.label, districts: planA.districts }}
      planB={{ label: planB.label, districts: planB.districts }}
    />
  {:else if !planAId || !planBId}
    <div style="text-align:center;padding:3rem;color:var(--gray);font-size:.85rem;
                background:var(--card);border:1.5px solid var(--border);border-radius:8px;">
      Select two plans above to see a district-by-district comparison.
    </div>
  {/if}
</div>
