<script setup lang="ts">
import type { Schemas, SimulationSummary } from '~/composables/useApi'
import type { Comparison, ComparisonSeries } from '~/composables/useSedml'

// One SED-ML task run on several solvers (docs/plan-sedml.md, D4): its runs, then, once all have finished, a score per
// report, data set and solver pair (close below 1), the SED-ML plots with every run's traces overlaid, and any one data
// set from every run and every reference. Its verifications against BioSimulators' simulators say which of our solvers
// they side with (docs/plan-verify-oracle.md, V5), and their series join the overlay as references.
const route = useRoute()
const id = computed(() => Number(route.params.id))
const comparison = shallowRef<Comparison | null>(null)
const error = ref<string | null>(null)

async function load() {
  const { data, error: err } = await useApi().GET('/comparisons/{comparison_id}', { params: { path: { comparison_id: id.value } } })
  if (err || !data) {
    error.value = errorMessage(err, 'Could not load the comparison')
    return
  }
  error.value = null
  comparison.value = data
  void loadRuns(data)
  void loadVerifications()
}
onMounted(load)

// where each member ran (plan-webapp-admin 5c): its version, or its simulator when it ran before versions
const runs = ref<Record<number, SimulationSummary>>({})
async function loadRuns(c: Comparison) {
  const missing = c.members.filter(m => !runs.value[m.simulation_id])
  const found = await Promise.all(missing.map(m =>
    useApi().GET('/simulations/{simulation_id}', { params: { path: { simulation_id: m.simulation_id } } }).then(r => r.data)))
  runs.value = { ...runs.value, ...Object.fromEntries(found.filter(s => s != null).map(s => [s.simulation_id, s])) }
}
useIntervalFn(() => {
  if (comparison.value?.status === 'running' || verifying.value) load()
}, 10000)

// its verifications, newest first; asking for one needs sign-in (it spends biosim's shared budget), and asking again
// while one is going answers that one
type Verification = Schemas['Verification']
const verifications = ref<Verification[]>([])
const verifying = computed(() => verifications.value.some(v => v.state === 'requested' || v.state === 'submitted'))
const { enabled: signInOffered, isAuthenticated } = useAuth()
const needsSignIn = computed(() => signInOffered.value && !isAuthenticated.value)
const asking = ref(false)
const verifyError = ref<string | null>(null)
async function loadVerifications() {
  const { data } = await useApi().GET('/comparisons/{comparison_id}/verifications', { params: { path: { comparison_id: id.value } } })
  verifications.value = [...(data ?? [])].reverse()
}
async function verify() {
  asking.value = true
  verifyError.value = null
  const { error: err } = await useApi().POST('/comparisons/{comparison_id}/verify', { params: { path: { comparison_id: id.value } } })
  asking.value = false
  if (err) verifyError.value = errorMessage(err, 'Could not ask for a verification')
  await loadVerifications()
}

type PairResult = { score: number | string | null, close: boolean | null, missing?: string[], lengths?: number[], reference?: boolean }
type ReportResult = { labels: Record<string, Record<string, PairResult>>, worst: { label: string | null, score: number | null } }
const result = computed(() => comparison.value?.result as { reports?: Record<string, ReportResult>, close?: boolean, close_to_references?: boolean | null, references?: string[] } | null | undefined)
const reports = computed(() => Object.entries(result.value?.reports ?? {}))
const pairsOf = (r: ReportResult) => [...new Set(Object.values(r.labels).flatMap(p => Object.keys(p)))]
const fmt = (p: PairResult | undefined) => {
  if (!p) return '—'
  if (p.score === null) return p.missing ? `missing in ${p.missing.join(', ')}` : p.lengths ? `lengths ${p.lengths.join(' ≠ ')}` : '—'
  return typeof p.score === 'number' ? p.score.toPrecision(3) : String(p.score)
}

// one report, every run's and reference's columns, for the overlays
const reportIds = computed(() => Object.keys((comparison.value?.settings?.reports ?? {}) as Record<string, unknown>))
const report = ref<string | undefined>(undefined)
const label = ref<string | undefined>(undefined)
const series = shallowRef<ComparisonSeries | null>(null)
watch(reportIds, ids => (report.value ??= ids[0]), { immediate: true })
watch([report, () => comparison.value?.status], async ([r, status]) => {
  if (!r || status === 'running') return
  const { data } = await useApi().GET('/comparisons/{comparison_id}/series', { params: { path: { comparison_id: id.value }, query: { report: r } } })
  series.value = data ?? null
  label.value ??= data?.labels.find((_, i) => i > 0) ?? data?.labels[0]
})
const timeLabel = computed(() => series.value?.labels[0])
const overlay = computed(() => {
  const s = series.value
  if (!s || !label.value || !timeLabel.value) return []
  const lines = Object.entries(s.solvers).map(([solver, cols], i) => ({
    type: 'scatter', mode: 'lines', name: solver, x: cols[timeLabel.value!], y: cols[label.value!], line: { dash: ['solid', 'dash', 'dot', 'dashdot'][i % 4] }
  }))
  // a legacy run's results grey; each BioSimulators simulator's in a colour of its own
  const refs = Object.entries(s.references).map(([origin, cols]) => ({
    type: 'scatter', mode: 'markers', name: isOracle(origin) ? `BioSimulators ${oracleName(origin)}` : origin,
    x: cols[timeLabel.value!], y: cols[label.value!], marker: isOracle(origin) ? { size: 5, symbol: 'circle-open' } : { size: 4, color: '#888' }
  }))
  return [...lines, ...refs]
})

// the SED-ML plots: each member's figures, overlaid by plot
const figures = shallowRef<Record<string, { data: Record<string, unknown>[], layout: Record<string, unknown> }>>({})
watch(() => comparison.value?.status, async (status) => {
  const c = comparison.value
  if (!c || status === 'running') return
  const merged: Record<string, { data: Record<string, unknown>[], layout: Record<string, unknown> }> = {}
  for (const [i, m] of c.members.entries()) {
    const { data } = await useApi().GET('/datasets', { params: { query: { simulation_id: m.simulation_id, q: '.plotly.json', limit: 100 } } })
    for (const d of data?.datasets ?? []) {
      const response = await fetchContent(`/datasets/${d.id}/content`)
      if (!response.ok) continue
      const figure = await response.json() as { data?: Record<string, unknown>[], layout?: Record<string, unknown> }
      const key = d.path.replace(/^output\//, '')
      merged[key] ??= { data: [], layout: figure.layout ?? {} }
      for (const t of figure.data ?? []) {
        merged[key].data.push({ ...t, name: `${t.name as string} (${m.solver})`, line: { dash: ['solid', 'dash', 'dot', 'dashdot'][i % 4] } })
      }
    }
  }
  figures.value = merged
}, { immediate: true })
</script>

<template>
  <div>
    <PageHeader :title="comparison ? comparison.name : `Comparison #${id}`" :description="comparison ? `${comparison.source} · ${comparison.sedml} · task ${comparison.task}` : undefined">
      <template #actions>
        <FavoriteStar
          v-if="comparison"
          :model-value="comparison.favorite"
          kind="comparison"
          :ref-id="id"
          size="md"
          @update:model-value="(v: boolean) => { if (comparison) comparison = { ...comparison, favorite: v } }"
        />
        <UButton to="/comparisons" icon="i-lucide-arrow-left" label="Comparisons" color="neutral" variant="ghost" />
      </template>
    </PageHeader>
    <UContainer class="py-6 flex flex-col gap-6">
      <UAlert v-if="error" color="error" variant="subtle" :title="error" />
      <template v-if="comparison">
        <div class="flex flex-wrap items-center gap-2">
          <UBadge v-if="comparison.status === 'running'" color="neutral" variant="subtle" icon="i-lucide-loader">running: compared when every run has finished</UBadge>
          <template v-else>
            <UBadge :color="comparison.close ? 'success' : 'error'" variant="subtle">{{ comparison.close ? 'the solvers agree' : comparison.status === 'incomplete' ? 'a run did not complete' : 'the solvers differ' }}</UBadge>
            <UBadge v-if="result?.references?.length" :color="scoreColor(result.close_to_references)" variant="outline">
              {{ result.close_to_references ? 'and match every reference' : 'references: ' + result.references.map(oracleName).join(', ') + (result.close_to_references === false ? ': one differs' : '') }}
            </UBadge>
          </template>
          <span class="text-sm text-muted">close when the score is below 1: max |a−b| / (atol + rtol·|b|), rtol {{ (comparison.settings as any)?.tolerances?.rel_tol }}</span>
        </div>
        <UCard>
          <template #header><h3 class="font-semibold">Runs</h3></template>
          <ul class="flex flex-col gap-1 text-sm">
            <li v-for="m in comparison.members" :key="m.simulation_id" class="flex items-center gap-2">
              <UBadge color="neutral" variant="outline">{{ m.solver }}</UBadge>
              <NuxtLink :to="`/simulations/${m.simulation_id}`" class="font-mono text-primary">#{{ m.simulation_id }}</NuxtLink>
              <StatusBadge :status="m.status ?? 'unknown'" />
              <RanIn v-if="runs[m.simulation_id]" :version="runs[m.simulation_id]!.environment_version" :simulator-id="runs[m.simulation_id]!.simulator_id" class="text-xs" />
            </li>
          </ul>
        </UCard>
        <UCard>
          <template #header>
            <div class="flex flex-wrap items-center gap-2">
              <h3 class="font-semibold">Checked against BioSimulators</h3>
              <span class="grow" />
              <UTooltip :text="needsSignIn ? 'Sign in to ask for a verification' : ''" :disabled="!needsSignIn">
                <UButton
                  icon="i-lucide-shield-check" label="Verify" size="sm" variant="soft" :loading="asking"
                  :disabled="needsSignIn || !canVerify(comparison.status, verifications)" @click="verify"
                />
              </UTooltip>
            </div>
          </template>
          <p class="text-sm text-muted mb-2">
            biosim's /verify runs the archive this comparison ran on BioSimulators' own simulators and compares them
            with each other. Each simulator's results become a reference here, scored against our solvers like any other.
          </p>
          <UAlert v-if="verifyError" color="error" variant="subtle" :title="verifyError" class="mb-2" />
          <ul v-if="verifications.length" class="flex flex-col gap-2 text-sm">
            <li v-for="v in verifications" :key="v.verification_id" class="flex flex-wrap items-center gap-2">
              <UTooltip :text="verificationOracle(v)?.hint ?? ''">
                <UBadge :color="verificationOracle(v)?.color ?? 'neutral'" variant="subtle">{{ verificationOracle(v)?.text }}</UBadge>
              </UTooltip>
              <span class="text-muted">{{ formatTime(v.created_at) }}</span>
              <UBadge v-for="o in v.references" :key="o" color="neutral" variant="outline" size="sm">{{ oracleName(o) }}</UBadge>
              <span v-if="!v.references?.length" class="text-xs text-muted">{{ v.simulators.join(', ') }}</span>
              <UTooltip v-for="f in v.failed_simulators" :key="String(f.simulator_version)" :text="String(f.error_message ?? '')" :disabled="!f.error_message">
                <span class="text-xs text-warning">{{ f.simulator_version }} produced no results</span>
              </UTooltip>
              <span v-if="v.last_error" class="text-xs text-error">{{ v.last_error }}</span>
            </li>
          </ul>
          <p v-else class="text-sm text-muted">Not verified yet.</p>
        </UCard>
        <UCard v-for="[reportId, r] in reports" :key="reportId">
          <template #header>
            <div class="flex items-center gap-2">
              <h3 class="font-semibold">Report <code>{{ reportId }}</code></h3>
              <span v-if="r.worst.label" class="text-sm text-muted">worst: {{ r.worst.label }} ({{ typeof r.worst.score === 'number' ? r.worst.score.toPrecision(3) : r.worst.score }})</span>
            </div>
          </template>
          <div class="overflow-auto max-h-[28rem]">
            <table class="text-xs">
              <thead class="sticky top-0 bg-default">
                <tr><th class="text-left pr-4 py-1">data set</th><th v-for="p in pairsOf(r)" :key="p" class="text-left pr-4 py-1 font-mono">{{ p }}</th></tr>
              </thead>
              <tbody>
                <tr v-for="(pairs, lbl) in r.labels" :key="lbl" class="border-t border-default">
                  <td class="pr-4 py-1"><button class="hover:underline text-left" @click="report = reportId; label = String(lbl)">{{ lbl }}</button></td>
                  <td v-for="p in pairsOf(r)" :key="p" class="pr-4 py-1 font-mono" :class="pairs[p]?.close === true ? 'text-success' : pairs[p]?.close === false ? 'text-error font-semibold' : 'text-muted'">{{ fmt(pairs[p]) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </UCard>
        <UCard v-if="series">
          <template #header>
            <div class="flex flex-wrap items-center gap-2">
              <h3 class="font-semibold">One data set, every run</h3>
              <USelect v-model="report" :items="reportIds" class="w-48" />
              <USelect v-model="label" :items="series.labels" class="w-64" />
            </div>
          </template>
          <PlotlyChart :data="overlay" :layout="{ xaxis: { title: { text: timeLabel } }, yaxis: { title: { text: label } } }" class="h-96" />
        </UCard>
        <UCard v-for="(fig, path) in figures" :key="path">
          <template #header><h3 class="font-semibold">Plot <code>{{ path }}</code></h3></template>
          <PlotlyChart :data="fig.data" :layout="fig.layout" class="h-96" />
        </UCard>
      </template>
    </UContainer>
  </div>
</template>
