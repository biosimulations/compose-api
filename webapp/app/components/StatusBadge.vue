<script setup lang="ts">
import type { Schemas } from '~/composables/useApi'

// While a run is `submitting` (no SLURM job yet), its submission says where it is on the way
// (docs/plan-durable-submission.md): queued with its place in line, making its image ready, or being submitted.
const props = defineProps<{ status: string | null | undefined, submission?: Schemas['SubmissionInfo'] | null }>()

const label = computed(() => {
  const status = props.status ?? 'unknown'
  const s = props.submission
  if (status !== 'submitting' || !s) return status.replaceAll('_', ' ')
  if (s.state === 'requested') return s.position ? `requested · #${s.position}` : 'requested'
  return s.attempts ? `${s.state} · attempt ${s.attempts + 1}` : s.state
})
const title = computed(() => props.submission?.last_error ?? undefined)
</script>

<template>
  <UBadge :color="statusColor(status)" variant="subtle" class="capitalize" :title="title">
    <UIcon v-if="status && !isTerminal(status) && status !== 'unknown'" name="i-lucide-loader-circle" class="animate-spin size-3" />
    {{ label }}
  </UBadge>
</template>
