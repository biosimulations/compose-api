<script setup lang="ts">
import type { TableColumn } from '@nuxt/ui'
import type { Dataset } from '~/composables/useApi'

// A page of datasets, with preview and download. After ../platform/frontend/app/components/FilesOutputsTable.vue.
const props = defineProps<{ datasets: Dataset[], showSimulation?: boolean, loading?: boolean }>()

const UButton = resolveComponent('UButton')
const UBadge = resolveComponent('UBadge')
const NuxtLink = resolveComponent('NuxtLink')
const selected = ref<Dataset | null>(null)
const open = computed({ get: () => !!selected.value, set: (v) => { if (!v) selected.value = null } })
const error = ref<string | null>(null)

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
      h('span', { class: 'font-medium' }, row.original.display_name),
      h('span', { class: 'text-xs text-muted font-mono' }, row.original.path)
    ])
  },
  { accessorKey: 'kind', header: 'Kind', cell: ({ row }) => h(UBadge, { variant: 'soft', color: 'neutral' }, () => row.original.kind) },
  { accessorKey: 'media_type', header: 'Type', cell: ({ row }) => h('span', { class: 'text-xs' }, row.original.media_type) },
  { accessorKey: 'size_bytes', header: 'Size', cell: ({ row }) => formatBytes(row.original.size_bytes) },
  { accessorKey: 'origin', header: 'Origin' },
  {
    id: 'actions',
    cell: ({ row }) => h('div', { class: 'flex justify-end gap-1' }, [
      h(UButton, { icon: 'i-lucide-eye', variant: 'ghost', color: 'neutral', title: 'Preview', disabled: !row.original.available, onClick: () => { selected.value = row.original } }),
      h(UButton, { icon: 'i-lucide-download', variant: 'ghost', color: 'neutral', title: 'Download', disabled: !row.original.available, onClick: () => save(row.original) })
    ])
  }
])
</script>

<template>
  <div>
    <UAlert v-if="error" color="error" variant="subtle" :description="error" class="mb-2" />
    <UTable :data="datasets" :columns="columns" :loading="loading" empty="No datasets recorded." />
    <UModal v-model:open="open" :title="selected?.display_name" :description="selected?.path" fullscreen>
      <template #body>
        <DatasetPreview v-if="selected" :key="selected.id" :dataset="selected" />
      </template>
    </UModal>
  </div>
</template>
