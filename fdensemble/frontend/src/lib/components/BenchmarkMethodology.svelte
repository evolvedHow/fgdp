<script lang="ts">
  import type { RunMeta, ElectionOption } from '../types.js';

  interface Props {
    run: RunMeta;
    nVTDs?: number;
  }
  let { run, nVTDs = 2698 }: Props = $props();

  let open = $state(false);

  const elections: ElectionOption[] = $derived(run.elections ?? []);
  const nElections = $derived(elections.length > 0 ? elections.length : 7);
  const nDraws   = $derived(run.n_plans.toLocaleString());
  const chamber  = $derived((run.chamber ?? run.id).replace(/_/g, ' '));
  const isAlarm  = $derived(run.source === 'alarm');
  // Use statewide_dem_2pv from the run object (fraction → percent); fall back to null to hide row.
  const demSharePct = $derived(
    run.statewide_dem_2pv != null ? (run.statewide_dem_2pv * 100).toFixed(1) : null
  );
</script>

<div style="background:var(--card);border:1.5px solid var(--border);border-radius:8px;margin-bottom:.8rem;overflow:hidden;">
  <button
    onclick={() => open = !open}
    style="width:100%;text-align:left;padding:.65rem 1rem;background:var(--light);
           border:none;cursor:pointer;display:flex;align-items:center;justify-content:space-between;
           font-size:.78rem;font-weight:700;color:var(--blue);gap:.5rem;"
  >
    <span style="display:flex;align-items:center;gap:.5rem;">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
      </svg>
      How This Benchmark Was Built
    </span>
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"
         style="transform: {open ? 'rotate(180deg)' : 'none'}; transition: transform .2s;">
      <polyline points="6 9 12 15 18 9"/>
    </svg>
  </button>

  {#if open}
  <div style="padding:.9rem 1rem 1rem;font-size:.76rem;line-height:1.65;color:#333;
              display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:.8rem 1.4rem;">

    <!-- ── Algorithm description ── -->
    {#if isAlarm}
      <div>
        <div style="font-weight:700;font-size:.7rem;text-transform:uppercase;letter-spacing:.05em;
                    color:var(--blue);margin-bottom:.35rem;">What ALARM SMC Does</div>
        <p style="margin:0 0 .5rem;">
          The <b>ALARM Project</b> (Harvard, Kenny &amp; McCartan et al.) uses
          <b>Sequential Monte Carlo (SMC)</b> to generate redistricting plans.
          Unlike GerryChain's Markov chain approach — which produces plans sequentially
          by perturbing the previous plan — SMC draws each plan <em>independently</em>
          from the full target distribution using two completely separate chains.
          This independence eliminates burn-in bias and provides unbiased samples
          with formal statistical guarantees.
        </p>
        <p style="margin:0;">
          The result is a neutral baseline of what Georgia's congressional map would
          look like under geography-driven, non-partisan redistricting — against which
          the enacted map is compared. Plans outside the 5th–95th percentile range
          are statistical outliers unlikely to arise from a fair process.
        </p>
        <p style="margin:.5rem 0 0;font-size:.71rem;color:var(--gray);">
          Source: ALARM Project via Harvard Dataverse
          (<a href="https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/SLCD3E"
              target="_blank" rel="noopener" style="color:var(--blue);">doi:10.7910/DVN/SLCD3E</a>).
          Original ensemble: 2 independent chains × 10,000 simulations, thinned to 5,000 plans.
        </p>
      </div>
    {:else}
      <div>
        <div style="font-weight:700;font-size:.7rem;text-transform:uppercase;letter-spacing:.05em;
                    color:var(--blue);margin-bottom:.35rem;">What GerryChain Does</div>
        <p style="margin:0;">
          GerryChain uses a Markov chain Monte Carlo (MCMC) random walk to generate thousands of
          redistricting plans that satisfy all legal constraints — equal population, contiguity,
          compactness, and Voting Rights Act requirements — but are drawn <em>without any partisan intent</em>.
          This creates a neutral baseline: the range of outcomes you'd see from a fair, geography-driven process.
          Plans that fall outside this range are statistical outliers — unlikely to arise from neutral mapmaking.
        </p>
      </div>
    {/if}

    <!-- ── Election composite ── -->
    <div>
      <div style="font-weight:700;font-size:.7rem;text-transform:uppercase;letter-spacing:.05em;
                  color:var(--blue);margin-bottom:.35rem;">Composite Election Benchmark</div>
      <p style="margin:0 0 .4rem;">
        Rather than relying on a single election, this benchmark averages {nElections} elections across
        multiple electoral cycles, giving a stable picture of Georgia's underlying partisan geography:
      </p>
      {#if elections.length > 0}
        <ul style="margin:.2rem 0 0;padding-left:1.2rem;line-height:1.8;">
          {#each elections as e}
            <li><b>{e.year} {e.office}</b></li>
          {/each}
        </ul>
      {:else}
        <ul style="margin:.2rem 0 0;padding-left:1.2rem;line-height:1.8;">
          <li><b>2018 Governor</b> (Kemp vs. Abrams)</li>
          <li><b>2020 President</b> (Trump vs. Biden)</li>
          <li><b>2021 Senate Runoff</b> (Warnock vs. Loeffler)</li>
          <li><b>2022 Governor</b> (Kemp vs. Abrams)</li>
          <li><b>2022 Senate</b> (Walker vs. Warnock general)</li>
          <li><b>2022 Senate Runoff</b> (Walker vs. Warnock Dec. 6)</li>
          <li><b>2024 President</b> (Trump vs. Harris)</li>
        </ul>
      {/if}
      <p style="margin:.4rem 0 0;font-size:.72rem;color:var(--gray);">
        All shares are <em>two-party</em> (third-party candidates excluded from denominator),
        so the baseline captures the structural Dem/Rep balance independent of minor-party vote splitting.
      </p>
      {#if isAlarm}
        <p style="margin:.4rem 0 0;font-size:.72rem;color:var(--gray);">
          <em>Note:</em> The original ALARM ensemble used a 2016–2020 election composite.
          It has been re-scored here with the same 2018–2024 composite used by the GerryChain
          benchmark, so both algorithms are compared on an identical electoral baseline.
        </p>
      {/if}
    </div>

    <!-- ── Key numbers ── -->
    <div>
      <div style="font-weight:700;font-size:.7rem;text-transform:uppercase;letter-spacing:.05em;
                  color:var(--blue);margin-bottom:.35rem;">Key Numbers</div>
      <dl style="margin:0;display:grid;grid-template-columns:auto 1fr;gap:.2rem .7rem;align-items:baseline;">
        <dt style="font-weight:700;white-space:nowrap;">{nDraws}</dt>
        <dd style="margin:0;">neutral maps generated</dd>
        {#if isAlarm}
          <dt style="font-weight:700;">2 chains</dt>
          <dd style="margin:0;">independent SMC chains × 10,000 simulations, thinned to 5,000</dd>
        {/if}
        <dt style="font-weight:700;">{nVTDs.toLocaleString()}</dt>
        <dd style="margin:0;">Georgia VTDs (2020 Census)</dd>
        {#if demSharePct !== null}
          <dt style="font-weight:700;">{demSharePct}%</dt>
          <dd style="margin:0;">statewide composite Dem 2-party vote share</dd>
        {/if}
        <dt style="font-weight:700;">{nElections} elections</dt>
        <dd style="margin:0;">averaged into the composite partisan score</dd>
        {#if isAlarm}
          <dt style="font-weight:700;">VAP</dt>
          <dd style="margin:0;">minority metrics use 2020 Census Voting Age Population
            (GerryChain uses 2024 CVAP — citizens only; both are valid VRA measures)</dd>
        {:else}
          <dt style="font-weight:700;">CVAP</dt>
          <dd style="margin:0;">minority metrics use 2024 ACS 5-year Citizen Voting Age Population
            (citizens only — the legally relevant measure for Voting Rights Act analysis)</dd>
        {/if}
      </dl>
      <p style="margin:.6rem 0 0;font-size:.72rem;color:var(--gray);">
        The Princeton grading thresholds treat plans below the 5th percentile as failing
        (statistical outliers) and above the 95th percentile as excellent. Plans between the
        5th and 95th are within the normal range for neutral mapmaking.
      </p>
    </div>

  </div>
  {/if}
</div>
