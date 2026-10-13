<script setup lang="ts">
import type { TableColumn } from '@nuxt/ui'
import type { Comparison } from '~/composables/useSedml'

// Comparisons: one SED-ML task run on several solvers (docs/plan-sedml.md), newest first.
const rows = ref<Comparison[]>([])
const total = ref(0)
const page = ref(1)
const PAGE = 25
const loading = ref(false)
const error = ref<string | null>(null)

async function load() {
  loading.value = true
  const { data, error: err } = await useApi().GET('/comparisons', { params: { query: { limit: PAGE, offset: (page.value - 1) * PAGE } } })
  loading.value = false
  if (err || !data) {
    error.value = errorMessage(err, 'Could not load comparisons')
    return
  }
  error.value = null
  rows.value = data.comparisons
  total.value = data.total
}
onMounted(load)
watch(page, load)

const UBadge = resolveComponent('UBadge')
const NuxtLink = resolveComponent('NuxtLink')
const verdict = (c: Comparison) =>
  c.status === 'running' ? { color: 'neutral', text: 'running' }
  : c.close ? { color: 'success', text: 'solvers agree' }
  : { color: 'error', text: c.status === 'incomplete' ? 'incomplete' : 'solvers differ' }

const columns: TableColumn<Comparison>[] = [
  { accessorKey: 'comparison_id', header: 'ID', cell: ({ row }) => h(NuxtLink, { to: `/comparisons/${row.original.comparison_id}`, class: 'font-mono text-primary' }, () => `#${row.original.comparison_id}`) },
  { accessorKey: 'name', header: 'Model and task' },
  { accessorKey: 'source', header: 'Source', cell: ({ row }) => h('span', { class: 'text-xs font-mono' }, row.original.source) },
  { id: 'solvers', header: 'Solvers', cell: ({ row }) => row.original.members.map(m => m.solver).join(', ') },
  { id: 'verdict', header: 'Result', cell: ({ row }) => { const v = verdict(row.original); return h(UBadge, { color: v.color, variant: 'subtle' }, () => v.text) } },
  { accessorKey: 'created_at', header: 'Created', cell: ({ row }) => formatTime(row.original.created_at) }
]
</script>

<template>
  <div>
    <PageHeader title="Comparisons" :description="`${total} SED-ML tasks run on several solvers`">
      <template #actions>
        <UButton to="/sedml" icon="i-lucide-play" label="Run SED-ML" />
      </template>
    </PageHeader>
    <UContainer class="py-6 flex flex-col gap-4">
      <UAlert v-if="error" color="error" variant="subtle" :description="error" />
      <UTable :data="rows" :columns="columns" :loading="loading" empty="No comparisons yet." />
      <div class="flex justify-end">
        <UPagination v-model:page="page" :total="total" :items-per-page="PAGE" />
      </div>
    </UContainer>
  </div>
</template>
