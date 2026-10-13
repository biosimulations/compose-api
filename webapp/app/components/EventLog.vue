<script setup lang="ts">
import type { RunEvent } from '~/composables/useApi'

// A run's events, oldest first, paged by cursor and tailed while the run is live.
// Styled after ../platform/frontend/app/components/SimulationLogs.vue.
const props = defineProps<{ simulationId: number, live: boolean }>()

const api = useApi()
const events = ref<RunEvent[]>([])
const cursor = ref<number | null>(null)
const error = ref<string | null>(null)
const loading = ref(false)
const level = ref<string | undefined>(undefined)
const eventName = ref('')
const expanded = ref<Set<number>>(new Set())

const levels = ['debug', 'info', 'warning', 'error']

async function fetchMore(reset = false) {
  if (loading.value) return
  loading.value = true
  if (reset) {
    events.value = []
    cursor.value = null
  }
  try {
    // Drain every page available now; the tail timer picks up anything written later.
    for (;;) {
      const { data, error: err } = await api.GET('/results/simulation/events', {
        params: {
          query: {
            simulation_id: props.simulationId,
            after: cursor.value ?? undefined,
            limit: 1000,
            level: level.value || undefined,
            event: eventName.value || undefined
          }
        }
      })
      if (err || !data) {
        error.value = errorMessage(err, 'Could not load events')
        return
      }
      error.value = null
      events.value.push(...data.events)
      if (data.next_cursor == null || data.events.length === 0) return
      cursor.value = data.next_cursor
    }
  } finally {
    loading.value = false
  }
}

onMounted(() => fetchMore(true))
useIntervalFn(() => {
  if (props.live) fetchMore()
}, 5000)
watch([level, eventName], () => fetchMore(true))

function levelClass(l: string | null | undefined) {
  if (l === 'error') return 'text-error'
  if (l === 'warning') return 'text-warning'
  if (l === 'debug') return 'text-dimmed'
  return 'text-default'
}

function toggle(i: number) {
  const next = new Set(expanded.value)
  if (next.has(i)) next.delete(i)
  else next.add(i)
  expanded.value = next
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <div class="flex flex-wrap items-center gap-2">
      <USelect v-model="level" :items="levels" placeholder="Any level" class="w-36" clearable />
      <UInput v-model.lazy="eventName" placeholder="Event name, e.g. job.started" icon="i-lucide-search" class="w-72" />
      <UButton icon="i-lucide-refresh-cw" variant="ghost" color="neutral" :loading="loading" @click="fetchMore(true)" />
      <span class="text-sm text-muted ml-auto">
        {{ events.length }} events<template v-if="live"> · tailing</template>
      </span>
    </div>
    <UAlert v-if="error" color="error" variant="subtle" icon="i-lucide-circle-alert" :description="error" />
    <div class="rounded-lg border border-default bg-elevated/40 font-mono text-xs max-h-[60vh] overflow-auto">
      <p v-if="!events.length && !loading" class="p-4 text-muted font-sans text-sm">No events recorded yet.</p>
      <div
        v-for="(e, i) in events"
        :key="`${e.source}-${e.seq}`"
        class="px-3 py-1 border-b border-default/60 hover:bg-elevated cursor-pointer"
        @click="toggle(i)"
      >
        <div class="grid grid-cols-[11rem_3.5rem_9rem_9rem_minmax(0,1fr)] gap-3 whitespace-nowrap">
          <span class="text-dimmed">{{ formatTime(e.ts) }}</span>
          <span class="uppercase" :class="levelClass(e.level)">{{ e.level ?? 'info' }}</span>
          <span class="text-muted truncate" :title="e.component">{{ e.component }}</span>
          <span class="font-semibold truncate" :title="e.event">{{ e.event }}</span>
          <span class="text-muted truncate">{{ e.payload ? JSON.stringify(e.payload) : '' }}</span>
        </div>
        <pre v-if="expanded.has(i)" class="mt-1 p-2 rounded bg-default whitespace-pre-wrap">{{ JSON.stringify(e, null, 2) }}</pre>
      </div>
    </div>
  </div>
</template>
