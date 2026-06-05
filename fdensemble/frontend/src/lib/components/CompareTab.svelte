<script lang="ts">
  import type { ScoredPlan, DistrictResult } from '../types.js';
  import DistrictDeltaTable from './DistrictDeltaTable.svelte';
  import DistrictSummaryCard from './DistrictSummaryCard.svelte';

  interface Props {
    scoredPlans: ScoredPlan[];
  }
  let { scoredPlans }: Props = $props();

  let planAId: string = $state('');
  let planBId: string = $state('');
  let selectedDistrictId: string = $state('');

  $effect(() => {
    const plans = scoredPlans;
    if (plans.length >= 1 && !planAId) planAId = plans[0].id;
    if (plans.length >= 2 && !planBId) planBId = plans[1]?.id ?? '';
  });

  // Reset district selection when plans change
  $effect(() => { planAId; planBId; selectedDistrictId = ''; });

  const planA: ScoredPlan | null = $derived(scoredPlans.find(p => p.id === planAId) ?? null);
  const planB: ScoredPlan | null = $derived(scoredPlans.find(p => p.id === planBId) ?? null);

  const canCompare: boolean = $derived(
    planA !== null && planB !== null &&
    planAId !== planBId &&
    planA.districts.length > 0 && planB.districts.length > 0
  );

  // Get the matched district for Plan B corresponding to the selected Plan A district
  function getMatchedDistrictB(districtId: string, a: ScoredPlan, b: ScoredPlan): DistrictResult | null {
    const aDistrict = a.districts.find(d => d.id === districtId);
    if (!aDistrict) return null;
    let best = b.districts[0];
    let bestD = Infinity;
    for (const bd of b.districts) {
      const dlat = aDistrict.centroid_lat - bd.centroid_lat;
      const dlon = aDistrict.centroid_lon - bd.centroid_lon;
      const d = dlat * dlat + dlon * dlon;
      if (d < bestD) { bestD = d; best = bd; }
    }
    return best ?? null;
  }

  const selectedDistrictA: DistrictResult | null = $derived(
    selectedDistrictId && planA
      ? planA.districts.find(d => d.id === selectedDistrictId) ?? null
      : null
  );
  const selectedDistrictB: DistrictResult | null = $derived(
    selectedDistrictId && planA && planB
      ? getMatchedDistrictB(selectedDistrictId, planA, planB)
      : null
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
          {#if planA.vtd_assignments}
            · <span style="color:#27ae60;">VTD data available</span>
          {/if}
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
          {#if planB.vtd_assignments}
            · <span style="color:#27ae60;">VTD data available</span>
          {/if}
        </div>
      {/if}
    </div>
  </div>

  {#if planAId === planBId && planAId}
    <div style="background:#fff8e1;border:1px solid #f9a825;border-radius:6px;padding:.5rem .8rem;
                font-size:.76rem;color:#e65100;margin-bottom:.8rem;">
      Plan A and Plan B are the same. Select two different plans to compare.
    </div>
  {/if}

  {#if scoredPlans.length < 2}
    <div style="text-align:center;padding:3rem;color:var(--gray);font-size:.85rem;
                background:var(--card);border:1.5px solid var(--border);border-radius:8px;">
      Upload a second plan in the <b>Score a Map</b> tab to enable comparison.
    </div>
  {:else if canCompare && planA && planB}

    <!-- District filter -->
    <div style="display:flex;align-items:center;gap:.7rem;margin-bottom:.8rem;flex-wrap:wrap;">
      <label for="district-filter" style="font-size:.76rem;font-weight:700;color:var(--gray);white-space:nowrap;">
        Focus on district:
      </label>
      <select
        id="district-filter"
        value={selectedDistrictId}
        onchange={(e) => selectedDistrictId = (e.target as HTMLSelectElement).value}
        style="padding:.3rem .5rem;font-size:.78rem;border:1px solid var(--border);
               border-radius:4px;background:var(--card);color:inherit;cursor:pointer;"
      >
        <option value="">— all districts —</option>
        {#each planA.districts.slice().sort((a, b) => a.district_num - b.district_num) as d}
          <option value={d.id}>
            District {d.id} ({d.dem_2pv >= 0.5 ? 'Dem' : 'Rep'} {(d.dem_2pv * 100).toFixed(1)}%)
          </option>
        {/each}
      </select>
      {#if selectedDistrictId}
        <button
          onclick={() => selectedDistrictId = ''}
          style="font-size:.72rem;padding:.2rem .5rem;border:1px solid var(--border);
                 border-radius:4px;background:transparent;cursor:pointer;color:var(--gray);"
        >Clear</button>
      {/if}
    </div>

    <!-- District summary card (when a district is selected) -->
    {#if selectedDistrictId}
      <DistrictSummaryCard
        districtId={selectedDistrictId}
        planA={{ label: planA.label, district: selectedDistrictA }}
        planB={{ label: planB.label, district: selectedDistrictB }}
      />
    {/if}

    <!-- Delta table -->
    <DistrictDeltaTable
      planA={{
        label: planA.label,
        districts: planA.districts,
        vtd_assignments: planA.vtd_assignments,
        vtd_details: planA.vtd_details,
      }}
      planB={{
        label: planB.label,
        districts: planB.districts,
        vtd_assignments: planB.vtd_assignments,
      }}
      highlightDistrictId={selectedDistrictId}
      onDistrictClick={(id) => selectedDistrictId = selectedDistrictId === id ? '' : id}
    />

  {:else if !planAId || !planBId}
    <div style="text-align:center;padding:3rem;color:var(--gray);font-size:.85rem;
                background:var(--card);border:1.5px solid var(--border);border-radius:8px;">
      Select two plans above to see a district-by-district comparison.
    </div>
  {/if}
</div>
