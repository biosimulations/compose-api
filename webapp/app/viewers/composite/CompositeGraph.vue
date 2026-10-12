<script setup lang="ts">
import type { Graph } from 'process-bigraph-lang'
import { layoutGraph, linkPath } from './layout'

// The wiring of one composite as SVG: stores left, processes and steps right, a link per wired port. A nested
// composite's inner graph is drawn below it with the same layout.
const props = defineProps<{ graph: Graph, title?: string }>()

const layout = computed(() => layoutGraph(props.graph))
const nested = computed(() => props.graph.nodes.filter(n => n.children != null))
const selected = ref<string | null>(null)

// Nuxt UI's semantic color tokens: inputs in the primary color, outputs in the warning (amber) one
const color = (direction: 'input' | 'output') => (direction === 'input' ? 'var(--ui-primary)' : 'var(--ui-warning)')
const kindLabel = (kind: string) => kind.replace('shared_process_ref', 'shared').replace('shared_process', 'shared process')
const truncate = (s: string, n = 28) => (s.length > n ? `${s.slice(0, n - 1)}…` : s)
</script>

<template>
  <div class="flex flex-col gap-2">
    <p v-if="title" class="text-sm font-medium">{{ title }}</p>
    <p v-if="!graph.nodes.length && !graph.stores.length" class="text-sm text-muted">
      Nothing to draw: the document has no processes, steps or stores at its top level. If the Text tab shows the
      composite's content inside a <code>meta</code> block, this build does not yet read this document's form.
    </p>
    <div v-else class="overflow-auto rounded border border-default bg-elevated/30">
      <svg :width="layout.width" :height="layout.height" :viewBox="`0 0 ${layout.width} ${layout.height}`" class="text-xs select-none" font-family="ui-monospace, monospace">
        <defs>
          <marker id="arrow-in" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
            <path d="M 0 0 L 8 4 L 0 8 z" :fill="color('input')" />
          </marker>
          <marker id="arrow-out" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
            <path d="M 0 0 L 8 4 L 0 8 z" :fill="color('output')" />
          </marker>
        </defs>

        <g v-for="l in layout.links" :key="`${l.node}:${l.direction}:${l.port}`">
          <path
            :d="linkPath(l)"
            fill="none"
            :stroke="color(l.direction)"
            :stroke-width="selected === l.node || selected === l.store ? 2.5 : 1.2"
            :stroke-dasharray="l.store == null ? '4 3' : undefined"
            :opacity="selected && selected !== l.node && selected !== l.store ? 0.25 : 0.9"
            :marker-end="l.direction === 'input' ? 'url(#arrow-in)' : 'url(#arrow-out)'"
          >
            <title>{{ l.direction }} {{ l.node }}.{{ l.port }} {{ l.direction === 'input' ? '<-' : '->' }} {{ l.store ?? '(outside this composite)' }}{{ l.type ? ` : ${l.type}` : '' }}</title>
          </path>
        </g>

        <g v-for="s in layout.stores" :key="s.id" class="cursor-pointer" @click="selected = selected === s.id ? null : s.id">
          <rect
            :x="s.x" :y="s.y" :width="s.w" :height="s.h" rx="6"
            :fill="selected === s.id ? 'var(--ui-bg-accented)' : 'var(--ui-bg)'"
            stroke="var(--ui-border-accented)"
            :stroke-dasharray="s.open ? '2 2' : s.declared ? undefined : '5 3'"
          />
          <text :x="s.x + 8" :y="s.y + 19" fill="var(--ui-text)">{{ truncate(s.id, 22) }}</text>
          <title>store {{ s.id }}{{ s.type ? ` : ${s.type}` : '' }}{{ s.declared ? '' : ' (not declared: created by a wire)' }}{{ s.open ? ' (open site)' : '' }}</title>
        </g>

        <g v-for="n in layout.nodes" :key="n.id" class="cursor-pointer" @click="selected = selected === n.id ? null : n.id">
          <rect
            :x="n.x" :y="n.y" :width="n.w" :height="n.h" rx="6"
            :fill="selected === n.id ? 'var(--ui-bg-accented)' : 'var(--ui-bg)'"
            stroke="var(--ui-text-muted)"
            :stroke-width="n.hasChildren ? 2 : 1.2"
          />
          <text :x="n.x + 8" :y="n.y + 13" fill="var(--ui-text)" font-weight="600">{{ truncate(n.id, 24) }}</text>
          <text :x="n.x + 8" :y="n.y + 25" fill="var(--ui-text-muted)">{{ kindLabel(n.kind) }}{{ n.interface ? ` : ${truncate(n.interface, 18)}` : '' }}{{ n.interval != null ? ` every ${n.interval}` : '' }}</text>
          <g v-for="p in n.ports" :key="`${p.direction}:${p.name}`">
            <circle :cx="n.x" :cy="p.y" r="3" :fill="color(p.direction)" />
            <text :x="n.x + 10" :y="p.y + 4" :fill="p.direction === 'input' ? 'var(--ui-text)' : 'var(--ui-text-muted)'">{{ p.direction === 'input' ? '→' : '←' }} {{ truncate(p.name, 24) }}</text>
          </g>
          <title>{{ n.kind }} {{ n.id }}{{ n.address ? ` at ${n.address}` : '' }}{{ n.doc ? `\n${n.doc}` : '' }}{{ n.dynamicPorts ? '\n(dynamic ports)' : '' }}</title>
        </g>
      </svg>
    </div>
    <CompositeGraph v-for="n in nested" :key="n.id" :graph="n.children!" :title="`inside ${n.id}`" />
  </div>
</template>
