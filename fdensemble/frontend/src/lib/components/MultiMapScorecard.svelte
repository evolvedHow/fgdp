<script lang="ts">
  import type { Analysis, ScoredPlan, MetricGrade } from '../types.js';

  interface Props {
    analysis: Analysis;
    plans: ScoredPlan[];
    onRemovePlan?: (planId: string) => void;
  }
  let { analysis, plans, onRemovePlan }: Props = $props();

  const gradeColor: Record<string, string> = {
    A: '#27ae60', B: '#2980b9', C: '#d68910', D: '#e67e22', F: '#c0392b',
  };

  interface ScorecardRow {
    key: string;
    label: string;
    isInt: boolean;
    section?: string;
  }

  const ROWS: ScorecardRow[] = [
    { key: 'dem_seats',      label: 'Dem-Lean Seats',      isInt: true,  section: 'Partisan' },
    { key: 'comp_seats_7pt', label: 'Competitive (7-pt)',  isInt: true  },
    { key: 'comp_seats_10pt',label: 'Competitive (10-pt)', isInt: true  },
    { key: 'rep_safe_seats', label: 'Rep Safe Seats',      isInt: true  },
    { key: 'dem_safe_seats', label: 'Dem Safe Seats',      isInt: true  },
    { key: 'partisan_bias',  label: 'Partisan Bias',       isInt: false },
    { key: 'efficiency_gap', label: 'Efficiency Gap',      isInt: false },
    { key: 'mean_median',    label: 'Mean–Median',         isInt: false },
    { key: 'maj_black',      label: 'Majority Black',      isInt: true,  section: 'Minority' },
    { key: 'min_coal',       label: 'Majority Minority',   isInt: true  },
    { key: 'maj_hisp',       label: 'Majority Hispanic',   isInt: true  },
    { key: 'maj_white',      label: 'Majority White',      isInt: true  },
    { key: 'polsby_popper',  label: 'Polsby-Popper',       isInt: false, section: 'Geographic' },
    { key: 'county_splits',  label: 'County Splits',       isInt: true  },
    { key: 'muni_splits',    label: 'City Splits',         isInt: true  },
  ];

  const activeRows = $derived(ROWS.filter(r => r.key in analysis.grades));

  function metricGrade(key: string): MetricGrade | null {
    const g = analysis.grades[key];
    if (!g || !('histogram' in g)) return null;
    return g as MetricGrade;
  }

  function fmt(v: number | null | undefined, isInt: boolean) {
    if (v == null) return '—';
    return isInt ? Math.round(v).toString() : v.toFixed(3);
  }

  function gradeBadge(grade: string) {
    return grade ?? '?';
  }
</script>

<div style="background:var(--card);border:1.5px solid var(--border);border-radius:8px;overflow:hidden;margin-top:1rem;">
  <div style="padding:.6rem 1rem;background:var(--light);border-bottom:1.5px solid var(--border);
              display:flex;align-items:center;justify-content:space-between;gap:.5rem;flex-wrap:wrap;">
    <div style="font-size:.74rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--gray);">
      Multi-Map Scorecard
    </div>
    <div style="font-size:.66rem;color:var(--gray);">
      {plans.length} plan{plans.length !== 1 ? 's' : ''} compared — benchmarks from neutral ensemble
    </div>
  </div>

  <div style="overflow-x:auto;">
    <table style="width:100%;border-collapse:collapse;font-size:.74rem;">
      <thead>
        <tr style="background:var(--light);border-bottom:1.5px solid var(--border);">
          <th style="padding:.4rem .8rem;text-align:left;font-size:.62rem;text-transform:uppercase;
                     letter-spacing:.05em;color:var(--gray);min-width:130px;">Metric</th>
          <th style="padding:.4rem .6rem;text-align:center;font-size:.62rem;text-transform:uppercase;
                     letter-spacing:.05em;color:var(--gray);white-space:nowrap;">
            Benchmark<br><span style="font-weight:400;">90% range (p5–p95)</span>
          </th>
          <th style="padding:.4rem .6rem;text-align:center;font-size:.62rem;text-transform:uppercase;
                     letter-spacing:.05em;color:#27ae60;white-space:nowrap;">
            Benchmark<br><span style="font-weight:400;">Most rep (p25–p75)</span>
          </th>
          <th style="padding:.4rem .6rem;text-align:center;font-size:.62rem;text-transform:uppercase;
                     letter-spacing:.05em;color:var(--gray);white-space:nowrap;border-left:2px solid var(--border);">
            Enacted
          </th>
          {#each plans as plan}
            <th style="padding:.4rem .5rem;text-align:center;font-size:.62rem;letter-spacing:.05em;
                       color:var(--gray);white-space:nowrap;border-left:1px solid var(--border);
                       max-width:120px;overflow:hidden;text-overflow:ellipsis;">
              <div style="display:flex;align-items:center;justify-content:center;gap:.3rem;">
                <span style="overflow:hidden;text-overflow:ellipsis;max-width:90px;" title={plan.label}>{plan.label}</span>
                {#if onRemovePlan}
                  <button
                    onclick={() => onRemovePlan?.(plan.id)}
                    style="flex-shrink:0;background:none;border:none;cursor:pointer;color:var(--gray);
                           font-size:.7rem;padding:.05rem .1rem;line-height:1;"
                    title="Remove from comparison">✕</button>
                {/if}
              </div>
            </th>
          {/each}
        </tr>
      </thead>
      <tbody>
        {#each activeRows as row, ri}
          {@const mg = metricGrade(row.key)}
          {#if row.section}
            <tr>
              <td colspan={4 + plans.length}
                  style="padding:.3rem .8rem;font-size:.6rem;font-weight:700;text-transform:uppercase;
                         letter-spacing:.07em;color:var(--gray);background:#f0f2f5;border-top:1.5px solid var(--border);">
                {row.section}
              </td>
            </tr>
          {/if}
          {#if mg}
            <tr style="border-bottom:1px solid var(--border);background:{ri % 2 === 0 ? 'var(--card)' : 'var(--light)'};">
              <!-- Metric name -->
              <td style="padding:.35rem .8rem;font-weight:500;">{row.label}</td>

              <!-- Benchmark 98% -->
              <td style="padding:.35rem .6rem;text-align:center;font-family:monospace;font-size:.72rem;color:var(--gray);">
                {fmt(mg.histogram.p5, row.isInt)} – {fmt(mg.histogram.p95, row.isInt)}
              </td>

              <!-- Benchmark most representative -->
              <td style="padding:.35rem .6rem;text-align:center;font-family:monospace;font-size:.72rem;color:#27ae60;font-weight:600;">
                {fmt(mg.histogram.p25, row.isInt)} – {fmt(mg.histogram.p75, row.isInt)}
              </td>

              <!-- Enacted -->
              <td style="padding:.35rem .6rem;text-align:center;border-left:2px solid var(--border);">
                <div style="display:flex;align-items:center;justify-content:center;gap:.3rem;">
                  <span style="font-family:monospace;font-size:.78rem;font-weight:600;">
                    {fmt(mg.enacted, row.isInt)}
                  </span>
                  <span style="display:inline-flex;align-items:center;justify-content:center;
                               width:1.3rem;height:1.3rem;border-radius:50%;
                               background:{gradeColor[mg.grade] ?? '#888'};
                               color:#fff;font-weight:800;font-size:.62rem;flex-shrink:0;">
                    {gradeBadge(mg.grade)}
                  </span>
                </div>
              </td>

              <!-- Each plan -->
              {#each plans as plan}
                {@const pm = plan.metrics[row.key]}
                <td style="padding:.35rem .5rem;text-align:center;border-left:1px solid var(--border);">
                  {#if pm}
                    <div style="display:flex;align-items:center;justify-content:center;gap:.3rem;">
                      <span style="font-family:monospace;font-size:.78rem;font-weight:600;">
                        {fmt(pm.value, row.isInt)}
                      </span>
                      <span style="display:inline-flex;align-items:center;justify-content:center;
                                   width:1.3rem;height:1.3rem;border-radius:50%;
                                   background:{gradeColor[pm.grade] ?? '#888'};
                                   color:#fff;font-weight:800;font-size:.62rem;flex-shrink:0;">
                        {gradeBadge(pm.grade)}
                      </span>
                    </div>
                  {:else}
                    <span style="color:var(--gray);">—</span>
                  {/if}
                </td>
              {/each}
            </tr>
          {/if}
        {/each}
      </tbody>
    </table>
  </div>
  <div style="padding:.3rem .8rem;font-size:.62rem;color:var(--gray);border-top:1px solid var(--border);background:var(--light);">
    Benchmarks from the neutral ensemble distribution. Grade reflects percentile rank vs. {analysis.summary?.n_plans?.toLocaleString() ?? ''} neutral maps.
  </div>
</div>
