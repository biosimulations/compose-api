<script setup lang="ts">
import type { Schemas } from '~/composables/useApi'

// One suite: its runs, and for the chosen one (`?run=N`, else the newest) a row per model: whether the solvers agree,
// whether they match the references, and whether each solver drifted from its own result in the baseline run.
type View = Schemas['SuiteRunView']
const route = useRoute()
const name = computed(() => String(route.params.name))
const suite = ref<Schemas['Suite'] | null>(null)
const runs = ref<Schemas['SuiteRunInfo'][]>([])
const selected = ref<number | undefined>(route.query.run ? Number(route.query.run) : undefined)
const view = shallowRef<View | null>(null)
const error = ref<string | null>(null)
const starting = ref(false)

async function load() {
  const api = useApi()
  const [all, list] = await Promise.all([
    api.GET('/suites'),
    api.GET('/suites/{name}/runs', { params: { path: { name: name.value } } })
  ])
  suite.value = all.data?.find(s => s.name === name.value) ?? null
  if (!suite.value) error.value = `No suite ${name.value}.`
  runs.value = list.data ?? []
  selected.value ??= runs.value[0]?.number
  await loadRun()
}
async function loadRun() {
  if (selected.value === undefined) return
  const { data } = await useApi().GET('/suites/{name}/runs/{number}', { params: { path: { name: name.value, number: selected.value } } })
  view.value = data ?? null
}
onMounted(load)
watch(selected, (n) => {
  navigateTo({ query: { ...route.query, run: n } }, { replace: true })
  loadRun()
})
useIntervalFn(() => {
  if (view.value && (view.value.status === 'submitting' || view.value.summary.running)) loadRun()
}, 15000)

async function runNow() {
  starting.value = true
  // every environment at its current default; the run records the versions as numbers (plan-environment-versions)
  const { data, error: err } = await useApi().POST('/suites/{name}/run', {
    params: { path: { name: name.value }, query: { environment_version: ['default'] } },
  })
  starting.value = false
  if (err || !data) {
    error.value = errorMessage(err, 'Could not start the suite')
    return
  }
  selected.value = data.number
  await load()
}

const verdict = (close: boolean | null | undefined, running: boolean) =>
  running ? { color: 'neutral' as const, text: 'running' } : close === true ? { color: 'success' as const, text: 'agree' } : close === false ? { color: 'error' as const, text: 'differ' } : { color: 'neutral' as const, text: '—' }
const fmt = (s: number | string | null | undefined) => (typeof s === 'number' ? s.toPrecision(3) : s ?? '')
</script>

<template>
  <div>
    <PageHeader :title="name" :description="suite?.description">
      <template #actions>
        <UButton to="/suites" icon="i-lucide-arrow-left" label="Suites" color="neutral" variant="ghost" />
        <UButton icon="i-lucide-play" label="Run the suite" :loading="starting" @click="runNow" />
      </template>
    </PageHeader>
    <UContainer class="py-6 flex flex-col gap-4">
      <UAlert v-if="error" color="error" variant="subtle" :title="error" />
      <div v-if="suite" class="flex flex-wrap items-center gap-3 text-sm">
        <span class="text-muted">{{ suite.sources.length }} models · solvers {{ suite.solvers?.join(', ') || 'all' }} · baseline run {{ suite.baseline ?? 'none yet (accepted by a pull request to its suite.yaml)' }}</span>
        <span class="grow" />
        <USelect v-if="runs.length" v-model="selected" :items="runs.map(r => ({ label: `run ${r.number}${r.number === suite?.baseline ? ' (baseline)' : ''} · ${formatTime(r.created_at)}`, value: r.number }))" class="w-72" />
      </div>
      <p v-if="!runs.length" class="text-muted text-sm">This suite has not run yet.</p>
      <template v-if="view">
        <div class="flex flex-wrap gap-2 text-sm">
          <UBadge color="success" variant="subtle">{{ view.summary.agree }} agree</UBadge>
          <UBadge v-if="view.summary.differ" color="error" variant="subtle">{{ view.summary.differ }} differ</UBadge>
          <UBadge v-if="view.summary.drifted" color="warning" variant="subtle">{{ view.summary.drifted }} drifted from the baseline</UBadge>
          <UBadge v-if="view.summary.expected" color="neutral" variant="outline">{{ view.summary.expected }} expected</UBadge>
          <UBadge v-if="view.summary.running" color="neutral" variant="subtle">{{ view.summary.running }} running</UBadge>
          <UBadge v-if="view.summary.failed" color="error" variant="outline">{{ view.summary.failed }} not submitted</UBadge>
        </div>
        <table class="text-sm">
          <thead>
            <tr class="text-left text-muted">
              <th class="pr-4 py-1">Model</th><th class="pr-4">Task</th><th class="pr-4">Solvers</th><th class="pr-4">References</th><th class="pr-4">Worst</th><th class="pr-4">Since baseline</th><th>Note</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(r, i) in view.rows" :key="i" class="border-t border-default align-top">
              <td class="pr-4 py-1 font-mono text-xs">
                <NuxtLink v-if="r.comparison_id" :to="`/comparisons/${r.comparison_id}`" class="text-primary">{{ r.source }}</NuxtLink>
                <span v-else>{{ r.source }}</span>
              </td>
              <td class="pr-4 font-mono text-xs">{{ r.task }}</td>
              <td class="pr-4"><UBadge v-if="r.comparison_id" :color="verdict(r.close, r.status === 'running').color" variant="subtle" size="sm">{{ verdict(r.close, r.status === 'running').text }}</UBadge></td>
              <td class="pr-4"><UBadge v-if="r.close_to_references !== null && r.close_to_references !== undefined" :color="r.close_to_references ? 'success' : 'error'" variant="outline" size="sm">{{ r.close_to_references ? 'match' : 'differ' }}</UBadge></td>
              <td class="pr-4 text-xs">{{ r.worst_label }} <span class="text-muted">{{ fmt(r.worst_score) }}</span></td>
              <td class="pr-4">
                <UBadge v-for="(d, solver) in r.drift ?? {}" :key="solver" :color="d.close ? 'success' : d.close === false ? 'warning' : 'neutral'" variant="outline" size="sm" class="mr-1">{{ solver }} {{ d.close ? 'same' : d.close === false ? 'drifted' : '?' }}</UBadge>
              </td>
              <td class="text-xs" :class="r.failure && !r.expected ? 'text-error' : 'text-muted'">{{ r.expected ?? r.failure }}</td>
            </tr>
          </tbody>
        </table>
      </template>
    </UContainer>
  </div>
</template>
