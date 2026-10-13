<script setup lang="ts">
import type { Dataset } from '~/composables/useApi'
import ViewerState from './ViewerState.vue'

// A Plotly figure written by a run (`*.plotly.json`: a SED-ML plot from biosim-toolkit's Plots step), drawn as it is.
const props = defineProps<{ dataset: Dataset }>()
const { text, error: loadError, loading, tooBig } = useDatasetFile(() => props.dataset, 'text', 20 * 1024 * 1024)

const figure = computed(() => {
  if (text.value == null) return null
  try {
    const parsed = JSON.parse(text.value) as { data?: Record<string, unknown>[], layout?: Record<string, unknown> }
    return Array.isArray(parsed.data) ? { data: parsed.data, layout: parsed.layout ?? {} } : null
  } catch {
    return null
  }
})
const error = computed(() => loadError.value ?? (text.value != null && !figure.value ? 'Not a Plotly figure' : null))
</script>

<template>
  <div class="flex flex-col gap-3">
    <ViewerState :loading="loading" :error="error" :too-big="tooBig" :size="dataset.size_bytes" />
    <PlotlyChart v-if="figure" :data="figure.data" :layout="figure.layout" class="h-[28rem]" />
  </div>
</template>
