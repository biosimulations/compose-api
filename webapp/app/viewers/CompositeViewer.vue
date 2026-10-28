<script setup lang="ts">
import type * as monaco from 'monaco-editor/editor/editor.api'
import type { Diagnostic, Graph } from 'process-bigraph-lang'
import { Pblang } from 'process-bigraph-lang'
import type { Dataset } from '~/composables/useApi'
import ViewerState from './ViewerState.vue'
import CompositeGraph from './composite/CompositeGraph.vue'
import { JSON_LANGUAGE, LANGUAGE, registerLanguage, setHover, stringAt, toMarkers } from './composite/monaco'
import { type ArchiveDocument, compositeDocuments, documentName, isZip } from './composite/archive'
import { type Component, ComponentIndex, interfaceMarkdown, reindentJson } from './composite/interfaces'

/**
 * A submitted composite (`.pbg`, a process-bigraph `{schema, state}` document, on its own or inside an OMEX archive)
 * as `.pblang` text and as a wiring graph. An archive's documents are found the way the service finds them at
 * submission (./composite/archive.ts); when it holds several, one is picked. The document is decompiled in the browser with process-bigraph-lang, checked against the interface manifest
 * of the environment its run used (so its processes resolve to their ports and config), and shown read-only in Monaco
 * with the checker's findings as markers. Large values the printer moved to sidecar assets are listed below the text.
 * The Document tab shows the JSON that was submitted and run, re-indented only. Hovering a class's name in the text,
 * or its address in the document, shows its interface from that manifest, with a link to the environment's page.
 */
const props = defineProps<{ dataset: Dataset }>()
const { bytes, error: loadError, loading, tooBig } = useDatasetFile(() => props.dataset, 'bytes')

const fileName = computed(() => props.dataset.path.split('/').pop() ?? 'composite')
const documents = shallowRef<ArchiveDocument[]>([])
const fromArchive = ref(false)
const chosen = ref<string | undefined>(undefined)
const name = computed(() => documentName(chosen.value ?? fileName.value))
const copyLink = computed(() =>
  `/composites/new?from=${props.dataset.id}${fromArchive.value && chosen.value ? `&member=${encodeURIComponent(chosen.value)}` : ''}`
)
const text = ref<string | null>(null)
// the document as submitted, and re-indented for reading (whitespace only: every token is kept as it was)
const source = ref<string | null>(null)
const sourcePretty = computed(() => (source.value != null && /^\s*[{[]/.test(source.value) ? reindentJson(source.value) : source.value))
const assets = ref<Record<string, string>>({})
const diagnostics = ref<Diagnostic[]>([])
const graph = ref<Graph | null>(null)
const error = ref<string | null>(null)
// what the text was checked against: the run's environment and its manifest, or why there was none
const checkedAgainst = ref<{ environment: string | null, components: number, note: string | null } | null>(null)
// the classes of that environment, for hovers
const index = shallowRef<ComponentIndex | null>(null)
const environmentPage = (environment: string, component?: Component) =>
  `/environments/${encodeURIComponent(environment)}${component ? `#${encodeURIComponent(component.name)}` : ''}`
const tab = ref('text')
const shownAsset = ref<string | null>(null)
const editorHost = ref<HTMLElement | null>(null)
const documentHost = ref<HTMLElement | null>(null)
let editor: monaco.editor.IStandaloneCodeEditor | null = null
let documentEditor: monaco.editor.IStandaloneCodeEditor | null = null

const counts = computed(() => ({
  error: diagnostics.value.filter(d => d.severity === 'error').length,
  warning: diagnostics.value.filter(d => d.severity === 'warning').length,
  info: diagnostics.value.filter(d => d.severity !== 'error' && d.severity !== 'warning').length
}))
const tabs = computed(() => [
  { label: 'Text', icon: 'i-lucide-file-code', value: 'text', slot: 'text' as const },
  { label: 'Document', icon: 'i-lucide-braces', value: 'document', slot: 'document' as const },
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
    index.value = new ComponentIndex(environment.name, manifest)
    checkedAgainst.value = {
      environment: environment.name,
      components: manifest.components.length,
      note: environment.stale ? 'its manifest was read from an earlier image' : null
    }
  } catch (e) {
    checkedAgainst.value = { environment: null, components: 0, note: (e as Error).message }
  }
}

watch(bytes, (value) => {
  if (value == null) return
  try {
    fromArchive.value = isZip(value)
    documents.value = compositeDocuments(value, fileName.value)
    if (!documents.value.length) error.value = 'This archive holds no composite document (no .pbg or .json member).'
    chosen.value = documents.value[0]?.path
  } catch (e) {
    error.value = `Not an archive this viewer can read: ${(e as Error).message}`
  }
})

// one session for the dataset, holding the manifest of the environment its run used
let session: Promise<Pblang> | null = null
function runSession(): Promise<Pblang> {
  session ??= (async () => {
    const pblang = new Pblang()
    await addRunManifest(pblang)
    return pblang
  })()
  return session
}
// started now, not once the file has arrived: finding the run's environment and its manifest takes three requests of
// its own, which then overlap the download
void runSession()

watch(chosen, async (path) => {
  const document = documents.value.find(d => d.path === path)
  if (!document) return
  error.value = null
  try {
    const pblang = await runSession()
    const printed = pblang.decompile(document.text, { name: name.value })
    diagnostics.value = (await pblang.check(printed.text)).diagnostics
    graph.value = await pblang.graph({ document: document.text })
    assets.value = printed.assets
    shownAsset.value = null
    source.value = document.text
    text.value = printed.text
  } catch (e) {
    text.value = null
    source.value = null
    graph.value = null
    diagnostics.value = []
    error.value = `${fromArchive.value ? `${path}: n` : 'N'}ot a composite this viewer can read: ${(e as Error).message}`
  }
})

/** A class's interface as a Monaco hover over `range`. */
function hoverFor(c: Component | null, range: monaco.IRange): monaco.languages.Hover | null {
  if (!c || !index.value) return null
  // absolute: Monaco opens a hover's links itself (in a new tab), and reads a bare path as a file
  const href = `${window.location.origin}${useRuntimeConfig().app.baseURL.replace(/\/$/, '')}${environmentPage(index.value.environment, c)}`
  return { range, contents: [{ value: interfaceMarkdown(c, index.value.environment, href) }] }
}

/**
 * A read-only Monaco editor in `host`, made once the value exists and its tab has rendered (tabs keep their content
 * mounted), and reused for another document of the same archive.
 */
function showReadOnly(
  current: monaco.editor.IStandaloneCodeEditor | null,
  host: HTMLElement,
  value: string,
  language: string,
  hover: (model: monaco.editor.ITextModel, position: monaco.Position) => monaco.languages.Hover | null
): monaco.editor.IStandaloneCodeEditor {
  const m = registerLanguage()
  if (current && current.getContainerDomNode() === host) {
    current.getModel()!.setValue(value)
    return current
  }
  if (current) {
    // the host was re-rendered (after a document that could not be read)
    current.getModel()?.dispose()
    current.dispose()
  }
  const model = m.editor.createModel(value, language, m.Uri.parse(`inmemory://composite/${props.dataset.id}/${language}`))
  const hovering = setHover(model, hover)
  model.onWillDispose(() => hovering.dispose())
  return m.editor.create(host, {
    model,
    readOnly: true,
    automaticLayout: true,
    minimap: { enabled: false },
    scrollBeyondLastLine: false,
    fontSize: 12,
    lineNumbersMinChars: 3,
    renderLineHighlight: 'none',
    folding: true,
    fixedOverflowWidgets: true // hover boxes may extend past the editor's frame
  })
}

watch([text, editorHost], ([value, host]) => {
  if (value == null || !host) return
  editor = showReadOnly(editor, host, value, LANGUAGE, (model, position) => {
    const word = model.getWordAtPosition(position)
    if (!word) return null
    const range = { startLineNumber: position.lineNumber, startColumn: word.startColumn, endLineNumber: position.lineNumber, endColumn: word.endColumn }
    return hoverFor(index.value?.named(word.word) ?? null, range)
  })
  registerLanguage().editor.setModelMarkers(editor.getModel()!, 'pblang', toMarkers(diagnostics.value))
})
watch([sourcePretty, documentHost], ([value, host]) => {
  if (value == null || !host) return
  documentEditor = showReadOnly(documentEditor, host, value, JSON_LANGUAGE, (model, position) => {
    const s = stringAt(model, position)
    // an address: `local:…` (the classes' protocol; other protocols name no class here)
    return s && s.value.startsWith('local:') ? hoverFor(index.value?.find(s.value) ?? null, s.range) : null
  })
})
onBeforeUnmount(() => {
  for (const e of [editor, documentEditor]) {
    e?.getModel()?.dispose()
    e?.dispose()
  }
})

function revealFinding(d: Diagnostic) {
  tab.value = 'text'
  nextTick(() => {
    editor?.revealLineInCenter(d.range.start.line + 1)
    editor?.setPosition({ lineNumber: d.range.start.line + 1, column: d.range.start.character + 1 })
    editor?.focus()
  })
}

function download(content: string | null, filename: string, type: string) {
  if (content == null) return
  const url = URL.createObjectURL(new Blob([content], { type }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}
const documentFile = computed(() => (fromArchive.value && chosen.value ? chosen.value.split('/').pop()! : fileName.value))

const severityColor = (s: Diagnostic['severity']) => (s === 'error' ? 'error' : s === 'warning' ? 'warning' : 'neutral')
</script>

<template>
  <div class="flex flex-col gap-3">
    <div v-if="fromArchive && documents.length" class="flex flex-wrap items-center gap-2 text-sm">
      <UIcon name="i-lucide-file-archive" class="text-muted" />
      <span class="text-muted">{{ documents.length === 1 ? 'The composite document in this archive:' : `${documents.length} composite documents in this archive:` }}</span>
      <USelect v-if="documents.length > 1" v-model="chosen" :items="documents.map(d => d.path)" size="sm" class="min-w-64" />
      <code v-else>{{ chosen }}</code>
    </div>
    <ViewerState :loading="loading" :error="loadError ?? error" :too-big="tooBig" :size="dataset.size_bytes" />
    <template v-if="text != null">
      <div class="flex flex-wrap items-center gap-2 text-sm">
        <UBadge v-if="counts.error" color="error" variant="subtle">{{ counts.error }} error{{ counts.error === 1 ? '' : 's' }}</UBadge>
        <UBadge v-if="counts.warning" color="warning" variant="subtle">{{ counts.warning }} warning{{ counts.warning === 1 ? '' : 's' }}</UBadge>
        <UBadge v-if="!counts.error && !counts.warning" color="success" variant="subtle">no errors or warnings</UBadge>
        <UBadge v-if="counts.info" color="neutral" variant="subtle">{{ counts.info }} note{{ counts.info === 1 ? '' : 's' }}</UBadge>
        <span v-if="graph" class="text-muted">{{ graph.nodes.length }} node{{ graph.nodes.length === 1 ? '' : 's' }}, {{ graph.stores.length }} store{{ graph.stores.length === 1 ? '' : 's' }}</span>
        <UTooltip v-if="checkedAgainst" :text="checkedAgainst.note ?? 'Addresses resolve to the ports and config this environment\'s classes declare'">
          <ULink v-if="checkedAgainst.environment" :to="environmentPage(checkedAgainst.environment)">
            <UBadge :color="checkedAgainst.components && !checkedAgainst.note ? 'neutral' : 'warning'" variant="outline" icon="i-lucide-package-check">
              <template v-if="checkedAgainst.components">checked against {{ checkedAgainst.environment }} ({{ checkedAgainst.components }} components)</template>
              <template v-else>not checked against an environment ({{ checkedAgainst.environment }})</template>
            </UBadge>
          </ULink>
          <UBadge v-else color="warning" variant="outline" icon="i-lucide-package-check">not checked against an environment</UBadge>
        </UTooltip>
        <span class="grow" />
        <UButton icon="i-lucide-square-pen" label="Edit a copy" size="sm" variant="subtle" color="neutral" :to="copyLink" />
        <UButton icon="i-lucide-download" :label="`${name}.pblang`" size="sm" variant="subtle" color="neutral" @click="download(text, `${name}.pblang`, 'text/plain')" />
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
        <template #document>
          <div class="pt-3 flex flex-col gap-2">
            <div class="flex flex-wrap items-center gap-2 text-sm">
              <span class="text-muted">
                The process-bigraph document as submitted{{ fromArchive ? ` (${chosen} in the archive)` : '' }}, indented for
                reading. Hover an <code>address</code> to see its class's interface.
              </span>
              <span class="grow" />
              <UButton icon="i-lucide-download" :label="documentFile" size="sm" variant="subtle" color="neutral" @click="download(source, documentFile, 'application/json')" />
            </div>
            <div ref="documentHost" class="h-[60vh] rounded border border-default overflow-hidden" />
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
