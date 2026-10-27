<script setup lang="ts">
import type { ComplianceReport, EnvironmentVersionDetail, EnvironmentVersions } from '~/composables/useRegistry'
import type { Component } from '~/viewers/composite/interfaces'

// One environment version (docs/plan-webapp-admin.md, step 5): what it was made from, the packages its image installed
// (and how they differ from another version's), where each registry entry stands in it (its compliance cases), the
// classes its image provides, and the files that recreate it locally. `?tab=` opens a tab.
const route = useRoute()
const name = computed(() => String(route.params.name))
const number = computed(() => Number(route.params.number))
const version = shallowRef<EnvironmentVersionDetail | null>(null)
const all = ref<EnvironmentVersions | null>(null)
const compliance = ref<ComplianceReport | null>(null)
const files = ref<Record<string, string> | null>(null)
const uvFiles = ref<Record<string, string> | null>(null)
const against = ref<number | undefined>(undefined)
const other = shallowRef<EnvironmentVersionDetail | null>(null)
const error = ref<string | null>(null)
const loading = ref(true)
const filter = ref('')
const tab = ref(typeof route.query.tab === 'string' ? route.query.tab : 'packages')

const installed = computed(() => parseInstalled(version.value?.installed))
const packages = computed(() => {
  const f = filter.value.toLowerCase()
  return [...installed.value].filter(([n]) => !f || n.includes(f))
})
const changes = computed(() => (other.value ? packageChanges(parseInstalled(other.value.installed), installed.value) : []))
const entries = computed(() => specEntries(version.value?.spec))
const core = computed(() => (version.value ? corePackages(version.value, installed.value) : []))
const components = computed<Component[]>(() => {
  const list = ((version.value?.interfaces?.components ?? []) as Component[]).slice()
  return list.sort((a, b) => a.name.localeCompare(b.name))
})
const isDefault = computed(() => all.value?.default === number.value)
const comparable = computed(() =>
  (all.value?.versions ?? []).filter(v => v.number !== number.value && v.state === 'ready').map(v => ({
    label: `${name.value}@${v.number}${v.number === all.value?.default ? ' (default)' : ''}`,
    value: v.number
  }))
)
const tabs = computed(() => [
  { label: `Packages (${installed.value.size})`, value: 'packages', slot: 'packages' as const },
  { label: 'Entries and compliance', value: 'entries', slot: 'entries' as const },
  { label: `Classes (${components.value.length})`, value: 'classes', slot: 'classes' as const },
  { label: 'Files', value: 'files', slot: 'files' as const }
])

function download(text: string, filename: string) {
  const link = document.createElement('a')
  link.href = URL.createObjectURL(new Blob([text], { type: 'text/plain' }))
  link.download = filename
  link.click()
  URL.revokeObjectURL(link.href)
}

async function load() {
  loading.value = true
  error.value = null
  try {
    const [v, list] = await Promise.all([fetchVersion(name.value, number.value), fetchVersions(name.value)])
    version.value = v
    all.value = list
    // compare with the default by default, or the newest other ready version
    against.value = comparable.value.find(c => c.value === list.default)?.value ?? comparable.value[0]?.value
    void fetchCompliance(name.value, number.value).then(c => (compliance.value = c)).catch(() => {})
    void fetchExport(name.value, number.value, 'pixi').then(f => (files.value = f)).catch(() => {})
    void fetchExport(name.value, number.value, 'uv').then(f => (uvFiles.value = f)).catch(() => {})
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}
onMounted(load)
watch(number, load)
watch(against, async (n) => {
  other.value = n === undefined ? null : await fetchVersion(name.value, n).catch(() => null)
})
watch(tab, t => navigateTo({ query: { ...route.query, tab: t === 'packages' ? undefined : t } }, { replace: true }))

const levelColor = (level: string) =>
  level === 'tested' ? 'success' as const : level === 'failed' ? 'error' as const : level === 'pending' ? 'info' as const : 'neutral' as const
const caseColor = (state: string) =>
  state === 'passed' ? 'success' as const : state === 'pending' ? 'info' as const : 'error' as const
</script>

<template>
  <div>
    <PageHeader :title="`${name}@${number}`" :description="version?.note ?? 'One version of the environment: a locked set of packages and its image.'">
      <template #actions>
        <UButton :to="`/environments/${encodeURIComponent(name)}`" icon="i-lucide-arrow-left" :label="name" color="neutral" variant="ghost" />
        <UButton :to="runsLink({ environment_version: { environment: name, number } })" icon="i-lucide-list" label="Runs" color="neutral" variant="subtle" />
      </template>
    </PageHeader>
    <UContainer class="py-6 flex flex-col gap-4">
      <UAlert v-if="error" color="error" variant="subtle" icon="i-lucide-circle-alert" :title="error" />
      <p v-if="loading" class="text-muted text-sm">Loading…</p>
      <template v-if="version">
        <div class="flex flex-wrap items-center gap-2">
          <UBadge :color="stateColor(version.state)" variant="subtle">{{ version.state }}</UBadge>
          <UBadge v-if="isDefault" color="primary" variant="subtle">default</UBadge>
          <UBadge color="neutral" variant="outline">{{ version.runtime_contract === 2 ? 'composed (pixi)' : version.image ? 'prebuilt image' : 'shared (uv)' }}</UBadge>
          <UBadge v-for="c in core" :key="c" color="neutral" variant="outline">{{ c }}</UBadge>
        </div>
        <UAlert v-if="version.failure" color="error" variant="subtle" icon="i-lucide-circle-alert" title="This version failed" :description="version.failure" />
        <div class="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-[auto_1fr]">
          <span class="text-muted">Created</span>
          <span>{{ formatTime(version.created_at) }}<span v-if="version.created_by" class="text-muted"> by {{ version.created_by }}</span></span>
          <template v-if="version.resolved_at">
            <span class="text-muted">Resolved as of</span><span>{{ formatTime(version.resolved_at) }}</span>
          </template>
          <template v-if="version.image">
            <span class="text-muted">Image</span><code class="text-xs break-all">{{ version.image }}</code>
          </template>
          <template v-if="version.lock_sha256">
            <span class="text-muted">Lock</span><code class="text-xs break-all">sha256 {{ version.lock_sha256 }}</code>
          </template>
          <template v-if="version.simulator_id != null">
            <span class="text-muted">Simulator</span>
            <NuxtLink :to="`/simulators/${version.simulator_id}`" class="text-xs text-primary">{{ version.simulator_id }}</NuxtLink>
          </template>
        </div>

        <UTabs v-model="tab" :items="tabs" variant="link" class="w-full">
          <template #packages>
            <div class="pt-3 flex flex-col gap-3">
              <p v-if="!installed.size" class="text-muted text-sm">Its image's packages have not been read back.</p>
              <template v-else>
                <div class="flex flex-wrap items-center gap-3">
                  <span class="text-sm text-muted">Changes from</span>
                  <USelect v-if="comparable.length" v-model="against" :items="comparable" class="w-60" />
                  <span v-else class="text-sm text-muted">— (no other ready version)</span>
                </div>
                <table v-if="other" class="text-sm">
                  <thead><tr class="text-left text-muted"><th class="pr-4 py-1">Package</th><th class="pr-4">{{ name }}@{{ against }}</th><th>{{ name }}@{{ number }}</th></tr></thead>
                  <tbody>
                    <tr v-for="c in changes" :key="c.name" class="border-t border-default">
                      <td class="pr-4 py-0.5 font-mono text-xs">{{ c.name }}</td>
                      <td class="pr-4 font-mono text-xs" :class="c.from === null ? 'text-muted' : ''">{{ c.from ?? 'not installed' }}</td>
                      <td class="font-mono text-xs" :class="c.to === null ? 'text-muted' : 'text-success'">{{ c.to ?? 'removed' }}</td>
                    </tr>
                    <tr v-if="!changes.length"><td colspan="3" class="text-muted text-sm py-1">The same packages.</td></tr>
                  </tbody>
                </table>
                <div class="flex flex-wrap items-center gap-3 pt-2">
                  <UInput v-model="filter" placeholder="Filter packages" icon="i-lucide-search" class="w-60" />
                  <span class="text-sm text-muted">{{ packages.length }} of {{ installed.size }} installed</span>
                </div>
                <div class="flex flex-wrap gap-1">
                  <UBadge v-for="[pkg, v] in packages" :key="pkg" color="neutral" variant="outline" size="sm" class="font-mono">{{ pkg }} {{ v }}</UBadge>
                </div>
              </template>
            </div>
          </template>

          <template #entries>
            <div class="pt-3 flex flex-col gap-3">
              <p class="text-sm text-muted">
                The registry entries the version is made of. An entry is tested in this version when its compliance cases
                pass here; a component a generic check refuses is not admitted.
              </p>
              <table class="text-sm">
                <thead><tr class="text-left text-muted"><th class="pr-4 py-1">Entry</th><th class="pr-4">Installed as</th><th class="pr-4">Level here</th><th>Cases</th></tr></thead>
                <tbody>
                  <tr v-for="e in entries" :key="e.id" class="border-t border-default align-top">
                    <td class="pr-4 py-1 font-mono text-xs">{{ e.id }}</td>
                    <td class="pr-4 font-mono text-xs">{{ e.install }}</td>
                    <td class="pr-4">
                      <template v-for="c in compliance?.entries?.filter(x => x.entry === e.id) ?? []" :key="c.entry">
                        <UBadge :color="levelColor(c.level)" variant="subtle" size="sm">{{ c.level }}</UBadge>
                      </template>
                    </td>
                    <td class="text-xs">
                      <template v-for="c in compliance?.entries?.filter(x => x.entry === e.id) ?? []" :key="c.entry">
                        <div v-for="k in c.cases ?? []" :key="k.case" class="flex items-center gap-1">
                          <UBadge :color="caseColor(k.state)" variant="outline" size="sm">{{ k.state }}</UBadge>
                          <NuxtLink v-if="k.simulation_id" :to="`/simulations/${k.simulation_id}`" class="text-primary">{{ k.case }}</NuxtLink>
                          <span v-else>{{ k.case }}</span>
                          <span v-if="k.failures?.length" class="text-error">{{ k.failures.join('; ') }}</span>
                        </div>
                      </template>
                    </td>
                  </tr>
                  <tr v-if="!entries.length"><td colspan="4" class="text-muted text-sm py-1">Not a composed version: it lists no registry entries.</td></tr>
                </tbody>
              </table>
              <UAlert
                v-if="compliance?.findings?.length" color="warning" variant="subtle" icon="i-lucide-triangle-alert"
                :title="`The generic checks found ${compliance.findings.length} problem${compliance.findings.length === 1 ? '' : 's'}`"
              >
                <template #description>
                  <ul class="text-xs flex flex-col gap-1 mt-1">
                    <li v-for="(f, i) in compliance.findings" :key="i"><code>{{ f.component }}</code> ({{ f.check }}, {{ f.severity }}): {{ f.detail }}</li>
                  </ul>
                </template>
              </UAlert>
            </div>
          </template>

          <template #classes>
            <div class="pt-3 flex flex-col gap-3">
              <p v-if="!components.length" class="text-muted text-sm">Its image's classes have not been read back.</p>
              <InterfaceCard v-for="c in components" :key="c.address" :component="c" :highlighted="false" />
            </div>
          </template>

          <template #files>
            <div class="pt-3 flex flex-col gap-3 text-sm">
              <p class="text-muted">Recreate this version locally: <code>pixi install --frozen</code> in a directory holding its pixi files, or <code>uv sync --frozen</code> with its uv project when it needs nothing from conda.</p>
              <div class="flex flex-wrap gap-2">
                <UButton v-for="(text, file) in files ?? {}" :key="file" icon="i-lucide-download" :label="file" color="neutral" variant="subtle" size="sm" @click="download(text, file)" />
                <UButton v-for="(text, file) in uvFiles ?? {}" :key="`uv-${file}`" icon="i-lucide-download" :label="`${file} (uv)`" color="neutral" variant="subtle" size="sm" @click="download(text, file)" />
                <UButton v-if="version.lock && !files" icon="i-lucide-download" label="lock" color="neutral" variant="subtle" size="sm" @click="download(version.lock, `${name}-${number}.lock`)" />
              </div>
              <p v-if="files && !uvFiles" class="text-muted text-xs">No uv form: it needs packages from conda-forge, which uv cannot install.</p>
              <p v-if="!files && !version.lock" class="text-muted text-xs">This version has no files to export.</p>
            </div>
          </template>
        </UTabs>
      </template>
    </UContainer>
  </div>
</template>
