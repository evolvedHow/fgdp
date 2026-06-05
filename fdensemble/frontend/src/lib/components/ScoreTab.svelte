<script lang="ts">
  import type { Analysis, ElectionOption, MetricGrade, Grades, ScoredPlan } from '../types.js';
  import GradePanel   from './GradePanel.svelte';
  import MetricCard   from './MetricCard.svelte';
  import RiverChart   from './RiverChart.svelte';
  import PlanUploader from './PlanUploader.svelte';

  interface Props {
    analysis: Analysis;
    scoredPlans: ScoredPlan[];
    selectedRunId: string;
    selectedElectionIdx: number;
    onSwitchElection: (idx: number) => void;
    onAddPlan: (plan: ScoredPlan) => void;
    onRemovePlan: (id: string) => void;
  }
  let {
    analysis, scoredPlans, selectedRunId, selectedElectionIdx,
    onSwitchElection, onAddPlan, onRemovePlan,
  }: Props = $props();

  let selectedPlanId: string = $state('');

  // Default to the first (enacted) plan when scoredPlans changes
  $effect(() => {
    const plans = scoredPlans;
    if (plans.length && (!selectedPlanId || !plans.find(p => p.id === selectedPlanId))) {
      selectedPlanId = plans[0]?.id ?? '';
    }
  });

  const selectedPlan: ScoredPlan | null = $derived(
    scoredPlans.find(p => p.id === selectedPlanId) ?? null
  );
  const isEnacted: boolean = $derived(selectedPlan?.source === 'catalog');

  const uploadedPlans: ScoredPlan[] = $derived(scoredPlans.filter(p => p.source === 'upload'));

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

  const displayGrades: Grades | null = $derived(
    isEnacted ? analysis.grades : (selectedPlan?.grades ?? null)
  );

  function planMetricFor(key: string) {
    if (!selectedPlan || isEnacted) return null;
    return selectedPlan.metrics[key] ?? null;
  }

  const summary           = $derived(analysis.summary);
  const river             = $derived(analysis.river);
  const availableElections: ElectionOption[] = $derived(summary?.run?.elections ?? []);

  function handlePlanAdded(plan: ScoredPlan) {
    onAddPlan(plan);
    selectedPlanId = plan.id;
  }
</script>

<div>
  <!-- Run info strip with plan switcher -->
  <div style="background:var(--card);border-radius:8px;padding:.6rem 1rem;box-shadow:var(--shadow);
              border:1.5px solid var(--border);margin-bottom:.9rem;
              display:flex;gap:1rem;flex-wrap:wrap;font-size:.78rem;color:var(--gray);align-items:center;">
    <span><b>State:</b> {summary?.state_full}</span>
    <span><b>Chamber:</b> {(summary?.run?.chamber ?? summary?.plan_type ?? '').toUpperCase()}</span>
    <span><b>Cycle:</b> {summary?.plan_year}</span>
    <span><b>Plans:</b> {summary?.n_plans.toLocaleString()}</span>
    <span><b>Algorithm:</b> {summary?.run.algorithm}</span>
    <span><b>Run date:</b> {summary?.run.date}</span>

    <span style="margin-left:auto;display:flex;align-items:center;gap:.6rem;flex-wrap:wrap;">
      <!-- Election selector -->
      {#if availableElections.length > 1}
        <span class="no-print" style="display:flex;align-items:center;gap:.4rem;">
          <b>Election:</b>
          <select
            value={selectedElectionIdx}
            onchange={(e) => onSwitchElection(parseInt((e.target as HTMLSelectElement).value))}
            style="font-size:.78rem;padding:.2rem .4rem;border:1px solid var(--border);
                   border-radius:4px;background:var(--card);color:inherit;cursor:pointer;"
          >
            {#each availableElections as elec, i}
              <option value={i}>{elec.label}</option>
            {/each}
          </select>
        </span>
      {/if}

      <!-- Plan selector (only if uploads exist) -->
      {#if scoredPlans.length > 1}
        <span class="no-print" style="display:flex;align-items:center;gap:.4rem;">
          <b>Viewing:</b>
          <select
            value={selectedPlanId}
            onchange={(e) => selectedPlanId = (e.target as HTMLSelectElement).value}
            style="font-size:.78rem;padding:.2rem .4rem;border:1px solid var(--border);
                   border-radius:4px;background:var(--card);color:inherit;cursor:pointer;max-width:200px;"
          >
            {#each scoredPlans as plan}
              <option value={plan.id}>{plan.label}{plan.source === 'upload' ? ' ↑' : ''}</option>
            {/each}
          </select>
          {#if selectedPlan?.source === 'upload'}
            <button
              onclick={() => { onRemovePlan(selectedPlanId); selectedPlanId = scoredPlans[0]?.id ?? ''; }}
              title="Remove uploaded plan"
              style="background:none;border:1px solid var(--border);border-radius:4px;
                     cursor:pointer;color:var(--gray);padding:.15rem .4rem;font-size:.72rem;"
            >Remove</button>
          {/if}
        </span>
      {/if}

      <!-- Upload button -->
      <span class="no-print">
        <PlanUploader runId={selectedRunId} onPlanScored={handlePlanAdded} compact={true} />
      </span>

      <!-- Export PDF -->
      <button class="export-pdf-btn no-print" onclick={() => window.print()} title="Export as PDF">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="6,9 6,2 18,2 18,9"/>
          <path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/>
          <rect x="6" y="14" width="12" height="8"/>
        </svg>
        Export PDF
      </button>
    </span>
  </div>

  <!-- Plan label (for uploaded plans) -->
  {#if !isEnacted && selectedPlan}
    <div style="background:var(--light);border:1.5px solid var(--border);border-radius:8px;
                padding:.55rem 1rem;margin-bottom:.8rem;font-size:.78rem;display:flex;
                align-items:center;gap:.6rem;">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--blue)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
        <polyline points="17,8 12,3 7,8"/>
        <line x1="12" y1="3" x2="12" y2="15"/>
      </svg>
      <span>
        <b>{selectedPlan.label}</b>
        <span style="color:var(--gray);margin-left:.4rem;">— {selectedPlan.districts.length} districts · scored against neutral ensemble</span>
      </span>
    </div>
  {/if}

  <!-- Print-only title -->
  <div class="print-only" style="font-size:1.1rem;font-weight:700;margin-bottom:.6rem;color:#111;">
    Fair Districts GA — Redistricting Ensemble Analysis
    {#if summary}· {summary.state_full} {summary.plan_type.toUpperCase()} {summary.plan_year}{/if}
  </div>

  <!-- Composite grade cards -->
  {#if displayGrades}
    <GradePanel grades={analysis.grades} planGrades={isEnacted ? null : displayGrades} />
  {/if}

  <!-- Metric groups -->
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

  <!-- River chart -->
  {#if river}
    <div style="margin:.8rem 0 .4rem;">
      <RiverChart {river} enactedShares={null} />
    </div>
  {/if}
</div>
