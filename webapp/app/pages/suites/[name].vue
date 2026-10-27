<script setup lang="ts">
import type { Schemas } from '~/composables/useApi'
import type { Confirmation } from '~/utils/admin'
import type { VersionChoice } from '~/utils/suites'

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

// Running it (plan-webapp-admin step 5, A4): it needs sign-in, a nudge rather than a guard, and names a version of
// each environment its solvers use (default: each one's default); the run records them as numbers. The API refuses a
// second run while one is going (409).
const { enabled: signInOffered, isAuthenticated } = useAuth()
const needsSignIn = computed(() => signInOffered.value && !isAuthenticated.value)
const solvers = ref<Schemas['Solver'][]>([])
const environments = computed(() => (suite.value ? suiteEnvironments(suite.value, solvers.value) : []))
const choices = ref<Record<string, VersionChoice[]>>({})
const chosen = ref<Record<string, string>>({})
const confirming = ref(false)
const runError = ref<string | null>(null)
const selectedInfo = computed(() => runs.value.find(r => r.number === selected.value) ?? null)

async function openRun() {
  runError.value = null
  confirming.value = true
  if (!solvers.value.length) solvers.value = await listSolvers().catch(() => [])
  for (const env of environments.value) {
    chosen.value[env] ??= 'default'
    if (!choices.value[env]) {
      fetchVersions(env)
        .then(v => (choices.value = { ...choices.value, [env]: versionChoices(env, v.versions ?? [], v.default) }))
        .catch(() => (choices.value = { ...choices.value, [env]: versionChoices(env, [], null) }))
    }
  }
}

const runConfirmation = computed<Confirmation | null>(() => suite.value
  ? {
      title: `Run ${name.value}?`,
      description: `It submits about ${jobCount(suite.value, solvers.value)} simulations: each of its ${suite.value.sources.length} models on each solver, in the versions below. `
        + 'Only one run of a suite goes at a time.',
      confirm: 'Run the suite',
      danger: false
    }
  : null)

async function runNow() {
  starting.value = true
  runError.value = null
  const picked = Object.fromEntries(environments.value.map(env => [env, chosen.value[env] ?? 'default']))
  const { data, error: err } = await useApi().POST('/suites/{name}/run', {
    params: { path: { name: name.value }, query: { environment_version: versionParameters(picked) } }
  })
  starting.value = false
  if (err || !data) {
    runError.value = errorMessage(err, 'Could not start the suite')
    return
  }
  confirming.value = false
  selected.value = data.number
  await load()
}

// Curating its known problems (docs/plan-known-problems.md, 2b): offered with suites:curate, which the API checks
// again; each change is confirmed first. A mark or a clear is made at the run being viewed.
type Problem = Schemas['KnownProblem']
type Curation = { kind: 'mark', source: string } | { kind: 'clear', problem: Problem } | { kind: 'edit', problem: Problem }
const { principal } = useAuth()
const curator = computed(() => canCurate(principal.value?.capabilities))
const curation = ref<Curation | null>(null)
const curating = ref(false)
const curateBusy = ref(false)
const curateError = ref<string | null>(null)
const form = reactive({ solver: '', category: '', reason: '' })
const EVERY = '(every solver)'
const solverIds = computed(() => (suite.value ? suiteSolvers(suite.value, solvers.value).map(s => s.id) : []))
const curationRun = computed(() => view.value?.number ?? runs.value[0]?.number ?? 0)
const curationConfirmation = computed<Confirmation | null>(() => {
  const c = curation.value
  if (!c) return null
  if (c.kind === 'mark') return markConfirmation(c.source, form.solver === EVERY ? null : form.solver || 'The solver you choose', curationRun.value)
  return c.kind === 'clear' ? clearConfirmation(c.problem, curationRun.value) : editConfirmation(c.problem)
})
const curationInvalid = computed(() => {
  const c = curation.value
  if (!c || c.kind === 'clear') return false
  return !validMark(form.category, form.reason) || (c.kind === 'mark' && !form.solver)
})

async function startCuration(c: Curation) {
  curation.value = c
  curateError.value = null
  if (c.kind === 'mark') {
    if (!solvers.value.length) solvers.value = await listSolvers().catch(() => [])
    Object.assign(form, { solver: '', category: '', reason: '' })
  } else {
    Object.assign(form, { solver: c.problem.solver ?? EVERY, category: c.problem.category, reason: c.problem.reason })
  }
  curating.value = true
}

async function saveCuration() {
  const c = curation.value
  if (!c) return
  curateBusy.value = true
  curateError.value = null
  const api = useApi()
  const path = { name: name.value }
  const result = c.kind === 'mark'
    ? await api.POST('/suites/{name}/problems', {
        params: { path },
        body: { source: c.source, solver: form.solver === EVERY ? null : form.solver, category: form.category.trim(),
          reason: form.reason.trim(), seen_run: curationRun.value || null }
      })
    : c.kind === 'clear'
      ? await api.POST('/suites/{name}/problems/{problem_id}/clear', {
          params: { path: { ...path, problem_id: c.problem.problem_id } }, body: { run: curationRun.value }
        })
      : await api.PATCH('/suites/{name}/problems/{problem_id}', {
          params: { path: { ...path, problem_id: c.problem.problem_id } },
          body: { category: form.category.trim(), reason: form.reason.trim() }
        })
  curateBusy.value = false
  if (result.error || !result.data) {
    curateError.value = errorMessage(result.error, 'The change was not saved')
    return
  }
  curating.value = false
  const known = await api.GET('/suites/{name}/problems', { params: { path } })
  problems.value = known.data ?? problems.value
  await loadRun()
}

const fmt = (s: number | string | null | undefined) => (typeof s === 'number' ? s.toPrecision(3) : s ?? '')
</script>

<template>
  <div>
    <PageHeader :title="name" :description="suite?.description">
      <template #actions>
        <UButton to="/suites" icon="i-lucide-arrow-left" label="Suites" color="neutral" variant="ghost" />
        <UTooltip :text="needsSignIn ? 'Sign in to run the suite' : ''" :disabled="!needsSignIn">
          <UButton icon="i-lucide-play" label="Run the suite" :loading="starting" :disabled="needsSignIn || !suite" @click="openRun" />
        </UTooltip>
      </template>
    </PageHeader>
    <UContainer class="py-6 flex flex-col gap-4">
      <UAlert v-if="error" color="error" variant="subtle" :title="error" />
      <div v-if="suite" class="flex flex-wrap items-center gap-3 text-sm">
        <span class="text-muted">{{ suite.sources.length }} models · solvers {{ suite.solvers?.join(', ') || 'all' }} · baseline run {{ suite.baseline ?? 'none yet (accepted by a pull request to its suite.yaml)' }}</span>
        <span class="grow" />
        <USelect v-if="runs.length" v-model="selected" :items="runs.map(r => ({ label: `run ${r.number}${r.number === suite?.baseline ? ' (baseline)' : ''} · ${formatTime(r.created_at)}${runVersions(r.environment_versions).length ? ' · ' + runVersions(r.environment_versions).map(versionLabel).join(', ') : ''}`, value: r.number }))" class="w-96" />
      </div>
      <div v-if="selectedInfo" class="flex flex-wrap items-center gap-2 text-sm">
        <span class="text-muted">Run {{ selectedInfo.number }} ran in</span>
        <RanIn v-for="v in runVersions(selectedInfo.environment_versions)" :key="v.environment" :version="v" :simulator-id="0" class="text-xs" />
        <span v-if="!runVersions(selectedInfo.environment_versions).length" class="text-muted">each environment's image at the time (started before versions were recorded)</span>
      </div>
      <ConfirmDialog
        v-model:open="curating"
        :confirmation="curationConfirmation"
        :busy="curateBusy"
        :error="curateError"
        :disabled="curationInvalid"
        @confirm="saveCuration"
      >
        <template v-if="curation && curation.kind !== 'clear'">
          <UFormField v-if="curation.kind === 'mark'" label="Solver">
            <USelect v-model="form.solver" :items="[...solverIds, EVERY]" placeholder="Which solver has the problem" class="w-64" />
          </UFormField>
          <UFormField label="Category" help="What kind of problem, e.g. VCell's fault name; reuse one when it fits.">
            <UInput v-model="form.category" :maxlength="64" class="w-64 font-mono" />
            <div v-if="knownCategories(problems).length" class="flex flex-wrap gap-1 mt-1">
              <UButton
                v-for="c in knownCategories(problems)" :key="c" :label="c" size="xs" variant="soft"
                :color="form.category === c ? 'primary' : 'neutral'" class="font-mono" @click="form.category = c"
              />
            </div>
          </UFormField>
          <UFormField label="Reason" help="Why it fails or differs: the solver's own message, when it gives one.">
            <UTextarea v-model="form.reason" :rows="3" :maxlength="2000" class="w-full" />
          </UFormField>
        </template>
      </ConfirmDialog>
      <ConfirmDialog v-model:open="confirming" :confirmation="runConfirmation" :busy="starting" :error="runError" @confirm="runNow">
        <UFormField v-for="env in environments" :key="env" :label="env">
          <USelect v-model="chosen[env]" :items="choices[env] ?? [{ label: 'default', value: 'default' }]" class="w-56" />
        </UFormField>
      </ConfirmDialog>
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
                        <UButton
                          v-if="curator && p.resolved && problemToClear(r, p.solver, problems)"
                          size="xs" variant="ghost" color="warning" icon="i-lucide-check" label="Clear"
                          @click="startCuration({ kind: 'clear', problem: problemToClear(r, p.solver, problems)! })"
                        />
                      </div>
                      <UButton
                        v-if="curator && markable(r)"
                        size="xs" variant="ghost" color="neutral" icon="i-lucide-flag" label="Mark a known problem"
                        @click="startCuration({ kind: 'mark', source: r.source })"
                      />
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
                    <th class="pr-4 py-1">Model</th><th class="pr-4">Solver</th><th class="pr-4">Category</th><th class="pr-4">Reason</th><th class="pr-4 whitespace-nowrap">Seen in</th><th class="pr-4">Marked</th><th class="pr-4">Cleared</th><th v-if="curator" />
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
                    <td class="pr-4 text-xs text-muted">{{ p.cleared_run != null ? `at run ${p.cleared_run}, ${formatTime(p.cleared_at)}` : 'open' }}</td>
                    <td v-if="curator" class="whitespace-nowrap">
                      <UButton size="xs" variant="ghost" color="neutral" icon="i-lucide-pencil" label="Edit" @click="startCuration({ kind: 'edit', problem: p })" />
                      <UButton
                        v-if="p.cleared_run == null && curationRun"
                        size="xs" variant="ghost" color="warning" icon="i-lucide-check" :label="`Clear at run ${curationRun}`"
                        @click="startCuration({ kind: 'clear', problem: p })"
                      />
                    </td>
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
