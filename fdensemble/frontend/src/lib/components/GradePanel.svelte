<script lang="ts">
  import type { Grades, CompositeGrade } from '../types.js';

  interface Props { grades: Grades; }
  let { grades }: Props = $props();

  const overall    = $derived(grades._overall    as CompositeGrade | undefined);
  const partisan   = $derived(grades._partisan_fairness as CompositeGrade | undefined);
  const geographic = $derived(grades._geographic as CompositeGrade | undefined);
  const compSeats  = $derived((grades as any).comp_seats);

  const gradeColor: Record<string, string> = {
    A: '#27ae60', B: '#2980b9', C: '#d68910', D: '#e67e22', F: '#c0392b',
  };
  const gradeDesc: Record<string, string> = {
    A: 'Excellent', B: 'Good', C: 'Average', D: 'Poor', F: 'Failing',
  };

  function badge(grade: string, size: 'lg' | 'sm' = 'sm') {
    const bg = gradeColor[grade] ?? '#888';
    const s  = size === 'lg' ? '2.8rem' : '1.6rem';
    const fs = size === 'lg' ? '1.4rem' : '.85rem';
    return `display:inline-flex;align-items:center;justify-content:center;
            width:${s};height:${s};border-radius:50%;
            background:${bg};color:#fff;font-weight:800;font-size:${fs};
            flex-shrink:0;`;
  }
</script>

<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:.8rem;margin-bottom:1rem;">
  <!-- Overall -->
  {#if overall}
  <div style="background:var(--card);border-radius:10px;padding:1rem 1.2rem;
              box-shadow:var(--shadow);border:2.5px solid {gradeColor[overall.grade] ?? '#ccc'};
              display:flex;flex-direction:column;gap:.4rem;">
    <div style="font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--gray);">Overall</div>
    <div style="display:flex;align-items:center;gap:.7rem;">
      <span style={badge(overall.grade, 'lg')}>{overall.grade}</span>
      <div>
        <div style="font-weight:700;font-size:.95rem;">{gradeDesc[overall.grade] ?? ''}</div>
        <div style="font-size:.72rem;color:var(--gray);">{overall.description}</div>
      </div>
    </div>
  </div>
  {/if}

  <!-- Partisan Fairness -->
  {#if partisan}
  <div style="background:var(--card);border-radius:10px;padding:1rem 1.2rem;box-shadow:var(--shadow);border:1.5px solid var(--border);">
    <div style="font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--gray);margin-bottom:.4rem;">Partisan Fairness</div>
    <div style="display:flex;align-items:center;gap:.6rem;margin-bottom:.5rem;">
      <span style={badge(partisan.grade, 'sm')}>{partisan.grade}</span>
      <span style="font-size:.82rem;font-weight:600;">{gradeDesc[partisan.grade] ?? ''}</span>
    </div>
    <div style="display:flex;gap:.4rem;flex-wrap:wrap;">
      <span style="font-size:.68rem;padding:.15rem .45rem;border-radius:10px;font-weight:700;
                   background:{partisan.ensemble_pass ? '#e6f7ee' : '#fef0f0'};
                   color:{partisan.ensemble_pass ? 'var(--green)' : 'var(--red)'};">
        Ensemble: {partisan.ensemble_pass ? '✓ Pass' : '✗ Fail'}
      </span>
      <span style="font-size:.68rem;padding:.15rem .45rem;border-radius:10px;font-weight:700;
                   background:{partisan.normative_pass ? '#e6f7ee' : '#fef0f0'};
                   color:{partisan.normative_pass ? 'var(--green)' : 'var(--red)'};">
        Normative: {partisan.normative_pass ? '✓ Pass' : '✗ Fail'}
      </span>
    </div>
    <div style="font-size:.7rem;color:var(--gray);margin-top:.4rem;line-height:1.4;">Princeton dual test: ensemble distribution + cube-law symmetry.</div>
  </div>
  {/if}

  <!-- Geographic -->
  {#if geographic}
  <div style="background:var(--card);border-radius:10px;padding:1rem 1.2rem;box-shadow:var(--shadow);border:1.5px solid var(--border);">
    <div style="font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--gray);margin-bottom:.4rem;">Geographic</div>
    <div style="display:flex;align-items:center;gap:.6rem;margin-bottom:.3rem;">
      <span style={badge(geographic.grade, 'sm')}>{geographic.grade}</span>
      <span style="font-size:.82rem;font-weight:600;">{gradeDesc[geographic.grade] ?? ''}</span>
    </div>
    <div style="font-size:.7rem;color:var(--gray);line-height:1.4;">{geographic.description}</div>
  </div>
  {/if}

  <!-- Competitiveness -->
  {#if compSeats}
  <div style="background:var(--card);border-radius:10px;padding:1rem 1.2rem;box-shadow:var(--shadow);border:1.5px solid var(--border);">
    <div style="font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--gray);margin-bottom:.4rem;">Competitiveness</div>
    <div style="display:flex;align-items:center;gap:.6rem;margin-bottom:.3rem;">
      <span style={badge(compSeats.grade, 'sm')}>{compSeats.grade}</span>
      <span style="font-size:.82rem;font-weight:600;">{compSeats.enacted} competitive seats</span>
    </div>
    <div style="font-size:.7rem;color:var(--gray);">Percentile: {compSeats.pct_rank}th</div>
    <div style="font-size:.7rem;color:var(--gray);margin-top:.2rem;line-height:1.4;">{compSeats.description}</div>
  </div>
  {/if}
</div>
