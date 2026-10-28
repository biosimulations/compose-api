<script setup lang="ts">
import type { Dataset } from '~/composables/useApi'
import TableGrid from './TableGrid.vue'
import ViewerState from './ViewerState.vue'
import { parseTable } from './tabular'

// A delimited table, as a table; its Plot is a viewer of its own (TablePlotViewer).
const props = defineProps<{ dataset: Dataset }>()
const { text, error, loading, tooBig } = useDatasetFile(() => props.dataset, 'text')
const table = computed(() => (text.value == null ? null : parseTable(text.value)))
</script>

<template>
  <div class="flex flex-col gap-3">
    <ViewerState :loading="loading" :error="error" :too-big="tooBig" :size="dataset.size_bytes" />
    <TableGrid v-if="table" :table="table" />
  </div>
</template>
