<script setup lang="ts">
import type { EnvironmentSummary, InterfaceManifest } from '~/composables/useRegistry'
import type { Component } from '~/viewers/composite/interfaces'

// One environment: its image, the versions its manifest was read with, and every class it provides with its config
// and ports. `#Name` opens on a class (the viewer's hovers link here).
const route = useRoute()
const name = computed(() => String(route.params.name))
const summary = ref<EnvironmentSummary | null>(null)
const manifest = shallowRef<InterfaceManifest | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const filter = ref('')
const highlighted = ref<string | null>(null)

const environment = computed(() => (manifest.value?.environment ?? {}) as Record<string, unknown>)
const versions = computed(() => {
  const e = environment.value
  const rows: [string, string][] = []
  for (const key of ['python', 'process_bigraph', 'bigraph_schema']) {
    if (typeof e[key] === 'string') rows.push([key.replace('_', '-'), e[key] as string])
  }
  for (const [pkg, version] of Object.entries((e.packages ?? {}) as Record<string, string>)) rows.push([pkg, version])
  return rows
})
const components = computed<Component[]>(() => {
  const all = [...(manifest.value?.components ?? [])].sort((a, b) => a.name.localeCompare(b.name))
  const f = filter.value.toLowerCase()
  return f ? all.filter(c => `${c.name} ${c.address} ${c.kind}`.toLowerCase().includes(f)) : all
})
const manifestUrl = computed(() => apiUrl(`/registry/environments/${encodeURIComponent(name.value)}/manifest`))

onMounted(async () => {
  try {
    const [list, m] = await Promise.all([listEnvironments(), fetchManifest(name.value)])
    summary.value = list.find(e => e.name === name.value) ?? null
    if (!summary.value) error.value = `There is no environment named ${name.value}.`
    else if (!m) error.value = `No interface manifest has been generated for ${name.value}.`
    manifest.value = m
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
  // the class in the address bar, once the cards exist
  const target = decodeURIComponent(route.hash.slice(1))
  if (target) {
    highlighted.value = target
    await nextTick()
    document.getElementById(target)?.scrollIntoView({ block: 'start' })
  }
})
watch(() => route.hash, hash => (highlighted.value = decodeURIComponent(hash.slice(1)) || null))
</script>

<template>
  <div>
    <PageHeader :title="name" description="The processes and steps this environment provides, as its image declares them.">
      <template #actions>
        <UButton to="/environments" icon="i-lucide-arrow-left" label="All environments" color="neutral" variant="ghost" />
        <UButton :to="manifestUrl" external target="_blank" icon="i-lucide-braces" label="Manifest JSON" color="neutral" variant="subtle" />
      </template>
    </PageHeader>
    <UContainer class="py-6 flex flex-col gap-4">
      <UAlert v-if="error" color="error" variant="subtle" icon="i-lucide-circle-alert" :title="error" />
      <p v-if="loading" class="text-muted text-sm">Loading…</p>
      <div v-if="summary" class="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-[auto_1fr]">
        <span class="text-muted">Kind</span>
        <span>{{ summary.kind }}{{ summary.simulator ? ` · run with simulator=${summary.simulator}` : ' · the default for runs that name no simulator' }}</span>
        <span class="text-muted">Image</span>
        <code class="text-xs break-all">{{ summary.image ?? '—' }}</code>
        <template v-if="summary.stale">
          <span class="text-muted">Manifest read from</span>
          <span><code class="text-xs break-all">{{ summary.manifest_image }}</code> <UBadge color="warning" variant="subtle" size="sm">earlier image</UBadge></span>
        </template>
        <template v-if="versions.length">
          <span class="text-muted">Versions</span>
          <span class="flex flex-wrap gap-1">
            <UBadge v-for="[pkg, v] in versions" :key="pkg" color="neutral" variant="outline" size="sm">{{ pkg }} {{ v }}</UBadge>
          </span>
        </template>
        <template v-if="summary.entries.length">
          <span class="text-muted">Registry entries</span>
          <span class="flex flex-wrap gap-1">
            <UBadge v-for="e in summary.entries" :key="e.id" color="neutral" variant="subtle" size="sm">{{ e.id }} · {{ e.level }}</UBadge>
          </span>
        </template>
      </div>
      <UAlert
        v-if="manifest?.errors?.length"
        color="warning"
        variant="subtle"
        icon="i-lucide-triangle-alert"
        :title="`${manifest.errors.length} module${manifest.errors.length === 1 ? '' : 's'} could not be imported when the manifest was generated`"
      >
        <template #description>
          <ul class="text-xs font-mono flex flex-col gap-1 mt-1">
            <li v-for="(e, i) in manifest.errors" :key="i" class="break-all">{{ Object.values(e).join(': ') }}</li>
          </ul>
        </template>
      </UAlert>
      <template v-if="manifest">
        <div class="flex flex-wrap items-center gap-3">
          <UInput v-model="filter" placeholder="Filter by name or address" icon="i-lucide-search" class="w-72" />
          <span class="text-sm text-muted">{{ components.length }} of {{ manifest.components.length }}</span>
        </div>
        <InterfaceCard v-for="c in components" :key="c.address" :component="c" :highlighted="highlighted === c.name" />
      </template>
    </UContainer>
  </div>
</template>
