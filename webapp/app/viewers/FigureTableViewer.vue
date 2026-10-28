<script setup lang="ts">
import type { Dataset } from '~/composables/useApi'
import TableGrid from './TableGrid.vue'
import ViewerState from './ViewerState.vue'
import { figureTable } from './tabular'

// A Plotly figure's data as a table (its x/y series), for reading the values behind a plot.
const props = defineProps<{ dataset: Dataset }>()
const { text, error: loadError, loading, tooBig } = useDatasetFile(() => props.dataset, 'text', 20 * 1024 * 1024)

const table = computed(() => {
  if (text.value == null) return null
  try {
    const parsed = JSON.parse(text.value) as { data?: Record<string, unknown>[], layout?: Record<string, unknown> }
    return Array.isArray(parsed.data) ? figureTable({ data: parsed.data, layout: parsed.layout }) : null
  } catch {
    return null
  }
})
</script>

<template>
  <div class="flex flex-col gap-3">
    <ViewerState :loading="loading" :error="loadError" :too-big="tooBig" :size="dataset.size_bytes" />
    <TableGrid v-if="table" :table="table" />
    <p v-else-if="text != null" class="text-sm text-muted">This figure's data are not x/y series, so they have no table.</p>
  </div>
</template>
