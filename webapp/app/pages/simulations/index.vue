<script setup lang="ts">
import type { TableColumn } from '@nuxt/ui'
import type { SimulationSummary } from '~/composables/useApi'

// Paged, filterable list. After ../platform/frontend/app/pages/simulations/index.vue; the filters live in the
// query string so a filtered view can be linked.
const api = useApi()
const route = useRoute()
const router = useRouter()

const PAGE = 25
const status = ref<typeof STATUSES[number] | undefined>(route.query.status as typeof STATUSES[number] | undefined)
const simulator = ref<string>((route.query.simulator as string) ?? '')
const since = ref<string>((route.query.since as string) ?? '')
// label=key:value and tag=name, each repeatable, all required (docs/plan-sedml.md, phase 0)
const asList = (v: unknown) => (Array.isArray(v) ? v : v ? [v] : []).map(String)
const labels = ref<string[]>(asList(route.query.label))
const tags = ref<string[]>(asList(route.query.tag))
const page = ref(Number(route.query.page ?? 1))
// only the runs the signed-in caller submitted (docs/plan-favorites-and-studies.md, step 1a); offered when signed in
const { isAuthenticated } = useAuth()
const mine = ref(route.query.mine === 'true')
// where the runs ran: set by the links on environment, version and simulator pages (plan-webapp-admin 5c)
const ranIn = ref({
  environment: (route.query.environment as string) || undefined,
  environment_version: (route.query.environment_version as string) || undefined,
  simulator_id: route.query.simulator_id ? Number(route.query.simulator_id) : undefined
})
const ranInLabel = computed(() => ranIn.value.environment_version ?? ranIn.value.environment
  ?? (ranIn.value.simulator_id != null ? `simulator ${ranIn.value.simulator_id}` : null))
function clearRanIn() {
  ranIn.value = { environment: undefined, environment_version: undefined, simulator_id: undefined }
}

const rows = ref<SimulationSummary[]>([])
const total = ref(0)
const loading = ref(false)
const error = ref<string | null>(null)

async function load() {
  loading.value = true
  const { data, error: err } = await api.GET('/simulations', {
    params: {
      query: {
        status: status.value || undefined,
        simulator: simulator.value || undefined,
        since: since.value ? new Date(since.value).toISOString() : undefined,
        label: labels.value.length ? labels.value : undefined,
        tag: tags.value.length ? tags.value : undefined,
        mine: mine.value && isAuthenticated.value ? true : undefined,
        ...ranIn.value,
        limit: PAGE,
        offset: (page.value - 1) * PAGE
      }
    }
  })
  loading.value = false
  if (err || !data) {
    error.value = errorMessage(err, 'Could not load simulations')
    return
  }
  error.value = null
  rows.value = data.simulations
  total.value = data.total
}

watch([status, simulator, since, labels, tags, ranIn, mine], () => {
  page.value = 1
})
watch([status, simulator, since, labels, tags, ranIn, mine, page], () => {
  router.replace({
    query: {
      status: status.value || undefined,
      simulator: simulator.value || undefined,
      since: since.value || undefined,
      label: labels.value.length ? labels.value : undefined,
      tag: tags.value.length ? tags.value : undefined,
      mine: mine.value ? 'true' : undefined,
      ...ranIn.value,
      page: page.value > 1 ? page.value : undefined
    }
  })
  load()
})

// Refresh while anything on the page is still moving. GET /results/simulations/status/batch would be cheaper,
// but it takes a JSON body on a GET, which browsers cannot send.
const live = computed(() => rows.value.some(r => !isTerminal(r.status)))
onMounted(load)
useIntervalFn(() => {
  if (live.value && !loading.value) load()
}, 10000)

const UButton = resolveComponent('UButton')
const NuxtLink = resolveComponent('NuxtLink')
const StatusBadge = resolveComponent('StatusBadge')
const RunLabels = resolveComponent('RunLabels')
const RanIn = resolveComponent('RanIn')

// a chip clicked elsewhere (the detail page, this table) navigates here with a new query: follow it
watch(() => route.query, (q) => {
  const nextLabels = asList(q.label)
  const nextTags = asList(q.tag)
  if (nextLabels.join('\n') !== labels.value.join('\n')) labels.value = nextLabels
  if (nextTags.join('\n') !== tags.value.join('\n')) tags.value = nextTags
})

async function saveResults(id: number) {
  try {
    await downloadFile('/results/simulation/results/file', { simulation_id: id }, `simulation-${id}-results.zip`)
  } catch (e) {
    error.value = (e as Error).message
  }
}

const columns: TableColumn<SimulationSummary>[] = [
  {
    accessorKey: 'simulation_id',
    header: 'ID',
    cell: ({ row }) => h(NuxtLink, { to: `/simulations/${row.original.simulation_id}`, class: 'font-mono text-primary' }, () => `#${row.original.simulation_id}`)
  },
  { accessorKey: 'status', header: 'Status', cell: ({ row }) => h(StatusBadge, { status: row.original.status, submission: row.original.submission }) },
  {
    accessorKey: 'simulator',
    header: 'Simulator',
    cell: ({ row }) => row.original.simulator
      ? h('span', { class: 'block max-w-72 truncate', title: row.original.simulator }, row.original.simulator)
      : h('span', { class: 'font-mono text-xs text-muted', title: row.original.container_def_hash }, `built ${row.original.container_def_hash.slice(0, 10)}`)
  },
  {
    id: 'ran_in',
    header: 'Ran in',
    cell: ({ row }) => h(RanIn, { version: row.original.environment_version, simulatorId: row.original.simulator_id, class: 'text-xs whitespace-nowrap' })
  },
  {
    accessorKey: 'experiment_id',
    header: 'Experiment',
    cell: ({ row }) => h('span', { class: 'block max-w-56 truncate font-mono text-xs', title: row.original.experiment_id }, row.original.experiment_id)
  },
  {
    id: 'labels',
    header: 'Labels and tags',
    cell: ({ row }) => h(RunLabels, { labels: row.original.labels, tags: row.original.tags, size: 'sm', class: 'max-w-96' })
  },
  { accessorKey: 'created_at', header: 'Submitted', cell: ({ row }) => formatTime(row.original.created_at) },
  { accessorKey: 'slurm_job_id', header: 'SLURM job', cell: ({ row }) => row.original.slurm_job_id ?? '—' },
  {
    id: 'actions',
    cell: ({ row }) => h('div', { class: 'flex justify-end gap-1' }, [
      h(UButton, { icon: 'i-lucide-eye', variant: 'ghost', color: 'neutral', title: 'Details', to: `/simulations/${row.original.simulation_id}` }),
      h(UButton, {
        icon: 'i-lucide-file-archive',
        variant: 'ghost',
        color: 'neutral',
        title: 'Download results.zip',
        disabled: row.original.status !== 'completed',
        onClick: () => saveResults(row.original.simulation_id)
      })
    ])
  }
]
</script>

<template>
  <div>
    <PageHeader title="Simulations" :description="`${total} simulations, newest first`">
      <template #actions>
        <UButton to="/simulations/new" icon="i-lucide-play" label="Run a simulation" />
      </template>
    </PageHeader>
    <UContainer class="py-6 flex flex-col gap-4">
      <div class="flex flex-wrap items-center gap-2">
        <AnySelect v-model="status" :items="STATUSES" placeholder="Any status" class="w-44" />
        <UInput v-model.lazy="simulator" placeholder="Simulator name or hash prefix" icon="i-lucide-cpu" class="w-64" />
        <UInput v-model="since" type="date" class="w-44" title="Submitted on or after" />
        <UInputTags v-model="labels" placeholder="Label key:value" icon="i-lucide-filter" class="w-64" title="Labels, e.g. source:biomodels; all must match" />
        <UInputTags v-model="tags" placeholder="Tag" icon="i-lucide-tag" class="w-56" title="Tags; all must match" />
        <USwitch v-if="isAuthenticated" v-model="mine" label="Mine" title="Only the runs you submitted, signed in" />
        <UButton v-if="ranInLabel" icon="i-lucide-x" :label="`Ran in ${ranInLabel}`" color="primary" variant="subtle" size="sm" title="Show runs from anywhere" @click="clearRanIn" />
        <UButton icon="i-lucide-refresh-cw" variant="ghost" color="neutral" :loading="loading" @click="load" />
      </div>
      <UAlert v-if="error" color="error" variant="subtle" icon="i-lucide-circle-alert" :description="error" />
      <UTable :data="rows" :columns="columns" :loading="loading" empty="No simulations match." />
      <div class="flex justify-end">
        <UPagination v-model:page="page" :total="total" :items-per-page="PAGE" />
      </div>
    </UContainer>
  </div>
</template>
