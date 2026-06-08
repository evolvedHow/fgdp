<script lang="ts">
  import type { Analysis, Grades, MetricGrade, CompositeGrade, ScoredPlan } from '../types.js';

  interface BenchmarkSide {
    label: string;          // e.g. "GerryChain ReCom · 9,501 plans"
    grades: Grades | null;
    nPlans?: number;
    algorithm?: string;
  }

  interface Props {
    primary: BenchmarkSide;
    companion: BenchmarkSide;
    /** If provided, show scored-plan metrics instead of benchmark enacted grades */
    primaryPlan?: ScoredPlan | null;
    companionPlan?: ScoredPlan | null;
    scoringMode?: boolean;
  }

  let { primary, companion, primaryPlan, companionPlan, scoringMode = false }: Props = $props();

  const GRADE_COLOR: Record<string, string> = {
    'A': '#27ae60', 'B': '#2980b9', 'C': '#d68910', 'F': '#c0392b',
  };

  function gradeColor(g: string | undefined) {
    return GRADE_COLOR[g ?? ''] ?? '#888';
  }

  function pct(v: number | null | undefined) {
    if (v == null) return '—';
    return `${Math.round(v)}th`;
  }

  function fmt(v: number | null | undefined, isCount = false) {
    if (v == null) return '—';
    return isCount ? `${Math.round(v)}` : v.toFixed(3);
  }

  // Extract a metric from grades (handles both MetricGrade and election metrics)
  function getMetric(grades: Grades | null, key: string): MetricGrade | null {
    if (!grades) return null;
    const g = grades[key];
    return (g && 'histogram' in g) ? g as MetricGrade : null;
  }

  function getComposite(grades: Grades | null, key: string): CompositeGrade | null {
    if (!grades) return null;
    const g = grades[key];
    return (g && !('histogram' in g)) ? g as CompositeGrade : null;
  }

  // For scoring mode: extract from ScoredPlan.metrics
  function getPlanMetric(plan: ScoredPlan | null | undefined, key: string) {
    return plan?.metrics?.[key] ?? null;
  }

  interface Row {
    key: string;
    label: string;
    isComposite?: boolean;
    isCount?: boolean;
  }

  const ROWS: Row[] = scoringMode
    ? [
        { key: '_overall',           label: 'Overall',             isComposite: true },
        { key: '_partisan_fairness', label: 'Partisan Fairness',   isComposite: true },
        { key: 'dem_seats',          label: 'Dem Seats',           isCount: true },
        { key: 'efficiency_gap',     label: 'Efficiency Gap' },
        { key: 'mean_median',        label: 'Mean–Median' },
        { key: 'comp_seats_7pt',     label: 'Competitive (7-pt)',  isCount: true },
        { key: 'muni_splits',        label: 'Split Cities',        isCount: true },
      ]
    : [
        { key: '_overall',           label: 'Overall',             isComposite: true },
        { key: '_partisan_fairness', label: 'Partisan Fairness',   isComposite: true },
        { key: 'dem_seats',          label: 'Dem Seats',           isCount: true },
        { key: 'efficiency_gap',     label: 'Efficiency Gap' },
        { key: 'mean_median',        label: 'Mean–Median' },
        { key: 'comp_seats_7pt',     label: 'Competitive (7-pt)',  isCount: true },
        { key: 'muni_splits',        label: 'Split Cities',        isCount: true },
        { key: 'maj_black',          label: 'Majority-Black Districts', isCount: true },
        { key: 'min_coal',           label: 'Minority Coalition Districts', isCount: true },
      ];
</script>

<div style="background:var(--card);border:1.5px solid var(--border);border-radius:8px;overflow:hidden;margin-bottom:.9rem;">
  <table style="width:100%;border-collapse:collapse;font-size:.76rem;">
    <thead>
      <tr style="background:var(--light);border-bottom:1.5px solid var(--border);">
        <th style="padding:.5rem .8rem;text-align:left;font-size:.65rem;text-transform:uppercase;
                   letter-spacing:.05em;color:var(--gray);width:34%;">Metric</th>
        <th style="padding:.5rem .8rem;text-align:center;font-size:.65rem;text-transform:uppercase;
                   letter-spacing:.05em;color:var(--gray);width:33%;border-left:1px solid var(--border);">
          {primary.label}
        </th>
        <th style="padding:.5rem .8rem;text-align:center;font-size:.65rem;text-transform:uppercase;
                   letter-spacing:.05em;color:var(--gray);width:33%;border-left:1px solid var(--border);">
          {companion.label}
        </th>
      </tr>
    </thead>
    <tbody>
      {#each ROWS as row, i}
        {@const rowBg = i % 2 === 0 ? 'var(--card)' : 'var(--light)'}

        {#if row.isComposite}
          {@const pg = getComposite(primary.grades, row.key)}
          {@const cg = getComposite(companion.grades, row.key)}
          <tr style="border-bottom:1px solid var(--border);background:{rowBg};">
            <td style="padding:.45rem .8rem;font-weight:600;color:#333;">{row.label}</td>

            <!-- primary composite -->
            <td style="padding:.45rem .8rem;text-align:center;border-left:1px solid var(--border);">
              {#if pg}
                <span style="display:inline-flex;align-items:center;justify-content:center;
                             width:1.5rem;height:1.5rem;border-radius:50%;font-weight:800;
                             font-size:.72rem;color:#fff;background:{gradeColor(pg.grade)};">
                  {pg.grade}
                </span>
                {#if row.key === '_partisan_fairness' && 'ensemble_pass' in pg}
                  <span style="font-size:.65rem;color:var(--gray);margin-left:.3rem;">
                    {pg.ensemble_pass ? '✓ ens' : '✗ ens'}
                  </span>
                {/if}
              {:else}
                <span style="color:var(--gray);">—</span>
              {/if}
            </td>

            <!-- companion composite -->
            <td style="padding:.45rem .8rem;text-align:center;border-left:1px solid var(--border);">
              {#if cg}
                <span style="display:inline-flex;align-items:center;justify-content:center;
                             width:1.5rem;height:1.5rem;border-radius:50%;font-weight:800;
                             font-size:.72rem;color:#fff;background:{gradeColor(cg.grade)};">
                  {cg.grade}
                </span>
                {#if row.key === '_partisan_fairness' && 'ensemble_pass' in cg}
                  <span style="font-size:.65rem;color:var(--gray);margin-left:.3rem;">
                    {cg.ensemble_pass ? '✓ ens' : '✗ ens'}
                  </span>
                {/if}
              {:else}
                <span style="color:var(--gray);">—</span>
              {/if}
            </td>
          </tr>

        {:else if scoringMode}
          {@const pm = getPlanMetric(primaryPlan, row.key)}
          {@const cm = getPlanMetric(companionPlan, row.key)}
          <tr style="border-bottom:1px solid var(--border);background:{rowBg};">
            <td style="padding:.45rem .8rem;color:#333;">{row.label}</td>

            <td style="padding:.45rem .8rem;text-align:center;border-left:1px solid var(--border);">
              {#if pm}
                <span style="display:inline-flex;align-items:center;justify-content:center;
                             width:1.3rem;height:1.3rem;border-radius:50%;font-weight:800;
                             font-size:.65rem;color:#fff;background:{gradeColor(pm.grade)};margin-right:.3rem;">
                  {pm.grade}
                </span>
                <span style="font-family:monospace;font-size:.73rem;">
                  {fmt(pm.value, row.isCount)}
                </span>
                <span style="font-size:.65rem;color:var(--gray);margin-left:.2rem;">
                  · {pct(pm.pct_rank)}
                </span>
              {:else}
                <span style="color:var(--gray);">—</span>
              {/if}
            </td>

            <td style="padding:.45rem .8rem;text-align:center;border-left:1px solid var(--border);">
              {#if cm}
                <span style="display:inline-flex;align-items:center;justify-content:center;
                             width:1.3rem;height:1.3rem;border-radius:50%;font-weight:800;
                             font-size:.65rem;color:#fff;background:{gradeColor(cm.grade)};margin-right:.3rem;">
                  {cm.grade}
                </span>
                <span style="font-family:monospace;font-size:.73rem;">
                  {fmt(cm.value, row.isCount)}
                </span>
                <span style="font-size:.65rem;color:var(--gray);margin-left:.2rem;">
                  · {pct(cm.pct_rank)}
                </span>
              {:else}
                <span style="color:var(--gray);">—</span>
              {/if}
            </td>
          </tr>

        {:else}
          {@const pm = getMetric(primary.grades, row.key)}
          {@const cm = getMetric(companion.grades, row.key)}
          <tr style="border-bottom:1px solid var(--border);background:{rowBg};">
            <td style="padding:.45rem .8rem;color:#333;">{row.label}</td>

            <td style="padding:.45rem .8rem;text-align:center;border-left:1px solid var(--border);">
              {#if pm}
                <span style="display:inline-flex;align-items:center;justify-content:center;
                             width:1.3rem;height:1.3rem;border-radius:50%;font-weight:800;
                             font-size:.65rem;color:#fff;background:{gradeColor(pm.grade)};margin-right:.3rem;">
                  {pm.grade}
                </span>
                <span style="font-family:monospace;font-size:.73rem;">
                  {fmt(pm.enacted, row.isCount)}
                </span>
                <span style="font-size:.65rem;color:var(--gray);margin-left:.2rem;">
                  · {pct(pm.pct_rank)}
                </span>
              {:else}
                <span style="color:var(--gray);">—</span>
              {/if}
            </td>

            <td style="padding:.45rem .8rem;text-align:center;border-left:1px solid var(--border);">
              {#if cm}
                <span style="display:inline-flex;align-items:center;justify-content:center;
                             width:1.3rem;height:1.3rem;border-radius:50%;font-weight:800;
                             font-size:.65rem;color:#fff;background:{gradeColor(cm.grade)};margin-right:.3rem;">
                  {cm.grade}
                </span>
                <span style="font-family:monospace;font-size:.73rem;">
                  {fmt(cm.enacted, row.isCount)}
                </span>
                <span style="font-size:.65rem;color:var(--gray);margin-left:.2rem;">
                  · {pct(cm.pct_rank)}
                </span>
              {:else}
                <span style="color:var(--gray);">—</span>
              {/if}
            </td>
          </tr>
        {/if}
      {/each}
    </tbody>
  </table>
  <div style="padding:.35rem .8rem;font-size:.65rem;color:var(--gray);border-top:1px solid var(--border);background:var(--light);">
    Grade · enacted value · percentile rank within neutral ensemble.  — = not available for this benchmark.
  </div>
</div>
