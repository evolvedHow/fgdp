<script lang="ts">
  interface Props {
    value: string;
    label: string;
    sublabel?: string;
    accent?: string;
  }
  let { value, label, sublabel, accent = 'var(--blue)' }: Props = $props();
</script>

<div style="background:var(--card);border:1.5px solid var(--border);border-radius:10px;
            padding:1rem 1.2rem;display:flex;flex-direction:column;gap:.25rem;">
  <div style="font-size:1.8rem;font-weight:800;color:{accent};line-height:1.1;">{value}</div>
  <div style="font-size:.8rem;font-weight:600;color:#222;">{label}</div>
  {#if sublabel}
    <div style="font-size:.7rem;color:var(--gray);line-height:1.4;">{sublabel}</div>
  {/if}
</div>
