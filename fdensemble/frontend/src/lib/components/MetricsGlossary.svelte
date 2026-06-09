<script lang="ts">
  /**
   * MetricsGlossary.svelte
   *
   * Collapsible reference panel listing every metric in the benchmark scorecard with:
   *   - Category badge, label, grade badge, percentile rank
   *   - Formula in monospace
   *   - Technical detail, data source, grading method
   *   - Enacted value and percentile
   *   - Configurable threshold values (if analysis.config is present)
   *
   * Props:
   *   analysis — the full /api/analysis response object
   */

  interface Props {
    analysis: any; // full /api/analysis response
  }
  let { analysis }: Props = $props();

  // ── Collapse state ────────────────────────────────────────────────────────────
  let open = $state(false);

  // ── Category filter ───────────────────────────────────────────────────────────
  type CategoryKey = 'all' | 'partisan' | 'competitive' | 'geographic' | 'minority';
  let activeFilter: CategoryKey = $state('all');

  const CATEGORY_ORDER: CategoryKey[] = ['all', 'partisan', 'competitive', 'geographic', 'minority'];

  const CATEGORY_LABELS: Record<string, string> = {
    partisan:    'Partisan Fairness',
    competitive: 'Competitiveness',
    geographic:  'Geographic Integrity',
    minority:    'Minority Representation',
  };

  const CATEGORY_COLORS: Record<string, string> = {
    partisan:    '#3D77BB',
    competitive: '#17a589',
    geographic:  '#7f8c8d',
    minority:    '#8e44ad',
  };

  // ── Grade colour lookup ───────────────────────────────────────────────────────
  const GRADE_COLORS: Record<string, string> = {
    A: '#27ae60', B: '#2980b9', C: '#d68910', D: '#e67e22', F: '#c0392b',
  };

  // ── Grading-method plain-English description ──────────────────────────────────
  const GRADING_DETAIL: Record<string, string> = {
    'seats (directional, one-sided)':
      'A ≥ 50th pct · B ≥ 20th · C ≥ 5th · F < 5th  (penalises too few only)',
    'symmetric (both tails bad)':
      'A = pct 40–60 · B = 20–80 · C = 5–95 · F = outside 5–95',
    'symmetric (both tails notable)':
      'A = pct 40–60 · B = 20–80 · C = 5–95 · F = outside 5–95',
    'competitive (higher = more competitive)':
      'A ≥ 95th pct · B ≥ 64th · C ≥ 5th · F < 5th',
    'directional (lower = fewer splits)':
      'A = inverted rank ≥ 95th · B ≥ 64th · C ≥ 5th · F < 5th',
    'directional (higher = more compact)':
      'A ≥ 95th pct · B ≥ 64th · C ≥ 5th · F < 5th',
    'directional (higher = more influence districts)':
      'A ≥ 95th pct · B ≥ 64th · C ≥ 5th · F < 5th',
    'normative test (Princeton cube-law)':
      'Pass/fail test — not shown as A/B/C/F',
  };

  // ── Config key human-readable labels ─────────────────────────────────────────
  const CONFIG_KEY_LABELS: Record<string, string> = {
    competitive_margin:      'Competitive margin (half-width from 50%)',
    competitive_threshold:   'Competitive margin (±pp from 50%)',
    majority_threshold:      'Majority threshold',
    bvap_majority_threshold: 'Black majority threshold (BVAP, 2020 Census)',
    influence_min_threshold: 'Minority influence lower bound',
    influence_max_threshold: 'Minority influence upper bound (= majority threshold)',
  };

  // ── Category sort order for rendering ────────────────────────────────────────
  const CATEGORY_SORT: Record<string, number> = {
    partisan: 0, competitive: 1, geographic: 2, minority: 3,
  };

  // ── Derived: collect and sort all scoreable metrics ───────────────────────────
  // Filters out underscore-prefixed composite keys (_overall, _partisan_fairness, etc.)
  // and any grade entries that don't have a histogram (composite grades only have label/grade).
  interface MetricEntry {
    key:      string;
    label:    string;
    headline: string;
    category: string;
    description: string;
    grade:    string;
    enacted:  number | null;
    pct_rank: number | null;
    formula_info: {
      formula:        string;
      detail:         string;
      data_source:    string;
      config_keys:    string[];
      grading_method?: string;
    } | null;
  }

  const metrics: MetricEntry[] = $derived.by(() => {
    if (!analysis?.grades) return [];
    return (
      Object.entries(analysis.grades as Record<string, any>)
        .filter(([k, v]) =>
          !k.startsWith('_') &&
          v &&
          typeof v === 'object' &&
          'histogram' in v   // only full metric grade entries
        )
        .map(([key, v]) => ({
          key,
          label:          v.label       ?? key,
          headline:       v.headline    ?? '',
          category:       v.category    ?? 'other',
          description:    v.description ?? '',
          grade:          v.grade       ?? '—',
          enacted:        v.enacted     ?? null,
          pct_rank:       v.pct_rank    ?? null,
          formula_info:   v.formula_info ?? null,
        } as MetricEntry))
        .sort((a, b) => {
          const ca = CATEGORY_SORT[a.category] ?? 99;
          const cb = CATEGORY_SORT[b.category] ?? 99;
          return ca !== cb ? ca - cb : a.label.localeCompare(b.label);
        })
    );
  });

  // ── Filtered metrics (respects activeFilter) ─────────────────────────────────
  const visibleMetrics: MetricEntry[] = $derived(
    activeFilter === 'all'
      ? metrics
      : metrics.filter(m => m.category === activeFilter)
  );

  // ── Unique categories present in the data (for pill buttons) ─────────────────
  const presentCategories: Set<string> = $derived(
    new Set(metrics.map(m => m.category))
  );

  // ── Config block (may be null if backend hasn't added it yet) ────────────────
  const config: Record<string, any> | null = $derived(
    analysis?.config ?? null
  );

  // Helper: resolve a config key value from the config block
  function configVal(key: string): string {
    if (!config) return '(not in API response yet)';
    const v = config[key];
    if (v == null) return '—';
    return typeof v === 'number' ? v.toFixed(2) : String(v);
  }

  // Helper: resolve a source location from config.source_locations
  function configSource(key: string): string {
    const src = config?.source_locations?.[key];
    return src ?? 'fdensemble/main.py (env var override available)';
  }

  // Helper: format enacted value for display (integers cleanly, floats to 3dp)
  function fmtEnacted(v: number | null): string {
    if (v == null) return '—';
    return Number.isInteger(v) ? String(v) : v.toFixed(3);
  }

  // Helper: ordinal suffix for percentile labels
  function ordinal(n: number): string {
    const abs = Math.abs(Math.round(n));
    const s = ['th','st','nd','rd'];
    const idx = abs % 100;
    return n.toFixed(1) + (s[(idx - 20) % 10] || s[idx] || s[0]);
  }
</script>

<!-- ── Outer wrapper — same card style as BenchmarkMethodology ───────────────── -->
<div style="background:var(--card);border:1.5px solid var(--border);border-radius:8px;
            margin-bottom:.8rem;overflow:hidden;">

  <!-- ── Collapsible header ──────────────────────────────────────────────────── -->
  <button
    onclick={() => open = !open}
    style="width:100%;text-align:left;padding:.65rem 1rem;background:var(--light);
           border:none;cursor:pointer;display:flex;align-items:center;
           justify-content:space-between;font-size:.78rem;font-weight:700;
           color:var(--blue);gap:.5rem;"
  >
    <span style="display:flex;align-items:center;gap:.5rem;">
      <!-- Ruler icon -->
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
           stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <rect x="1" y="9" width="22" height="6" rx="1"/>
        <line x1="8"  y1="9"  x2="8"  y2="15"/>
        <line x1="12" y1="9"  x2="12" y2="15"/>
        <line x1="16" y1="9"  x2="16" y2="15"/>
      </svg>
      Metric Reference &amp; Configuration
      <span style="font-weight:400;color:var(--gray);font-size:.72rem;">
        — {metrics.length} metric{metrics.length !== 1 ? 's' : ''}
      </span>
    </span>
    <!-- Chevron rotates when open -->
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"
         style="transform:{open ? 'rotate(180deg)' : 'none'};transition:transform .2s;">
      <polyline points="6 9 12 15 18 9"/>
    </svg>
  </button>

  {#if open}
  <div style="padding:.8rem 1rem 1rem;">

    <!-- ── Category filter pills ───────────────────────────────────────────── -->
    <div style="display:flex;gap:.4rem;flex-wrap:wrap;margin-bottom:.9rem;">
      {#each CATEGORY_ORDER as cat}
        {#if cat === 'all' || presentCategories.has(cat)}
          {@const isActive = activeFilter === cat}
          {@const catColor = cat === 'all' ? 'var(--blue)' : (CATEGORY_COLORS[cat] ?? '#888')}
          <button
            onclick={() => activeFilter = cat}
            style="padding:.25rem .65rem;border-radius:99px;font-size:.71rem;font-weight:600;
                   cursor:pointer;border:1.5px solid {catColor};
                   background:{isActive ? catColor : 'transparent'};
                   color:{isActive ? '#fff' : catColor};
                   transition:background .15s,color .15s;"
          >
            {cat === 'all' ? 'All' : CATEGORY_LABELS[cat] ?? cat}
          </button>
        {/if}
      {/each}
    </div>

    <!-- ── Metric cards ─────────────────────────────────────────────────────── -->
    {#if visibleMetrics.length === 0}
      <div style="font-size:.78rem;color:var(--gray);padding:.6rem 0;">
        No metrics available for the current filter.
      </div>
    {:else}
      <div style="display:flex;flex-direction:column;gap:.7rem;">
        {#each visibleMetrics as m (m.key)}
          {@const catColor = CATEGORY_COLORS[m.category] ?? '#888'}
          {@const gradeColor = GRADE_COLORS[m.grade] ?? '#888'}
          {@const fi = m.formula_info}
          {@const hasConfig = (fi?.config_keys?.length ?? 0) > 0}

          <div style="border:1.5px solid var(--border);border-radius:7px;overflow:hidden;
                      background:var(--card);">

            <!-- ── Card header: category badge · label · grade · pct ──────── -->
            <div style="display:flex;align-items:flex-start;justify-content:space-between;
                        flex-wrap:wrap;gap:.4rem;
                        padding:.55rem .85rem;
                        background:{m.grade === 'F' ? '#fff5f5' : m.grade === 'A' ? '#f5fdf8' : 'var(--light)'};
                        border-bottom:1px solid var(--border);">
              <div style="display:flex;align-items:center;gap:.5rem;flex-wrap:wrap;min-width:0;">
                <!-- Category badge -->
                <span style="display:inline-block;padding:.15rem .5rem;border-radius:4px;
                             font-size:.62rem;font-weight:700;text-transform:uppercase;
                             letter-spacing:.05em;background:{catColor}1a;color:{catColor};
                             white-space:nowrap;border:1px solid {catColor}44;">
                  {CATEGORY_LABELS[m.category] ?? m.category}
                </span>
                <!-- Metric name -->
                <span style="font-size:.82rem;font-weight:700;color:#1a1a2e;">
                  {m.label}
                </span>
              </div>
              <!-- Grade badge + percentile -->
              <div style="display:flex;align-items:center;gap:.5rem;flex-shrink:0;">
                <span style="display:inline-flex;align-items:center;justify-content:center;
                             width:1.45rem;height:1.45rem;border-radius:50%;
                             background:{gradeColor};color:#fff;font-weight:800;font-size:.78rem;">
                  {m.grade}
                </span>
                {#if m.pct_rank != null}
                  <span style="font-size:.7rem;color:var(--gray);white-space:nowrap;">
                    {ordinal(m.pct_rank)} pctile
                  </span>
                {/if}
              </div>
            </div>

            <!-- ── Headline question ──────────────────────────────────────── -->
            {#if m.headline}
              <div style="padding:.35rem .85rem;font-size:.76rem;font-style:italic;
                          color:#555;border-bottom:1px solid var(--border);background:var(--card);">
                {m.headline}
              </div>
            {/if}

            <!-- ── Body: formula + detail rows ───────────────────────────── -->
            <div style="padding:.5rem .85rem;display:flex;flex-direction:column;gap:.35rem;">

              {#if fi}
                <!-- Formula -->
                <div style="display:flex;gap:.5rem;align-items:baseline;flex-wrap:wrap;">
                  <span style="font-size:.64rem;font-weight:700;text-transform:uppercase;
                               letter-spacing:.05em;color:var(--gray);white-space:nowrap;
                               min-width:6.5rem;">Formula</span>
                  <code style="font-family:monospace;font-size:.74rem;background:#f3f4f6;
                               padding:.1rem .35rem;border-radius:3px;color:#1a1a2e;
                               border:1px solid #e5e7eb;word-break:break-word;">
                    {fi.formula}
                  </code>
                </div>

                <!-- Detail -->
                {#if fi.detail}
                  <div style="display:flex;gap:.5rem;align-items:baseline;flex-wrap:wrap;">
                    <span style="font-size:.64rem;font-weight:700;text-transform:uppercase;
                                 letter-spacing:.05em;color:var(--gray);white-space:nowrap;
                                 min-width:6.5rem;">Detail</span>
                    <span style="font-size:.73rem;color:#444;line-height:1.55;flex:1;
                                 min-width:0;">{fi.detail}</span>
                  </div>
                {/if}

                <!-- Data source -->
                {#if fi.data_source}
                  <div style="display:flex;gap:.5rem;align-items:baseline;flex-wrap:wrap;">
                    <span style="font-size:.64rem;font-weight:700;text-transform:uppercase;
                                 letter-spacing:.05em;color:var(--gray);white-space:nowrap;
                                 min-width:6.5rem;">Data source</span>
                    <span style="font-size:.73rem;color:#444;flex:1;min-width:0;">
                      {fi.data_source}
                    </span>
                  </div>
                {/if}

                <!-- Grading method -->
                {#if fi.grading_method}
                  <div style="display:flex;gap:.5rem;align-items:baseline;flex-wrap:wrap;">
                    <span style="font-size:.64rem;font-weight:700;text-transform:uppercase;
                                 letter-spacing:.05em;color:var(--gray);white-space:nowrap;
                                 min-width:6.5rem;">Grading</span>
                    <div style="font-size:.73rem;color:#444;flex:1;min-width:0;">
                      <span style="font-style:italic;">{fi.grading_method}</span>
                      {#if GRADING_DETAIL[fi.grading_method]}
                        <span style="color:var(--gray);margin-left:.3rem;">
                          · {GRADING_DETAIL[fi.grading_method]}
                        </span>
                      {/if}
                    </div>
                  </div>
                {/if}

              {:else}
                <!-- formula_info absent -->
                <div style="font-size:.73rem;color:var(--gray);font-style:italic;">
                  Formula metadata not available for this metric.
                </div>
              {/if}

              <!-- Enacted value row -->
              <div style="display:flex;gap:.5rem;align-items:baseline;flex-wrap:wrap;">
                <span style="font-size:.64rem;font-weight:700;text-transform:uppercase;
                             letter-spacing:.05em;color:var(--gray);white-space:nowrap;
                             min-width:6.5rem;">Enacted</span>
                <span style="font-size:.78rem;font-weight:700;color:#1a1a2e;font-family:monospace;">
                  {fmtEnacted(m.enacted)}
                </span>
                {#if m.pct_rank != null}
                  <span style="font-size:.7rem;color:var(--gray);">
                    ({ordinal(m.pct_rank)} percentile of neutral ensemble)
                  </span>
                {/if}
              </div>

            </div><!-- /body -->

            <!-- ── Config threshold section (only when config_keys present) ─ -->
            {#if hasConfig && fi}
              <div style="border-top:1px solid var(--border);padding:.45rem .85rem;
                          background:#f8fafc;">
                <div style="font-size:.64rem;font-weight:700;text-transform:uppercase;
                            letter-spacing:.06em;color:var(--gray);margin-bottom:.4rem;
                            display:flex;align-items:center;gap:.4rem;">
                  <!-- Gear icon -->
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                       stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="12" cy="12" r="3"/>
                    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
                  </svg>
                  Configurable thresholds
                </div>
                <table style="width:100%;border-collapse:collapse;font-size:.7rem;">
                  <thead>
                    <tr style="text-align:left;">
                      <th style="padding:.15rem .4rem .15rem 0;font-weight:600;
                                 color:var(--gray);font-size:.62rem;white-space:nowrap;">
                        Parameter
                      </th>
                      <th style="padding:.15rem .4rem;font-weight:600;
                                 color:var(--gray);font-size:.62rem;white-space:nowrap;">
                        Current value
                      </th>
                      <th style="padding:.15rem 0 .15rem .4rem;font-weight:600;
                                 color:var(--gray);font-size:.62rem;">
                        Source location
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each fi.config_keys as ck (ck)}
                      <tr style="border-top:1px solid #eaecef;">
                        <td style="padding:.2rem .4rem .2rem 0;white-space:nowrap;
                                   font-weight:600;color:#333;">
                          {CONFIG_KEY_LABELS[ck] ?? ck}
                        </td>
                        <td style="padding:.2rem .4rem;font-family:monospace;
                                   font-size:.73rem;color:#1a1a2e;">
                          {configVal(ck)}
                        </td>
                        <td style="padding:.2rem 0 .2rem .4rem;
                                   color:var(--gray);font-size:.67rem;word-break:break-all;">
                          {configSource(ck)}
                        </td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
                {#if !config}
                  <div style="margin-top:.3rem;font-size:.66rem;color:var(--gray);
                              font-style:italic;">
                    Live threshold values will appear here once the API config block is populated.
                  </div>
                {/if}
              </div>
            {/if}<!-- /config section -->

          </div><!-- /metric card -->
        {/each}
      </div><!-- /metric list -->
    {/if}

    <!-- ── Footer note ───────────────────────────────────────────────────────── -->
    <div style="margin-top:.75rem;padding:.4rem .6rem;background:var(--light);
                border-radius:5px;border:1px solid var(--border);
                font-size:.67rem;color:var(--gray);line-height:1.55;">
      <b>Princeton grading thresholds:</b> A = near neutral median (40th–60th pct or directional top band);
      B = within normal range; C = within ensemble 5th–95th pct; F = statistical outlier outside 5–95.
      Minority representation metrics use symmetric grading — the same standard as all other metrics.
      Threshold env vars: <code style="font-family:monospace;font-size:.67rem;">COMPETITIVE_MARGIN_MAIN</code>,
      <code style="font-family:monospace;font-size:.67rem;">MAJORITY_THRESHOLD</code>,
      <code style="font-family:monospace;font-size:.67rem;">BVAP_MAJORITY_THRESHOLD</code>,
      <code style="font-family:monospace;font-size:.67rem;">INFLUENCE_MIN_THRESHOLD</code>,
      <code style="font-family:monospace;font-size:.67rem;">INFLUENCE_MAX_THRESHOLD</code>.
    </div>

  </div><!-- /panel body -->
  {/if}

</div><!-- /outer wrapper -->
