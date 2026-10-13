<script setup lang="ts">
import type { ArchiveSource, SedmlPreview, Solver } from '~/composables/useSedml'

// A SED-ML archive's translation (its tasks, which solvers accept each, the findings) and the choice to run it: the
// solvers, tags and a description. Running opens the comparison (docs/plan-sedml.md, phase 5).
const props = defineProps<{ source: ArchiveSource, label: string }>()

const solvers = ref<Solver[]>([])
const chosen = ref<string[]>([])
const tags = ref<string[]>([])
const description = ref('')
const preview = shallowRef<SedmlPreview | null>(null)
const loading = ref(false)
const running = ref(false)
const error = ref<string | null>(null)
const findings = ref<SedmlPreview['findings']>([])

async function load() {
  loading.value = true
  error.value = null
  preview.value = null
  try {
    solvers.value = await listSolvers()
    if (!chosen.value.length) chosen.value = solvers.value.map(s => s.id)
    const outcome = await previewSedml(await archiveOf(props.source), chosen.value)
    if (outcome.ok) {
      preview.value = outcome.value
      findings.value = outcome.value.findings
    } else {
      error.value = outcome.error
      findings.value = outcome.findings
    }
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}
watch(() => props.source, load, { immediate: true })

const runnable = computed(() => preview.value?.tasks.some(t => t.solvers.some(s => chosen.value.includes(s))) ?? false)

async function run() {
  running.value = true
  error.value = null
  try {
    const outcome = await runSedml(props.source, { solvers: chosen.value, tags: tags.value, description: description.value })
    if (!outcome.ok) {
      error.value = outcome.error
      if (outcome.findings.length) findings.value = outcome.findings
      return
    }
    const [first] = outcome.value.comparisons
    if (first) await navigateTo(`/comparisons/${first.comparison_id}`)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    running.value = false
  }
}

const severityColor = (s: string) => (s === 'error' ? 'error' : s === 'warning' ? 'warning' : 'neutral')
const shownTemplate = ref<string | null>(null)
</script>

<template>
  <UCard>
    <template #header>
      <div class="flex flex-wrap items-center gap-2">
        <UIcon name="i-lucide-file-archive" />
        <span class="font-semibold">{{ label }}</span>
        <span class="grow" />
        <UButton icon="i-lucide-refresh-cw" size="xs" variant="ghost" color="neutral" :loading="loading" @click="load" />
      </div>
    </template>
    <div class="flex flex-col gap-4 text-sm">
      <p v-if="loading" class="text-muted">Translating…</p>
      <UAlert v-if="error" color="error" variant="subtle" icon="i-lucide-circle-alert" :title="error" />
      <div v-if="preview" class="flex flex-col gap-2">
        <div v-for="t in preview.tasks" :key="`${t.sedml}/${t.task}`" class="flex flex-wrap items-center gap-2">
          <code>{{ t.sedml }}</code><span class="text-muted">task</span><code>{{ t.task }}</code>
          <UBadge v-for="s in t.solvers" :key="s" color="success" variant="subtle" size="sm">{{ s }}</UBadge>
          <UBadge v-for="s in t.refused" :key="s" color="error" variant="outline" size="sm" :title="'refused'">{{ s }}</UBadge>
          <span class="text-muted">{{ t.reports?.length ?? 0 }} report(s)</span>
          <UButton size="xs" variant="link" color="neutral" :label="shownTemplate === t.task ? 'Hide .pblang' : 'Show .pblang'" @click="shownTemplate = shownTemplate === t.task ? null : t.task" />
          <pre v-if="shownTemplate === t.task" class="w-full text-xs font-mono p-3 rounded bg-elevated/50 border border-default overflow-auto max-h-80">{{ t.template }}</pre>
        </div>
        <p v-if="!preview.tasks.length" class="text-muted">No task of this archive could be translated.</p>
      </div>
      <ul v-if="findings.length" class="flex flex-col gap-1">
        <li v-for="(f, i) in findings" :key="i" class="flex gap-2 items-start">
          <UBadge :color="severityColor(f.severity)" variant="subtle" size="sm" class="font-mono shrink-0">{{ f.code }}</UBadge>
          <span><span v-if="f.solver" class="text-muted">[{{ f.solver }}]</span> {{ f.message }}</span>
        </li>
      </ul>
      <div v-if="preview" class="flex flex-wrap items-end gap-3 pt-2 border-t border-default">
        <UFormField label="Solvers">
          <USelectMenu v-model="chosen" :items="solvers.map(s => ({ label: `${s.name} (${s.id})`, value: s.id }))" value-key="value" multiple class="min-w-72" @update:model-value="load" />
        </UFormField>
        <UFormField label="Tags">
          <UInputTags v-model="tags" placeholder="optional" class="w-64" />
        </UFormField>
        <UFormField label="Description" class="grow">
          <UInput v-model="description" placeholder="optional" class="w-full" />
        </UFormField>
        <UButton icon="i-lucide-play" label="Run on each solver" :loading="running" :disabled="!runnable" @click="run" />
      </div>
    </div>
  </UCard>
</template>
