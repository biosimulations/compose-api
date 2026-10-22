<script setup lang="ts">
import type { Comparison, ComparisonSeries } from '~/composables/useSedml'

// One SED-ML task run on several solvers (docs/plan-sedml.md, D4): its runs, then, once all have finished, a score per
// report, data set and solver pair (close below 1), the SED-ML plots with every run's traces overlaid, and any one data
// set from every run and every reference.
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
}
onMounted(load)
useIntervalFn(() => {
  if (comparison.value?.status === 'running') load()
}, 10000)

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
  const refs = Object.entries(s.references).map(([origin, cols]) => ({
    type: 'scatter', mode: 'markers', name: origin, x: cols[timeLabel.value!], y: cols[label.value!], marker: { size: 4, color: '#888' }
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
              {{ result.close_to_references ? 'and match the original results' : 'reference: ' + result.references.join(', ') + (result.close_to_references === false ? ' differs' : '') }}
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
            </li>
          </ul>
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
