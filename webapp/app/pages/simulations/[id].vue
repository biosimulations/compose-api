<script setup lang="ts">
import type { TabsItem } from '@nuxt/ui'
import type { Dataset, HpcRun, SimulationDetail } from '~/composables/useApi'

const route = useRoute()
const id = Number(route.params.id)
const api = useApi()

const sim = ref<SimulationDetail | null>(null)
const run = ref<HpcRun | null>(null)
const build = ref<HpcRun | null>(null)
const datasets = ref<Dataset[]>([])
const notFound = ref(false)
const error = ref<string | null>(null)

const live = computed(() => !!sim.value && !isTerminal(sim.value.status))

async function loadDatasets() {
  const { data } = await api.GET('/datasets', { params: { query: { simulation_id: id, limit: 1000 } } })
  datasets.value = data?.datasets ?? []
}

const checking = ref(false)

async function refresh() {
  checking.value = true
  try {
    await load()
  } finally {
    checking.value = false
  }
  if (notFound.value || isTerminal(sim.value?.status)) poll.pause()
}

async function load() {
  const { data, error: err, response } = await api.GET('/simulations/{simulation_id}', { params: { path: { simulation_id: id } } })
  if (response.status === 404) {
    notFound.value = true
    return
  }
  if (err || !data) {
    error.value = errorMessage(err, 'Could not load the simulation')
    return
  }
  error.value = null
  sim.value = data
  const [status, builds] = await Promise.all([
    api.GET('/results/simulation/status', { params: { query: { simulation_id: id } } }),
    api.GET('/results/simulator/build/status', { params: { query: { simulator_id: data.simulator_id } } })
  ])
  run.value = status.data ?? null
  build.value = builds.data ?? null
  await loadDatasets()
}

// Poll until the run is terminal, as ../platform/frontend/app/pages/simulations/check-status/[processing_id].vue does.
const poll = useTimeoutPoll(refresh, 5000, { immediate: true, immediateCallback: true })

async function saveResults() {
  try {
    await downloadFile('/results/simulation/results/file', { simulation_id: id }, `simulation-${id}-results.zip`)
  } catch (e) {
    error.value = (e as Error).message
  }
}

const tabs = computed<TabsItem[]>(() => [
  { label: 'Overview', icon: 'i-lucide-info', slot: 'overview' as const, value: 'overview' },
  { label: `Events${sim.value ? ` (${sim.value.event_count})` : ''}`, icon: 'i-lucide-scroll-text', slot: 'events' as const, value: 'events' },
  { label: 'Trace', icon: 'i-lucide-chart-gantt', slot: 'trace' as const, value: 'trace' },
  { label: `Datasets (${datasets.value.length})`, icon: 'i-lucide-files', slot: 'datasets' as const, value: 'datasets' }
])
const tab = ref((route.query.tab as string) || 'overview')
watch(tab, t => navigateTo({ query: { ...route.query, tab: t } }, { replace: true }))

const fields = computed(() => {
  const s = sim.value
  if (!s) return []
  return [
    ['Experiment', s.experiment_id],
    ['Simulator', s.simulator ?? 'Built from the registry container'],
    ['Container hash', s.container_def_hash],
    ['Visibility', s.visibility],
    ['Submitted', formatTime(s.created_at)],
    ['Started', formatTime(s.start_time)],
    ['Ended', formatTime(s.end_time)],
    ['SLURM job', s.slurm_job_id ?? '—'],
    ['Exit code', s.exit_code ?? '—'],
    ['Trace', s.trace_id ?? '—'],
    ['Correlation id', run.value?.correlation_id ?? '—']
  ] as const
})
</script>

<template>
  <div>
    <PageHeader :title="`Simulation #${id}`" :description="sim?.experiment_id">
      <template #actions>
        <StatusBadge v-if="sim" :status="sim.status" class="text-sm" />
        <UButton
          icon="i-lucide-file-archive"
          label="results.zip"
          :disabled="sim?.status !== 'completed'"
          @click="saveResults"
        />
      </template>
    </PageHeader>

    <UContainer class="py-6 flex flex-col gap-4">
      <UAlert v-if="notFound" color="neutral" variant="subtle" icon="i-lucide-search-x" title="Not found" description="This simulation does not exist, or you may not read it." />
      <template v-else>
        <UAlert v-if="error" color="error" variant="subtle" icon="i-lucide-circle-alert" :description="error" />
        <div v-if="live" class="flex items-center gap-2 text-sm text-muted">
          <UIcon name="i-lucide-loader-circle" class="animate-spin" />
          <span>{{ checking ? 'Checking…' : 'Updates every 5 seconds' }}</span>
          <UButton size="xs" variant="link" label="Check now" :disabled="checking" @click="refresh" />
        </div>

        <UTabs v-model="tab" :items="tabs" variant="link" class="w-full" :unmount-on-hide="false">
          <template #overview>
            <div class="grid lg:grid-cols-2 gap-4 pt-4">
              <UCard>
                <template #header><h3 class="font-semibold">Run</h3></template>
                <dl class="grid grid-cols-[9rem_1fr] gap-y-2 text-sm">
                  <template v-for="[k, v] in fields" :key="k">
                    <dt class="text-muted">{{ k }}</dt>
                    <dd class="font-mono text-xs break-all self-center">{{ v }}</dd>
                  </template>
                </dl>
              </UCard>
              <div class="flex flex-col gap-4">
                <UAlert
                  v-if="sim?.error_message"
                  color="error"
                  variant="subtle"
                  icon="i-lucide-circle-x"
                  title="Error"
                  :description="sim.error_message"
                />
                <UCard v-if="build">
                  <template #header>
                    <div class="flex items-center justify-between">
                      <h3 class="font-semibold">Container build</h3>
                      <StatusBadge :status="build.status" />
                    </div>
                  </template>
                  <dl class="grid grid-cols-[9rem_1fr] gap-y-2 text-sm">
                    <dt class="text-muted">SLURM job</dt><dd class="font-mono text-xs">{{ build.slurmjobid }}</dd>
                    <dt class="text-muted">Started</dt><dd>{{ formatTime(build.start_time) }}</dd>
                    <dt class="text-muted">Ended</dt><dd>{{ formatTime(build.end_time) }}</dd>
                    <template v-if="build.error_message">
                      <dt class="text-muted">Error</dt><dd class="text-error text-xs">{{ build.error_message }}</dd>
                    </template>
                  </dl>
                </UCard>
                <UCard>
                  <template #header><h3 class="font-semibold">Recorded</h3></template>
                  <div class="flex gap-8">
                    <button class="text-left" @click="tab = 'events'">
                      <p class="text-3xl font-bold tabular-nums">{{ sim?.event_count ?? '—' }}</p>
                      <p class="text-sm text-muted">events</p>
                    </button>
                    <button class="text-left" @click="tab = 'datasets'">
                      <p class="text-3xl font-bold tabular-nums">{{ sim?.dataset_count ?? '—' }}</p>
                      <p class="text-sm text-muted">datasets</p>
                    </button>
                  </div>
                </UCard>
              </div>
            </div>
          </template>
          <template #events>
            <div class="pt-4"><EventLog :simulation-id="id" :live="live" /></div>
          </template>
          <template #trace>
            <div class="pt-4"><TraceTree :simulation-id="id" :live="live" /></div>
          </template>
          <template #datasets>
            <div class="pt-4"><DatasetsTable :datasets="datasets" /></div>
          </template>
        </UTabs>
      </template>
    </UContainer>
  </div>
</template>
