<script setup lang="ts">
// After ../platform/frontend/app/components/PlotlyChart.vue, but bundled (plotly.js-dist-min, loaded on first
// use) rather than fetched from cdn.plot.ly, so the on-premise deployment has no CDN dependency.
const props = withDefaults(defineProps<{
  data: Record<string, unknown>[]
  layout?: Record<string, unknown>
}>(), { layout: () => ({}) })

const el = ref<HTMLDivElement | null>(null)
let plotly: typeof import('plotly.js-dist-min') | null = null

async function render() {
  if (!el.value) return
  if (!plotly) {
    // A CommonJS bundle: the build exposes it as `default`, Vite's dev server (it is excluded from optimizeDeps) as
    // the module namespace itself.
    const mod = (await import('plotly.js-dist-min')) as unknown as { default?: typeof import('plotly.js-dist-min') }
    plotly = mod.default ?? (mod as unknown as typeof import('plotly.js-dist-min'))
  }
  const layout = { margin: { t: 30, r: 20, b: 40, l: 50 }, autosize: true, ...props.layout }
  await plotly.react(el.value, props.data as never, layout as never, { responsive: true, displaylogo: false })
}

onMounted(render)
watch(() => [props.data, props.layout], render, { deep: true })
onBeforeUnmount(() => {
  if (el.value && plotly) plotly.purge(el.value)
})
</script>

<template>
  <div ref="el" class="w-full h-full min-h-80" />
</template>
