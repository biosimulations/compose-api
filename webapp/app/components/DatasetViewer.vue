<script setup lang="ts">
import type { Dataset } from '~/composables/useApi'
import { viewersFor } from '~/viewers/registry'

// Opens a dataset in the best registered viewer, with a switch when more than one applies (docs/plan-viewers.md F2).
const props = defineProps<{ dataset: Dataset }>()

const viewers = computed(() => viewersFor(props.dataset))
const active = ref(viewers.value[0]?.id)
watch(viewers, (v) => {
  if (!v.some(x => x.id === active.value)) active.value = v[0]?.id
})
const current = computed(() => viewers.value.find(v => v.id === active.value))
</script>

<template>
  <div class="flex flex-col gap-3">
    <p v-if="!viewers.length" class="text-sm text-muted">No viewer for {{ dataset.media_type }} ({{ dataset.kind }}); download it instead.</p>
    <template v-else>
      <div v-if="viewers.length > 1" class="flex gap-1">
        <UButton
          v-for="v in viewers"
          :key="v.id"
          :label="v.label"
          :icon="v.icon"
          size="sm"
          :variant="v.id === active ? 'soft' : 'ghost'"
          color="neutral"
          @click="active = v.id"
        />
      </div>
      <component :is="current.component" v-if="current" :key="`${dataset.id}:${current.id}`" :dataset="dataset" />
    </template>
  </div>
</template>
