<script setup lang="ts">
import { type Component, faceRows } from '~/viewers/composite/interfaces'

// One class of an environment's interface manifest: its address, config, ports, and registry entry, as declared in
// the image (types in bigraph-schema's own form).
// `header` is its `.pblang` declaration; it and the manifest entry open below the faces.
const props = defineProps<{ component: Component, highlighted?: boolean, header?: string }>()
const shown = ref<'header' | 'json' | null>(props.highlighted && props.header ? 'header' : null)
watch(() => [props.highlighted, props.header] as const, ([on, header]) => {
  if (on && header && !shown.value) shown.value = 'header'
})
const json = computed(() => {
  const { registry_entry: _entry, ...entry } = props.component
  return JSON.stringify(entry, null, 2)
})
// what a composite writes to use the class, above its declaration
const headerText = computed(() =>
  props.header && props.component.module ? `import ${props.component.module}.{${props.component.name}};\n\n${props.header}` : props.header
)
function toggle(view: 'header' | 'json') {
  shown.value = shown.value === view ? null : view
}
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
        <span class="ms-auto flex gap-1">
          <UButton
            v-if="header" size="xs" icon="i-lucide-file-code" label="Header" color="neutral"
            :variant="shown === 'header' ? 'soft' : 'ghost'" @click="toggle('header')"
          />
          <UButton
            size="xs" icon="i-lucide-braces" label="JSON" color="neutral"
            :variant="shown === 'json' ? 'soft' : 'ghost'" @click="toggle('json')"
          />
        </span>
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
      <pre
        v-if="shown"
        class="text-xs font-mono bg-elevated rounded p-3 overflow-x-auto"
        :aria-label="shown === 'header' ? `${component.name} as a .pblang header` : `${component.name} in the manifest`"
      >{{ shown === 'header' ? headerText : json }}</pre>
    </div>
  </UCard>
</template>
