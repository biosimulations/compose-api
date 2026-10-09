<script setup lang="ts">
import Papa from 'papaparse'
import type { Dataset } from '~/composables/useApi'

// Inline view of one dataset by its media type: images, delimited tables (plotted when numeric), JSON and text.
const props = defineProps<{ dataset: Dataset }>()

const MAX_BYTES = 5 * 1024 * 1024
const text = ref<string | null>(null)
const imageUrl = ref<string | null>(null)
const error = ref<string | null>(null)
const loading = ref(false)

const media = computed(() => props.dataset.media_type ?? '')
const isImage = computed(() => media.value.startsWith('image/'))
const isTable = computed(() => /csv|tab-separated|tsv/.test(media.value) || /\.(csv|tsv)$/i.test(props.dataset.path))
const isText = computed(() => isTable.value || media.value.startsWith('text/') || /json|yaml|xml/.test(media.value))
const tooBig = computed(() => (props.dataset.size_bytes ?? 0) > MAX_BYTES)

async function load() {
  if (!(isImage.value || isText.value) || tooBig.value) return
  loading.value = true
  try {
    const response = await fetchContent(`/datasets/${props.dataset.id}/content`)
    if (!response.ok) throw new Error(`Could not read the file (${response.status})`)
    if (isImage.value) imageUrl.value = URL.createObjectURL(await response.blob())
    else text.value = await response.text()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

onMounted(load)
onBeforeUnmount(() => {
  if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
})

const table = computed(() => {
  if (!isTable.value || text.value == null) return null
  const parsed = Papa.parse<string[]>(text.value.trim(), { skipEmptyLines: true })
  const [header, ...rows] = parsed.data
  return header ? { header: header.map(h => h.trim()), rows } : null
})

// First column as x, every other all-numeric column as a line.
const traces = computed(() => {
  const t = table.value
  if (!t || t.header.length < 2 || t.rows.length < 2) return null
  const numeric = (i: number) => t.rows.every(r => r[i] !== undefined && r[i] !== '' && !Number.isNaN(Number(r[i])))
  if (!numeric(0)) return null
  const x = t.rows.map(r => Number(r[0]))
  const ys = t.header.map((h, i) => ({ h, i })).slice(1).filter(({ i }) => numeric(i))
  if (!ys.length) return null
  return ys.map(({ h, i }) => ({ type: 'scatter', mode: 'lines', name: h, x, y: t.rows.map(r => Number(r[i])) }))
})

const showPlot = ref(true)

const pretty = computed(() => {
  if (text.value == null) return ''
  if (/json/.test(media.value)) {
    try {
      return JSON.stringify(JSON.parse(text.value), null, 2)
    } catch {
      return text.value
    }
  }
  return text.value
})
</script>

<template>
  <div class="flex flex-col gap-3">
    <p v-if="loading" class="text-sm text-muted"><UIcon name="i-lucide-loader-circle" class="animate-spin" /> Loading…</p>
    <UAlert v-else-if="error" color="error" variant="subtle" :description="error" />
    <p v-else-if="tooBig" class="text-sm text-muted">Too large to preview ({{ formatBytes(dataset.size_bytes) }}); download it instead.</p>
    <p v-else-if="!isImage && !isText" class="text-sm text-muted">No preview for {{ dataset.media_type }}; download it instead.</p>

    <img v-if="imageUrl" :src="imageUrl" :alt="dataset.display_name" class="max-w-full max-h-[70vh] object-contain self-start rounded border border-default">

    <template v-if="table">
      <div v-if="traces" class="flex items-center gap-2">
        <USwitch v-model="showPlot" label="Plot" />
      </div>
      <PlotlyChart v-if="traces && showPlot" :data="traces" :layout="{ xaxis: { title: { text: table.header[0] } } }" class="h-96" />
      <div v-else class="overflow-auto max-h-[60vh] border border-default rounded">
        <table class="text-xs font-mono">
          <thead class="sticky top-0 bg-elevated">
            <tr><th v-for="h in table.header" :key="h" class="px-2 py-1 text-left">{{ h }}</th></tr>
          </thead>
          <tbody>
            <tr v-for="(r, i) in table.rows.slice(0, 500)" :key="i" class="border-t border-default">
              <td v-for="(c, j) in r" :key="j" class="px-2 py-0.5 whitespace-nowrap">{{ c }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="table.rows.length > 500" class="p-2 text-xs text-muted">Showing 500 of {{ table.rows.length }} rows.</p>
      </div>
    </template>
    <pre v-else-if="text != null" class="text-xs font-mono p-3 rounded bg-elevated/50 border border-default overflow-auto max-h-[60vh] whitespace-pre-wrap">{{ pretty }}</pre>
  </div>
</template>
