<script lang="ts">
  import { onMount } from 'svelte';
  import type { Analysis, ElectionOption, MetricGrade, Grades, ScoredPlan, MapMeta } from '../types.js';
  import { STATIC_MODE, LIVE_SERVER_URL, apiPost, apiDelete } from '../api.js';
  import GradePanel              from './GradePanel.svelte';
  import MetricCard              from './MetricCard.svelte';
  import RiverChart              from './RiverChart.svelte';
  import BenchmarkComparisonTable from './BenchmarkComparisonTable.svelte';
  import MultiMapScorecard       from './MultiMapScorecard.svelte';
  import UrbanCrackPanel         from './UrbanCrackPanel.svelte';
  import ProportionalityGapPanel from './ProportionalityGapPanel.svelte';

  interface Props {
    analysis: Analysis;
    companionAnalysis?: Analysis | null;
    companionRunId?: string | null;
    selectedRunId: string;
    selectedElectionIdx: number;
    onSwitchElection: (idx: number) => void;
    onAddPlan: (plan: ScoredPlan) => void;
  }
  let {
    analysis, companionAnalysis = null, companionRunId = null,
    selectedRunId, selectedElectionIdx, onSwitchElection, onAddPlan,
  }: Props = $props();

  // Map library state
  let maps: MapMeta[]    = $state([]);
  let selectedMapId      = $state('');
  let scoredPlan: ScoredPlan | null         = $state(null);
  let companionScoredPlan: ScoredPlan | null = $state(null);
  let scoring            = $state(false);
  let companionScoring   = $state(false);
  let scoreError         = $state('');

  // Metric display constants
  const PARTISAN_KEYS    = ['dem_seats', 'partisan_bias', 'efficiency_gap', 'mean_median'];
  const COMPETITIVE_KEYS = ['comp_seats_7pt', 'comp_seats_10pt', 'comp_seats', 'rep_safe_seats', 'dem_safe_seats'];
  const GEOGRAPHIC_KEYS  = ['polsby_popper', 'county_splits', 'muni_splits'];  // muni_splits = Split Cities
  // 3-column threshold metrics (White / Black / Minority Coalition) — shown in compact side-by-side layout
  const THRESHOLD_KEYS   = ['maj_white', 'maj_black', 'min_coal'];
  // Other minority metrics shown full-width below the 3-column block
  const MINORITY_KEYS    = ['maj_hisp', 'maj_aian', 'maj_asian', 'min_influence'];
  const ALL_METRIC_GROUPS = [PARTISAN_KEYS, COMPETITIVE_KEYS, GEOGRAPHIC_KEYS, MINORITY_KEYS];
  const GROUP_LABELS = ['Partisan Fairness', 'Political Balance', 'Geographic', 'Other Minority Metrics'];

  // Demographic threshold slider — 20%–50% BVAP for Black / White / Minority Coalition
  // Default 50% = true VRA majority. Slide left to 20% to see influence districts.
  let demoThresholdPct = $state(50);
  const demoThresholdKey = $derived(
    (demoThresholdPct / 100).toFixed(2)  // "0.50", "0.45", ..., "0.20"
  );

  let showUploader = $state(false);

  // Multi-map comparison
  let comparisonPlans: ScoredPlan[] = $state([]);

  function pinPlan(plan: ScoredPlan) {
    if (!comparisonPlans.some(p => p.id === plan.id)) {
      comparisonPlans = [...comparisonPlans, plan];
    }
  }
  function unpinPlan(planId: string) {
    comparisonPlans = comparisonPlans.filter(p => p.id !== planId);
  }

  function allMetrics(keys: string[]): {key: string; metric: MetricGrade}[] {
    return keys
      .filter(k => k in analysis.grades && !k.startsWith('_'))
      .map(k => ({ key: k, metric: analysis.grades[k] as MetricGrade }))
      .filter(({metric}) => metric && 'histogram' in metric);
  }

  // When a map is selected and run changes, re-score automatically against both benchmarks
  $effect(() => {
    const mapId = selectedMapId;
    const runId = selectedRunId;
    if (mapId && runId) {
      scoreMap(mapId, runId);
    } else if (!mapId) {
      scoredPlan = null;
      companionScoredPlan = null;
      scoreError = '';
    }
  });

  // When run changes, reset scored result so the effect triggers a fresh score
  $effect(() => {
    selectedRunId;
    if (selectedMapId) {
      scoredPlan = null;
    }
  });

  async function loadMaps() {
    if (STATIC_MODE) return; // map library not available in static mode
    try {
      const res = await fetch('/api/maps');
      maps = await res.json();
    } catch {
      maps = [];
    }
  }

  async function scoreMap(mapId: string, runId: string) {
    scoring    = true;
    scoreError = '';
    scoredPlan = null;
    companionScoredPlan = null;

    try {
      const plan = await apiPost<ScoredPlan>('/score-map', { map_id: mapId, run_id: runId });
      plan.run_id = runId;
      plan.source = 'library';
      scoredPlan = plan;
      onAddPlan(plan);
    } catch (e: any) {
      scoreError = e.message ?? 'Scoring failed';
    } finally {
      scoring = false;
    }

    // Score against companion benchmark in parallel (non-blocking)
    if (companionRunId) {
      companionScoring = true;
      try {
        const cPlan = await apiPost<ScoredPlan>('/score-map', { map_id: mapId, run_id: companionRunId });
        cPlan.run_id = companionRunId;
        cPlan.source = 'library';
        companionScoredPlan = cPlan;
      } catch { /* companion scoring failure is non-fatal */ }
      finally { companionScoring = false; }
    }
  }

  async function handleMapSaved(meta: MapMeta) {
    maps = [...maps, meta];
    selectedMapId = meta.id;
    showUploader = false;
  }

  async function handleDeleteMap(mapId: string) {
    await apiDelete(`/maps/${mapId}`);
    maps = maps.filter(m => m.id !== mapId);
    if (selectedMapId === mapId) { selectedMapId = ''; scoredPlan = null; }
  }

  const displayGrades: Grades | null = $derived(
    scoredPlan ? scoredPlan.grades : analysis.grades
  );

  function planMetricFor(key: string) {
    return scoredPlan?.metrics[key] ?? null;
  }

  const summary            = $derived(analysis.summary);
  const river              = $derived(analysis.river);
  const availableElections: ElectionOption[] = $derived(summary?.run?.elections ?? []);
  const selectedMap        = $derived(maps.find(m => m.id === selectedMapId) ?? null);

  onMount(loadMaps);
</script>

<div>
  <!-- Controls strip -->
  <div style="background:var(--card);border-radius:8px;padding:.65rem 1rem;box-shadow:var(--shadow);
              border:1.5px solid var(--border);margin-bottom:.9rem;
              display:flex;gap:1rem;flex-wrap:wrap;font-size:.78rem;color:var(--gray);align-items:center;">

    <!-- Ensemble metadata -->
    <span><b>State:</b> {summary?.state_full}</span>
    <span><b>Chamber:</b> {(summary?.run?.chamber ?? summary?.plan_type ?? '').toUpperCase()}</span>
    <span><b>Plans:</b> {summary?.n_plans?.toLocaleString()}</span>

    <span style="display:flex;align-items:center;gap:1.2rem;margin-left:auto;flex-wrap:wrap;">

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

      <!-- Export PDF -->
      <button class="export-pdf-btn no-print" onclick={() => window.print()} title="Export as PDF"
        style="display:flex;align-items:center;gap:.3rem;padding:.25rem .6rem;
               border:1px solid var(--border);border-radius:4px;background:transparent;
               cursor:pointer;font-size:.78rem;color:var(--gray);">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="6,9 6,2 18,2 18,9"/>
          <path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/>
          <rect x="6" y="14" width="12" height="8"/>
        </svg>
        Export PDF
      </button>
    </span>
  </div>

  <!-- Static mode notice: map upload not available -->
  {#if STATIC_MODE}
    <div style="background:#f0f4ff;border:1.5px solid #b8c8f0;border-radius:8px;
                padding:.6rem 1rem;margin-bottom:.9rem;font-size:.76rem;color:#2c4a8a;
                display:flex;align-items:center;gap:.6rem;">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
           stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/>
        <line x1="12" y1="16" x2="12.01" y2="16"/>
      </svg>
      Map upload and shapefile scoring require the live server.
      <a href={LIVE_SERVER_URL} target="_blank" rel="noopener"
         style="color:var(--blue);font-weight:600;">Open live app ↗</a>
    </div>
  {/if}

  <!-- Map picker (live mode only) -->
  {#if !STATIC_MODE}
  <div style="background:var(--card);border:1.5px solid var(--border);border-radius:8px;
              padding:.8rem 1rem;margin-bottom:.9rem;">
    <div style="display:flex;align-items:center;gap:.8rem;flex-wrap:wrap;">
      <div style="font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;
                  color:var(--gray);white-space:nowrap;">Score a map:</div>

      <!-- Map select -->
      <select
        value={selectedMapId}
        onchange={(e) => selectedMapId = (e.target as HTMLSelectElement).value}
        style="flex:1;min-width:200px;max-width:400px;padding:.35rem .5rem;font-size:.84rem;
               border:1.5px solid var(--border);border-radius:6px;
               background:var(--card);color:inherit;cursor:pointer;"
      >
        <option value="">— show neutral ensemble baseline —</option>
        {#each maps as m}
          <option value={m.id}>{m.label} ({m.n_districts}d · {m.created})</option>
        {/each}
      </select>

      <!-- Delete selected map -->
      {#if selectedMapId}
        <button
          onclick={() => handleDeleteMap(selectedMapId)}
          title="Remove map from library"
          style="padding:.3rem .6rem;border:1px solid var(--border);border-radius:4px;
                 background:transparent;cursor:pointer;font-size:.72rem;color:var(--gray);"
        >Remove</button>
      {/if}

    </div>

    <!-- API hint: maps are preloaded server-side, not uploaded here -->
    {#if maps.length === 0}
      <div style="margin-top:.5rem;font-size:.67rem;color:var(--gray);line-height:1.5;">
        No proposed maps loaded yet. Preload a QC'd map via the API:<br>
        <code style="font-size:.66rem;background:#f0f2f5;padding:.1rem .35rem;border-radius:3px;user-select:all;">
          POST /api/maps  · body: &#123;"label":"Plan A","geojson":&#123;...&#125;&#125;
        </code>
      </div>
    {/if}

    <!-- Companion scoring status -->
    {#if companionScoring}
      <div style="margin-top:.4rem;font-size:.72rem;color:var(--gray);display:flex;align-items:center;gap:.4rem;">
        <span style="display:inline-block;width:8px;height:8px;border:2px solid var(--gray);
                     border-top-color:transparent;border-radius:50%;animation:spin 0.7s linear infinite;"></span>
        Also scoring against companion benchmark…
      </div>
    {/if}

    <!-- Scoring status -->
    {#if scoring}
      <div style="margin-top:.6rem;font-size:.76rem;color:var(--gray);display:flex;align-items:center;gap:.5rem;">
        <span style="display:inline-block;width:10px;height:10px;border:2px solid var(--blue);
                     border-top-color:transparent;border-radius:50%;animation:spin 0.7s linear infinite;"></span>
        Scoring <b>{selectedMap?.label}</b> against the neutral ensemble…
      </div>
    {/if}
    {#if scoreError}
      <div style="margin-top:.6rem;font-size:.75rem;color:var(--red);background:#fef0f0;
                  border:1px solid #f5a9a9;border-radius:4px;padding:.35rem .6rem;">
        {scoreError}
      </div>
    {/if}
  </div>
  {/if}<!-- end !STATIC_MODE map picker -->

  <!-- Active map banner -->
  {#if scoredPlan && !scoring}
    <div style="background:var(--light);border:1.5px solid var(--border);border-radius:8px;
                padding:.55rem 1rem;margin-bottom:.8rem;font-size:.78rem;
                display:flex;align-items:center;justify-content:space-between;gap:.6rem;flex-wrap:wrap;">
      <div style="display:flex;align-items:center;gap:.6rem;">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--blue)"
             stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10"/>
          <polyline points="12 8 12 12 14 14"/>
        </svg>
        <span>
          Showing <b>{scoredPlan.label}</b>
          <span style="color:var(--gray);margin-left:.4rem;">
            — {scoredPlan.districts.length} districts · scored against {summary?.n_plans?.toLocaleString()} neutral alternatives
          </span>
        </span>
      </div>
      <button
        onclick={() => scoredPlan && pinPlan(scoredPlan)}
        disabled={comparisonPlans.some(p => p.id === scoredPlan?.id)}
        style="padding:.25rem .6rem;border:1.5px solid var(--blue);border-radius:4px;
               background:{comparisonPlans.some(p => p.id === scoredPlan?.id) ? 'var(--blue)' : 'transparent'};
               color:{comparisonPlans.some(p => p.id === scoredPlan?.id) ? '#fff' : 'var(--blue)'};
               cursor:{comparisonPlans.some(p => p.id === scoredPlan?.id) ? 'default' : 'pointer'};
               font-size:.72rem;font-weight:600;white-space:nowrap;"
      >
        {comparisonPlans.some(p => p.id === scoredPlan?.id) ? '✓ Pinned' : '+ Pin to scorecard'}
      </button>
    </div>
  {:else if !selectedMapId}
    <div style="background:var(--light);border:1.5px solid var(--border);border-radius:8px;
                padding:.55rem 1rem;margin-bottom:.8rem;font-size:.78rem;color:var(--gray);">
      Showing the <b>enacted map</b> — the current {summary?.state_full ?? ''} congressional districts scored against {summary?.n_plans?.toLocaleString() ?? ''} neutral alternatives.
      Select a map above to compare a different plan.
    </div>
  {/if}

  <!-- Print header -->
  <div class="print-only" style="font-size:1.1rem;font-weight:700;margin-bottom:.6rem;color:#111;">
    Fair Districts GA — Redistricting Ensemble Analysis
    {#if summary}· {summary.state_full} {summary.plan_type.toUpperCase()} {summary.plan_year}{/if}
  </div>

  <!-- Composite grade cards -->
  <GradePanel
    grades={analysis.grades}
    planGrades={scoredPlan ? scoredPlan.grades : null}
  />

  <!-- ── Minority Representation — 3-column threshold block ───────────────── -->
  {#if THRESHOLD_KEYS.some(k => k in analysis.grades && 'histogram' in (analysis.grades[k] ?? {}))}
    <div style="font-size:.74rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;
                color:var(--gray);margin:.8rem 0 .4rem;">Minority Representation</div>

    <!-- Demographic threshold slider -->
    <div class="no-print" style="background:#f8f4ff;border:1px solid #d7bde2;border-radius:6px;
                padding:.55rem .9rem;margin-bottom:.6rem;">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:.5rem;flex-wrap:wrap;">
        <span style="font-size:.72rem;font-weight:700;color:#8e44ad;white-space:nowrap;">
          Threshold: {demoThresholdPct}% BVAP
        </span>
        <span style="font-size:.65rem;color:var(--gray);">
          {demoThresholdPct === 50 ? '50% = True majority (VRA Section 2 standard)' :
           demoThresholdPct === 20 ? '20% = Influence threshold (meaningful electoral impact)' :
           `${demoThresholdPct}% — between influence and majority`}
        </span>
      </div>
      <input type="range" min=20 max=50 step=5 bind:value={demoThresholdPct}
        style="width:100%;margin:.3rem 0 .2rem;accent-color:#8e44ad;cursor:pointer;" />
      <div style="font-size:.61rem;color:var(--gray);line-height:1.45;">
        For each of the 99,001 neutral maps, counts how many districts have ≥{demoThresholdPct}% BVAP for each group,
        producing a bell curve. The enacted map is scored against that distribution.
        <b>50%</b>: true VRA majority standard.
        <b>20%</b>: influence district threshold.
      </div>
    </div>

    <!-- 3-column grid: White | Black | Minority Coalition -->
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:.55rem;margin-bottom:.55rem;">
      {#each THRESHOLD_KEYS as key}
        {#if key in analysis.grades && 'histogram' in (analysis.grades[key] ?? {})}
          {@const metric = analysis.grades[key] as any}
          <MetricCard {metric} planMetric={planMetricFor(key)}
            demoThresholdKey={demoThresholdKey}
            compact={true}
            nDistricts={analysis.summary?.n_districts ?? 14} />
        {/if}
      {/each}
    </div>
  {/if}

  <!-- Metric groups (Partisan / Competitive / Geographic / Other Minority) -->
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

  <!-- Proportionality gap panel — shows the "GIGO" baseline problem -->
  {#if analysis.proportionality}
    <ProportionalityGapPanel
      data={analysis.proportionality}
      nDistricts={analysis.summary?.n_districts ?? 14}
    />
  {/if}

  <!-- Urban Crack correlation panel -->
  <UrbanCrackPanel runId={selectedRunId} />

  <!-- River chart -->
  {#if river}
    <div style="margin:.8rem 0 .4rem;">
      <RiverChart {river} enactedShares={null} />
    </div>
  {/if}

  <!-- Multi-map scorecard -->
  {#if comparisonPlans.length > 0}
    <MultiMapScorecard
      {analysis}
      plans={comparisonPlans}
      onRemovePlan={unpinPlan}
    />
  {/if}

  <!-- Proposed vs Enacted delta table -->
  {#if scoredPlan}
    {@const grades = analysis.grades}
    {@const nDistricts = analysis.summary?.n_districts ?? 14}

    {@const ROWS = [
      { key: 'dem_seats',      label: 'Dem-Lean Districts',   isInt: true  },
      { key: '_rep_seats',     label: 'Rep-Lean Districts',   isInt: true  },
      { key: 'comp_seats_7pt', label: 'Competitive (7-pt)',   isInt: true  },
      { key: 'comp_seats_10pt',label: 'Competitive (10-pt)',  isInt: true  },
      { key: 'rep_safe_seats', label: 'Rep Safe Seats',       isInt: true  },
      { key: 'dem_safe_seats', label: 'Dem Safe Seats',       isInt: true  },
      { key: 'efficiency_gap', label: 'Efficiency Gap',       isInt: false },
      { key: 'mean_median',    label: 'Mean–Median',          isInt: false },
      { key: 'muni_splits',    label: 'City Splits',          isInt: true  },
    ]}

    <div style="margin-top:1.2rem;">
      <div style="font-size:.74rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;
                  color:var(--gray);margin-bottom:.3rem;">
        Map B (proposed) vs Map A (enacted) — metric deltas
      </div>
      <div style="font-size:.7rem;color:var(--gray);margin-bottom:.55rem;font-style:italic;">
        Δ = Map B minus Map A. Positive means Map B is higher on that metric.
      </div>
      <div style="background:var(--card);border:1.5px solid var(--border);border-radius:8px;overflow:hidden;">
        <table style="width:100%;border-collapse:collapse;font-size:.76rem;">
          <thead>
            <tr style="background:var(--light);border-bottom:1.5px solid var(--border);">
              <th style="padding:.4rem .8rem;text-align:left;font-size:.64rem;text-transform:uppercase;letter-spacing:.05em;color:var(--gray);">Metric</th>
              <th style="padding:.4rem .7rem;text-align:right;font-size:.64rem;text-transform:uppercase;letter-spacing:.05em;color:var(--gray);">Map A (enacted)</th>
              <th style="padding:.4rem .7rem;text-align:right;font-size:.64rem;text-transform:uppercase;letter-spacing:.05em;color:var(--gray);">Map B (proposed)</th>
              <th style="padding:.4rem .7rem;text-align:right;font-size:.64rem;text-transform:uppercase;letter-spacing:.05em;color:var(--gray);">Δ (B minus A)</th>
            </tr>
          </thead>
          <tbody>
            {#each ROWS as row, ri}
              {@const enactedRaw = row.key === '_rep_seats'
                ? (grades['dem_seats'] as any)?.enacted != null ? nDistricts - (grades['dem_seats'] as any).enacted : null
                : (grades[row.key] as any)?.enacted ?? null}
              {@const proposedRaw = row.key === '_rep_seats'
                ? scoredPlan.metrics['dem_seats']?.value != null ? nDistricts - scoredPlan.metrics['dem_seats'].value : null
                : scoredPlan.metrics[row.key]?.value ?? null}
              {@const d = (enactedRaw != null && proposedRaw != null) ? proposedRaw - enactedRaw : null}
              {#if enactedRaw != null || proposedRaw != null}
                <tr style="border-bottom:1px solid var(--border);background:{ri % 2 === 0 ? 'var(--card)' : 'var(--light)'};">
                  <td style="padding:.4rem .8rem;font-weight:500;">{row.label}</td>
                  <td style="padding:.4rem .7rem;text-align:right;font-family:monospace;">
                    {enactedRaw == null ? '—' : row.isInt ? Math.round(enactedRaw) : enactedRaw.toFixed(3)}
                  </td>
                  <td style="padding:.4rem .7rem;text-align:right;font-family:monospace;">
                    {proposedRaw == null ? '—' : row.isInt ? Math.round(proposedRaw) : proposedRaw.toFixed(3)}
                  </td>
                  <td style="padding:.4rem .7rem;text-align:right;font-family:monospace;font-weight:700;">
                    {#if d == null}
                      —
                    {:else}
                      {d > 0 ? '+' : ''}{row.isInt ? Math.round(d) : d.toFixed(3)}
                    {/if}
                  </td>
                </tr>
              {/if}
            {/each}
          </tbody>
        </table>
        <div style="padding:.3rem .8rem;font-size:.63rem;color:var(--gray);border-top:1px solid var(--border);background:var(--light);">
          Enacted values from the benchmark scorecard. Proposed values from the uploaded map scored against the same VTD composite.
        </div>
      </div>
    </div>
  {/if}
</div>

<style>
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
