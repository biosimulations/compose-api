<script setup lang="ts">
import type { TableColumn, TableRow } from '@nuxt/ui'
import type { Dataset } from '~/composables/useApi'
import { isDirectoryDataset, viewersFor } from '~/viewers/registry'

// A page of datasets. A row a viewer is registered for opens its page (/datasets/<id>) when clicked, and its name is
// that link (to open in a new tab); the others are not clickable. Download is shown where it applies (not for a
// directory, a zarr store, nor a file no longer available), its place kept so the buttons stay in a column. After
// ../platform/frontend/app/components/FilesOutputsTable.vue.
const props = defineProps<{ datasets: Dataset[], showSimulation?: boolean, loading?: boolean }>()

const UButton = resolveComponent('UButton')
const UBadge = resolveComponent('UBadge')
const NuxtLink = resolveComponent('NuxtLink')
const error = ref<string | null>(null)
const viewable = (d: Dataset) => d.available && viewersFor(d).length > 0
function view(_: Event, row: TableRow<Dataset>) {
  if (viewable(row.original)) navigateTo(`/datasets/${row.original.id}`)
}
const meta = { class: { tr: (row: TableRow<Dataset>) => (viewable(row.original) ? 'cursor-pointer' : 'cursor-default hover:!bg-transparent') } }

async function save(d: Dataset) {
  try {
    await downloadFile(`/datasets/${d.id}/content`, {}, d.path.split('/').pop() || d.display_name)
  } catch (e) {
    error.value = (e as Error).message
  }
}

const columns = computed<TableColumn<Dataset>[]>(() => [
  ...(props.showSimulation
    ? [{
        accessorKey: 'simulation_id',
        header: 'Simulation',
        cell: ({ row }) => h(NuxtLink, { to: `/simulations/${row.original.simulation_id}`, class: 'text-primary' }, () => `#${row.original.simulation_id}`)
      } satisfies TableColumn<Dataset>]
    : []),
  {
    accessorKey: 'display_name',
    header: 'Name',
    cell: ({ row }) => h('div', { class: 'flex flex-col' }, [
      viewable(row.original)
        ? h(NuxtLink, { to: `/datasets/${row.original.id}`, class: 'font-medium text-primary' }, () => row.original.display_name)
        : h('span', { class: 'font-medium' }, row.original.display_name),
      h('span', { class: 'text-xs text-muted font-mono' }, row.original.path)
    ])
  },
  { accessorKey: 'kind', header: 'Kind', cell: ({ row }) => h(UBadge, { variant: 'soft', color: 'neutral' }, () => row.original.kind) },
  { accessorKey: 'media_type', header: 'Type', cell: ({ row }) => h('span', { class: 'text-xs' }, row.original.media_type) },
  { accessorKey: 'size_bytes', header: 'Size', cell: ({ row }) => formatBytes(row.original.size_bytes) },
  { accessorKey: 'origin', header: 'Origin' },
  {
    id: 'actions',
    cell: ({ row }) => {
      const d = row.original
      const downloadable = d.available && !isDirectoryDataset(d)
      return h('div', { class: 'flex justify-end' }, [
        h(UButton, { icon: 'i-lucide-download', variant: 'ghost', color: 'neutral', title: 'Download', 'aria-label': 'Download', onClick: () => save(d), class: downloadable ? '' : 'invisible' })
      ])
    }
  }
])
</script>

<template>
  <div>
    <UAlert v-if="error" color="error" variant="subtle" :description="error" class="mb-2" />
    <UTable :data="datasets" :columns="columns" :meta="meta" :loading="loading" empty="No datasets recorded." @select="view" />
  </div>
</template>
