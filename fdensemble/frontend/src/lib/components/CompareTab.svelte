<script lang="ts">
  import { onMount } from 'svelte';
  import type { RunMeta, MapMeta, ScoredPlan, DistrictResult, VtdDetail } from '../types.js';
  import DistrictDeltaTable from './DistrictDeltaTable.svelte';
  import DistrictSummaryCard from './DistrictSummaryCard.svelte';

  interface Props {
    runs: RunMeta[];
  }
  let { runs }: Props = $props();

  // ── Map library ──────────────────────────────────────────────────────────────
  let libraryMaps: MapMeta[] = $state([]);

  onMount(async () => {
    try {
      const res = await fetch('/api/maps');
      if (res.ok) libraryMaps = await res.json();
    } catch { /* non-fatal */ }
  });

  // ── Plan selection state ─────────────────────────────────────────────────────
  // Keys are "enacted:{runId}" or "library:{mapId}"
  let selA: string = $state('');
  let selB: string = $state('');

  let planA: ScoredPlan | null = $state(null);
  let planB: ScoredPlan | null = $state(null);
  let loadingA = $state(false);
  let loadingB = $state(false);
  let errorA   = $state('');
  let errorB   = $state('');

  let selectedDistrictId = $state('');

  // Reset district focus when plans change
  $effect(() => { selA; selB; selectedDistrictId = ''; });

  // ── Option helpers ────────────────────────────────────────────────────────────
  interface MapOption {
    value: string;
    label: string;
    group: string;
  }

  const options: MapOption[] = $derived([
    // Enacted plans from all benchmarks
    ...runs
      .filter(r => r.plans && r.plans.length > 0)
      .map(r => ({
        value: `enacted:${r.id}`,
        label: `${r.plans![0].label ?? 'Enacted Map'} — ${r.name ?? r.id}`,
        group: 'Enacted Plans',
      })),
    // Library maps
    ...libraryMaps.map(m => ({
      value: `library:${m.id}`,
      label: `${m.label} (${m.n_districts}d · ${m.created})`,
      group: 'Map Library',
    })),
  ]);

  // ── Plan loading ─────────────────────────────────────────────────────────────
  function defaultRunId(): string {
    // Pick the first non-ALARM GerryChain congress run for scoring library maps
    return (
      runs.find(r => r.source !== 'alarm' && r.chamber === 'congress')?.id ??
      runs[0]?.id ?? ''
    );
  }

  async function loadPlan(key: string): Promise<ScoredPlan | null> {
    if (!key) return null;

    if (key.startsWith('enacted:')) {
      const runId = key.slice(8);
      const run   = runs.find(r => r.id === runId);
      const raw   = run?.plans?.[0];
      if (!raw) return null;
      return { ...raw, run_id: runId, source: 'catalog' } as ScoredPlan;
    }

    if (key.startsWith('library:')) {
      const mapId = key.slice(8);
      const runId = defaultRunId();
      if (!runId) return null;
      const res = await fetch('/api/score-map', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ map_id: mapId, run_id: runId }),
      });
      if (!res.ok) throw new Error(`Server error ${res.status}`);
      const plan: ScoredPlan = await res.json();
      plan.source = 'library';
      return plan;
    }

    return null;
  }

  async function selectA(key: string) {
    selA = key;
    if (!key) { planA = null; errorA = ''; return; }
    loadingA = true; errorA = '';
    try   { planA = await loadPlan(key); }
    catch (e: any) { errorA = e.message ?? 'Failed to load'; planA = null; }
    finally { loadingA = false; }
  }

  async function selectB(key: string) {
    selB = key;
    if (!key) { planB = null; errorB = ''; return; }
    loadingB = true; errorB = '';
    try   { planB = await loadPlan(key); }
    catch (e: any) { errorB = e.message ?? 'Failed to load'; planB = null; }
    finally { loadingB = false; }
  }

  // ── Comparison helpers ────────────────────────────────────────────────────────
  const canCompare = $derived(
    planA !== null && planB !== null &&
    selA !== selB &&
    planA.districts.length > 0 && planB.districts.length > 0
  );

  function getMatchedB(distId: string): DistrictResult | null {
    if (!planA || !planB) return null;
    const da = planA.districts.find(d => d.id === distId);
    if (!da) return null;
    let best = planB.districts[0]; let bestD = Infinity;
    for (const db of planB.districts) {
      const d = (da.centroid_lat - db.centroid_lat) ** 2 + (da.centroid_lon - db.centroid_lon) ** 2;
      if (d < bestD) { bestD = d; best = db; }
    }
    return best ?? null;
  }

  const selDistA = $derived(
    selectedDistrictId && planA
      ? planA.districts.find(d => d.id === selectedDistrictId) ?? null : null
  );
  const selDistB = $derived(
    selectedDistrictId && planA && planB ? getMatchedB(selectedDistrictId) : null
  );

  function pct(v: number) { return (v * 100).toFixed(1) + '%'; }
  function partyLabel(d: DistrictResult) { return d.dem_2pv >= 0.5 ? 'Dem' : 'Rep'; }
</script>

<!-- ── Map selectors ─────────────────────────────────────────────────────────── -->
<div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:.9rem;">

  {#each ([['A', selA, selectA, planA, loadingA, errorA], ['B', selB, selectB, planB, loadingB, errorB]] as const) as [side, sel, doSelect, plan, loading, err]}
    <div style="background:var(--card);border:1.5px solid var(--border);border-radius:8px;padding:.75rem 1rem;">
      <label style="font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;
                    color:var(--gray);display:block;margin-bottom:.35rem;">
        Map {side} {side === 'A' ? '(reference)' : '(proposed)'}
      </label>
      <select
        value={sel}
        onchange={(e) => doSelect((e.target as HTMLSelectElement).value)}
        style="width:100%;padding:.38rem .5rem;font-size:.82rem;border:1px solid var(--border);
               border-radius:4px;background:var(--card);color:inherit;cursor:pointer;"
      >
        <option value="">— select a map —</option>
        {#each ['Enacted Plans', 'Map Library'] as group}
          {@const grpOpts = options.filter(o => o.group === group)}
          {#if grpOpts.length}
            <optgroup label={group}>
              {#each grpOpts as opt}
                <option value={opt.value}>{opt.label}</option>
              {/each}
            </optgroup>
          {/if}
        {/each}
      </select>

      <div style="margin-top:.35rem;min-height:1.2rem;font-size:.68rem;">
        {#if loading}
          <span style="color:var(--gray);">Loading district data…</span>
        {:else if err}
          <span style="color:var(--red);">{err}</span>
        {:else if plan}
          <span style="color:var(--gray);">
            {plan.districts.length} districts ·
            <b style="color:#2980b9;">{plan.districts.filter(d => d.dem_2pv >= 0.5).length} Dem</b> /
            <b style="color:#c0392b;">{plan.districts.filter(d => d.dem_2pv < 0.5).length} Rep</b>
          </span>
        {/if}
      </div>
    </div>
  {/each}

</div>

<!-- ── Same map warning ──────────────────────────────────────────────────────── -->
{#if selA && selB && selA === selB}
  <div style="background:#fff8e1;border:1px solid #f9a825;border-radius:6px;padding:.5rem .8rem;
              font-size:.76rem;color:#e65100;margin-bottom:.8rem;">
    Map A and Map B are the same. Select two different maps to compare.
  </div>
{/if}

<!-- ── Empty state ───────────────────────────────────────────────────────────── -->
{#if !selA || !selB}
  <div style="text-align:center;padding:3rem 2rem;color:var(--gray);font-size:.85rem;
              background:var(--card);border:1.5px solid var(--border);border-radius:8px;">
    <div style="font-size:1.4rem;margin-bottom:.6rem;">↕</div>
    Select two maps above to compare them district by district.
    <div style="margin-top:.5rem;font-size:.76rem;">
      You can compare any combination of enacted plans and uploaded maps —
      no scoring against a benchmark required.
    </div>
  </div>

{:else if canCompare && planA && planB}

  <!-- ── District focus selector ──────────────────────────────────────────────── -->
  <div style="background:var(--card);border:1.5px solid var(--border);border-radius:8px;
              padding:.7rem 1rem;margin-bottom:.9rem;display:flex;align-items:center;
              gap:.8rem;flex-wrap:wrap;">
    <div>
      <div style="font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;
                  color:var(--gray);margin-bottom:.25rem;">Focus on a specific district</div>
      <div style="font-size:.71rem;color:var(--gray);">
        Select a district to see exactly what changes for that constituency.
      </div>
    </div>
    <select
      value={selectedDistrictId}
      onchange={(e) => selectedDistrictId = (e.target as HTMLSelectElement).value}
      style="flex:1;min-width:180px;max-width:340px;padding:.38rem .5rem;font-size:.82rem;
             border:1.5px solid {selectedDistrictId ? 'var(--blue)' : 'var(--border)'};
             border-radius:5px;background:var(--card);color:inherit;cursor:pointer;"
    >
      <option value="">— show all districts —</option>
      {#each planA.districts.slice().sort((a, b) => a.district_num - b.district_num) as d}
        {@const matchedB = getMatchedB(d.id)}
        {@const delta = matchedB ? (matchedB.dem_2pv - d.dem_2pv) * 100 : null}
        <option value={d.id}>
          District {d.id} · {partyLabel(d)} {pct(d.dem_2pv)} in Map A
          {#if delta !== null && Math.abs(delta) >= 1}
             → {delta > 0 ? '+' : ''}{delta.toFixed(1)}pp
          {/if}
        </option>
      {/each}
    </select>
    {#if selectedDistrictId}
      <button
        onclick={() => selectedDistrictId = ''}
        style="padding:.3rem .6rem;border:1px solid var(--border);border-radius:4px;
               background:transparent;cursor:pointer;font-size:.72rem;color:var(--gray);"
      >Clear</button>
    {/if}
  </div>

  <!-- ── District summary card ────────────────────────────────────────────────── -->
  {#if selectedDistrictId && selDistA}
    <DistrictSummaryCard
      districtId={selectedDistrictId}
      planA={{ label: planA.label, district: selDistA }}
      planB={{ label: planB.label, district: selDistB }}
    />
  {/if}

  <!-- ── Delta table ───────────────────────────────────────────────────────────── -->
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

{/if}
