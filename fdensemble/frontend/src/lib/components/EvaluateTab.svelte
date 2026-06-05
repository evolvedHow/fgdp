<script lang="ts">
  import type { Analysis, ScoredPlan, MetricGrade, Grades } from '../types.js';
  import GradePanel    from './GradePanel.svelte';
  import MetricCard    from './MetricCard.svelte';
  import PlanUploader  from './PlanUploader.svelte';

  interface Props {
    analysis: Analysis;
    scoredPlans: ScoredPlan[];
    selectedRunId: string;
    onAddPlan: (plan: ScoredPlan) => void;
    onRemovePlan: (id: string) => void;
  }
  let { analysis, scoredPlans, selectedRunId, onAddPlan, onRemovePlan }: Props = $props();

  let selectedPlanId: string = $state('');

  // When scoredPlans changes (e.g., run switch), reset selection to first plan
  $effect(() => {
    const plans = scoredPlans;
    if (plans.length && (!selectedPlanId || !plans.find(p => p.id === selectedPlanId))) {
      selectedPlanId = plans[0]?.id ?? '';
    }
  });

  const selectedPlan: ScoredPlan | null = $derived(
    scoredPlans.find(p => p.id === selectedPlanId) ?? null
  );

  // Whether the selected plan is the enacted/catalog plan
  const isEnacted: boolean = $derived(selectedPlan?.source === 'catalog');

  const PARTISAN_KEYS    = ['dem_seats', 'partisan_bias', 'efficiency_gap', 'mean_median'];
  const COMPETITIVE_KEYS = ['comp_seats'];
  const GEOGRAPHIC_KEYS  = ['polsby_popper', 'county_splits', 'muni_splits'];
  const MINORITY_KEYS    = ['maj_black', 'maj_hisp', 'maj_aian', 'maj_asian', 'min_coal'];
  const ALL_METRIC_GROUPS = [PARTISAN_KEYS, COMPETITIVE_KEYS, GEOGRAPHIC_KEYS, MINORITY_KEYS];
  const GROUP_LABELS = ['Partisan Fairness', 'Competitiveness', 'Geographic', 'Minority Representation'];

  function allMetrics(keys: string[]): {key: string; metric: MetricGrade}[] {
    return keys
      .filter(k => k in analysis.grades && !k.startsWith('_'))
      .map(k => ({ key: k, metric: analysis.grades[k] as MetricGrade }))
      .filter(({metric}) => metric && 'histogram' in metric);
  }

  // Grades to show in GradePanel: plan's composite grades (or benchmark grades for enacted)
  const displayGrades: Grades | null = $derived(
    isEnacted ? analysis.grades : (selectedPlan?.grades ?? null)
  );

  // For uploaded plans, look up plan metric override per key
  function planMetricFor(key: string) {
    if (!selectedPlan || isEnacted) return null;
    return selectedPlan.metrics[key] ?? null;
  }

  const gradeColor: Record<string, string> = {
    A: '#27ae60', B: '#2980b9', C: '#d68910', D: '#e67e22', F: '#c0392b',
  };
</script>

<div style="display:grid;grid-template-columns:240px 1fr;gap:1rem;align-items:start;">

  <!-- Left sidebar: plan list -->
  <div style="background:var(--card);border:1.5px solid var(--border);border-radius:8px;
              overflow:hidden;position:sticky;top:.5rem;">
    <div style="padding:.5rem .7rem;background:var(--light);border-bottom:1px solid var(--border);
                font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--gray);">
      Plans
    </div>

    {#each scoredPlans as plan}
      {@const overallGrade = (plan.grades._overall as any)?.grade ?? '—'}
      <div
        role="button"
        tabindex="0"
        onclick={() => selectedPlanId = plan.id}
        onkeydown={(e) => e.key === 'Enter' && (selectedPlanId = plan.id)}
        style="width:100%;text-align:left;padding:.5rem .7rem;cursor:pointer;
               background:{selectedPlanId === plan.id ? 'var(--light)' : 'transparent'};
               border-left:{selectedPlanId === plan.id ? '3px solid var(--blue)' : '3px solid transparent'};
               display:flex;align-items:center;gap:.5rem;transition:background .1s;"
      >
        <span style="display:inline-flex;align-items:center;justify-content:center;
                     width:1.4rem;height:1.4rem;border-radius:50%;flex-shrink:0;
                     background:{gradeColor[overallGrade] ?? '#888'};
                     color:#fff;font-weight:800;font-size:.72rem;">
          {overallGrade}
        </span>
        <div style="min-width:0;flex:1;">
          <div style="font-size:.76rem;font-weight:600;color:inherit;
                      overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
            {plan.label}
          </div>
          <div style="font-size:.62rem;color:var(--gray);">
            {plan.source === 'catalog' ? 'Enacted' : 'Uploaded'} · {plan.districts.length}d
          </div>
        </div>
        {#if plan.source === 'upload'}
          <button
            onclick={(e) => { e.stopPropagation(); onRemovePlan(plan.id); }}
            title="Remove plan"
            style="flex-shrink:0;background:none;border:none;
                   cursor:pointer;color:var(--gray);padding:.1rem;line-height:1;font-size:.7rem;"
          >✕</button>
        {/if}
      </div>
    {/each}

    <!-- Upload button -->
    <div style="padding:.5rem .6rem;border-top:1px solid var(--border);">
      <PlanUploader runId={selectedRunId} onPlanScored={onAddPlan} />
    </div>
  </div>

  <!-- Right: plan detail -->
  {#if selectedPlan && displayGrades}
    <div>
      <!-- Plan header -->
      <div style="background:var(--card);border:1.5px solid var(--border);border-radius:8px;
                  padding:.6rem 1rem;margin-bottom:.8rem;display:flex;align-items:center;gap:.8rem;">
        <div>
          <div style="font-size:.9rem;font-weight:700;">{selectedPlan.label}</div>
          <div style="font-size:.72rem;color:var(--gray);">
            {selectedPlan.source === 'catalog' ? 'Enacted plan — ' : 'Uploaded plan — '}
            {selectedPlan.districts.length} districts
            {#if !isEnacted}
              &nbsp;·&nbsp;
              <span style="color:var(--blue);">Scored against benchmark</span>
            {/if}
          </div>
        </div>
      </div>

      <!-- Grades -->
      <GradePanel grades={analysis.grades} planGrades={isEnacted ? null : displayGrades} />

      <!-- Metrics grouped -->
      {#each ALL_METRIC_GROUPS as keys, gi}
        {#if allMetrics(keys).length}
          <div style="font-size:.74rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;
                      color:var(--gray);margin:.8rem 0 .4rem;">{GROUP_LABELS[gi]}</div>
          <div style="display:flex;flex-direction:column;gap:.55rem;">
            {#each allMetrics(keys) as {key, metric}}
              <MetricCard {metric} planMetric={planMetricFor(key)} />
            {/each}
          </div>
        {/if}
      {/each}
    </div>
  {:else}
    <div style="text-align:center;padding:3rem;color:var(--gray);font-size:.85rem;">
      Select a plan from the list to view its scores.
    </div>
  {/if}

</div>
