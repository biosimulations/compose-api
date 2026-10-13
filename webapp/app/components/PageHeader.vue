<script setup lang="ts">
defineProps<{ title: string, description?: string }>()
</script>

<template>
  <section class="page_header border-b border-default">
    <div class="background" />
    <div class="max-w-(--ui-container) mx-auto px-4 sm:px-6 lg:px-8 py-8 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 class="text-2xl font-bold">{{ title }}</h1>
        <p v-if="description" class="text-muted mt-1">{{ description }}</p>
      </div>
      <div class="flex items-center gap-2">
        <slot name="actions" />
      </div>
    </div>
  </section>
</template>
