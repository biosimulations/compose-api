<script setup lang="ts">
import type { Schemas } from '~/composables/useApi'

// Where a run ran: its environment version, or its simulator when it ran before versions (plan-webapp-admin 5c).
const props = defineProps<{ version?: Schemas['VersionRef'] | null, simulatorId: number }>()
const link = computed(() => ranInLink(props.version, props.simulatorId))
</script>

<template>
  <NuxtLink :to="link.to" :title="version ? 'Environment' : 'Legacy environment (before environments had versions)'" class="font-mono" :class="version ? 'text-primary' : 'text-muted hover:text-primary'">{{ link.label }}</NuxtLink>
</template>
