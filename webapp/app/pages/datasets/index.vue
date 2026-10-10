<script setup lang="ts">
import type { Dataset } from '~/composables/useApi'

// Every dataset any run produced, newest simulations first.
const api = useApi()
const PAGE = 50
const kind = ref<string | undefined>(undefined)
const q = ref('')
const simulationId = ref<number | undefined>(undefined)
const page = ref(1)
const rows = ref<Dataset[]>([])
const total = ref(0)
const loading = ref(false)
const error = ref<string | null>(null)

// The API publishes the kinds it infers; the fallback is for an API without them.
const webappConfig = useWebappConfig()
const kinds = computed(() => webappConfig.value?.dataset_kinds ?? ['results', 'results-bundle', 'table', 'figure', 'archive', 'log', 'file'])

async function load() {
  loading.value = true
  const { data, error: err } = await api.GET('/datasets', {
    params: {
      query: {
        kind: kind.value || undefined,
        q: q.value || undefined,
        simulation_id: simulationId.value || undefined,
        limit: PAGE,
        offset: (page.value - 1) * PAGE
      }
    }
  })
  loading.value = false
  if (err || !data) {
    error.value = errorMessage(err, 'Could not load datasets')
    rows.value = []
    total.value = 0
    return
  }
  error.value = null
  rows.value = data.datasets
  total.value = data.total
}

watch([kind, q, simulationId], () => {
  page.value = 1
  load()
})
watch(page, load)
onMounted(load)
</script>

<template>
  <div>
    <PageHeader title="Datasets" :description="`${total} files recorded by simulation runs`" />
    <UContainer class="py-6 flex flex-col gap-4">
      <div class="flex flex-wrap items-center gap-2">
        <USelect v-model="kind" :items="kinds" placeholder="Any kind" class="w-40" clearable />
        <UInput v-model.lazy="q" placeholder="Path or name contains…" icon="i-lucide-search" class="w-64" />
        <UInput v-model.lazy.number="simulationId" type="number" placeholder="Simulation #" icon="i-lucide-hash" :min="1" class="w-40" />
      </div>
      <UAlert v-if="error" color="error" variant="subtle" icon="i-lucide-circle-alert" :description="error" />
      <DatasetsTable :datasets="rows" :loading="loading" show-simulation />
      <div class="flex justify-end">
        <UPagination v-model:page="page" :total="total" :items-per-page="PAGE" />
      </div>
    </UContainer>
  </div>
</template>
