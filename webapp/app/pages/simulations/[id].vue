<script setup lang="ts">
import type { TabsItem } from '@nuxt/ui'
import type { Dataset, HpcRun, SimulationDetail } from '~/composables/useApi'
import { isFigure } from '~/viewers/kinds'
import { preloadViewer } from '~/viewers/registry'

const route = useRoute()
const id = Number(route.params.id)
const api = useApi()

const sim = ref<SimulationDetail | null>(null)
const run = ref<HpcRun | null>(null)
const build = ref<HpcRun | null>(null)
const datasets = ref<Dataset[]>([])
// The file the simulation was submitted with, announced by the job script when the run starts (kind "input").
const input = computed(() => datasets.value.find(d => d.kind === 'input') ?? null)
// The outputs a visualization is registered for (viewers/kinds.ts): plots, images, results bundles.
const figures = computed(() => datasets.value.filter(isFigure))
// Their viewers' code (the composite editor, Plotly) is fetched once the page is idle, so opening the Input or Figures
// tab waits only for the files themselves.
const preloaded = new Set<string>()
watch([input, figures], ([i, f]) => {
  const wanted = [...(i ? [i] : []), ...f].filter(d => !preloaded.has(d.id))
  if (!wanted.length) return
  wanted.forEach(d => preloaded.add(d.id))
  const idle = window.requestIdleCallback ?? ((run: () => void) => setTimeout(run, 200))
  idle(() => {
    wanted.forEach(preloadViewer)
    // the composite viewer checks the input against the manifest of the environment the run used: both are cached
    if (i && wanted.includes(i)) environmentFor(sim.value?.simulator).then(e => e && fetchManifest(e.name)).catch(() => undefined)
  })
})
const inputError = ref<string | null>(null)

async function saveInput(d: Dataset) {
  try {
    await downloadFile(`/datasets/${d.id}/content`, {}, d.path.split('/').pop() || d.display_name)
  } catch (e) {
    inputError.value = (e as Error).message
  }
}
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

// Overview, what was submitted, what it drew, what it recorded (its trace and events, one tab), and every file. The
// input and the figures load their viewers (Plotly, vtk.js) only once their tab is opened.
const tabs = computed<TabsItem[]>(() => [
  { label: 'Overview', icon: 'i-lucide-info', slot: 'overview' as const, value: 'overview' },
  { label: 'Input', icon: 'i-lucide-file-input', slot: 'input' as const, value: 'input', disabled: !input.value },
  { label: `Figures (${figures.value.length})`, icon: 'i-lucide-chart-spline', slot: 'figures' as const, value: 'figures' },
  { label: `Events and trace${sim.value ? ` (${sim.value.event_count})` : ''}`, icon: 'i-lucide-scroll-text', slot: 'events' as const, value: 'events' },
  { label: `Datasets (${datasets.value.length})`, icon: 'i-lucide-files', slot: 'datasets' as const, value: 'datasets' }
])
// `?tab=trace`, from before the trace and the events were one tab, opens that tab
const tab = ref(route.query.tab === 'trace' ? 'events' : (route.query.tab as string) || 'overview')
const opened = reactive(new Set([tab.value]))
watch(tab, (t) => {
  opened.add(t)
  navigateTo({ query: { ...route.query, tab: t } }, { replace: true })
})

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
        <StatusBadge v-if="sim" :status="sim.status" :submission="sim.submission" class="text-sm" />
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
                  <template v-if="sim?.description">
                    <dt class="text-muted">Description</dt>
                    <dd class="self-center">{{ sim.description }}</dd>
                  </template>
                  <template v-if="sim && (Object.keys(sim.labels ?? {}).length || sim.tags?.length)">
                    <dt class="text-muted">Labels and tags</dt>
                    <dd><RunLabels :labels="sim.labels" :tags="sim.tags" /></dd>
                  </template>
                  <template v-if="sim">
                    <dt class="text-muted">Ran in</dt>
                    <dd class="text-xs self-center"><RanIn :version="sim.environment_version" :simulator-id="sim.simulator_id" /></dd>
                  </template>
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
                <UCard v-if="input">
                  <template #header>
                    <div class="flex items-center justify-between">
                      <h3 class="font-semibold">Input</h3>
                      <div class="flex gap-1">
                        <UButton icon="i-lucide-eye" variant="ghost" color="neutral" title="View" :disabled="!input.available" @click="tab = 'input'" />
                        <UButton icon="i-lucide-maximize-2" variant="ghost" color="neutral" title="Open" :to="`/datasets/${input.id}`" :disabled="!input.available" />
                        <UButton icon="i-lucide-download" variant="ghost" color="neutral" title="Download" :disabled="!input.available" @click="saveInput(input)" />
                      </div>
                    </div>
                  </template>
                  <UAlert v-if="inputError" color="error" variant="subtle" :description="inputError" class="mb-2" />
                  <dl class="grid grid-cols-[9rem_1fr] gap-y-2 text-sm">
                    <dt class="text-muted">File</dt><dd class="font-mono text-xs break-all self-center">{{ input.path }}</dd>
                    <dt class="text-muted">Size</dt><dd>{{ formatBytes(input.size_bytes) }}</dd>
                    <template v-if="input.attributes?.end_time != null">
                      <dt class="text-muted">End time</dt><dd>{{ input.attributes.end_time }}</dd>
                    </template>
                    <template v-if="input.sha256">
                      <dt class="text-muted">SHA-256</dt><dd class="font-mono text-xs break-all self-center">{{ input.sha256 }}</dd>
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
          <template #input>
            <div v-if="input && opened.has('input')" class="pt-4 flex flex-col gap-3">
              <div class="flex flex-wrap items-center gap-2 text-sm">
                <span class="font-mono text-xs break-all">{{ input.path }}</span>
                <UBadge variant="outline" color="neutral">{{ formatBytes(input.size_bytes) }}</UBadge>
                <span class="grow" />
                <UButton icon="i-lucide-maximize-2" variant="ghost" color="neutral" label="Open" :to="`/datasets/${input.id}`" :disabled="!input.available" />
                <UButton icon="i-lucide-download" variant="ghost" color="neutral" label="Download" :disabled="!input.available" @click="saveInput(input)" />
              </div>
              <UAlert v-if="inputError" color="error" variant="subtle" :description="inputError" />
              <UAlert v-if="!input.available" color="neutral" variant="subtle" description="The input is no longer available." />
              <!-- the composite viewer's height, held while it loads, so the page does not jump when it appears -->
              <DatasetViewer v-else :dataset="input" class="min-h-[52rem]" />
            </div>
          </template>
          <template #figures>
            <div v-if="opened.has('figures')" class="pt-4">
              <p v-if="!figures.length" class="text-sm text-muted">
                {{ live ? 'No figures yet: they appear as the run writes them.' : 'This run wrote no figures: no plots, images or results bundles.' }}
              </p>
              <div v-else class="grid xl:grid-cols-2 gap-4">
                <UCard v-for="f in figures" :key="f.id">
                  <template #header>
                    <div class="flex items-center gap-2">
                      <h3 class="font-semibold truncate" :title="f.path">{{ f.display_name }}</h3>
                      <span class="grow" />
                      <UButton icon="i-lucide-maximize-2" variant="ghost" color="neutral" size="sm" title="Open" :to="`/datasets/${f.id}`" />
                    </div>
                  </template>
                  <p v-if="!f.available" class="text-sm text-muted">No longer available.</p>
                  <!-- a figure's height (PlotlyFigureViewer: its buttons and a 28rem chart), held while it loads -->
                  <DatasetViewer v-else :dataset="f" class="min-h-[31rem]" />
                </UCard>
              </div>
            </div>
          </template>
          <template #events>
            <div class="pt-4 flex flex-col gap-6">
              <section class="flex flex-col gap-2">
                <h3 class="font-semibold">Trace</h3>
                <TraceTree :simulation-id="id" :live="live" />
              </section>
              <section class="flex flex-col gap-2">
                <h3 class="font-semibold">Events</h3>
                <EventLog :simulation-id="id" :live="live" />
              </section>
            </div>
          </template>
          <template #datasets>
            <div class="pt-4"><DatasetsTable :datasets="datasets" /></div>
          </template>
        </UTabs>
      </template>
    </UContainer>
  </div>
</template>
