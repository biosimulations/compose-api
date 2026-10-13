<script setup lang="ts">
import Papa from 'papaparse'
import type { Dataset } from '~/composables/useApi'
import ViewerState from './ViewerState.vue'

// Delimited tables, plotted when numeric: the first column as x, every other all-numeric column as a line.
const props = defineProps<{ dataset: Dataset }>()
const { text, error, loading, tooBig } = useDatasetFile(() => props.dataset, 'text')

const table = computed(() => {
  if (text.value == null) return null
  const parsed = Papa.parse<string[]>(text.value.trim(), { skipEmptyLines: true })
  const [header, ...rows] = parsed.data
  return header ? { header: header.map(h => h.trim()), rows } : null
})

const traces = computed(() => {
  const t = table.value
  if (!t || t.header.length < 2 || t.rows.length < 2) return null
  const numeric = (i: number) => t.rows.every(r => r[i] !== undefined && r[i] !== '' && !Number.isNaN(Number(r[i])))
  if (!numeric(0)) return null
  const x = t.rows.map(r => Number(r[0]))
  const ys = t.header.map((h, i) => ({ h, i })).slice(1).filter(({ i }) => numeric(i))
  if (!ys.length) return null
  return ys.map(({ h, i }) => ({ type: 'scatter', mode: 'lines', name: h, x, y: t.rows.map(r => Number(r[i])) }))
})

const showPlot = ref(true)
</script>

<template>
  <div class="flex flex-col gap-3">
    <ViewerState :loading="loading" :error="error" :too-big="tooBig" :size="dataset.size_bytes" />
    <template v-if="table">
      <USwitch v-if="traces" v-model="showPlot" label="Plot" />
      <PlotlyChart v-if="traces && showPlot" :data="traces" :layout="{ xaxis: { title: { text: table.header[0] } } }" class="h-96" />
      <div v-else class="overflow-auto max-h-[65vh] border border-default rounded">
        <table class="text-xs font-mono">
          <thead class="sticky top-0 bg-elevated">
            <tr><th v-for="h in table.header" :key="h" class="px-2 py-1 text-left">{{ h }}</th></tr>
          </thead>
          <tbody>
            <tr v-for="(r, i) in table.rows.slice(0, 500)" :key="i" class="border-t border-default">
              <td v-for="(c, j) in r" :key="j" class="px-2 py-0.5 whitespace-nowrap">{{ c }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="table.rows.length > 500" class="p-2 text-xs text-muted">Showing 500 of {{ table.rows.length }} rows.</p>
      </div>
    </template>
  </div>
</template>
