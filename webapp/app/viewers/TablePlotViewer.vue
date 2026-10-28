<script setup lang="ts">
import type { Dataset } from '~/composables/useApi'
import ViewerState from './ViewerState.vue'
import { parseTable, tableTraces } from './tabular'

// A delimited table plotted: the first column as x, every other all-numeric column as a line.
const props = defineProps<{ dataset: Dataset }>()
const { text, error, loading, tooBig } = useDatasetFile(() => props.dataset, 'text')
const table = computed(() => (text.value == null ? null : parseTable(text.value)))
const traces = computed(() => (table.value ? tableTraces(table.value) : null))
</script>

<template>
  <div class="flex flex-col gap-3">
    <ViewerState :loading="loading" :error="error" :too-big="tooBig" :size="dataset.size_bytes" />
    <PlotlyChart v-if="table && traces" :data="traces" :layout="{ xaxis: { title: { text: table.header[0] } } }" class="h-[28rem]" />
    <p v-else-if="table" class="text-sm text-muted">
      Nothing to plot: a plot needs a numeric first column, as x, and another numeric column.
    </p>
  </div>
</template>
