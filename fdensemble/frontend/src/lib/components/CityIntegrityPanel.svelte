<script lang="ts">
  import { apiGet, STATIC_MODE } from '../api.js';

  interface CityRecord {
    muni_id:     number;
    name:        string;
    pop:         number;
    n_districts: number;
    is_split:    boolean;
    districts:   number[];
  }

  interface IntegrityData {
    run_id:          string;
    threshold:       number;
    total_fittable:  number;
    split_count:     number;
    split_pct:       number;
    split_cities:    CityRecord[];
    intact_cities:   CityRecord[];
  }

  // Georgia ideal district population by chamber (10,711,908 total pop)
  const CHAMBER_THRESHOLD: Record<string, number> = {
    congress: 765_000,   // 10.7M / 14
    senate:   191_000,   // 10.7M / 56
    house:     59_500,   // 10.7M / 180
  };

  interface Props {
    runId:   string;
    source:  string;   // 'alarm' | 'gerrychain'
    chamber: string;   // 'congress' | 'senate' | 'house'
  }
  let { runId, source, chamber }: Props = $props();

  const defaultThreshold = $derived(CHAMBER_THRESHOLD[chamber] ?? 191_000);
  let threshold  = $state(CHAMBER_THRESHOLD[chamber] ?? 191_000);
  let inputValue = $state(String(CHAMBER_THRESHOLD[chamber] ?? 191_000));
  let data: IntegrityData | null = $state(null);
  let loading    = $state(false);
  let error      = $state('');
  let showIntact = $state(false);

  async function load() {
    if (!runId || STATIC_MODE) return;
    loading = true;
    error   = '';
    try {
      data = await apiGet<IntegrityData>(`/city-integrity/${runId}`, { threshold: String(threshold) });
    } catch (e: any) {
      error = e.message ?? 'Failed to load city integrity data';
    } finally {
      loading = false;
    }
  }

  function applyThreshold() {
    const n = parseInt(inputValue, 10);
    if (!isNaN(n) && n > 0) {
      threshold = n;
      load();
    }
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter') applyThreshold();
  }

  function fmtPop(n: number) {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + 'M';
    if (n >= 1_000)     return Math.round(n / 1_000) + 'K';
    return String(n);
  }

  function cleanName(name: string) {
    return name.replace(/ (city|town|CDP|village|borough)$/i, '');
  }

  // Reset threshold and reload when run (chamber) changes
  $effect(() => {
    runId;
    const t = CHAMBER_THRESHOLD[chamber] ?? 191_000;
    threshold  = t;
    inputValue = String(t);
    data = null;
    load();
  });
</script>

<div class="panel">
  <div class="panel-header">
    <div class="panel-title">City Integrity</div>
    <div class="panel-subtitle">
      Incorporated municipalities that were split despite being small enough to fit in one district
    </div>
  </div>

  <!-- Threshold control -->
  <div class="threshold-row">
    <label class="threshold-label" for="ci-threshold">Population threshold</label>
    <div class="threshold-input-group">
      <input
        id="ci-threshold"
        class="threshold-input"
        type="number"
        min="1000"
        max="1000000"
        step="10000"
        bind:value={inputValue}
        onkeydown={handleKeydown}
      />
      <button class="threshold-btn" onclick={applyThreshold}>Apply</button>
    </div>
    <span class="threshold-hint">
      Cities with pop ≤ {threshold.toLocaleString()} could fit in one district
    </span>
  </div>

  {#if loading}
    <div class="loading">Loading…</div>
  {:else if error}
    <div class="error">{error}</div>
  {:else if data}
    <!-- Headline stat -->
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
              {fmtPop(city.pop)} pop
              · split into {city.n_districts} districts
              ({city.districts.join(', ')})
            </div>
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
            <div class="city-card intact">
              <div class="city-name">{cleanName(city.name)}</div>
              <div class="city-meta">{fmtPop(city.pop)} pop · district {city.districts[0]}</div>
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
  }

  .threshold-row {
    display: flex;
    align-items: center;
    gap: .6rem;
    flex-wrap: wrap;
    margin-bottom: .9rem;
    padding: .5rem .7rem;
    background: var(--light);
    border: 1px solid var(--border);
    border-radius: 6px;
  }
  .threshold-label {
    font-size: .7rem;
    font-weight: 600;
    color: var(--gray);
    white-space: nowrap;
  }
  .threshold-input-group { display: flex; gap: 0; }
  .threshold-input {
    width: 110px;
    padding: .22rem .45rem;
    font-size: .78rem;
    border: 1.5px solid var(--border);
    border-right: none;
    border-radius: 4px 0 0 4px;
    background: var(--card);
    color: var(--text);
  }
  .threshold-btn {
    padding: .22rem .55rem;
    font-size: .75rem;
    font-weight: 600;
    border: 1.5px solid var(--blue);
    border-radius: 0 4px 4px 0;
    background: var(--blue);
    color: #fff;
    cursor: pointer;
  }
  .threshold-hint {
    font-size: .68rem;
    color: var(--gray);
    flex: 1;
  }

  .loading { padding: 1rem; color: var(--gray); font-size: .82rem; text-align: center; }
  .error   { padding: .7rem; background: #fef0f0; border: 1px solid #f5a9a9;
              border-radius: 6px; color: var(--red); font-size: .8rem; }

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
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: .4rem;
    margin-bottom: .8rem;
  }
  .intact-grid { margin-top: .4rem; }

  .city-card {
    padding: .4rem .6rem;
    border-radius: 5px;
    border: 1px solid var(--border);
  }
  .city-card.split  { background: #fef5f5; border-color: #f5c6c6; }
  .city-card.intact { background: #f5fef7; border-color: #b8e0bf; }

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
