<script lang="ts">
  import type { CityIntegrityData } from '../types.js';

  const CHAMBER_THRESHOLD: Record<string, number> = {
    congress: 765_000,
    senate:   191_000,
    house:     59_500,
  };

  const CHAMBER_LABEL: Record<string, string> = {
    congress: 'U.S. Congressional district',
    senate:   'GA Senate district',
    house:    'GA House district',
  };

  interface Props {
    data:    CityIntegrityData | null;
    chamber: string;
  }
  let { data, chamber }: Props = $props();

  const threshold = $derived(CHAMBER_THRESHOLD[chamber] ?? 191_000);

  let showIntact = $state(false);

  // district → split city names that span it
  const splitsByDistrict = $derived.by(() => {
    const m = new Map<number, string[]>();
    if (!data) return m;
    for (const c of data.split_cities) {
      for (const d of c.districts) {
        const existing = m.get(d) ?? [];
        existing.push(cleanName(c.name));
        m.set(d, existing);
      }
    }
    return m;
  });

  function fmtPop(n: number) {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + 'M';
    if (n >= 1_000)     return Math.round(n / 1_000) + 'K';
    return String(n);
  }

  function cleanName(name: string) {
    return name.replace(/ (city|town|CDP|village|borough)$/i, '');
  }
</script>

<div class="panel">
  <div class="panel-header">
    <div class="panel-title">City Integrity</div>
    <div class="panel-subtitle">
      Incorporated municipalities with population ≤ {threshold.toLocaleString()}
      <span class="threshold-badge">≤ 1 {CHAMBER_LABEL[chamber] ?? 'district'}</span>
      — could fit entirely within a single district
    </div>
  </div>

  {#if !data}
    <div class="loading">Loading…</div>
  {:else}
    <div class="headline">
      {#if data.split_count === 0}
        <span class="stat-good">All {data.total_fittable} fittable cities kept intact</span>
      {:else}
        <span class="stat-bad">{data.split_count}</span>
        <span class="stat-of"> of {data.total_fittable} fittable cities</span>
        <span class="stat-pct"> ({data.split_pct}%)</span>
        <span class="stat-label"> were split unnecessarily</span>
      {/if}
    </div>

    {#if data.split_cities.length > 0}
      <div class="section-label">Split cities</div>
      <div class="city-grid">
        {#each data.split_cities as city}
          <div class="city-card split">
            <div class="city-name">{cleanName(city.name)}</div>
            <div class="city-meta">
              {fmtPop(city.pop)} total pop
              · split into {city.n_districts} districts
              ({city.districts.join(', ')})
            </div>
            {#if city.district_pops}
              <div class="city-dp">
                {#each city.districts as d}
                  <span class="dp-chip">Dist.{d}: {fmtPop(city.district_pops[String(d)] ?? 0)}</span>
                {/each}
              </div>
            {/if}
          </div>
        {/each}
      </div>
    {/if}

    {#if data.intact_cities.length > 0}
      <button class="toggle-intact" onclick={() => showIntact = !showIntact}>
        {showIntact ? '▲' : '▶'} {data.intact_cities.length} intact cities
      </button>
      {#if showIntact}
        <div class="city-grid intact-grid">
          {#each data.intact_cities as city}
            {@const cohabitants = splitsByDistrict.get(city.districts[0]) ?? []}
            <div class="city-card intact">
              <div class="card-body">
                <div class="city-name">{cleanName(city.name)}</div>
                <div class="city-meta">{fmtPop(city.pop)} pop · district {city.districts[0]}</div>
              </div>
              {#if cohabitants.length > 0}
                <div class="cohabitants">
                  {#each cohabitants as sc}
                    <div class="cohabitant-name">{sc}</div>
                  {/each}
                </div>
              {/if}
            </div>
          {/each}
        </div>
      {/if}
    {/if}
  {/if}
</div>

<style>
  .panel {
    background: var(--card);
    border: 1.5px solid var(--border);
    border-radius: 8px;
    padding: 1rem 1.2rem;
    margin-bottom: 1.2rem;
  }
  .panel-header { margin-bottom: .75rem; }
  .panel-title {
    font-size: .74rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .06em;
    color: var(--gray);
  }
  .panel-subtitle {
    font-size: .72rem;
    color: var(--gray);
    margin-top: .15rem;
    display: flex;
    align-items: center;
    gap: .4rem;
    flex-wrap: wrap;
  }
  .threshold-badge {
    display: inline-block;
    background: var(--light);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: .05rem .35rem;
    font-size: .66rem;
    font-weight: 600;
    color: var(--blue);
    white-space: nowrap;
  }

  .loading { padding: 1rem; color: var(--gray); font-size: .82rem; text-align: center; }

  .headline {
    font-size: .9rem;
    margin-bottom: .8rem;
    line-height: 1.4;
  }
  .stat-bad   { font-size: 1.5rem; font-weight: 800; color: var(--red); }
  .stat-good  { font-size: .9rem; font-weight: 700; color: var(--green, #27ae60); }
  .stat-of    { font-size: .85rem; color: #333; }
  .stat-pct   { font-size: .85rem; font-weight: 700; color: var(--red); }
  .stat-label { font-size: .85rem; color: #333; }

  .section-label {
    font-size: .65rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .05em;
    color: var(--gray);
    margin-bottom: .4rem;
  }

  .city-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
    gap: .4rem;
    margin-bottom: .8rem;
  }
  .intact-grid { margin-top: .4rem; }

  .city-card {
    padding: .4rem .6rem;
    border-radius: 5px;
    border: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    gap: .3rem;
  }
  .city-card.split  { background: #fef5f5; border-color: #f5c6c6; }
  .city-card.intact { background: #f5fef7; border-color: #b8e0bf; }

  .card-body { flex: 1; min-width: 0; }

  .city-name {
    font-size: .76rem;
    font-weight: 700;
    color: #222;
  }
  .city-meta {
    font-size: .66rem;
    color: var(--gray);
    margin-top: .1rem;
    line-height: 1.3;
  }

  .cohabitants {
    flex-shrink: 0;
    text-align: right;
  }
  .cohabitant-name {
    font-size: .6rem;
    color: #c0392b;
    font-weight: 600;
    line-height: 1.35;
    white-space: nowrap;
  }
  .city-dp {
    display: flex;
    flex-wrap: wrap;
    gap: .2rem;
    margin-top: .25rem;
  }
  .dp-chip {
    font-size: .62rem;
    background: #fde8e8;
    border: 1px solid #f5c6c6;
    border-radius: 3px;
    padding: .05rem .3rem;
    color: #c0392b;
    font-weight: 600;
  }

  .toggle-intact {
    background: none;
    border: none;
    font-size: .72rem;
    color: var(--blue);
    cursor: pointer;
    padding: 0;
    margin-bottom: .3rem;
  }
</style>
