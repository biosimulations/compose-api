<script setup lang="ts">
import type { Dataset } from '~/composables/useApi'
import ViewerState from './ViewerState.vue'

const props = defineProps<{ dataset: Dataset }>()
const { text, error, loading, tooBig } = useDatasetFile(() => props.dataset, 'text')

const pretty = computed(() => {
  if (text.value == null) return ''
  if (/json/.test(props.dataset.media_type ?? '') && !/ndjson/.test(props.dataset.media_type ?? '')) {
    try {
      return JSON.stringify(JSON.parse(text.value), null, 2)
    } catch {
      return text.value
    }
  }
  return text.value
})
</script>

<template>
  <div class="flex flex-col gap-3">
    <ViewerState :loading="loading" :error="error" :too-big="tooBig" :size="dataset.size_bytes" />
    <pre v-if="text != null" class="text-xs font-mono p-3 rounded bg-elevated/50 border border-default overflow-auto max-h-[70vh] whitespace-pre-wrap">{{ pretty }}</pre>
  </div>
</template>
