<script lang="ts">
  // A QR code for a link, drawn dark on light so phone cameras read it easily.
  import QRCode from "qrcode";

  let { text, size = 200 }: { text: string; size?: number } = $props();
  let canvas: HTMLCanvasElement;

  $effect(() => {
    void QRCode.toCanvas(canvas, text, { width: size, margin: 2, errorCorrectionLevel: "M" });
  });
</script>

<canvas bind:this={canvas} width={size} height={size} aria-label="QR code for {text}"></canvas>

<style>
  canvas { display: block; border-radius: var(--r1); }
</style>
