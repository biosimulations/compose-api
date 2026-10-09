<script setup lang="ts">
import type { SpanTree } from '~/composables/useApi'

// The run's spans as an indented tree with a shared timeline, from GET /results/simulation/trace.
const props = defineProps<{ simulationId: number, live: boolean }>()

const api = useApi()
const roots = ref<SpanTree[]>([])
const traceId = ref<string | null>(null)
const error = ref<string | null>(null)
const loading = ref(false)

async function load() {
  loading.value = true
  const { data, error: err } = await api.GET('/results/simulation/trace', {
    params: { query: { simulation_id: props.simulationId } }
  })
  loading.value = false
  if (err || !data) {
    error.value = errorMessage(err, 'Could not load the trace')
    return
  }
  error.value = null
  roots.value = data.roots
  traceId.value = data.trace_id ?? null
}

function walk(nodes: SpanTree[], f: (n: SpanTree) => void) {
  for (const n of nodes) {
    f(n)
    walk(n.children ?? [], f)
  }
}

const range = computed(() => {
  let lo = Infinity
  let hi = -Infinity
  walk(roots.value, (n) => {
    const s = n.span.start_ts ? Date.parse(n.span.start_ts) : NaN
    const e = n.span.end_ts ? Date.parse(n.span.end_ts) : Date.now()
    if (!Number.isNaN(s)) lo = Math.min(lo, s)
    if (!Number.isNaN(e)) hi = Math.max(hi, e)
  })
  return Number.isFinite(lo) && hi > lo ? { origin: lo, total: hi - lo } : { origin: 0, total: 0 }
})

async function saveChrome() {
  try {
    await downloadFile('/results/simulation/trace/chrome', { simulation_id: props.simulationId }, `simulation-${props.simulationId}-trace.json`)
  } catch (e) {
    error.value = (e as Error).message
  }
}

onMounted(load)
useIntervalFn(() => {
  if (props.live) load()
}, 10000)
</script>

<template>
  <div class="flex flex-col gap-3">
    <div class="flex flex-wrap items-center gap-2">
      <span v-if="traceId" class="text-sm text-muted font-mono">trace {{ traceId }}</span>
      <div class="ml-auto flex gap-2">
        <UButton icon="i-lucide-refresh-cw" variant="ghost" color="neutral" :loading="loading" @click="load" />
        <UButton icon="i-lucide-download" variant="subtle" color="neutral" label="Chrome trace" @click="saveChrome" />
        <UButton
          icon="i-lucide-external-link"
          variant="subtle"
          color="neutral"
          label="Perfetto"
          to="https://ui.perfetto.dev"
          target="_blank"
          title="Open Perfetto, then drag the downloaded Chrome trace into it"
        />
      </div>
    </div>
    <UAlert v-if="error" color="error" variant="subtle" icon="i-lucide-circle-alert" :description="error" />
    <p v-else-if="!roots.length && !loading" class="text-sm text-muted">No spans recorded yet.</p>
    <div v-else class="rounded-lg border border-default p-2">
      <SpanNode v-for="r in roots" :key="r.span.span_id" :node="r" :depth="0" :origin="range.origin" :total="range.total" />
    </div>
  </div>
</template>
