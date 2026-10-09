<script setup lang="ts">
import type { StepperItem } from '@nuxt/ui'

// Submit a run. A three-step UStepper after ../platform/frontend/app/pages/simulations/run.vue:
// what to run, how to run it, review and submit.
const api = useApi()
const prebuilt = computed(() => useWebappConfig().value?.prebuilt_simulators ?? [])

type Mode = 'archive' | 'copasi' | 'tellurium'
const mode = ref<Mode>('archive')
const file = ref<File | null>(null)

// /simulation/run
const intervalTime = ref(1)
const batch = ref(false)
const simulator = ref<string | undefined>(undefined)
// /curated/*
const startTime = ref(0)
const duration = ref(10)
const endTime = ref(10)
const points = ref(100)

const step = ref(0)
const submitting = ref(false)
const error = ref<string | null>(null)
const violations = ref<Violation[]>([])

const steps: StepperItem[] = [
  { title: 'Upload', description: 'What to run', icon: 'i-lucide-upload' },
  { title: 'Options', description: 'How to run it', icon: 'i-lucide-sliders-horizontal' },
  { title: 'Submit', description: 'Review and send', icon: 'i-lucide-send' }
]

const modes = [
  { label: 'Composite / COMBINE archive', value: 'archive', description: '.pbg document or .omex archive, run as given' },
  { label: 'SBML with COPASI', value: 'copasi', description: 'A curated time course from an SBML model' },
  { label: 'SBML with Tellurium', value: 'tellurium', description: 'A curated time course from an SBML model' }
]

const accept = computed(() => (mode.value === 'archive' ? '.omex,.pbg,.sbml' : '.xml,.sbml'))
const fileOk = computed(() => !!file.value)
const optionsOk = computed(() => {
  if (mode.value === 'archive') return intervalTime.value >= 0 && intervalTime.value <= 1000
  if (points.value < 1) return false
  return mode.value === 'copasi' ? duration.value > 0 : endTime.value > startTime.value
})

watch(mode, () => {
  file.value = null
})

// The API types an upload by its suffix and takes only `.sbml` as SBML; models usually arrive as `.xml`.
function asSbml(f: File): File {
  return /\.sbml$/i.test(f.name) ? f : new File([f], f.name.replace(/\.[^.]*$/, '') + '.sbml', { type: f.type })
}

async function submit() {
  if (!file.value) return
  submitting.value = true
  error.value = null
  violations.value = []
  const form = new FormData()
  const asIs = { bodySerializer: (b: unknown) => b as FormData }
  let result
  if (mode.value === 'archive') {
    form.append('uploaded_file', file.value)
    result = await api.POST('/simulation/run', {
      params: { query: { interval_time: intervalTime.value, batch_submission: batch.value, simulator: simulator.value || undefined } },
      body: form as never,
      ...asIs
    })
  } else if (mode.value === 'copasi') {
    form.append('sbml', asSbml(file.value))
    result = await api.POST('/curated/copasi', {
      params: { query: { start_time: startTime.value, duration: duration.value, num_data_points: points.value } },
      body: form as never,
      ...asIs
    })
  } else {
    form.append('sbml', asSbml(file.value))
    result = await api.POST('/curated/tellurium', {
      params: { query: { start_time: startTime.value, end_time: endTime.value, num_data_points: points.value } },
      body: form as never,
      ...asIs
    })
  }
  submitting.value = false
  if (result.error || !result.data) {
    error.value = errorMessage(result.error, `Submission failed (${result.response.status})`)
    violations.value = errorViolations(result.error)
    return
  }
  await navigateTo(`/simulations/${result.data.simulation_database_id}`)
}
</script>

<template>
  <div>
    <PageHeader title="Run a simulation" description="Runs go to the SLURM cluster as Apptainer containers. Only processes the registry allows are accepted." />
    <UContainer class="py-8 max-w-3xl flex flex-col gap-8">
      <UStepper v-model="step" :items="steps" disabled />

      <section v-if="step === 0" class="flex flex-col gap-6">
        <URadioGroup v-model="mode" :items="modes" variant="card" />
        <UFileUpload
          v-model="file"
          :accept="accept"
          :label="mode === 'archive' ? 'Drop a .pbg or .omex file' : 'Drop an SBML model'"
          :description="accept"
          icon="i-lucide-file-up"
          class="w-full min-h-40"
        />
        <div class="flex justify-end">
          <UButton label="Next" trailing-icon="i-lucide-arrow-right" :disabled="!fileOk" @click="step = 1" />
        </div>
      </section>

      <section v-else-if="step === 1" class="flex flex-col gap-6">
        <template v-if="mode === 'archive'">
          <UFormField label="Simulator" :help="prebuilt.length ? 'A prebuilt image this deployment lists, or the shared container' : 'This deployment lists no prebuilt images; runs use the shared container'">
            <USelect v-model="simulator" :items="prebuilt" placeholder="Shared container" clearable class="w-72" :disabled="!prebuilt.length" />
          </UFormField>
          <UFormField label="Interval time" help="End time point, between 0 and 1000">
            <UInputNumber v-model="intervalTime" :min="0" :max="1000" :step="0.1" class="w-48" />
          </UFormField>
          <USwitch v-model="batch" label="Batch submission" description="Use the batch partition (1 CPU, 1 GB)" />
          <UAlert
            v-if="simulator"
            variant="subtle"
            color="info"
            icon="i-lucide-info"
            description="A prebuilt image brings its own processes, so the registry does not check this document."
          />
        </template>
        <template v-else>
          <UFormField label="Start time"><UInputNumber v-model="startTime" :min="0" class="w-48" /></UFormField>
          <UFormField v-if="mode === 'copasi'" label="Duration"><UInputNumber v-model="duration" :min="0" class="w-48" /></UFormField>
          <UFormField v-else label="End time"><UInputNumber v-model="endTime" :min="0" class="w-48" /></UFormField>
          <UFormField label="Data points"><UInputNumber v-model="points" :min="1" class="w-48" /></UFormField>
        </template>
        <div class="flex justify-between">
          <UButton label="Back" variant="ghost" leading-icon="i-lucide-arrow-left" @click="step = 0" />
          <UButton label="Next" trailing-icon="i-lucide-arrow-right" :disabled="!optionsOk" @click="step = 2" />
        </div>
      </section>

      <section v-else class="flex flex-col gap-6">
        <UCard>
          <dl class="grid grid-cols-[10rem_1fr] gap-y-2 text-sm">
            <dt class="text-muted">File</dt><dd class="font-mono">{{ file?.name }} ({{ formatBytes(file?.size) }})</dd>
            <dt class="text-muted">Run as</dt><dd>{{ modes.find(m => m.value === mode)?.label }}</dd>
            <template v-if="mode === 'archive'">
              <dt class="text-muted">Simulator</dt><dd>{{ simulator || 'Shared container' }}</dd>
              <dt class="text-muted">Interval time</dt><dd>{{ intervalTime }}</dd>
              <dt class="text-muted">Batch</dt><dd>{{ batch ? 'yes' : 'no' }}</dd>
            </template>
            <template v-else>
              <dt class="text-muted">Start</dt><dd>{{ startTime }}</dd>
              <dt class="text-muted">{{ mode === 'copasi' ? 'Duration' : 'End' }}</dt><dd>{{ mode === 'copasi' ? duration : endTime }}</dd>
              <dt class="text-muted">Data points</dt><dd>{{ points }}</dd>
            </template>
          </dl>
        </UCard>

        <UAlert v-if="error" color="error" variant="subtle" icon="i-lucide-circle-x" title="Not submitted" :description="error">
          <template v-if="violations.length" #description>
            <p>{{ error }}</p>
            <ul class="mt-2 flex flex-col gap-1 font-mono text-xs">
              <li v-for="v in violations" :key="`${v.document}:${v.address}`">
                <span class="font-semibold">{{ v.address }}</span> in {{ v.document }}: {{ v.reason }}
              </li>
            </ul>
          </template>
        </UAlert>

        <div class="flex justify-between">
          <UButton label="Back" variant="ghost" leading-icon="i-lucide-arrow-left" :disabled="submitting" @click="step = 1" />
          <UButton label="Submit" icon="i-lucide-send" :loading="submitting" @click="submit" />
        </div>
      </section>
    </UContainer>
  </div>
</template>
