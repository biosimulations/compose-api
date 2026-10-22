<script setup lang="ts">
import type { Schemas } from '~/composables/useApi'

// Regression and reproducibility suites (docs/plan-sedml.md, phase 6): reviewed lists of SED-ML models, each run on
// every solver and compared with the others, with references, and with the suite's accepted baseline run.
const suites = ref<Schemas['Suite'][]>([])
const error = ref<string | null>(null)
onMounted(async () => {
  const { data, error: err } = await useApi().GET('/suites')
  if (err || !data) error.value = errorMessage(err, 'Could not list the suites')
  suites.value = data ?? []
})
</script>

<template>
  <div>
    <PageHeader title="Suites" description="Reviewed lists of SED-ML models, run on every solver and compared, now and against an accepted baseline." />
    <UContainer class="py-6 flex flex-col gap-4">
      <UAlert v-if="error" color="error" variant="subtle" :title="error" />
      <div class="grid gap-4 md:grid-cols-2">
        <ULink v-for="s in suites" :key="s.name" :to="`/suites/${s.name}`" class="block">
          <UCard class="h-full hover:ring-2 hover:ring-primary transition">
            <div class="flex flex-col gap-2 text-sm">
              <span class="text-lg font-semibold">{{ s.name }}</span>
              <span>{{ s.description }}</span>
              <span class="text-muted">{{ s.sources.length }} models · solvers {{ s.solvers?.join(', ') || 'all' }} · baseline {{ s.baseline ?? 'none yet' }}</span>
            </div>
          </UCard>
        </ULink>
      </div>
    </UContainer>
  </div>
</template>
