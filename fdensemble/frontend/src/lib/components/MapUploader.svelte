<script lang="ts">
  import type { MapMeta } from '../types.js';
  import { parseAndValidateShapefile } from '../utils/shapefileParser.js';
  import type { ValidationResult } from '../utils/shapefileParser.js';

  interface Props {
    onMapSaved: (meta: MapMeta) => void;
  }
  let { onMapSaved }: Props = $props();

  let fileInput: HTMLInputElement;
  let state: 'idle' | 'parsing' | 'confirm' | 'saving' | 'error' = $state('idle');
  let parsedGeoJSON: GeoJSON.FeatureCollection | null = $state(null);
  let validation: ValidationResult | null = $state(null);
  let label = $state('');
  let errorMsg = $state('');

  function openPicker() { fileInput?.click(); }

  async function onFileChange(e: Event) {
    const file = (e.target as HTMLInputElement).files?.[0];
    if (!file) return;
    state = 'parsing';
    errorMsg = '';
    parsedGeoJSON = null;
    validation = null;
    label = file.name.replace(/\.zip$/i, '').replace(/_/g, ' ');

    try {
      const { geojson, validation: v } = await parseAndValidateShapefile(file);
      parsedGeoJSON = geojson;
      validation = v;
      state = 'confirm';
    } catch (err) {
      errorMsg = err instanceof Error ? err.message : String(err);
      state = 'error';
    } finally {
      if (fileInput) fileInput.value = '';
    }
  }

  function cancel() {
    state = 'idle';
    parsedGeoJSON = null;
    validation = null;
    label = '';
    errorMsg = '';
  }

  async function saveMap() {
    if (!parsedGeoJSON || !validation?.valid) return;
    state = 'saving';
    errorMsg = '';
    try {
      const res = await fetch('/api/maps', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          label:   label.trim() || 'Uploaded Map',
          geojson: parsedGeoJSON,
        }),
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(`Server error ${res.status}: ${txt}`);
      }
      const meta: MapMeta = await res.json();
      cancel();
      onMapSaved(meta);
    } catch (err) {
      errorMsg = err instanceof Error ? err.message : String(err);
      state = 'error';
    }
  }
</script>

<input bind:this={fileInput} type="file" accept=".zip" onchange={onFileChange} style="display:none;" />

{#if state === 'idle' || state === 'error'}
  <div style="display:flex;align-items:center;gap:.7rem;flex-wrap:wrap;">
    <button
      onclick={openPicker}
      style="display:inline-flex;align-items:center;gap:.4rem;padding:.4rem .8rem;
             border:1.5px dashed var(--border);border-radius:6px;background:transparent;
             cursor:pointer;font-size:.78rem;color:var(--gray);font-weight:500;"
    >
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
           stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
        <polyline points="17 8 12 3 7 8"/>
        <line x1="12" y1="3" x2="12" y2="15"/>
      </svg>
      Choose shapefile (.zip)
    </button>
    <span style="font-size:.72rem;color:var(--gray);">
      Upload a district shapefile to add it to the map library.
      Once saved, it's available to score against any ensemble.
    </span>
  </div>
  {#if state === 'error' && errorMsg}
    <div style="margin-top:.4rem;font-size:.72rem;color:var(--red);padding:.35rem .6rem;
                background:#fef0f0;border-radius:4px;border:1px solid #f5a9a9;">{errorMsg}</div>
  {/if}
{/if}

{#if state === 'parsing'}
  <div style="font-size:.78rem;color:var(--gray);padding:.4rem 0;">Parsing shapefile…</div>
{/if}

{#if state === 'saving'}
  <div style="font-size:.78rem;color:var(--gray);padding:.4rem 0;">Saving to map library…</div>
{/if}

{#if state === 'confirm' && validation}
  <div style="border:1.5px solid var(--border);border-radius:6px;padding:.7rem .9rem;
              background:var(--light);max-width:480px;">
    <div style="font-size:.72rem;margin-bottom:.5rem;">
      {#if validation.errors.length === 0}
        <div style="color:var(--green);font-weight:700;margin-bottom:.2rem;">
          ✓ Valid — {validation.districtCount} districts ({validation.geometryType})
        </div>
      {:else}
        <div style="color:var(--red);font-weight:700;margin-bottom:.2rem;">✗ Validation errors:</div>
        {#each validation.errors as err}
          <div style="color:var(--red);margin-left:.5rem;">• {err}</div>
        {/each}
      {/if}
      {#each validation.warnings as w}
        <div style="color:#d68910;margin-top:.15rem;">⚠ {w}</div>
      {/each}
    </div>

    {#if validation.valid}
      <div style="margin-bottom:.5rem;">
        <label for="map-label" style="font-size:.72rem;font-weight:700;display:block;margin-bottom:.2rem;">
          Map name (shown in selector)
        </label>
        <input
          id="map-label"
          type="text"
          bind:value={label}
          placeholder="e.g. Proposed Senate Map 2026"
          style="width:100%;box-sizing:border-box;padding:.3rem .5rem;font-size:.78rem;
                 border:1px solid var(--border);border-radius:4px;background:var(--card);color:inherit;"
        />
      </div>
      <div style="display:flex;gap:.4rem;">
        <button
          onclick={saveMap}
          style="flex:1;padding:.4rem;background:var(--blue);color:#fff;border:none;
                 border-radius:4px;font-size:.78rem;font-weight:700;cursor:pointer;"
        >Save to Map Library</button>
        <button
          onclick={cancel}
          style="padding:.4rem .7rem;background:transparent;border:1px solid var(--border);
                 border-radius:4px;font-size:.78rem;cursor:pointer;"
        >Cancel</button>
      </div>
    {:else}
      <button onclick={cancel}
        style="padding:.35rem .7rem;background:transparent;border:1px solid var(--border);
               border-radius:4px;font-size:.78rem;cursor:pointer;">Dismiss</button>
    {/if}
  </div>
{/if}
