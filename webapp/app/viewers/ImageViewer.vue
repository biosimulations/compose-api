<script setup lang="ts">
import type { Dataset } from '~/composables/useApi'
import ViewerState from './ViewerState.vue'

const props = defineProps<{ dataset: Dataset }>()
const { blobUrl, error, loading, tooBig } = useDatasetFile(() => props.dataset, 'blob', 20 * 1024 * 1024)
</script>

<template>
  <div class="flex flex-col gap-3">
    <ViewerState :loading="loading" :error="error" :too-big="tooBig" :size="dataset.size_bytes" />
    <img v-if="blobUrl" :src="blobUrl" :alt="dataset.display_name" class="max-w-full max-h-[75vh] object-contain self-start rounded border border-default">
  </div>
</template>
