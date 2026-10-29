<script setup lang="ts">
import type { EnvironmentSummary, EnvironmentVersions, SimulatorSummary } from '~/composables/useRegistry'

// The environments composites run in, each with the interface manifest generated inside its image
// (docs/plan-authoring.md): what the checker, the viewer and the editor resolve a document's classes against. The
// declared ones come first, then the mash-ups made on demand (docs/plan-environment-composition.md, D7.9).
const environments = ref<EnvironmentSummary[]>([])
const versions = ref<Record<string, EnvironmentVersions>>({})
// simulators from before environment versions: no version's, so reached only from here and from their runs (5c)
const earlier = ref<SimulatorSummary[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

onMounted(async () => {
  try {
    listSimulators().then(all => (earlier.value = all.filter(s => !s.versions?.length))).catch(() => {})
    environments.value = await listEnvironments()
    for (const e of environments.value) {
      fetchVersions(e.name).then(v => (versions.value = { ...versions.value, [e.name]: v })).catch(() => {})
    }
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div>
    <PageHeader
      title="Environments"
      description="Where composites run, and the processes and steps each one provides, as read inside its image."
    />
    <UContainer class="py-6 flex flex-col gap-4">
      <UAlert v-if="error" color="error" variant="subtle" icon="i-lucide-circle-alert" :title="error" />
      <p v-if="loading" class="text-muted text-sm">Loading…</p>
      <div class="grid gap-4 md:grid-cols-2">
        <ULink v-for="e in environments" :key="e.name" :to="`/environments/${encodeURIComponent(e.name)}`" class="block">
          <UCard class="h-full hover:ring-2 hover:ring-primary transition">
            <div class="flex flex-col gap-2 text-sm">
              <div class="flex flex-wrap items-center gap-2">
                <span class="text-lg font-semibold">{{ e.name }}</span>
                <UBadge variant="subtle" :color="e.kind === 'shared' ? 'primary' : e.kind === 'mash-up' ? 'info' : 'neutral'">{{ e.kind }}</UBadge>
                <UBadge v-if="e.stale" color="warning" variant="subtle">manifest from an earlier image</UBadge>
              </div>
              <div>
                {{ e.components }} component{{ e.components === 1 ? '' : 's' }}
                <span v-if="e.errors" class="text-warning">· {{ e.errors }} module{{ e.errors === 1 ? '' : 's' }} failed to import</span>
                <span v-if="e.process_bigraph" class="text-muted">· process-bigraph {{ e.process_bigraph }}</span>
              </div>
              <div v-if="versions[e.name]?.versions?.length" class="flex flex-wrap items-center gap-2">
                <span>{{ versions[e.name]!.versions!.length }} version{{ versions[e.name]!.versions!.length === 1 ? '' : 's' }}</span>
                <span class="text-muted">· {{ versions[e.name]!.versions!.filter(v => v.state === 'ready').length }} ready</span>
                <UBadge v-if="versions[e.name]!.default != null" color="primary" variant="subtle" size="sm">default @{{ versions[e.name]!.default }}</UBadge>
              </div>
              <div v-if="e.kind === 'mash-up'" class="text-muted">
                Made on demand from the {{ e.entries.length }} entries below, for runs that no named environment covers
              </div>
              <div v-else class="text-muted">
                Run with <code>{{ e.kind === 'shared' ? 'no environment named (the default)' : `environment=${e.name}` }}</code>
              </div>
              <code v-if="e.image" class="text-xs text-muted break-all">{{ e.image }}</code>
              <div v-if="e.entries.length" class="flex flex-wrap gap-1">
                <UBadge v-for="entry in e.entries" :key="entry.id" color="neutral" variant="outline" size="sm">{{ entry.id }} · {{ entry.level }}</UBadge>
              </div>
            </div>
          </UCard>
        </ULink>
      </div>
      <details v-if="earlier.length" class="text-sm">
        <summary class="cursor-pointer font-semibold">
          Legacy environments (before versions)
          <span class="font-normal text-muted">· {{ earlier.length }}, used by {{ earlier.reduce((n, s) => n + (s.run_count ?? 0), 0) }} runs</span>
        </summary>
        <p class="text-muted my-2">
          Environments runs used before compose-api recorded how each was built. They are no environment's versions; each
          page shows the definition its runs ran in.
        </p>
        <table>
          <thead>
            <tr class="text-left text-muted">
              <th class="pr-4 py-1">Environment</th><th class="pr-4">Definition hash</th><th class="pr-4">Runs</th><th>Used</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in earlier" :key="s.simulator_id" class="border-t border-default">
              <td class="pr-4 py-1"><NuxtLink :to="`/simulators/${s.simulator_id}`" class="text-primary font-mono">{{ s.simulator_id }}</NuxtLink></td>
              <td class="pr-4 font-mono text-xs">{{ s.container_def_hash.slice(0, 12) }}</td>
              <td class="pr-4"><NuxtLink :to="runsLink({ simulator_id: s.simulator_id })" class="text-primary">{{ s.run_count }}</NuxtLink></td>
              <td class="text-xs text-muted whitespace-nowrap">{{ formatTime(s.first_run_at) }} to {{ formatTime(s.last_run_at) }}</td>
            </tr>
          </tbody>
        </table>
      </details>
    </UContainer>
  </div>
</template>
