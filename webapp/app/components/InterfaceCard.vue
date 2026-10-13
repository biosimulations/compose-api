<script setup lang="ts">
import { type Component, faceRows } from '~/viewers/composite/interfaces'

// One class of an environment's interface manifest: its address, config, ports, and registry entry, as declared in
// the image (types in bigraph-schema's own form).
const props = defineProps<{ component: Component, highlighted?: boolean }>()
const faces = computed(() => [
  { title: 'Config', rows: faceRows(props.component.config_schema) },
  { title: 'Inputs', rows: faceRows(props.component.inputs) },
  { title: 'Outputs', rows: faceRows(props.component.outputs) }
])
</script>

<template>
  <UCard :id="component.name" class="scroll-mt-20" :class="highlighted ? 'ring-2 ring-primary' : ''" :ui="{ body: 'p-4 sm:p-4' }">
    <div class="flex flex-col gap-3">
      <div class="flex flex-wrap items-center gap-2">
        <a :href="`#${component.name}`" class="font-semibold hover:underline">{{ component.name }}</a>
        <UBadge :color="component.kind === 'process' ? 'primary' : 'neutral'" variant="subtle" size="sm">{{ component.kind }}</UBadge>
        <UBadge v-if="component.dynamic_ports" color="warning" variant="subtle" size="sm">dynamic ports</UBadge>
        <UBadge v-if="component.registry_entry" color="neutral" variant="outline" size="sm">
          {{ component.registry_entry.id }} · {{ component.registry_entry.level }}
        </UBadge>
      </div>
      <code class="text-xs text-muted break-all">{{ component.address }}</code>
      <p v-if="component.description" class="text-sm">{{ component.description }}</p>
      <div class="grid gap-3 md:grid-cols-3">
        <div v-for="face in faces" :key="face.title" class="min-w-0">
          <div class="text-xs font-medium text-muted mb-1">{{ face.title }}</div>
          <p v-if="!face.rows.length" class="text-xs text-dimmed">
            {{ component.dynamic_ports && face.title !== 'Config' ? 'from its config' : 'none' }}
          </p>
          <table v-else class="text-xs font-mono">
            <tr v-for="row in face.rows" :key="row.name" class="align-top">
              <td class="pr-3 py-0.5 whitespace-nowrap">{{ row.name }}</td>
              <td class="py-0.5 text-muted break-all">{{ row.type }}</td>
            </tr>
          </table>
        </div>
      </div>
    </div>
  </UCard>
</template>
