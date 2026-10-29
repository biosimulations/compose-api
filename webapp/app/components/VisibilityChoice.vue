<script setup lang="ts">
import type { Schemas } from '~/composables/useApi'

// Who may read a new run (docs/plan-favorites-and-studies.md, F3): private by default when signed in; an anonymous
// run is always public, so signed out there is nothing to choose.
const visibility = defineModel<Schemas['Visibility']>({ default: 'private' })
const { isAuthenticated } = useAuth()

const items = [
  { label: 'Private', value: 'private', description: 'Only you (and administrators); you can make it public later' },
  { label: 'Public', value: 'public', description: 'Anyone with the link, and the public lists' }
]
</script>

<template>
  <UFormField label="Visibility">
    <URadioGroup v-if="isAuthenticated" v-model="visibility" :items="items" orientation="horizontal" />
    <p v-else class="text-sm text-muted">
      Signed out, the run is public. Sign in to keep it private.
    </p>
  </UFormField>
</template>
