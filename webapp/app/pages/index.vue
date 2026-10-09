<script setup lang="ts">
import type { SimulationSummary } from '~/composables/useApi'

const api = useApi()
const recent = ref<SimulationSummary[]>([])
const total = ref<number | null>(null)
const counts = ref<Record<string, number>>({})
const error = ref<string | null>(null)

const tiles = ['running', 'queued', 'completed', 'failed'] as const

onMounted(async () => {
  const { data, error: err } = await api.GET('/simulations', { params: { query: { limit: 8 } } })
  if (err || !data) {
    error.value = errorMessage(err, 'Could not reach the API')
    return
  }
  recent.value = data.simulations
  total.value = data.total
  // One count per tile: `total` of a 1-row page.
  await Promise.all(tiles.map(async (status) => {
    const { data: page } = await api.GET('/simulations', { params: { query: { status, limit: 1 } } })
    counts.value[status] = page?.total ?? 0
  }))
})
</script>

<template>
  <div>
    <PageHeader title="Compose simulations on HPC" description="Submit process-bigraph composites and COMBINE archives to the UConn Health SLURM cluster, follow them live, and browse what they produced.">
      <template #actions>
        <UButton to="/simulations/new" icon="i-lucide-play" label="Run a simulation" size="lg" />
      </template>
    </PageHeader>

    <UContainer class="py-8 flex flex-col gap-8">
      <UAlert v-if="error" color="error" variant="subtle" icon="i-lucide-circle-alert" :description="error" />

      <div class="grid grid-cols-2 md:grid-cols-5 gap-4">
        <UCard>
          <p class="text-sm text-muted">All simulations</p>
          <p class="text-3xl font-bold tabular-nums">{{ total ?? '—' }}</p>
        </UCard>
        <NuxtLink v-for="s in tiles" :key="s" :to="{ path: '/simulations', query: { status: s } }">
          <UCard class="hover:ring-primary transition">
            <p class="text-sm text-muted capitalize">{{ s }}</p>
            <p class="text-3xl font-bold tabular-nums">{{ counts[s] ?? '—' }}</p>
          </UCard>
        </NuxtLink>
      </div>

      <section class="flex flex-col gap-3">
        <div class="flex items-center justify-between">
          <h2 class="text-lg font-semibold">Recent simulations</h2>
          <UButton to="/simulations" variant="link" trailing-icon="i-lucide-arrow-right" label="All simulations" />
        </div>
        <div class="grid gap-2">
          <NuxtLink
            v-for="s in recent"
            :key="s.simulation_id"
            :to="`/simulations/${s.simulation_id}`"
            class="flex items-center gap-4 px-4 py-3 rounded-lg border border-default hover:bg-elevated"
          >
            <span class="font-mono text-muted w-16">#{{ s.simulation_id }}</span>
            <StatusBadge :status="s.status" />
            <span class="truncate">{{ s.simulator ?? s.container_def_hash.slice(0, 12) }}</span>
            <span class="ml-auto text-sm text-muted">{{ formatTime(s.created_at) }}</span>
          </NuxtLink>
        </div>
      </section>
    </UContainer>
  </div>
</template>
