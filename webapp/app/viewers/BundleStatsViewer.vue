<script setup lang="ts">
import type { Dataset } from '~/composables/useApi'
import { Bundle, httpStore, type BundleVariable, type Stats } from './bundle/bundle'

// mean / min / max (and total) of each variable over time, from the bundle's stats arrays: cheap, no field rows are
// read, and it works for any results bundle. Follows a running simulation.
const props = defineProps<{ dataset: Dataset }>()

const bundle = shallowRef<Bundle | null>(null)
const error = ref<string | null>(null)
const variable = ref<string | undefined>()
const stats = shallowRef<Stats | null>(null)
const showTotal = ref(false)

const variables = computed<BundleVariable[]>(() => bundle.value?.variablesOf() ?? [])
const items = computed(() => variables.value.map(v => ({ label: `${v.name} (${v.domain})`, value: v.path })))
const selected = computed(() => variables.value.find(v => v.path === variable.value))

async function loadStats() {
  if (!bundle.value || !selected.value) return
  stats.value = await bundle.value.stats(selected.value)
}

onMounted(async () => {
  try {
    bundle.value = await Bundle.open(httpStore(datasetFilesUrl(props.dataset.id), authFetch))
    variable.value = variables.value[0]?.path
  } catch (e) {
    error.value = (e as Error).message
  }
})
watch(variable, () => loadStats().catch((e) => { error.value = (e as Error).message }))

useIntervalFn(async () => {
  if (bundle.value?.live && (await bundle.value.refresh())) await loadStats()
}, 5000)

const traces = computed(() => {
  const s = stats.value
  if (!s) return []
  const line = (name: string, y: number[], extra: Record<string, unknown> = {}) =>
    ({ type: 'scatter', mode: 'lines', name, x: s.times, y, ...extra })
  if (showTotal.value) return [line('total', s.total)]
  return [
    line('max', s.max, { line: { width: 0 }, showlegend: false }),
    line('min', s.min, { fill: 'tonexty', fillcolor: 'rgba(43,127,255,0.15)', line: { width: 0 }, name: 'min–max' }),
    line('mean', s.mean, { line: { width: 2 } })
  ]
})
</script>

<template>
  <div class="flex flex-col gap-3">
    <UAlert v-if="error" color="error" variant="subtle" :description="error" />
    <div v-if="bundle" class="flex flex-wrap items-center gap-3">
      <USelect v-model="variable" :items="items" class="w-64" />
      <USwitch v-model="showTotal" label="Total" />
      <span class="text-sm text-muted">
        {{ bundle.times.length }} time points
        <template v-if="bundle.live"> · <UIcon name="i-lucide-loader-circle" class="animate-spin size-3" /> running</template>
      </span>
    </div>
    <PlotlyChart
      v-if="stats"
      :data="traces"
      :layout="{ xaxis: { title: { text: 'time' } }, yaxis: { title: { text: selected?.name } }, legend: { orientation: 'h' } }"
      class="h-96"
    />
    <p v-else-if="!error" class="text-sm text-muted"><UIcon name="i-lucide-loader-circle" class="animate-spin" /> Loading…</p>
  </div>
</template>
