<script lang="ts">
  interface Props {
    matrix: Record<string, Record<string, number | null>>;
    onCellClick?: (xKey: string, yKey: string) => void;
  }
  let { matrix, onCellClick }: Props = $props();

  const SHORT_LABELS: Record<string, string> = {
    dem_seats:      'Dem Seats',
    efficiency_gap: 'Eff. Gap',
    mean_median:    'Mean-Med',
    comp_seats:     'Comp.',
    muni_splits:    'City Splits',
    county_splits:  'Co. Splits',
    rep_safe_seats: 'Rep Safe',
    dem_safe_seats: 'Dem Safe',
  };

  const keys = $derived(Object.keys(matrix));

  // Color scale: -1 = red(192,57,43) → 0 = white → +1 = green(39,174,96)
  function rColor(r: number | null): string {
    if (r == null) return '#f0f2f5';
    const v = Math.max(-1, Math.min(1, r));
    if (v >= 0) {
      // white → green
      return `rgb(${Math.round(255 - 216 * v)},${Math.round(255 - 81 * v)},${Math.round(255 - 159 * v)})`;
    } else {
      // white → red
      const t = -v;
      return `rgb(${Math.round(255 - 63 * t)},${Math.round(255 - 198 * t)},${Math.round(255 - 212 * t)})`;
    }
  }

  function rTextColor(r: number | null): string {
    return Math.abs(r ?? 0) > 0.45 ? '#fff' : '#333';
  }

  function cellLabel(k1: string, k2: string): string {
    if (k1 === k2) return '1.00';
    const v = matrix[k1]?.[k2];
    return v != null ? v.toFixed(2) : '—';
  }

  function isClickable(k1: string, k2: string): boolean {
    return k1 !== k2 && !!onCellClick && matrix[k1]?.[k2] != null;
  }
</script>

<div style="overflow-x:auto;">
  <table style="border-collapse:collapse;font-size:.66rem;width:100%;">
    <thead>
      <tr>
        <th style="padding:.25rem .4rem;text-align:left;font-size:.6rem;color:var(--gray);border-bottom:1.5px solid var(--border);min-width:70px;"></th>
        {#each keys as k}
          <th style="padding:.25rem .3rem;text-align:center;font-size:.6rem;color:var(--gray);
                     border-bottom:1.5px solid var(--border);white-space:nowrap;min-width:58px;">
            {SHORT_LABELS[k] ?? k}
          </th>
        {/each}
      </tr>
    </thead>
    <tbody>
      {#each keys as k1, ri}
        <tr style="border-bottom:1px solid var(--border);">
          <td style="padding:.25rem .4rem;font-size:.6rem;font-weight:600;color:var(--gray);
                     border-right:1px solid var(--border);white-space:nowrap;">
            {SHORT_LABELS[k1] ?? k1}
          </td>
          {#each keys as k2}
            {@const r = k1 === k2 ? 1.0 : (matrix[k1]?.[k2] ?? null)}
            <td
              onclick={() => isClickable(k1, k2) && onCellClick?.(k1, k2)}
              style="padding:.3rem .3rem;text-align:center;font-family:monospace;font-size:.66rem;
                     font-weight:{k1 === k2 ? '400' : '700'};
                     background:{rColor(r)};
                     color:{rTextColor(r)};
                     cursor:{isClickable(k1, k2) ? 'pointer' : 'default'};
                     transition:opacity .1s;
                     opacity:{k1 === k2 ? '0.35' : '1'};"
              title={k1 !== k2 ? `${SHORT_LABELS[k1] ?? k1} vs ${SHORT_LABELS[k2] ?? k2}: r = ${r?.toFixed(3) ?? '—'}` : ''}
            >
              {cellLabel(k1, k2)}
            </td>
          {/each}
        </tr>
      {/each}
    </tbody>
  </table>
</div>
<div style="font-size:.58rem;color:var(--gray);margin-top:.3rem;text-align:right;">
  Pearson r across {#if keys.length > 0}neutral ensemble draws{/if}
  {#if onCellClick}· Click a cell to see the scatter plot{/if}
</div>
