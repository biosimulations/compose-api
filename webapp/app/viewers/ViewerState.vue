<script setup lang="ts">
// Loading / error / too-big states shared by the whole-file viewers.
defineProps<{ loading: boolean, error: string | null, tooBig?: boolean, size?: number | null }>()
</script>

<template>
  <p v-if="loading" class="text-sm text-muted"><UIcon name="i-lucide-loader-circle" class="animate-spin" /> Loading…</p>
  <UAlert v-else-if="error" color="error" variant="subtle" :description="error" />
  <p v-else-if="tooBig" class="text-sm text-muted">Too large to preview ({{ formatBytes(size) }}); download it instead.</p>
</template>
