<script lang="ts">
  import type { RunMeta, Summary } from '../types.js';

  interface Props {
    runs: RunMeta[];
    summary: Summary | null;
    selectedRunId: string;
    onRunChange: (id: string) => void;
  }

  let { runs, summary, selectedRunId, onRunChange }: Props = $props();
</script>

<header style="background:var(--blue);color:#fff;padding:.75rem 1.5rem;display:flex;align-items:center;gap:1rem;flex-wrap:wrap;">
  <a href="https://fairdistricts.ga" target="_blank" rel="noopener"
     style="display:flex;align-items:center;gap:.6rem;text-decoration:none;color:inherit;flex-shrink:0">
    <img src="/fdga_logo.svg" alt="Fair Districts GA" style="height:32px;width:auto;" />
    <span style="font-weight:800;font-size:1rem;letter-spacing:-.01em;">Fair Districts GA</span>
  </a>

  <div style="flex:1;min-width:0">
    <div style="font-weight:700;font-size:.95rem;">Redistricting Ensemble Analysis</div>
    {#if summary}
      <div style="font-size:.75rem;opacity:.75;margin-top:.1rem;">
        {summary.state_full} · {summary.plan_type.toUpperCase()} {summary.plan_year}
      </div>
    {/if}
  </div>

  <!-- Run selector -->
  {#if runs.length > 0}
    <div style="display:flex;align-items:center;gap:.5rem;flex-shrink:0">
      <label for="run-select" style="font-size:.75rem;opacity:.8;white-space:nowrap;">Benchmark run:</label>
      <select id="run-select"
              value={selectedRunId}
              onchange={(e) => onRunChange((e.target as HTMLSelectElement).value)}
              style="font-size:.8rem;padding:.3rem .55rem;border-radius:5px;border:none;
                     background:rgba(255,255,255,.15);color:#fff;cursor:pointer;">
        {#each runs as run}
          <option value={run.id} style="background:var(--blue);">
            {run.name} · {run.date} · {run.n_plans.toLocaleString()} plans
          </option>
        {/each}
      </select>
    </div>
  {/if}

  <!-- Compare (future) -->
  <button disabled title="Side-by-side comparison coming soon"
          style="font-size:.78rem;padding:.3rem .8rem;border-radius:5px;border:1px solid rgba(255,255,255,.3);
                 background:transparent;color:rgba(255,255,255,.4);cursor:not-allowed;white-space:nowrap;">
    Compare ↔
  </button>
</header>

<!-- Credits bar -->
<div style="background:#163e78;color:rgba(255,255,255,.65);font-size:.7rem;
            padding:.3rem 1.5rem;display:flex;gap:1.5rem;flex-wrap:wrap;">
  <span>Data &amp; methodology:</span>
  <a href="https://alarm-redist.org" target="_blank" rel="noopener"
     style="color:rgba(255,255,255,.8);text-decoration:none;">ALARM Project</a>
  <a href="https://mggg.org/gerrychain" target="_blank" rel="noopener"
     style="color:rgba(255,255,255,.8);text-decoration:none;">GerryChain / MGGG</a>
  <a href="https://gerrymander.princeton.edu" target="_blank" rel="noopener"
     style="color:rgba(255,255,255,.8);text-decoration:none;">Princeton Gerrymandering Project</a>
</div>
