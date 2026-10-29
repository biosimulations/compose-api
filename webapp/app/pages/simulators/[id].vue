<script setup lang="ts">
import type { SimulatorDetail } from '~/composables/useRegistry'

// One simulator: a container definition, identified by its hash, which runs record (docs/plan-webapp-admin.md, 5c).
// A simulator from before environment versions is no version's, and this page is the only place it is described.
const route = useRoute()
const id = Number(route.params.id)

const simulator = ref<SimulatorDetail | null>(null)
const loading = ref(true)
const notFound = ref(false)
const error = ref<string | null>(null)

onMounted(async () => {
  try {
    simulator.value = await fetchSimulator(id)
    notFound.value = simulator.value === null
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
})

function saveDefinition() {
  if (!simulator.value) return
  const url = URL.createObjectURL(new Blob([simulator.value.definition], { type: 'text/plain' }))
  const a = Object.assign(document.createElement('a'), { href: url, download: `environment-${id}.def` })
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <div>
    <PageHeader :title="simulator && !simulator.versions?.length ? `Legacy environment ${id}` : `Definition ${id}`" description="A container definition, identified by its hash, and the runs that used it.">
      <template #actions>
        <UButton to="/environments" icon="i-lucide-arrow-left" label="Environments" color="neutral" variant="ghost" />
        <UButton v-if="simulator" icon="i-lucide-download" label="Definition" color="neutral" variant="subtle" @click="saveDefinition" />
      </template>
    </PageHeader>
    <UContainer class="py-6 flex flex-col gap-4">
      <UAlert v-if="error" color="error" variant="subtle" icon="i-lucide-circle-alert" :title="error" />
      <p v-if="loading" class="text-muted text-sm">Loading…</p>
      <UAlert
        v-if="notFound"
        color="neutral"
        variant="subtle"
        icon="i-lucide-search-x"
        title="Not found"
        description="No such environment, or it is no environment's version and no run you can read used it."
      />
      <template v-if="simulator">
        <UAlert
          v-if="!simulator.versions?.length"
          color="info"
          variant="subtle"
          icon="i-lucide-history"
          title="From before environment versions"
          description="Its runs were recorded before environments had versions, so it belongs to none. Its definition below is what they ran in."
        />
        <div class="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-[auto_1fr]">
          <template v-if="simulator.versions?.length">
            <span class="text-muted">Versions</span>
            <span class="flex flex-wrap gap-2">
              <RanIn v-for="v in simulator.versions" :key="versionLabel(v)" :version="v" :simulator-id="id" />
            </span>
          </template>
          <span class="text-muted">Definition hash</span><code class="text-xs break-all">{{ simulator.container_def_hash }}</code>
          <span class="text-muted">Recorded</span><span>{{ formatTime(simulator.created_at) }}</span>
          <span class="text-muted">Runs</span>
          <span>
            <NuxtLink v-if="simulator.run_count" :to="runsLink({ simulator_id: id })" class="text-primary">
              {{ simulator.run_count }} run{{ simulator.run_count === 1 ? '' : 's' }}
            </NuxtLink>
            <template v-else>none yet</template>
            <span v-if="simulator.first_run_at" class="text-muted">
              · {{ formatTime(simulator.first_run_at) }} to {{ formatTime(simulator.last_run_at) }}
            </span>
          </span>
        </div>
        <section class="flex flex-col gap-2">
          <h2 class="text-lg font-semibold">Container definition</h2>
          <pre class="text-xs font-mono p-3 rounded bg-elevated/50 border border-default overflow-auto max-h-[36rem]">{{ simulator.definition }}</pre>
        </section>
      </template>
    </UContainer>
  </div>
</template>
