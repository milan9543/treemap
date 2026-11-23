<script lang="ts">
  import type { Component, Snippet } from "svelte";

  let {
    variant = "secondary", size = "md", icon, active = false, full = false, disabled = false,
    title, onclick, children,
  }: {
    variant?: "primary" | "secondary" | "ghost" | "danger";
    size?: "sm" | "md" | "lg";
    icon?: Component<any>;
    active?: boolean;
    full?: boolean;
    disabled?: boolean;
    title?: string;
    onclick?: (e: MouseEvent) => void;
    children?: Snippet;
  } = $props();
  const iconSize = $derived(size === "sm" ? 14 : size === "lg" ? 18 : 15);
</script>

<button class="btn {variant} {size}" class:active class:full {disabled} {title} {onclick} type="button">
  {#if icon}{@const Icon = icon}<Icon size={iconSize} strokeWidth={2} />{/if}
  {#if children}<span>{@render children()}</span>{/if}
</button>

<style>
  .btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; cursor: pointer;
    border: 1px solid var(--border); border-radius: var(--r1); background: var(--surface-2);
    color: var(--text); white-space: nowrap; transition: background 0.12s, border-color 0.12s; }
  .md { padding: 5px 11px; font-size: var(--t-md); }
  .sm { padding: 3px 8px; font-size: var(--t-sm); }
  .lg { padding: 9px 16px; font-size: var(--t-lg); font-weight: 600; }
  .full { width: 100%; }
  .btn:hover:not(:disabled) { background: var(--surface-3); border-color: var(--border-strong); }
  .primary { background: var(--accent); border-color: var(--accent); color: #07140e; font-weight: 600; }
  .primary:hover:not(:disabled) { background: #85dfb6; border-color: #85dfb6; }
  .ghost { background: transparent; border-color: transparent; color: var(--muted); }
  .ghost:hover:not(:disabled) { color: var(--text); }
  .danger { background: var(--bad-bg); border-color: rgba(239, 111, 111, 0.4); color: var(--bad); }
  .danger:hover:not(:disabled) { background: rgba(239, 111, 111, 0.22); border-color: var(--bad); }
  .active { background: var(--accent-bg); border-color: var(--accent-border); color: var(--accent); }
  .btn:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
