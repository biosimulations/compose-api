<script setup lang="ts">
import type { SpanTree } from '~/composables/useApi'

const props = defineProps<{ node: SpanTree, depth: number, origin: number, total: number }>()
const open = ref(props.depth < 2)

const bar = computed(() => {
  const start = props.node.span.start_ts ? Date.parse(props.node.span.start_ts) : NaN
  const end = props.node.span.end_ts ? Date.parse(props.node.span.end_ts) : Date.now()
  if (Number.isNaN(start) || props.total <= 0) return null
  return {
    left: `${Math.max(0, ((start - props.origin) / props.total) * 100)}%`,
    width: `${Math.max(0.5, ((end - start) / props.total) * 100)}%`
  }
})

const color = computed(() => {
  const s = props.node.span.status
  if (props.node.span.error || s === 'error') return 'bg-error'
  return props.node.span.end_ts ? 'bg-primary' : 'bg-info animate-pulse'
})
</script>

<template>
  <div>
    <div class="grid grid-cols-[minmax(16rem,2fr)_3fr_6rem] items-center gap-3 py-1 text-sm hover:bg-elevated rounded">
      <button class="flex items-center gap-1 text-left truncate" :style="{ paddingLeft: `${depth * 1}rem` }" @click="open = !open">
        <UIcon
          :name="node.children?.length ? (open ? 'i-lucide-chevron-down' : 'i-lucide-chevron-right') : 'i-lucide-dot'"
          class="size-4 shrink-0 text-muted"
        />
        <span class="truncate" :title="node.span.name">{{ node.span.name }}</span>
        <UBadge v-if="node.events?.length" size="sm" variant="soft" color="neutral">{{ node.events.length }}</UBadge>
      </button>
      <div class="relative h-3 bg-elevated rounded">
        <div v-if="bar" class="absolute h-3 rounded" :class="color" :style="bar" />
      </div>
      <span class="text-right text-muted tabular-nums">{{ formatDuration(node.span.duration_s) }}</span>
    </div>
    <p v-if="node.span.error" class="text-error text-xs" :style="{ paddingLeft: `${depth + 1.25}rem` }">{{ node.span.error }}</p>
    <template v-if="open">
      <SpanNode v-for="child in node.children ?? []" :key="child.span.span_id" :node="child" :depth="depth + 1" :origin="origin" :total="total" />
    </template>
  </div>
</template>
