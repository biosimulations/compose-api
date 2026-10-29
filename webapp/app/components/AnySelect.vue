<script setup lang="ts">
// A select whose first option clears it ("Any status", "Automatic"): USelect has no `clearable` prop, so a
// value once chosen could not be removed. The model is undefined while that first option is chosen.
type Item = string | { label: string, value: string }
const props = defineProps<{ items: readonly Item[], placeholder: string }>()
const model = defineModel<string | null | undefined>()

const ANY = '__any__' // a value reka-ui accepts (it refuses an empty string)
const options = computed(() => [
  { label: props.placeholder, value: ANY },
  ...props.items.map(item => (typeof item === 'string' ? { label: item.replaceAll('_', ' '), value: item } : item))
])
const value = computed({
  get: () => model.value || ANY,
  set: (v: string) => {
    model.value = v === ANY ? undefined : v
  }
})
</script>

<template>
  <USelect v-model="value" :items="options" />
</template>
