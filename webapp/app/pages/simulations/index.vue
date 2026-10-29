<script setup lang="ts">
import type { TableColumn, TableRow } from '@nuxt/ui'
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
// only the runs the signed-in caller starred (step 2b)
const favorite = ref(route.query.favorite === 'true')
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
        favorite: favorite.value && isAuthenticated.value ? true : undefined,
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

watch([status, simulator, since, labels, tags, ranIn, mine, favorite], () => {
  page.value = 1
})
watch([status, simulator, since, labels, tags, ranIn, mine, favorite, page], () => {
  router.replace({
    query: {
      status: status.value || undefined,
      simulator: simulator.value || undefined,
      since: since.value || undefined,
      label: labels.value.length ? labels.value : undefined,
      tag: tags.value.length ? tags.value : undefined,
      mine: mine.value ? 'true' : undefined,
      favorite: favorite.value ? 'true' : undefined,
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

const UIcon = resolveComponent('UIcon')
const NuxtLink = resolveComponent('NuxtLink')
const FavoriteStar = resolveComponent('FavoriteStar')
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

// A row opens its run (whose page has its results.zip and SLURM job); a link or chip in it keeps its own action.
function open(e: Event, row: TableRow<SimulationSummary>) {
  if ((e.target as HTMLElement | null)?.closest('a, button')) return
  navigateTo(`/simulations/${row.original.simulation_id}`)
}
const meta = { class: { tr: 'cursor-pointer' } }

const columns: TableColumn<SimulationSummary>[] = [
  {
    accessorKey: 'simulation_id',
    header: 'ID',
    cell: ({ row }) => h('span', { class: 'inline-flex items-center gap-1' }, [
      h(FavoriteStar, {
        kind: 'simulation',
        refId: row.original.simulation_id,
        modelValue: row.original.favorite,
        'onUpdate:modelValue': (v: boolean) => { row.original.favorite = v }
      }),
      h(NuxtLink, { to: `/simulations/${row.original.simulation_id}`, class: 'font-mono text-primary' }, () => `#${row.original.simulation_id}`),
      row.original.visibility === 'private' ? h(UIcon, { name: 'i-lucide-lock', class: 'size-3.5 text-warning', title: 'Private: you and administrators' }) : null
    ])
  },
  { accessorKey: 'status', header: 'Status', cell: ({ row }) => h(StatusBadge, { status: row.original.status, submission: row.original.submission }) },
  {
    id: 'ran_in',
    header: 'Ran in',
    cell: ({ row }) => h(RanIn, { version: row.original.environment_version, simulatorId: row.original.simulator_id, class: 'text-xs whitespace-nowrap' })
  },
  {
    id: 'labels',
    header: 'Labels and tags',
    cell: ({ row }) => h(RunLabels, { labels: row.original.labels, tags: row.original.tags, size: 'sm', class: 'max-w-96' })
  },
  { accessorKey: 'created_at', header: 'Submitted', cell: ({ row }) => formatTime(row.original.created_at) },
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
        <USwitch v-if="isAuthenticated" v-model="favorite" label="Favorites" title="Only the runs you starred" />
        <UButton v-if="ranInLabel" icon="i-lucide-x" :label="`Ran in ${ranInLabel}`" color="primary" variant="subtle" size="sm" title="Show runs from anywhere" @click="clearRanIn" />
        <UButton icon="i-lucide-refresh-cw" variant="ghost" color="neutral" :loading="loading" @click="load" />
      </div>
      <UAlert v-if="error" color="error" variant="subtle" icon="i-lucide-circle-alert" :description="error" />
      <UTable :data="rows" :columns="columns" :meta="meta" :loading="loading" empty="No simulations match." @select="open" />
      <div class="flex justify-end">
        <UPagination v-model:page="page" :total="total" :items-per-page="PAGE" />
      </div>
    </UContainer>
  </div>
</template>
