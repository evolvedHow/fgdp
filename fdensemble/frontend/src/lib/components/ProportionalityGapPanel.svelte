<script lang="ts">
  import type { ProportionalityGap } from '../types.js';

  interface Props {
    data: ProportionalityGap;
    /** Total number of districts in this chamber */
    nDistricts?: number;
  }

  let { data, nDistricts = 14 }: Props = $props();

  // ── Derived display values ────────────────────────────────────────────────
  const demPct        = $derived((data.statewide_dem_2pv * 100).toFixed(1));
  const propTarget    = $derived(data.proportional_target.toFixed(2));
  const neutralMedian = $derived(data.ensemble_median.toFixed(1));
  const enacted       = $derived(data.enacted_seats.toFixed(0));

  // Gap directions: negative = shortfall below proportionality / below neutral
  const structGap     = $derived(data.structural_gap);   // neutral − proportional
  const manipGap      = $derived(data.manipulation_gap); // enacted  − neutral
  const totalGap      = $derived(data.total_gap);        // enacted  − proportional

  const structAbs     = $derived(Math.abs(structGap).toFixed(2));
  const manipAbs      = $derived(Math.abs(manipGap).toFixed(1));
  const totalAbs      = $derived(Math.abs(totalGap).toFixed(2));

  // ── Number-line layout ────────────────────────────────────────────────────
  // Place the three markers on a 0–n_districts axis, scaled to SVG width
  const SVG_W = 520;
  const SVG_H = 110;
  const PAD_L = 30;
  const PAD_R = 30;
  const AXIS_W = SVG_W - PAD_L - PAD_R;
  const AXIS_Y = 54;

  // We show a window around the three values with some breathing room
  const allVals  = $derived([data.proportional_target, data.ensemble_median, data.enacted_seats]);
  const minVal   = $derived(Math.min(...allVals) - 1.2);
  const maxVal   = $derived(Math.max(...allVals) + 1.2);
  const range    = $derived(maxVal - minVal);

  function toX(val: number) {
    return PAD_L + ((val - minVal) / range) * AXIS_W;
  }

  const xProp    = $derived(toX(data.proportional_target));
  const xNeutral = $derived(toX(data.ensemble_median));
  const xEnacted = $derived(toX(data.enacted_seats));

  // Tick marks for integer seat values in the window
  const ticks = $derived(
    Array.from({ length: Math.ceil(maxVal) - Math.floor(minVal) + 1 },
      (_, i) => Math.floor(minVal) + i
    ).filter(v => v >= 0 && v <= nDistricts)
  );

  // Color helpers
  const GRAY   = '#888';
  const BLUE   = '#3D77BB';
  const RED    = '#c0392b';
  const ORANGE = '#e67e22';
</script>

<div style="background:#fff;border:1.5px solid #e2e8f0;border-radius:8px;
            padding:1rem 1.1rem 1rem;margin:.8rem 0;">

  <!-- Header -->
  <div style="font-size:.78rem;font-weight:700;color:#444;margin-bottom:.25rem;
              display:flex;align-items:center;gap:.5rem;">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#e67e22"
         stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
      <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
    </svg>
    The Proportionality Gap — Why "C" Understates the Problem
  </div>
  <div style="font-size:.7rem;color:#666;margin-bottom:.9rem;line-height:1.5;">
    The ensemble grade (C) measures the enacted map <em>relative to the neutral baseline</em>.
    But the baseline itself is already biased — Democratic voters self-sort into dense cities,
    so even perfectly fair maps fall short of proportional representation.
    Measuring against proportionality exposes the full structural problem.
  </div>

  <!-- Number line SVG -->
  <div style="overflow-x:auto;">
    <svg width={SVG_W} height={SVG_H} style="display:block;margin:0 auto;overflow:visible;">

      <!-- Axis line -->
      <line x1={PAD_L} y1={AXIS_Y} x2={SVG_W - PAD_R} y2={AXIS_Y}
            stroke="#ccc" stroke-width="1.5"/>

      <!-- Integer seat tick marks -->
      {#each ticks as t}
        {@const tx = toX(t)}
        <line x1={tx} y1={AXIS_Y - 4} x2={tx} y2={AXIS_Y + 4}
              stroke="#ddd" stroke-width="1"/>
        <text x={tx} y={AXIS_Y + 16} text-anchor="middle"
              font-size="9" fill="#aaa">{t}</text>
      {/each}
      <text x={SVG_W / 2} y={AXIS_Y + 28} text-anchor="middle"
            font-size="8.5" fill="#aaa">Democratic-leaning seats (out of {nDistricts})</text>

      <!-- ── Structural gap bracket (prop → neutral) ── -->
      {#if structGap < -0.05}
        {@const bx1 = Math.min(xProp, xNeutral)}
        {@const bx2 = Math.max(xProp, xNeutral)}
        {@const by  = AXIS_Y - 26}
        <line x1={bx1} y1={by} x2={bx2} y2={by} stroke={GRAY} stroke-width="1" stroke-dasharray="3,2"/>
        <line x1={bx1} y1={by - 4} x2={bx1} y2={by + 4} stroke={GRAY} stroke-width="1"/>
        <line x1={bx2} y1={by - 4} x2={bx2} y2={by + 4} stroke={GRAY} stroke-width="1"/>
        <text x={(bx1 + bx2) / 2} y={by - 7} text-anchor="middle"
              font-size="8.5" fill={GRAY}>−{structAbs} seats</text>
      {/if}

      <!-- ── Manipulation gap bracket (neutral → enacted) ── -->
      {#if manipGap < -0.05}
        {@const bx1 = Math.min(xNeutral, xEnacted)}
        {@const bx2 = Math.max(xNeutral, xEnacted)}
        {@const by  = AXIS_Y - 26}
        <line x1={bx1} y1={by} x2={bx2} y2={by} stroke={RED} stroke-width="1.3" stroke-dasharray="3,2"/>
        <line x1={bx1} y1={by - 4} x2={bx1} y2={by + 4} stroke={RED} stroke-width="1.3"/>
        <line x1={bx2} y1={by - 4} x2={bx2} y2={by + 4} stroke={RED} stroke-width="1.3"/>
        <text x={(bx1 + bx2) / 2} y={by - 7} text-anchor="middle"
              font-size="8.5" fill={RED}>−{manipAbs} seats</text>
      {/if}

      <!-- ── Marker: Proportional target (gray) ── -->
      <circle cx={xProp} cy={AXIS_Y} r="6" fill={GRAY} opacity="0.85"/>
      <text x={xProp} y={AXIS_Y - 14} text-anchor="middle"
            font-size="9" font-weight="700" fill={GRAY}>Proportional</text>
      <text x={xProp} y={AXIS_Y - 5} text-anchor="middle"
            font-size="8" fill={GRAY}>{propTarget}</text>

      <!-- ── Marker: Neutral median (blue) ── -->
      <circle cx={xNeutral} cy={AXIS_Y} r="6" fill={BLUE}/>
      <text x={xNeutral} y={AXIS_Y - 14} text-anchor="middle"
            font-size="9" font-weight="700" fill={BLUE}>Neutral median</text>
      <text x={xNeutral} y={AXIS_Y - 5} text-anchor="middle"
            font-size="8" fill={BLUE}>{neutralMedian}</text>

      <!-- ── Marker: Enacted (red) ── -->
      <polygon
        points="{xEnacted},{AXIS_Y - 8} {xEnacted - 6},{AXIS_Y + 5} {xEnacted + 6},{AXIS_Y + 5}"
        fill={RED}
      />
      <text x={xEnacted} y={AXIS_Y - 17} text-anchor="middle"
            font-size="9" font-weight="700" fill={RED}>Enacted</text>
      <text x={xEnacted} y={AXIS_Y - 8} text-anchor="middle"
            font-size="8" fill={RED}>{enacted}</text>

    </svg>
  </div>

  <!-- Three-column gap summary -->
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:.6rem;margin-top:.7rem;">

    <!-- Geographic structural gap -->
    <div style="background:#f8f9fb;border:1px solid #e2e8f0;border-radius:6px;padding:.55rem .7rem;">
      <div style="font-size:.65rem;text-transform:uppercase;letter-spacing:.06em;color:{GRAY};font-weight:700;margin-bottom:.25rem;">
        Geographic Baseline Gap
      </div>
      <div style="font-size:1.3rem;font-weight:800;color:{GRAY};">
        {structGap < 0 ? '−' : '+'}{structAbs} seats
      </div>
      <div style="font-size:.67rem;color:#666;margin-top:.2rem;line-height:1.4;">
        Even neutral redistricting falls short of proportionality.
        Democratic voters self-sort into cities, concentrating votes into
        fewer, safer districts — <em>this is the garbage-in baseline.</em>
      </div>
    </div>

    <!-- Manipulation gap -->
    <div style="background:#fef5f5;border:1px solid #f5c6c6;border-radius:6px;padding:.55rem .7rem;">
      <div style="font-size:.65rem;text-transform:uppercase;letter-spacing:.06em;color:{RED};font-weight:700;margin-bottom:.25rem;">
        Partisan Manipulation Gap
      </div>
      <div style="font-size:1.3rem;font-weight:800;color:{RED};">
        {manipGap < 0 ? '−' : '+'}{manipAbs} seats
      </div>
      <div style="font-size:.67rem;color:#666;margin-top:.2rem;line-height:1.4;">
        Additional shortfall beyond the neutral baseline — what the
        Princeton ensemble test measures as the partisan fingerprint
        of deliberate line-drawing.
      </div>
    </div>

    <!-- Total gap -->
    <div style="background:#fff8f0;border:1px solid #f5d9a8;border-radius:6px;padding:.55rem .7rem;">
      <div style="font-size:.65rem;text-transform:uppercase;letter-spacing:.06em;color:{ORANGE};font-weight:700;margin-bottom:.25rem;">
        Total Gap from Proportionality
      </div>
      <div style="font-size:1.3rem;font-weight:800;color:{ORANGE};">
        {totalGap < 0 ? '−' : '+'}{totalAbs} seats
      </div>
      <div style="font-size:.67rem;color:#666;margin-top:.2rem;line-height:1.4;">
        Statewide vote share ({demPct}% Dem) implies {propTarget} Democratic
        seats; the enacted map delivers {enacted}.
        Combined geography + manipulation = {totalAbs}-seat deficit.
      </div>
    </div>

  </div>

  <!-- Interpretive note -->
  <div style="margin-top:.75rem;padding:.5rem .7rem;background:#fffbf0;
              border-left:3px solid {ORANGE};border-radius:0 4px 4px 0;font-size:.68rem;color:#555;line-height:1.5;">
    <b>Why this matters for grading:</b>
    The C grade reflects the enacted map's position relative to the neutral ensemble —
    it correctly flags <em>manipulation beyond the baseline</em>.
    But the neutral ensemble itself sits {structAbs} seats below proportionality,
    meaning the C grade is measured against a floor that already disadvantages Democrats.
    Measuring from proportionality, the full deficit is {totalAbs} seats —
    {structAbs} from geographic self-sorting that mapmakers could not prevent,
    and {manipAbs} from line-drawing choices they made deliberately.
  </div>

  <!-- Methodology footnote -->
  <div style="margin-top:.55rem;font-size:.62rem;color:#aaa;line-height:1.4;">
    Statewide Dem 2pv = VAP-weighted average of composite_dem_pct across 2,698 Georgia VTDs.
    Composite = 2018 Gov · 2020 Pres · 2021 Warnock runoff · 2022 Gov+Sen avg · 2024 Pres.
    Proportional target = {demPct}% × {nDistricts} districts = {propTarget} seats.
    Neutral median and enacted values from the Princeton ensemble histogram.
  </div>

</div>
