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
const page = ref(Number(route.query.page ?? 1))

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

watch([status, simulator, since], () => {
  page.value = 1
})
watch([status, simulator, since, page], () => {
  router.replace({
    query: {
      status: status.value || undefined,
      simulator: simulator.value || undefined,
      since: since.value || undefined,
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
  { accessorKey: 'status', header: 'Status', cell: ({ row }) => h(StatusBadge, { status: row.original.status }) },
  {
    accessorKey: 'simulator',
    header: 'Simulator',
    cell: ({ row }) => row.original.simulator
      ? h('span', { class: 'block max-w-72 truncate', title: row.original.simulator }, row.original.simulator)
      : h('span', { class: 'font-mono text-xs text-muted', title: row.original.container_def_hash }, `built ${row.original.container_def_hash.slice(0, 10)}`)
  },
  {
    accessorKey: 'experiment_id',
    header: 'Experiment',
    cell: ({ row }) => h('span', { class: 'block max-w-56 truncate font-mono text-xs', title: row.original.experiment_id }, row.original.experiment_id)
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
        <USelect v-model="status" :items="[...STATUSES]" placeholder="Any status" class="w-44" clearable />
        <UInput v-model.lazy="simulator" placeholder="Simulator name or hash prefix" icon="i-lucide-cpu" class="w-64" />
        <UInput v-model="since" type="date" class="w-44" title="Submitted on or after" />
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
