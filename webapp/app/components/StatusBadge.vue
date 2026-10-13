<script setup lang="ts">
defineProps<{ status: string | null | undefined }>()
</script>

<template>
  <UBadge :color="statusColor(status)" variant="subtle" class="capitalize">
    <UIcon v-if="status && !isTerminal(status) && status !== 'unknown'" name="i-lucide-loader-circle" class="animate-spin size-3" />
    {{ (status ?? 'unknown').replaceAll('_', ' ') }}
  </UBadge>
</template>
