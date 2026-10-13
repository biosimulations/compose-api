<script setup lang="ts">
// A run's labels (written by the service: what the run is) and tags (the submitter's), as chips that filter the
// simulations list (docs/plan-sedml.md, phase 0).
defineProps<{ labels?: Record<string, string>, tags?: string[], size?: 'xs' | 'sm' | 'md' }>()
</script>

<template>
  <div class="flex flex-wrap gap-1">
    <ULink v-for="(value, key) in labels ?? {}" :key="`l-${key}`" :to="{ path: '/simulations', query: { label: `${key}:${value}` } }">
      <UBadge color="neutral" variant="outline" :size="size ?? 'sm'" :title="`label ${key}`">
        <span class="text-muted">{{ key }}</span>&nbsp;{{ value }}
      </UBadge>
    </ULink>
    <ULink v-for="tag in tags ?? []" :key="`t-${tag}`" :to="{ path: '/simulations', query: { tag } }">
      <UBadge color="primary" variant="subtle" :size="size ?? 'sm'" icon="i-lucide-tag" :title="'tag'">{{ tag }}</UBadge>
    </ULink>
  </div>
</template>
