<script setup lang="ts">
import type { EnvironmentHeaders, EnvironmentSummary, EnvironmentVersion, EnvironmentVersions, ImageStatus, InterfaceManifest } from '~/composables/useRegistry'
import type { VersionAction } from '~/utils/admin'
import type { Component } from '~/viewers/composite/interfaces'

// One environment: its versions (each a page of its own), its image, the packages its committed manifest was read with,
// and every class it provides with its config and ports. `#Name` opens on a class (the viewer's hovers link here).
const route = useRoute()
const name = computed(() => String(route.params.name))
const summary = ref<EnvironmentSummary | null>(null)
const manifest = shallowRef<InterfaceManifest | null>(null)
const headers = shallowRef<EnvironmentHeaders | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const filter = ref('')
const highlighted = ref<string | null>(null)
const image = ref<ImageStatus | null>(null)
const versionList = ref<EnvironmentVersions | null>(null)
const imageError = ref<string | null>(null)
// administration (step 6): offered only when the API says the caller may (A1); it checks every request again
const { principal } = useAuth()
const capabilities = computed(() => principal.value?.capabilities ?? [])
const admin = ref<{ act: (action: VersionAction, version: EnvironmentVersion) => void } | null>(null)
const reloadVersions = () => fetchVersions(name.value).then(v => (versionList.value = v)).catch(() => {})
const requesting = ref(false)
let imagePoll: ReturnType<typeof setInterval> | null = null

const imageBadge = computed(() => {
  switch (image.value?.state) {
    case 'available': return { color: 'success' as const, label: 'built' }
    case 'building': return { color: 'info' as const, label: 'building' }
    case 'failed': return { color: 'error' as const, label: 'last build failed' }
    default: return { color: 'neutral' as const, label: 'not built' }
  }
})

async function refreshImage() {
  try {
    image.value = await fetchImageStatus(name.value)
    imageError.value = null
  } catch (e) {
    imageError.value = (e as Error).message
  }
  // follow a build until it ends
  if (image.value?.state === 'building' && !imagePoll) imagePoll = setInterval(refreshImage, 15000)
  if (image.value?.state !== 'building' && imagePoll) {
    clearInterval(imagePoll)
    imagePoll = null
  }
}

async function build() {
  requesting.value = true
  try {
    image.value = await requestBuild(name.value)
    await refreshImage()
  } catch (e) {
    imageError.value = (e as Error).message
  } finally {
    requesting.value = false
  }
}
onBeforeUnmount(() => imagePoll && clearInterval(imagePoll))

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
// every module's header file in one `.pblang` text, saved under the environment's name
function downloadHeaders() {
  if (!headers.value) return
  const text = headers.value.modules.map(m => m.text).join('\n')
  const link = document.createElement('a')
  link.href = URL.createObjectURL(new Blob([text], { type: 'text/plain' }))
  link.download = `${name.value}.pblang`
  link.click()
  URL.revokeObjectURL(link.href)
}
const manifestUrl = computed(() => apiUrl(`/registry/environments/${encodeURIComponent(name.value)}/manifest`))

onMounted(async () => {
  try {
    const [list, m] = await Promise.all([listEnvironments(), fetchManifest(name.value)])
    summary.value = list.find(e => e.name === name.value) ?? null
    if (!summary.value) error.value = `There is no environment named ${name.value}.`
    // a mash-up has no committed manifest: its versions' pages list the classes each image provides
    else if (!m && summary.value.kind !== 'mash-up') error.value = `No interface manifest has been generated for ${name.value}.`
    manifest.value = m
    if (summary.value && summary.value.kind !== 'mash-up') void refreshImage() // a mash-up's image is its version's
    if (summary.value) void reloadVersions()
    // the headers are printed on the server; the page works without them
    if (m) fetchHeaders(name.value).then(h => (headers.value = h)).catch(() => {})
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
        <UButton v-if="versionList?.versions?.length" :to="runsLink({ environment: name })" icon="i-lucide-list" label="Runs" color="neutral" variant="subtle" />
        <UButton v-if="headers" icon="i-lucide-file-code" label="Headers (.pblang)" color="neutral" variant="subtle" @click="downloadHeaders" />
        <UButton :to="manifestUrl" external target="_blank" icon="i-lucide-braces" label="Manifest JSON" color="neutral" variant="subtle" />
      </template>
    </PageHeader>
    <UContainer class="py-6 flex flex-col gap-4">
      <UAlert v-if="error" color="error" variant="subtle" icon="i-lucide-circle-alert" :title="error" />
      <p v-if="loading" class="text-muted text-sm">Loading…</p>
      <div v-if="summary" class="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-[auto_1fr]">
        <span class="text-muted">Kind</span>
        <span>{{ summary.kind }}{{ summary.kind === 'mash-up' ? ' · made on demand from its entries' : summary.kind === 'prebuilt' ? ` · run with environment=${summary.name}` : ' · the default for runs that name no environment' }}</span>
        <template v-if="summary.kind !== 'mash-up'">
        <span class="text-muted">Image</span>
        <code class="text-xs break-all">{{ summary.image ?? '—' }}</code>
        <span class="text-muted">On the cluster</span>
        <span class="flex flex-wrap items-center gap-2">
          <template v-if="image">
            <UBadge :color="imageBadge.color" variant="subtle" size="sm">{{ imageBadge.label }}</UBadge>
            <span v-if="image.image?.size_bytes" class="text-xs text-muted">{{ (image.image.size_bytes / 1e9).toFixed(2) }} GB</span>
            <span v-if="image.build" class="text-xs text-muted">newest build run {{ image.build.database_id }} · {{ image.build.backend }} · {{ image.build.status ?? 'submitted' }}</span>
            <UButton
              v-if="image.state === 'missing' || image.state === 'failed'"
              size="xs" icon="i-lucide-hammer" label="Build" color="neutral" variant="subtle" :loading="requesting" @click="build"
            />
          </template>
          <span v-else-if="imageError" class="text-xs text-error">{{ imageError }}</span>
          <span v-else class="text-xs text-muted">…</span>
        </span>
        </template>
        <template v-if="summary.stale">
          <span class="text-muted">Manifest read from</span>
          <span><code class="text-xs break-all">{{ summary.manifest_image }}</code> <UBadge color="warning" variant="subtle" size="sm">earlier image</UBadge></span>
        </template>
        <template v-if="versions.length">
          <span class="text-muted">Manifest read with</span>
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
      <section v-if="versionList?.versions?.length" class="flex flex-col gap-2">
        <h2 class="text-lg font-semibold">Versions</h2>
        <p class="text-sm text-muted">
          Each version is one locked set of packages and its image; a run records the version it used. Runs that name no
          version get the default ({{ versionList.default_source === 'deployment' ? 'set by the deployment' : 'chosen by an administrator' }}).
        </p>
        <EnvironmentAdmin
          v-if="summary && canAdminister(capabilities)"
          ref="admin"
          :name="name"
          :kind="summary.kind"
          :versions="versionList"
          @changed="reloadVersions"
        />
        <table class="text-sm">
          <thead>
            <tr class="text-left text-muted">
              <th class="pr-4 py-1">Version</th><th class="pr-4">State</th><th class="pr-4">Made from</th><th class="pr-4">Created</th><th class="pr-4">Runs</th><th class="pr-4">Note</th><th v-if="canAdminister(capabilities)" />
            </tr>
          </thead>
          <tbody>
            <tr v-for="v in versionList.versions" :key="v.number" class="border-t border-default align-top">
              <td class="pr-4 py-1 whitespace-nowrap">
                <NuxtLink :to="`/environments/${encodeURIComponent(name)}/versions/${v.number}`" class="text-primary font-mono">{{ name }}@{{ v.number }}</NuxtLink>
                <UBadge v-if="v.number === versionList.default" color="primary" variant="subtle" size="sm" class="ml-2">default</UBadge>
              </td>
              <td class="pr-4"><UBadge :color="stateColor(v.state)" variant="subtle" size="sm">{{ v.state }}</UBadge></td>
              <td class="pr-4 text-xs">
                <span v-if="v.image" class="font-mono break-all">{{ v.image }}</span>
                <span v-else>{{ v.runtime_contract === 2 ? 'composed (pixi)' : v.origin ?? 'shared' }}<template v-if="v.resolved_at"> · resolved {{ formatTime(v.resolved_at) }}</template></span>
              </td>
              <td class="pr-4 text-xs text-muted whitespace-nowrap">{{ formatTime(v.created_at) }}</td>
              <td class="pr-4 text-xs whitespace-nowrap">
                <NuxtLink v-if="v.last_used_at" :to="runsLink({ environment_version: { environment: name, number: v.number } })" class="text-primary" :title="`Last run ${formatTime(v.last_used_at)}`">runs</NuxtLink>
                <span v-else class="text-muted">none</span>
              </td>
              <td class="pr-4 text-xs text-muted max-w-xl">{{ v.note }}<span v-if="v.failure" class="text-error"> {{ v.failure }}</span></td>
              <td v-if="canAdminister(capabilities)" class="whitespace-nowrap">
                <template v-for="action in versionActions(v, v.number === versionList.default, capabilities)" :key="action">
                  <UButton
                    size="xs"
                    variant="ghost"
                    :color="action === 'retire' ? 'error' : 'neutral'"
                    :icon="{ default: 'i-lucide-star', retire: 'i-lucide-archive', inspect: 'i-lucide-scan-search' }[action]"
                    :label="{ default: 'Make default', retire: 'Retire', inspect: 'Re-read contents' }[action]"
                    :title="{
                      default: 'Runs that name no version will run in this one',
                      retire: 'Refuse new runs in this version; recorded runs keep it',
                      inspect: 'Run its image again to record what it installed and the classes it provides'
                    }[action]"
                    @click="admin?.act(action, v)"
                  />
                </template>
              </td>
            </tr>
          </tbody>
        </table>
      </section>
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
        <h2 class="text-lg font-semibold">Classes</h2>
        <p class="text-sm text-muted">As the default version's image provides them, read back when it was built; each version's page lists its own.</p>
        <div class="flex flex-wrap items-center gap-3">
          <UInput v-model="filter" placeholder="Filter by name or address" icon="i-lucide-search" class="w-72" />
          <span class="text-sm text-muted">{{ components.length }} of {{ manifest.components.length }}</span>
        </div>
        <InterfaceCard
          v-for="c in components" :key="c.address" :component="c" :highlighted="highlighted === c.name"
          :header="headers?.components[c.address]"
        />
      </template>
    </UContainer>
  </div>
</template>
