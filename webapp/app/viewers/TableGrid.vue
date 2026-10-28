<script setup lang="ts">
import type { Table } from './tabular'

// A table's first rows, the header kept in view: the Table viewers of a delimited file and of a figure's data.
const props = withDefaults(defineProps<{ table: Table, limit?: number }>(), { limit: 500 })
const shown = computed(() => props.table.rows.slice(0, props.limit))
</script>

<template>
  <div class="overflow-auto max-h-[65vh] border border-default rounded">
    <table class="text-xs font-mono">
      <thead class="sticky top-0 bg-elevated">
        <tr><th v-for="(h, j) in table.header" :key="j" class="px-2 py-1 text-left">{{ h }}</th></tr>
      </thead>
      <tbody>
        <tr v-for="(r, i) in shown" :key="i" class="border-t border-default">
          <td v-for="(c, j) in r" :key="j" class="px-2 py-0.5 whitespace-nowrap">{{ c }}</td>
        </tr>
      </tbody>
    </table>
    <p v-if="table.rows.length > limit" class="p-2 text-xs text-muted">Showing {{ limit }} of {{ table.rows.length }} rows.</p>
  </div>
</template>
