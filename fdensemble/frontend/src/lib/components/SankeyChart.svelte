<script lang="ts">
  import { sankey as d3sankey, sankeyLeft } from 'd3-sankey';

  interface CityRecord {
    muni_id:       number;
    name:          string;
    pop:           number;
    n_districts:   number;
    is_split:      boolean;
    districts:     number[];
    district_pops?: Record<string, number>;
  }

  interface Props {
    splitCities:  CityRecord[];
    intactCities: CityRecord[];
  }
  let { splitCities, intactCities }: Props = $props();

  const W        = 560;
  const NODE_H   = 12;   // bar height (d3-sankey nodeWidth, swapped to height)
  const NODE_PAD = 14;   // horizontal gap between bars
  const TOP_Y    = 38;   // y of district row top
  const BOT_Y    = 148;  // y of city row top
  const MARGIN   = 28;

  function cleanName(n: string) {
    return n.replace(/ (city|town|CDP|village|borough|unified government)$/i, '');
  }

  function fmtPop(n: number) {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
    if (n >= 1_000)     return Math.round(n / 1_000) + 'K';
    return String(n);
  }

  // Vertical filled ribbon: source=top, target=bottom
  function vPath(link: any): string {
    const sx   = link.y0;
    const tx   = link.y1;
    const sy   = (link.source as any).x1;
    const ty   = (link.target as any).x0;
    const w    = link.width;
    const midY = (sy + ty) / 2;
    return [
      `M ${sx - w / 2} ${sy}`,
      `C ${sx - w / 2} ${midY}, ${tx - w / 2} ${midY}, ${tx - w / 2} ${ty}`,
      `L ${tx + w / 2} ${ty}`,
      `C ${tx + w / 2} ${midY}, ${sx + w / 2} ${midY}, ${sx + w / 2} ${sy}`,
      `Z`,
    ].join(' ');
  }

  const layout = $derived.by(() => {
    if (!splitCities.length) return null;

    const districtSet = new Set<number>();
    for (const c of splitCities) c.districts.forEach(d => districtSet.add(d));
    const coupled = intactCities.filter(c => districtSet.has(c.districts[0]));
    const districtArr = [...districtSet].sort((a, b) => a - b);

    // Districts as SOURCES (→ top after coord swap), cities as TARGETS (→ bottom)
    const nodeList: { id: string; label: string; nodeType: 'district' | 'split' | 'intact'; pop: number }[] = [
      ...districtArr.map(d => ({ id: `d_${d}`,         label: `D${d}`,             nodeType: 'district' as const, pop: 0 })),
      ...splitCities.map(c => ({ id: `c_${c.muni_id}`, label: cleanName(c.name),   nodeType: 'split'    as const, pop: c.pop })),
      ...coupled    .map(c => ({ id: `c_${c.muni_id}`, label: cleanName(c.name),   nodeType: 'intact'   as const, pop: c.pop })),
    ];

    const links: { source: string; target: string; value: number }[] = [];
    for (const c of splitCities) {
      for (const d of c.districts) {
        const value = c.district_pops
          ? (c.district_pops[String(d)] ?? Math.round(c.pop / c.n_districts))
          : Math.round(c.pop / c.n_districts);
        links.push({ source: `d_${d}`, target: `c_${c.muni_id}`, value: Math.max(value, 500) });
      }
    }
    for (const c of coupled) {
      links.push({ source: `d_${c.districts[0]}`, target: `c_${c.muni_id}`, value: Math.max(c.pop, 500) });
    }

    // Extent: [[x_depth_min, y_spread_min], [x_depth_max, y_spread_max]]
    // x → becomes y after coord swap (depth = top/bottom)
    // y → becomes x after coord swap (spread = left/right)
    const sk = d3sankey<typeof nodeList[0], typeof links[0]>()
      .nodeId((d: any) => d.id)
      .nodeAlign(sankeyLeft)
      .nodeWidth(NODE_H)
      .nodePadding(NODE_PAD)
      .extent([[TOP_Y, MARGIN], [BOT_Y, W - MARGIN]]);

    const graph = sk({
      nodes: nodeList.map(n => ({ ...n })),
      links: links.map(l => ({ ...l })),
    });

    const H = BOT_Y + NODE_H + 60;
    return { graph, H, districtSet };
  });
</script>

{#if layout}
  <div style="overflow-x:auto;">
    <svg
      width="100%"
      viewBox="0 0 {W} {layout.H}"
      style="display:block;min-width:320px;font-family:-apple-system,BlinkMacSystemFont,sans-serif;"
    >
      <!-- Links (vertical ribbons) -->
      {#each layout.graph.links as link}
        {@const isFromSplit = (link.target as any).nodeType === 'split'}
        <path
          d={vPath(link)}
          fill={isFromSplit ? '#d32f2f' : '#999'}
          fill-opacity="0.22"
          stroke="none"
        />
      {/each}

      <!-- Nodes -->
      {#each layout.graph.nodes as node}
        {@const n = node as any}
        {@const col = n.nodeType === 'district' ? '#3D77BB' : n.nodeType === 'split' ? '#d32f2f' : '#888'}
        <!-- Coord swap: rendered rect is (y0, x0) → (y1, x1) -->
        <rect
          x={n.y0}
          y={n.x0}
          width={n.y1 - n.y0}
          height={n.x1 - n.x0}
          fill={col}
          rx="2"
        />

        {#if n.nodeType === 'district'}
          <!-- District label: above bar, centered -->
          <text
            x={(n.y0 + n.y1) / 2}
            y={n.x0 - 5}
            text-anchor="middle"
            font-size="8.5"
            font-weight="700"
            fill="#3D77BB"
          >{n.label}</text>
          <text
            x={(n.y0 + n.y1) / 2}
            y={n.x0 - 15}
            text-anchor="middle"
            font-size="7"
            fill="#888"
          >{fmtPop(n.value ?? 0)}</text>
        {:else}
          <!-- City label: below bar, rotated -45° -->
          <text
            transform="rotate(-45, {(n.y0 + n.y1) / 2}, {n.x1 + 6})"
            x={(n.y0 + n.y1) / 2}
            y={n.x1 + 6}
            text-anchor="end"
            font-size="8.5"
            font-weight={n.nodeType === 'split' ? '700' : '500'}
            fill={n.nodeType === 'split' ? '#c0392b' : '#555'}
          >{n.label}</text>
        {/if}
      {/each}
    </svg>
  </div>

  <!-- Legend -->
  <div style="display:flex;gap:1rem;font-size:.65rem;color:var(--gray);margin-top:.3rem;flex-wrap:wrap;">
    <span><span style="color:#3D77BB;font-weight:700;">■</span> District</span>
    <span><span style="color:#d32f2f;font-weight:700;">■</span> Split city</span>
    <span><span style="color:#888;font-weight:700;">■</span> Intact city sharing a district</span>
    <span style="font-style:italic;">Flow width = population</span>
  </div>
{/if}
