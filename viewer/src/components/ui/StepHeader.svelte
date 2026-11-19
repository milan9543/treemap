<script lang="ts">
  let { title, description }: { title: string; description: string } = $props();
</script>

<header>
  <h2>{title}</h2>
  <p>{description}</p>
</header>

<style>
  header { display: flex; flex-direction: column; gap: 2px; }
  h2 { margin: 0; font-size: var(--t-xl); font-weight: 600; letter-spacing: -0.01em; }
  p { margin: 0; color: var(--muted); font-size: var(--t-sm); }
</style>
