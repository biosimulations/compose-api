<script setup lang="ts">
import type * as monaco from 'monaco-editor/editor/editor.api'
import { CompileError, Pblang, type Diagnostic } from 'process-bigraph-lang'
import { PblangLanguageClient } from '~/viewers/composite/languageClient'
import { LANGUAGE, registerLanguage, toMarkers } from '~/viewers/composite/monaco'
import { zipSync } from 'fflate'
import { companionFiles, compositeDocuments, documentName } from '~/viewers/composite/archive'
import type { EnvironmentSummary, InterfaceManifest } from '~/composables/useRegistry'

// Write a composite in .pblang and run it (docs/plan-authoring.md, step C). The language server checks the text as it
// changes, against the interface manifest of the environment picked here, and offers hover and completion from it.
// Submitting compiles the text in the browser into a process-bigraph document and sends it to /simulation/run in that
// environment. `?from=<dataset id>` starts from a submitted composite (the viewer's "Edit a copy"); `&member=<path>`
// picks a document inside an OMEX archive (else its first).
const route = useRoute()

const STARTER = `// A composite to run in the environment picked above. Hover a name to see its interface; completion
// (Ctrl+Space) offers processes, their ports and config keys, and stores.
composite my_composite {
}
`

const environments = ref<EnvironmentSummary[]>([])
const environment = ref<string | undefined>(undefined)
const manifest = shallowRef<InterfaceManifest | null>(null)
const intervalTime = ref(1)
const batch = ref(false)
const loadError = ref<string | null>(null)
const counts = ref({ error: 0, warning: 0, info: 0 })
const compileFindings = ref<Diagnostic[]>([])
const submitError = ref<string | null>(null)
const violations = ref<Violation[]>([])
const busy = ref(false)
// values too large for the text, which it references with file("…"): carried along and compiled back in
const assets = shallowRef<Record<string, string>>({})
const shownAsset = ref<string | null>(null)
// the files the starting document ran with in its archive (an SBML model, data): sent with it, in an .omex, on Run
const companions = shallowRef<Record<string, Uint8Array>>({})

const editorHost = ref<HTMLElement | null>(null)
let editor: monaco.editor.IStandaloneCodeEditor | null = null
let client: PblangLanguageClient | null = null
let opened: monaco.IDisposable | null = null

const selected = computed(() => environments.value.find(e => e.name === environment.value) ?? null)
const environmentItems = computed(() =>
  environments.value.map(e => ({
    label: `${e.name}${e.simulator ? '' : ' (shared)'}: ${e.components} component${e.components === 1 ? '' : 's'}`,
    value: e.name
  }))
)
const compositeName = () => /composite\s+([A-Za-z_][\w]*)/.exec(editor?.getValue() ?? '')?.[1] ?? 'composite'

/** The starting text: a submitted composite decompiled against its run's environment, or the starter. */
async function startingText(): Promise<{
  text: string
  environment: string | null
  assets: Record<string, string>
  companions: Record<string, Uint8Array>
}> {
  const from = typeof route.query.from === 'string' ? route.query.from : null
  if (!from) return { text: STARTER, environment: null, assets: {}, companions: {} }
  const api = useApi()
  const { data: dataset } = await api.GET('/datasets/{dataset_id}', { params: { path: { dataset_id: from } } })
  if (!dataset) throw new Error(`Dataset ${from} was not found`)
  const response = await fetchContent(`/datasets/${from}/content`)
  if (!response.ok) throw new Error(`Could not read dataset ${from} (HTTP ${response.status})`)
  const fileName = dataset.path.split('/').pop() ?? 'composite'
  const bytes = new Uint8Array(await response.arrayBuffer())
  const documents = compositeDocuments(bytes, fileName)
  const member = typeof route.query.member === 'string' ? route.query.member : null
  const document = documents.find(d => d.path === member) ?? documents[0]
  if (!document) throw new Error(`Dataset ${from} holds no composite document`)
  const { data: simulation } = await api.GET('/simulations/{simulation_id}', {
    params: { path: { simulation_id: dataset.simulation_id } }
  })
  const env = await environmentFor(simulation?.simulator).catch(() => null)
  const session = new Pblang()
  const runManifest = env ? await fetchManifest(env.name).catch(() => null) : null
  if (runManifest) session.addManifest(runManifest)
  const name = documentName(document.path).replace(/\W/g, '_')
  const printed = session.decompile(document.text, { name })
  return { text: printed.text, environment: env?.name ?? null, assets: printed.assets, companions: companionFiles(bytes, document.path) }
}

onMounted(async () => {
  try {
    const [list, start] = await Promise.all([listEnvironments(), startingText()])
    environments.value = list
    assets.value = start.assets
    companions.value = start.companions
    environment.value = start.environment ?? list.find(e => !e.simulator)?.name ?? list[0]?.name
    const m = registerLanguage()
    const model = m.editor.createModel(start.text, LANGUAGE, m.Uri.parse(`inmemory://editor/${Date.now()}.pblang`))
    editor = m.editor.create(editorHost.value!, {
      model,
      automaticLayout: true,
      minimap: { enabled: false },
      scrollBeyondLastLine: false,
      fontSize: 13,
      lineNumbersMinChars: 3,
      tabSize: 2,
      fixedOverflowWidgets: true // hover and suggest boxes may extend past the editor's frame
    })
    client = await PblangLanguageClient.start(m)
    client.onMarkers((uri, c) => {
      if (uri === model.uri.toString()) counts.value = c
    })
    await applyEnvironment()
    opened = client.open(model)
  } catch (e) {
    loadError.value = (e as Error).message
  }
})

onBeforeUnmount(() => {
  opened?.dispose()
  void client?.dispose()
  editor?.getModel()?.dispose()
  editor?.dispose()
})

async function applyEnvironment() {
  manifest.value = environment.value ? await fetchManifest(environment.value).catch(() => null) : null
  await client?.setManifests(manifest.value ? [manifest.value] : [])
}
watch(environment, (now, before) => {
  if (before !== undefined) void applyEnvironment()
})

/** The text as a process-bigraph document, addressed the way this service runs classes; null with findings shown. */
async function compile(): Promise<string | null> {
  compileFindings.value = []
  const session = new Pblang().setManifests(manifest.value ? [manifest.value] : [])
  try {
    const compiled = await session.compile(editor?.getValue() ?? '', { addresses: 'registered', assets: assets.value })
    return compiled.text
  } catch (e) {
    if (e instanceof CompileError) {
      compileFindings.value = e.diagnostics
      const model = editor?.getModel()
      if (model) registerLanguage().editor.setModelMarkers(model, 'pblang-compile', toMarkers(e.diagnostics))
      return null
    }
    throw e
  }
}

async function download() {
  const text = await compile()
  if (text == null) return
  const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }))
  const a = document.createElement('a')
  a.href = url
  a.download = `${compositeName()}.pbg`
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

async function submit() {
  busy.value = true
  submitError.value = null
  violations.value = []
  try {
    const text = await compile()
    if (text == null) return
    const name = compositeName()
    // with the files it names, in an archive; alone, as a document
    const file = Object.keys(companions.value).length
      ? new File([zipSync({ ...companions.value, [`${name}.pbg`]: new TextEncoder().encode(text) })], `${name}.omex`, { type: 'application/zip' })
      : new File([text], `${name}.pbg`, { type: 'application/json' })
    const outcome = await submitRun(file, {
      intervalTime: intervalTime.value,
      batch: batch.value,
      simulator: selected.value?.simulator ?? null
    })
    if (!outcome.ok) {
      submitError.value = outcome.error
      violations.value = outcome.violations
      return
    }
    await navigateTo(`/simulations/${outcome.simulationId}`)
  } catch (e) {
    submitError.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

function reveal(d: Diagnostic) {
  editor?.revealLineInCenter(d.range.start.line + 1)
  editor?.setPosition({ lineNumber: d.range.start.line + 1, column: d.range.start.character + 1 })
  editor?.focus()
}
</script>

<template>
  <div>
    <PageHeader
      title="Write a composite"
      description="Checked as you type against the processes the chosen environment provides; compiled in your browser and run on the cluster."
    />
    <UContainer class="py-6 flex flex-col gap-4">
      <UAlert v-if="loadError" color="error" variant="subtle" icon="i-lucide-circle-alert" :title="loadError" />
      <div class="flex flex-wrap items-end gap-3">
        <UFormField label="Environment" help="Where it runs, and what it is checked against">
          <USelect v-model="environment" :items="environmentItems" class="min-w-80" />
        </UFormField>
        <UFormField label="Interval">
          <UInputNumber v-model="intervalTime" :min="0" :max="1000" :step="0.1" class="w-32" />
        </UFormField>
        <UFormField label="Batch">
          <USwitch v-model="batch" />
        </UFormField>
        <span class="grow" />
        <UButton icon="i-lucide-file-down" label="Compiled .pbg" color="neutral" variant="subtle" @click="download" />
        <UButton icon="i-lucide-send" label="Run" :loading="busy" :disabled="!environment || counts.error > 0" @click="submit" />
      </div>
      <div class="flex flex-wrap items-center gap-2 text-sm">
        <UBadge v-if="counts.error" color="error" variant="subtle">{{ counts.error }} error{{ counts.error === 1 ? '' : 's' }}</UBadge>
        <UBadge v-if="counts.warning" color="warning" variant="subtle">{{ counts.warning }} warning{{ counts.warning === 1 ? '' : 's' }}</UBadge>
        <UBadge v-if="!counts.error && !counts.warning" color="success" variant="subtle">no errors or warnings</UBadge>
        <UBadge v-if="counts.info" color="neutral" variant="subtle">{{ counts.info }} note{{ counts.info === 1 ? '' : 's' }}</UBadge>
        <span v-if="selected" class="text-muted">
          {{ manifest ? `${manifest.components.length} components known in ${selected.name}` : `no interface manifest for ${selected.name}: processes are not checked` }}{{ selected.stale ? ' (read from an earlier image)' : '' }}
        </span>
      </div>
      <div ref="editorHost" class="h-[65vh] rounded border border-default overflow-hidden" />
      <p v-if="Object.keys(companions).length" class="text-sm text-muted">
        Runs with the files it had in its archive, sent along in an .omex:
        <code v-for="(content, path) in companions" :key="path" class="me-2">{{ path }} ({{ formatBytes(content.length) }})</code>
      </p>
      <div v-if="Object.keys(assets).length" class="flex flex-col gap-2 text-sm">
        <p class="text-muted">
          Values too large for the text are in sidecar files it references with <code>file("…")</code>; they are compiled
          back into the document when it runs:
        </p>
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
        <pre v-if="shownAsset && assets[shownAsset] != null" class="text-xs font-mono p-3 rounded bg-elevated/50 border border-default overflow-auto max-h-64 whitespace-pre-wrap">{{ assets[shownAsset]!.slice(0, 20000) }}</pre>
      </div>
      <UAlert
        v-if="compileFindings.length"
        color="error"
        variant="subtle"
        icon="i-lucide-circle-x"
        title="Not compiled: the checker found errors"
      >
        <template #description>
          <ul class="flex flex-col gap-1 mt-1">
            <li v-for="(d, i) in compileFindings.filter(f => f.severity === 'error')" :key="i">
              <button class="text-left hover:underline" @click="reveal(d)">
                <code>{{ d.code }}</code> line {{ d.range.start.line + 1 }}: {{ d.message }}
              </button>
            </li>
          </ul>
        </template>
      </UAlert>
      <UAlert v-if="submitError" color="error" variant="subtle" icon="i-lucide-circle-alert" :title="submitError">
        <template v-if="violations.length" #description>
          <ul class="flex flex-col gap-1 mt-1">
            <li v-for="(v, i) in violations" :key="i"><code>{{ v.address }}</code>: {{ v.reason }}</li>
          </ul>
        </template>
      </UAlert>
    </UContainer>
  </div>
</template>
