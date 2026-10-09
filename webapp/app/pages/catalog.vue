<script setup lang="ts">
import type { TableColumn, TabsItem } from '@nuxt/ui'
import type { Schemas } from '~/composables/useApi'

// What this deployment can run: simulator container versions, and the processes and steps they register.
type Compute = Schemas['BiGraphProcess']
type Version = Schemas['SimulatorVersion']

const api = useApi()
const versions = ref<Version[]>([])
const processes = ref<Compute[]>([])
const steps = ref<Compute[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const filter = ref('')

onMounted(async () => {
  const [v, p, s] = await Promise.all([
    api.GET('/core/simulator/list'),
    api.GET('/core/processes/list'),
    api.GET('/core/steps/list')
  ])
  loading.value = false
  const failed = [v, p, s].find(r => r.error)
  if (failed) error.value = errorMessage(failed.error, 'Could not load the catalog')
  versions.value = v.data?.versions ?? []
  processes.value = p.data ?? []
  steps.value = s.data ?? []
})

const match = (c: Compute) => !filter.value || `${c.module}.${c.name}`.toLowerCase().includes(filter.value.toLowerCase())

const computeColumns: TableColumn<Compute>[] = [
  { accessorKey: 'name', header: 'Name', cell: ({ row }) => h('span', { class: 'font-medium' }, row.original.name) },
  { accessorKey: 'module', header: 'Module', cell: ({ row }) => h('span', { class: 'font-mono text-xs' }, row.original.module) },
  { accessorKey: 'inputs', header: 'Inputs', cell: ({ row }) => h('code', { class: 'text-xs whitespace-pre-wrap break-all' }, row.original.inputs) },
  { accessorKey: 'outputs', header: 'Outputs', cell: ({ row }) => h('code', { class: 'text-xs whitespace-pre-wrap break-all' }, row.original.outputs) }
]

const versionColumns: TableColumn<Version>[] = [
  { accessorKey: 'database_id', header: 'ID' },
  { accessorKey: 'container_def_hash', header: 'Container hash', cell: ({ row }) => h('span', { class: 'font-mono text-xs' }, row.original.container_def_hash) },
  { accessorKey: 'packages', header: 'Packages', cell: ({ row }) => (row.original.packages ?? []).map(p => p.name).join(', ') || '—' },
  { accessorKey: 'created_at', header: 'Created', cell: ({ row }) => formatTime(row.original.created_at) }
]

const tabs = computed<TabsItem[]>(() => [
  { label: `Processes (${processes.value.length})`, slot: 'processes' as const },
  { label: `Steps (${steps.value.length})`, slot: 'steps' as const },
  { label: `Simulator versions (${versions.value.length})`, slot: 'versions' as const }
])
</script>

<template>
  <div>
    <PageHeader title="Catalog" description="Simulator containers this deployment has built, and the process-bigraph processes and steps they provide." />
    <UContainer class="py-6 flex flex-col gap-4">
      <UAlert v-if="error" color="error" variant="subtle" icon="i-lucide-circle-alert" :description="error" />
      <UTabs :items="tabs" variant="link">
        <template #processes>
          <UInput v-model="filter" placeholder="Filter by module or name" icon="i-lucide-search" class="w-72 my-3" />
          <UTable :data="processes.filter(match)" :columns="computeColumns" :loading="loading" />
        </template>
        <template #steps>
          <UInput v-model="filter" placeholder="Filter by module or name" icon="i-lucide-search" class="w-72 my-3" />
          <UTable :data="steps.filter(match)" :columns="computeColumns" :loading="loading" />
        </template>
        <template #versions>
          <UTable :data="versions" :columns="versionColumns" :loading="loading" class="mt-3" />
        </template>
      </UTabs>
    </UContainer>
  </div>
</template>
