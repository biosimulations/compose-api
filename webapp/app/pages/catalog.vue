<script setup lang="ts">
import type { TableColumn } from '@nuxt/ui'
import type { Schemas } from '~/composables/useApi'

// The catalog (docs/plan-sedml.md, "Concepts"): every registry entry, how far it is trusted (its curation level and
// the evidence for it), and which of this deployment's environments provide its classes. Discovery and trust, not
// runnability: most `listed` entries are in no environment. What an environment provides is on /environments.
type Entry = Schemas['CatalogEntry']
const LEVELS = ['curated', 'validated', 'tested', 'installable', 'listed'] as const
const LEVEL_HELP: Record<string, string> = {
  // docs/strategy.md, decision 5
  listed: 'discovered from the catalog; pinned to a commit',
  installable: 'its environment spec builds; the result has a digest',
  tested: 'its own test suite passes inside that environment, in our CI; runs on the cluster',
  validated: 'a study confirms it against a published reference or an independent simulator',
  curated: 'all of the above, plus documentation, declared port types and units, and a named reviewer'
}

const entries = ref<Entry[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const filter = ref('')
const level = ref<typeof LEVELS[number] | undefined>(undefined)

onMounted(async () => {
  const { data, error: err } = await useApi().GET('/registry/entries')
  loading.value = false
  if (err || !data) error.value = errorMessage(err, 'Could not load the catalog')
  entries.value = data ?? []
})

const shown = computed(() => {
  const f = filter.value.toLowerCase()
  return entries.value.filter(e =>
    (!level.value || e.level === level.value)
    && (!f || `${e.id} ${e.package} ${e.module_roots.join(' ')}`.toLowerCase().includes(f)))
})
const counts = computed(() => Object.fromEntries(LEVELS.map(l => [l, entries.value.filter(e => e.level === l).length])))

const UBadge = resolveComponent('UBadge')
const ULink = resolveComponent('ULink')
const levelColor = (l: string) => (l === 'listed' ? 'neutral' : l === 'installable' ? 'warning' : 'success')
const repo = (e: Entry) => e.source.replace(/\.git$/, '')

const columns: TableColumn<Entry>[] = [
  {
    accessorKey: 'id',
    header: 'Entry',
    cell: ({ row }) => h('div', { class: 'flex flex-col' }, [
      h(ULink, { to: repo(row.original), target: '_blank', class: 'font-medium hover:underline' }, () => row.original.id),
      h('span', { class: 'font-mono text-xs text-muted' }, row.original.module_roots.join(', '))
    ])
  },
  {
    accessorKey: 'level',
    header: 'Level',
    cell: ({ row }) => h(UBadge, { color: levelColor(row.original.level), variant: 'subtle', title: LEVEL_HELP[row.original.level] }, () => row.original.level)
  },
  {
    id: 'pin',
    header: 'Pinned at',
    cell: ({ row }) => row.original.version
      ? h('span', { class: 'font-mono text-xs' }, row.original.version)
      : h(ULink, { to: `${repo(row.original)}/tree/${row.original.commit}`, target: '_blank', class: 'font-mono text-xs hover:underline' }, () => row.original.commit?.slice(0, 12))
  },
  {
    id: 'environments',
    header: 'Environments',
    cell: ({ row }) => row.original.environments?.length
      ? h('div', { class: 'flex flex-wrap gap-1' }, row.original.environments.map(env =>
          h(ULink, { to: `/environments/${encodeURIComponent(env.name)}` }, () =>
            h(UBadge, { color: 'primary', variant: 'outline', size: 'sm' }, () => `${env.name} · ${env.components}`))))
      : h('span', { class: 'text-xs text-dimmed' }, 'no environment here')
  },
  {
    id: 'evidence',
    header: 'Evidence',
    cell: ({ row }) => h('div', { class: 'text-xs text-muted max-w-xl whitespace-normal' }, row.original.evidence?.join(' ') || '—')
  }
]
</script>

<template>
  <div>
    <PageHeader
      title="Catalog"
      description="What exists in the ecosystem and how far each package is trusted. What an environment can run is on Environments."
    >
      <template #actions>
        <UButton to="/environments" icon="i-lucide-package-check" label="Environments" color="neutral" variant="subtle" />
      </template>
    </PageHeader>
    <UContainer class="py-6 flex flex-col gap-4">
      <UAlert v-if="error" color="error" variant="subtle" icon="i-lucide-circle-alert" :description="error" />
      <div class="flex flex-wrap items-center gap-2">
        <UInput v-model="filter" placeholder="Filter by name or module" icon="i-lucide-search" class="w-72" />
        <AnySelect
          v-model="level"
          :items="LEVELS.map(l => ({ label: `${l} (${counts[l] ?? 0})`, value: l }))"
          placeholder="Any level"
          class="w-48"
        />
        <span class="text-sm text-muted">{{ shown.length }} of {{ entries.length }} entries</span>
      </div>
      <p class="text-sm text-muted">
        Levels, lowest first: <b>listed</b> (discovered and pinned), <b>installable</b> (its environment builds),
        <b>tested</b> (its tests pass in our CI; the minimum to run on the cluster), <b>validated</b> (confirmed against
        a reference or an independent simulator), <b>curated</b> (documented, typed and reviewed). Hover a level for more.
      </p>
      <UTable :data="shown" :columns="columns" :loading="loading" empty="No entries match." />
    </UContainer>
  </div>
</template>
