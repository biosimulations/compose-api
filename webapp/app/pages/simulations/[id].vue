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

// Its owner makes it public or private (docs/plan-favorites-and-studies.md, step 1b); the other runs of a comparison
// it is in change with it, so the comparison stays readable as a whole.
const changingVisibility = ref(false)
const visibilityNote = ref<string | null>(null)
async function changeVisibility() {
  if (!sim.value) return
  const visibility = sim.value.visibility === 'private' ? 'public' : 'private'
  changingVisibility.value = true
  visibilityNote.value = null
  const { data, error: err } = await api.PATCH('/simulations/{simulation_id}', {
    params: { path: { simulation_id: id } },
    body: { visibility }
  })
  changingVisibility.value = false
  if (err || !data) {
    visibilityNote.value = errorMessage(err, 'Could not change its visibility')
    return
  }
  sim.value = { ...sim.value, visibility: data.visibility }
  const others = data.simulation_ids.filter(i => i !== id)
  if (others.length) visibilityNote.value = `The other runs of its comparison are ${data.visibility} too: ${others.map(i => `#${i}`).join(', ')}`
}

const fields = computed(() => {
  const s = sim.value
  if (!s) return []
  // the experiment id is the page's subtitle; the simulator and its container hash are on the page "Ran in" links to;
  // the trace and correlation ids are on the Events and trace tab
  return [
    ['Submitted', formatTime(s.created_at)],
    ['Started', formatTime(s.start_time)],
    ['Ended', formatTime(s.end_time)],
    ['SLURM job', s.slurm_job_id ?? '—'],
    ['Exit code', s.exit_code ?? '—']
  ] as const
})
</script>

<template>
  <div>
    <PageHeader :title="`Simulation #${id}`" :description="sim?.experiment_id">
      <template #actions>
        <FavoriteStar v-if="sim" v-model="sim.favorite" kind="simulation" :ref-id="id" size="md" />
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
            <!-- the run itself: what it ran in and when; its environment's build is on the page "Ran in" links to, its
                 input on the Input tab -->
            <div class="flex flex-col gap-4 pt-4 max-w-3xl">
              <UAlert
                v-if="sim?.error_message"
                color="error"
                variant="subtle"
                icon="i-lucide-circle-x"
                title="Error"
                :description="sim.error_message"
              />
              <UAlert
                v-if="build?.error_message"
                color="error"
                variant="subtle"
                icon="i-lucide-hammer"
                title="Its environment's image did not build"
                :description="build.error_message"
              />
              <UCard>
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
                  <template v-if="sim">
                    <dt class="text-muted">Visibility</dt>
                    <dd class="flex flex-wrap items-center gap-2">
                      <UBadge
                        :icon="sim.visibility === 'private' ? 'i-lucide-lock' : 'i-lucide-globe'"
                        :color="sim.visibility === 'private' ? 'warning' : 'neutral'"
                        variant="subtle"
                        :label="sim.visibility === 'private' ? 'Private: you and administrators' : 'Public: anyone with the link'"
                      />
                      <UButton
                        v-if="sim.mine"
                        size="xs"
                        variant="link"
                        :label="sim.visibility === 'private' ? 'Make public' : 'Make private'"
                        :loading="changingVisibility"
                        @click="changeVisibility"
                      />
                      <span v-if="visibilityNote" class="w-full text-xs text-muted">{{ visibilityNote }}</span>
                    </dd>
                  </template>
                  <template v-for="[k, v] in fields" :key="k">
                    <dt class="text-muted">{{ k }}</dt>
                    <dd class="font-mono text-xs break-all self-center">{{ v }}</dd>
                  </template>
                </dl>
              </UCard>
            </div>
          </template>
          <template #input>
            <div v-if="input && opened.has('input')" class="pt-4 flex flex-col gap-3">
              <div class="flex flex-wrap items-center gap-2 text-sm">
                <span class="font-mono text-xs break-all">{{ input.path }}</span>
                <UBadge variant="outline" color="neutral">{{ formatBytes(input.size_bytes) }}</UBadge>
                <!-- the interval it was submitted to run for -->
                <UBadge v-if="input.attributes?.end_time != null" variant="outline" color="neutral">run to t = {{ input.attributes.end_time }}</UBadge>
                <UTooltip v-if="input.sha256" :text="`SHA-256 ${input.sha256}`">
                  <span class="font-mono text-xs text-muted">sha256 {{ input.sha256.slice(0, 12) }}…</span>
                </UTooltip>
                <span class="grow" />
                <UButton v-if="input.available" icon="i-lucide-download" variant="ghost" color="neutral" label="Download" @click="saveInput(input)" />
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
                      <UButton v-if="f.available" icon="i-lucide-maximize-2" variant="ghost" color="neutral" size="sm" title="Full size" aria-label="Full size" :to="`/datasets/${f.id}`" />
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
                <div class="flex flex-wrap items-baseline gap-x-3">
                  <h3 class="font-semibold">Trace</h3>
                  <!-- what the API, the job and the logs share (the trace id is derived from it) -->
                  <span v-if="run?.correlation_id" class="text-sm text-muted font-mono">correlation {{ run.correlation_id }}</span>
                </div>
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
