<script setup lang="ts">
import type { Schemas } from '~/composables/useApi'

// One suite: its runs, and for the chosen one (`?run=N`, else the newest) a row per model: whether the solvers agree,
// whether they match the references, and whether each solver drifted from its own result in the baseline run. Each
// solver's known problem on a row is shown with its reason, and excuses the row when only such solvers fail or differ
// (docs/plan-known-problems.md); the suite's problems, open and cleared, are on their own tab.
type View = Schemas['SuiteRunView']
const route = useRoute()
const name = computed(() => String(route.params.name))
const suite = ref<Schemas['Suite'] | null>(null)
const runs = ref<Schemas['SuiteRunInfo'][]>([])
const selected = ref<number | undefined>(route.query.run ? Number(route.query.run) : undefined)
const view = shallowRef<View | null>(null)
const error = ref<string | null>(null)
const starting = ref(false)
const problems = ref<Schemas['KnownProblem'][]>([])
const tab = ref(route.query.tab === 'problems' ? 'problems' : 'run')
const hideExcused = ref(false)
const rows = computed(() => (view.value?.rows ?? []).filter(r => !hideExcused.value || !r.excused))
const openProblems = computed(() => problems.value.filter(p => p.cleared_run == null))
const tabs = computed(() => [
  { label: 'Run', value: 'run', slot: 'run' as const },
  { label: `Known problems (${openProblems.value.length} open)`, value: 'problems', slot: 'problems' as const }
])

async function load() {
  const api = useApi()
  const [all, list, known] = await Promise.all([
    api.GET('/suites'),
    api.GET('/suites/{name}/runs', { params: { path: { name: name.value } } }),
    api.GET('/suites/{name}/problems', { params: { path: { name: name.value } } })
  ])
  suite.value = all.data?.find(s => s.name === name.value) ?? null
  if (!suite.value) error.value = `No suite ${name.value}.`
  runs.value = list.data ?? []
  problems.value = known.data ?? []
  selected.value ??= runs.value[0]?.number
  await loadRun()
}
async function loadRun() {
  if (selected.value === undefined) return
  const { data } = await useApi().GET('/suites/{name}/runs/{number}', { params: { path: { name: name.value, number: selected.value } } })
  view.value = data ?? null
}
onMounted(load)
watch(tab, t => navigateTo({ query: { ...route.query, tab: t === 'run' ? undefined : t } }, { replace: true }))
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
          <UBadge v-if="view.summary.excused" color="neutral" variant="subtle">{{ view.summary.excused }} excused by known problems</UBadge>
          <UBadge v-if="view.summary.resolved" color="warning" variant="outline">{{ view.summary.resolved }} with a problem resolved</UBadge>
          <UBadge v-if="view.summary.running" color="neutral" variant="subtle">{{ view.summary.running }} running</UBadge>
          <UBadge v-if="view.summary.failed" color="error" variant="outline">{{ view.summary.failed }} not submitted</UBadge>
        </div>
        <UTabs v-model="tab" :items="tabs" variant="link" class="w-full">
          <template #run>
            <div class="pt-3 flex flex-col gap-2">
              <USwitch v-if="view.summary.excused" v-model="hideExcused" label="Hide excused rows" size="sm" />
              <table class="text-sm">
                <thead>
                  <tr class="text-left text-muted">
                    <th class="pr-4 py-1">Model</th><th class="pr-4">Task</th><th class="pr-4">Solvers</th><th class="pr-4">References</th><th class="pr-4">Worst</th><th class="pr-4">Since baseline</th><th class="pr-4">Known problems</th><th>Note</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(r, i) in rows" :key="i" class="border-t border-default align-top">
                    <td class="pr-4 py-1 font-mono text-xs">
                      <NuxtLink v-if="r.comparison_id" :to="`/comparisons/${r.comparison_id}`" class="text-primary">{{ r.source }}</NuxtLink>
                      <span v-else>{{ r.source }}</span>
                    </td>
                    <td class="pr-4 font-mono text-xs">{{ r.task }}</td>
                    <td class="pr-4">
                      <UTooltip v-if="r.comparison_id" :text="rowVerdict(r).hint" :disabled="!rowVerdict(r).hint">
                        <UBadge :color="rowVerdict(r).color" variant="subtle" size="sm">{{ rowVerdict(r).text }}</UBadge>
                      </UTooltip>
                    </td>
                    <td class="pr-4"><UBadge v-if="r.close_to_references !== null && r.close_to_references !== undefined" :color="r.close_to_references ? 'success' : 'error'" variant="outline" size="sm">{{ r.close_to_references ? 'match' : 'differ' }}</UBadge></td>
                    <td class="pr-4 text-xs">{{ r.worst_label }} <span class="text-muted">{{ fmt(r.worst_score) }}</span></td>
                    <td class="pr-4">
                      <UBadge v-for="(d, solver) in r.drift ?? {}" :key="solver" :color="d.close ? 'success' : d.close === false ? 'warning' : 'neutral'" variant="outline" size="sm" class="mr-1">{{ solver }} {{ d.close ? 'same' : d.close === false ? 'drifted' : '?' }}</UBadge>
                    </td>
                    <td class="pr-4 text-xs max-w-md">
                      <div v-for="p in rowProblems(r, problems, view.number)" :key="p.solver" class="flex items-start gap-1 py-0.5">
                        <UBadge :color="p.resolved ? 'warning' : 'neutral'" variant="outline" size="sm" class="shrink-0">{{ p.solver }}{{ p.resolved ? ' resolved' : '' }}</UBadge>
                        <UBadge v-if="p.category" color="neutral" variant="soft" size="sm" class="shrink-0 font-mono">{{ p.category }}</UBadge>
                        <UTooltip :text="p.reason"><span class="text-muted line-clamp-2">{{ p.reason }}</span></UTooltip>
                      </div>
                    </td>
                    <td class="text-xs" :class="r.failure && !r.expected ? 'text-error' : 'text-muted'">{{ r.expected ?? r.failure }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </template>
          <template #problems>
            <div class="pt-3 flex flex-col gap-2">
              <p class="text-muted text-sm">
                Each solver's expected failures in this suite. A problem excuses its solver in the runs before the one
                that cleared it; a row lists a solver as resolved once it completes and agrees there.
              </p>
              <table v-if="problems.length" class="text-sm">
                <thead>
                  <tr class="text-left text-muted">
                    <th class="pr-4 py-1">Model</th><th class="pr-4">Solver</th><th class="pr-4">Category</th><th class="pr-4">Reason</th><th class="pr-4 whitespace-nowrap">Seen in</th><th class="pr-4">Marked</th><th>Cleared</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="p in problems" :key="p.problem_id" class="border-t border-default align-top" :class="p.cleared_run != null ? 'opacity-60' : ''">
                    <td class="pr-4 py-1 font-mono text-xs">{{ p.source }}</td>
                    <td class="pr-4 text-xs">{{ p.solver ?? 'every solver' }}</td>
                    <td class="pr-4 font-mono text-xs">{{ p.category }}</td>
                    <td class="pr-4 text-xs max-w-xl">{{ p.reason }}</td>
                    <td class="pr-4 text-xs whitespace-nowrap">{{ p.seen_run != null ? `run ${p.seen_run}` : '—' }}</td>
                    <td class="pr-4 text-xs text-muted whitespace-nowrap">{{ formatTime(p.marked_at) }}</td>
                    <td class="text-xs text-muted">{{ p.cleared_run != null ? `at run ${p.cleared_run}, ${formatTime(p.cleared_at)}` : 'open' }}</td>
                  </tr>
                </tbody>
              </table>
              <p v-else class="text-muted text-sm">No known problems are recorded for this suite.</p>
            </div>
          </template>
        </UTabs>
      </template>
    </UContainer>
  </div>
</template>
