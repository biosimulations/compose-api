<script setup lang="ts">
import type { Dataset } from '~/composables/useApi'
import { isDirectoryDataset } from '~/viewers/registry'

// One dataset, full width, in its registered viewers. A deep link: /ui/datasets/<id>.
const route = useRoute()
const id = String(route.params.id)
const api = useApi()
const dataset = ref<Dataset | null>(null)
const error = ref<string | null>(null)

onMounted(async () => {
  const { data, error: err } = await api.GET('/datasets/{dataset_id}', { params: { path: { dataset_id: id } } })
  if (err || !data) error.value = errorMessage(err, 'Dataset not found')
  else dataset.value = data
})

async function save() {
  const d = dataset.value
  if (!d) return
  try {
    await downloadFile(`/datasets/${d.id}/content`, {}, d.path.split('/').pop() || d.display_name)
  } catch (e) {
    error.value = (e as Error).message
  }
}
</script>

<template>
  <div>
    <PageHeader :title="dataset?.display_name ?? 'Dataset'" :description="dataset?.path">
      <template #actions>
        <UButton v-if="dataset" :to="`/simulations/${dataset.simulation_id}?tab=datasets`" variant="subtle" color="neutral" icon="i-lucide-arrow-left" :label="`Simulation #${dataset.simulation_id}`" />
        <UButton v-if="dataset && !isDirectoryDataset(dataset)" icon="i-lucide-download" label="Download" @click="save" />
      </template>
    </PageHeader>
    <UContainer class="py-6 flex flex-col gap-4">
      <UAlert v-if="error" color="error" variant="subtle" icon="i-lucide-circle-alert" :description="error" />
      <template v-if="dataset">
        <div class="flex flex-wrap gap-2 text-sm">
          <UBadge variant="soft" color="neutral">{{ dataset.kind }}</UBadge>
          <UBadge variant="outline" color="neutral">{{ dataset.media_type }}</UBadge>
          <UBadge variant="outline" color="neutral">{{ formatBytes(dataset.size_bytes) }}</UBadge>
          <UBadge v-if="!dataset.available" color="error" variant="subtle">no longer available</UBadge>
        </div>
        <DatasetViewer :dataset="dataset" />
      </template>
    </UContainer>
  </div>
</template>
