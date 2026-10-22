<script setup lang="ts">
import type { TabsItem } from '@nuxt/ui'
import type { ArchiveSource, BiomodelHit, ProjectInfo } from '~/composables/useSedml'

// SED-ML models run on several solvers (docs/plan-sedml.md): an archive you upload, a BioModels entry, or a
// biosimulations.org project, translated into one process-bigraph run per solver and compared. `?source=biomodels:ID`
// or `biosimulations:ID` opens that source directly.
const route = useRoute()
const tab = ref<string>('upload')
const source = shallowRef<ArchiveSource | null>(null)
const label = ref('')

const file = ref<File | null>(null)
watch(file, (f) => {
  if (f) open({ kind: 'upload', file: f }, f.name)
})

const query = ref('')
const searching = ref(false)
const searchError = ref<string | null>(null)
const models = ref<BiomodelHit[]>([])
const projects = ref<ProjectInfo[]>([])

function open(s: ArchiveSource, name: string) {
  source.value = s
  label.value = name
}

async function search() {
  searching.value = true
  searchError.value = null
  const api = useApi()
  try {
    if (tab.value === 'biomodels') {
      const { data, error } = await api.GET('/sources/biomodels/search', { params: { query: { q: query.value, limit: 25 } } })
      if (error) throw new Error(errorMessage(error, 'Search failed'))
      models.value = data ?? []
    } else {
      const { data, error } = await api.GET('/sources/biosimulations/projects', { params: { query: { q: query.value, limit: 25 } } })
      if (error) throw new Error(errorMessage(error, 'Search failed'))
      projects.value = data ?? []
    }
  } catch (e) {
    searchError.value = (e as Error).message
  } finally {
    searching.value = false
  }
}
watch(tab, () => {
  models.value = []
  projects.value = []
  searchError.value = null
})

onMounted(() => {
  const given = typeof route.query.source === 'string' ? route.query.source : ''
  const [kind, ...rest] = given.split(':')
  const id = rest.join(':')
  if ((kind === 'biomodels' || kind === 'biosimulations') && id) {
    tab.value = kind
    open({ kind, id }, id)
  }
})

const tabs: TabsItem[] = [
  { label: 'Upload', icon: 'i-lucide-upload', value: 'upload', slot: 'upload' as const },
  { label: 'BioModels', icon: 'i-lucide-library', value: 'biomodels', slot: 'search' as const },
  { label: 'biosimulations.org', icon: 'i-lucide-globe', value: 'biosimulations', slot: 'search' as const }
]
</script>

<template>
  <div>
    <PageHeader
      title="SED-ML on several solvers"
      description="A model described in SED-ML, translated into one process-bigraph run per solver, and the runs compared."
    >
      <template #actions>
        <UButton to="/comparisons" icon="i-lucide-scale" label="Comparisons" color="neutral" variant="subtle" />
      </template>
    </PageHeader>
    <UContainer class="py-6 flex flex-col gap-4">
      <UTabs v-model="tab" :items="tabs" variant="link">
        <template #upload>
          <div class="pt-4">
            <UFileUpload v-model="file" accept=".omex,.zip" label="Drop a COMBINE/OMEX archive with SED-ML and its models" icon="i-lucide-file-up" class="w-full min-h-32" />
          </div>
        </template>
        <template #search>
          <div class="pt-4 flex flex-col gap-3">
            <form class="flex gap-2" @submit.prevent="search">
              <UInput v-model="query" :placeholder="tab === 'biomodels' ? 'Search curated BioModels, e.g. repressilator' : 'Part of a project id, e.g. Ciliberto'" icon="i-lucide-search" class="w-96" />
              <UButton type="submit" label="Search" :loading="searching" />
            </form>
            <UAlert v-if="searchError" color="error" variant="subtle" :title="searchError" />
            <ul v-if="tab === 'biomodels'" class="flex flex-col gap-1 text-sm">
              <li v-for="m in models" :key="m.id" class="flex items-center gap-2">
                <UButton size="xs" variant="soft" icon="i-lucide-eye" :label="m.id" @click="open({ kind: 'biomodels', id: m.id }, `${m.id}: ${m.name}`)" />
                <span>{{ m.name }}</span>
                <ULink v-if="m.url" :to="m.url" target="_blank" class="text-muted text-xs">BioModels</ULink>
              </li>
            </ul>
            <ul v-else class="flex flex-col gap-1 text-sm">
              <li v-for="p in projects" :key="p.id" class="flex items-center gap-2">
                <UButton size="xs" variant="soft" icon="i-lucide-eye" :label="p.id" @click="open({ kind: 'biosimulations', id: p.id }, p.id)" />
                <ULink :to="p.url" target="_blank" class="text-muted text-xs">biosimulations.org</ULink>
              </li>
            </ul>
          </div>
        </template>
      </UTabs>
      <SedmlRunPanel v-if="source" :source="source" :label="label" />
    </UContainer>
  </div>
</template>
