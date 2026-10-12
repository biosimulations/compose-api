<script setup lang="ts">
import type * as monaco from 'monaco-editor/editor/editor.api'
import type { Diagnostic, Graph } from 'process-bigraph-lang'
import { Pblang } from 'process-bigraph-lang'
import type { Dataset } from '~/composables/useApi'
import ViewerState from './ViewerState.vue'
import CompositeGraph from './composite/CompositeGraph.vue'
import { LANGUAGE, registerLanguage, toMarkers } from './composite/monaco'

/**
 * A submitted composite (`.pbg`, a process-bigraph `{schema, state}` document) as `.pblang` text and as a wiring
 * graph. The document is decompiled in the browser with process-bigraph-lang, checked against the interface manifest
 * of the environment its run used (so its processes resolve to their ports and config), and shown read-only in Monaco
 * with the checker's findings as markers. Large values the printer moved to sidecar assets are listed below the text.
 */
const props = defineProps<{ dataset: Dataset }>()
const { text: json, error: loadError, loading, tooBig } = useDatasetFile(() => props.dataset, 'text')

const name = computed(() => (props.dataset.path.split('/').pop() ?? 'composite').replace(/\.(pbg|json|ya?ml)$/i, ''))
const text = ref<string | null>(null)
const assets = ref<Record<string, string>>({})
const diagnostics = ref<Diagnostic[]>([])
const graph = ref<Graph | null>(null)
const error = ref<string | null>(null)
// what the text was checked against: the run's environment and its manifest, or why there was none
const checkedAgainst = ref<{ environment: string | null, components: number, note: string | null } | null>(null)
const tab = ref('text')
const shownAsset = ref<string | null>(null)
const editorHost = ref<HTMLElement | null>(null)
let editor: monaco.editor.IStandaloneCodeEditor | null = null

const counts = computed(() => ({
  error: diagnostics.value.filter(d => d.severity === 'error').length,
  warning: diagnostics.value.filter(d => d.severity === 'warning').length,
  info: diagnostics.value.filter(d => d.severity !== 'error' && d.severity !== 'warning').length
}))
const tabs = computed(() => [
  { label: 'Text', icon: 'i-lucide-file-code', value: 'text', slot: 'text' as const },
  { label: 'Graph', icon: 'i-lucide-workflow', value: 'graph', slot: 'graph' as const },
  { label: `Findings (${diagnostics.value.length})`, icon: 'i-lucide-list-checks', value: 'findings', slot: 'findings' as const }
])

/** The manifest of the environment this dataset's run used; never fails the viewer, it only checks less. */
async function addRunManifest(pblang: Pblang): Promise<void> {
  try {
    const { data: simulation } = await useApi().GET('/simulations/{simulation_id}', {
      params: { path: { simulation_id: props.dataset.simulation_id } }
    })
    const environment = await environmentFor(simulation?.simulator)
    if (!environment) {
      checkedAgainst.value = { environment: null, components: 0, note: 'its run used an environment this service no longer offers' }
      return
    }
    const manifest = await fetchManifest(environment.name)
    if (!manifest) {
      checkedAgainst.value = { environment: environment.name, components: 0, note: 'no interface manifest has been generated for it' }
      return
    }
    pblang.addManifest(manifest)
    checkedAgainst.value = {
      environment: environment.name,
      components: manifest.components.length,
      note: environment.stale ? 'its manifest was read from an earlier image' : null
    }
  } catch (e) {
    checkedAgainst.value = { environment: null, components: 0, note: (e as Error).message }
  }
}

watch(json, async (value) => {
  if (value == null) return
  try {
    const pblang = new Pblang()
    await addRunManifest(pblang)
    const printed = pblang.decompile(value, { name: name.value })
    text.value = printed.text
    assets.value = printed.assets
    diagnostics.value = (await pblang.check(printed.text)).diagnostics
    graph.value = await pblang.graph({ document: value })
  } catch (e) {
    error.value = `Not a composite this viewer can read: ${(e as Error).message}`
  }
})

// Monaco mounts once the text exists and its tab is visible; it keeps the model when tabs switch (unmount-on-hide off).
watch([text, editorHost], ([value, host]) => {
  if (value == null || !host || editor) return
  const m = registerLanguage()
  const model = m.editor.createModel(value, LANGUAGE, m.Uri.parse(`inmemory://composite/${props.dataset.id}.pblang`))
  m.editor.setModelMarkers(model, 'pblang', toMarkers(diagnostics.value))
  editor = m.editor.create(host, {
    model,
    readOnly: true,
    automaticLayout: true,
    minimap: { enabled: false },
    scrollBeyondLastLine: false,
    fontSize: 12,
    lineNumbersMinChars: 3,
    renderLineHighlight: 'none'
  })
})
onBeforeUnmount(() => {
  editor?.getModel()?.dispose()
  editor?.dispose()
})

function revealFinding(d: Diagnostic) {
  tab.value = 'text'
  nextTick(() => {
    editor?.revealLineInCenter(d.range.start.line + 1)
    editor?.setPosition({ lineNumber: d.range.start.line + 1, column: d.range.start.character + 1 })
    editor?.focus()
  })
}

function download() {
  if (text.value == null) return
  const url = URL.createObjectURL(new Blob([text.value], { type: 'text/plain' }))
  const a = document.createElement('a')
  a.href = url
  a.download = `${name.value}.pblang`
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

const severityColor = (s: Diagnostic['severity']) => (s === 'error' ? 'error' : s === 'warning' ? 'warning' : 'neutral')
</script>

<template>
  <div class="flex flex-col gap-3">
    <ViewerState :loading="loading" :error="loadError ?? error" :too-big="tooBig" :size="dataset.size_bytes" />
    <template v-if="text != null">
      <div class="flex flex-wrap items-center gap-2 text-sm">
        <UBadge v-if="counts.error" color="error" variant="subtle">{{ counts.error }} error{{ counts.error === 1 ? '' : 's' }}</UBadge>
        <UBadge v-if="counts.warning" color="warning" variant="subtle">{{ counts.warning }} warning{{ counts.warning === 1 ? '' : 's' }}</UBadge>
        <UBadge v-if="!counts.error && !counts.warning" color="success" variant="subtle">no errors or warnings</UBadge>
        <UBadge v-if="counts.info" color="neutral" variant="subtle">{{ counts.info }} note{{ counts.info === 1 ? '' : 's' }}</UBadge>
        <span v-if="graph" class="text-muted">{{ graph.nodes.length }} node{{ graph.nodes.length === 1 ? '' : 's' }}, {{ graph.stores.length }} store{{ graph.stores.length === 1 ? '' : 's' }}</span>
        <UTooltip v-if="checkedAgainst" :text="checkedAgainst.note ?? 'Addresses resolve to the ports and config this environment\'s classes declare'">
          <UBadge :color="checkedAgainst.components && !checkedAgainst.note ? 'neutral' : 'warning'" variant="outline" icon="i-lucide-package-check">
            <template v-if="checkedAgainst.components">checked against {{ checkedAgainst.environment }} ({{ checkedAgainst.components }} components)</template>
            <template v-else>not checked against an environment{{ checkedAgainst.environment ? ` (${checkedAgainst.environment})` : '' }}</template>
          </UBadge>
        </UTooltip>
        <span class="grow" />
        <UButton icon="i-lucide-download" :label="`${name}.pblang`" size="sm" variant="subtle" color="neutral" @click="download" />
      </div>
      <UTabs v-model="tab" :items="tabs" variant="link" class="w-full" :unmount-on-hide="false">
        <template #text>
          <div class="pt-3 flex flex-col gap-3">
            <div ref="editorHost" class="h-[60vh] rounded border border-default overflow-hidden" />
            <div v-if="Object.keys(assets).length" class="flex flex-col gap-2 text-sm">
              <p class="text-muted">Values too large for the text are in sidecar files the text references with <code>file("…")</code>:</p>
              <div class="flex flex-wrap gap-1">
                <UButton
                  v-for="(content, path) in assets"
                  :key="path"
                  :label="`${path} (${formatBytes(content.length)})`"
                  size="xs"
                  :variant="shownAsset === path ? 'soft' : 'ghost'"
                  color="neutral"
                  @click="shownAsset = shownAsset === path ? null : path"
                />
              </div>
              <pre v-if="shownAsset && assets[shownAsset] != null" class="text-xs font-mono p-3 rounded bg-elevated/50 border border-default overflow-auto max-h-64 whitespace-pre-wrap">{{ assets[shownAsset]!.slice(0, 20000) }}{{ assets[shownAsset]!.length > 20000 ? '\n…' : '' }}</pre>
            </div>
          </div>
        </template>
        <template #graph>
          <div class="pt-3">
            <CompositeGraph v-if="graph" :graph="graph" />
          </div>
        </template>
        <template #findings>
          <div class="pt-3">
            <p v-if="!diagnostics.length" class="text-sm text-muted">The checker found nothing to report.</p>
            <ul v-else class="flex flex-col gap-1 text-sm">
              <li v-for="(d, i) in diagnostics" :key="i">
                <button class="text-left flex gap-2 items-start hover:underline" @click="revealFinding(d)">
                  <UBadge :color="severityColor(d.severity)" variant="subtle" size="sm" class="font-mono shrink-0">{{ d.code }}</UBadge>
                  <span><span class="text-muted font-mono">{{ d.path || `line ${d.range.start.line + 1}` }}</span> {{ d.message }}</span>
                </button>
              </li>
            </ul>
          </div>
        </template>
      </UTabs>
    </template>
  </div>
</template>
