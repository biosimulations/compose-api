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
type Badge = { color: 'success' | 'error' | 'warning' | 'neutral', text: string }
type Result = { close_to_references?: boolean | null, references?: string[], reports?: Record<string, { worst?: { score?: number | string | null } }> }
const resultOf = (c: Comparison) => (c.result ?? null) as Result | null

// Whether the solvers agree with each other: the comparison's own verdict.
const agreement = (c: Comparison): Badge =>
  c.status === 'running' ? { color: 'neutral', text: 'running' }
  : c.status === 'incomplete' ? { color: 'warning', text: 'a run failed' }
  : c.close ? { color: 'success', text: 'agree' }
  : { color: 'error', text: 'differ' }

// Whether they also match the results the archive was published with, when it carried any.
const original = (c: Comparison): Badge | null => {
  const r = resultOf(c)
  if (!r?.references?.length) return null
  if (r.close_to_references === true) return { color: 'success', text: 'match' }
  if (r.close_to_references === false) return { color: 'error', text: 'differ' }
  return { color: 'neutral', text: 'not compared' }
}

// The largest score over every report (close below 1), so a near miss shows without opening the comparison.
const worst = (c: Comparison): number | null => {
  const scores = Object.values(resultOf(c)?.reports ?? {}).map(r => r.worst?.score).filter((s): s is number => typeof s === 'number')
  return scores.length ? Math.max(...scores) : null
}

const badge = (b: Badge | null) => b ? h(UBadge, { color: b.color, variant: 'subtle' }, () => b.text) : h('span', { class: 'text-muted' }, '—')

const columns: TableColumn<Comparison>[] = [
  { accessorKey: 'comparison_id', header: 'ID', cell: ({ row }) => h(NuxtLink, { to: `/comparisons/${row.original.comparison_id}`, class: 'font-mono text-primary' }, () => `#${row.original.comparison_id}`) },
  { id: 'agreement', header: 'Solvers agree', cell: ({ row }) => badge(agreement(row.original)) },
  { id: 'original', header: 'Original results', cell: ({ row }) => badge(original(row.original)) },
  {
    id: 'worst',
    header: 'Worst score',
    cell: ({ row }) => {
      const s = worst(row.original)
      return s === null ? h('span', { class: 'text-muted' }, '—') : h('span', { class: ['font-mono tabular-nums', s < 1 ? 'text-success' : 'text-error'] }, s.toPrecision(3))
    }
  },
  {
    accessorKey: 'name',
    header: 'Model and task',
    // Names are archive file names and run long; the full name and the source are in the tooltip and the detail page.
    cell: ({ row }) => h('div', { class: 'max-w-xs xl:max-w-md', title: `${row.original.name}\n${row.original.source}` }, [
      h('div', { class: 'truncate' }, row.original.name),
      h('div', { class: 'truncate text-xs font-mono text-muted' }, row.original.source)
    ])
  },
  { id: 'solvers', header: 'Solvers', cell: ({ row }) => row.original.members.map(m => m.solver).join(', ') },
  { accessorKey: 'created_at', header: 'Created', cell: ({ row }) => h('span', { class: 'whitespace-nowrap' }, formatTime(row.original.created_at)) }
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
