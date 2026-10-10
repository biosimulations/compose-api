<script setup lang="ts">
import '@kitware/vtk.js/Rendering/Profiles/Geometry'
import vtkGenericRenderWindow from '@kitware/vtk.js/Rendering/Misc/GenericRenderWindow'
import vtkActor from '@kitware/vtk.js/Rendering/Core/Actor'
import vtkMapper from '@kitware/vtk.js/Rendering/Core/Mapper'
import vtkColorTransferFunction from '@kitware/vtk.js/Rendering/Core/ColorTransferFunction'
import vtkColorMaps from '@kitware/vtk.js/Rendering/Core/ColorTransferFunction/ColorMaps'
import vtkPolyData from '@kitware/vtk.js/Common/DataModel/PolyData'
import vtkDataArray from '@kitware/vtk.js/Common/Core/DataArray'
import type { Dataset } from '~/composables/useApi'
import { Bundle, httpStore, type BundleVariable } from './bundle/bundle'

// A results bundle drawn with vtk.js from its web extension (docs/plan-viewers.md B2): the precomputed surface of a
// domain coloured by one variable, one time row fetched per frame, particles as points. Standard components only: the
// server serves files, the browser does the rest.
const props = defineProps<{ dataset: Dataset }>()

const container = ref<HTMLDivElement | null>(null)
const bundle = shallowRef<Bundle | null>(null)
const error = ref<string | null>(null)
const busy = ref(false)
const domain = ref<string | undefined>()
const variable = ref<string | undefined>()
const row = ref(0)
const playing = ref(false)
const rangeMode = ref<'global' | 'frame'>('global')
const colormap = ref('Viridis (matplotlib)')
const showParticles = ref(true)
const opacity = ref(1)
const range = ref<[number, number]>([0, 1])

const COLORMAPS = ['Viridis (matplotlib)', 'Inferno (matplotlib)', 'Cool to Warm', 'Rainbow Uniform', 'Grayscale']

const domains = computed(() => Object.keys(bundle.value?.web?.surfaces ?? {}))
const variables = computed<BundleVariable[]>(() => bundle.value?.variablesOf(domain.value) ?? [])
const selected = computed(() => variables.value.find(v => v.name === variable.value))
const times = computed(() => bundle.value?.times ?? [])

let grw: ReturnType<typeof vtkGenericRenderWindow.newInstance> | null = null
let surface: ReturnType<typeof vtkPolyData.newInstance> | null = null
let particles: ReturnType<typeof vtkPolyData.newInstance> | null = null
let particleActor: ReturnType<typeof vtkActor.newInstance> | null = null
let surfaceActor: ReturnType<typeof vtkActor.newInstance> | null = null
const lut = vtkColorTransferFunction.newInstance()
let renderToken = 0

function render() {
  grw?.getRenderWindow().render()
}

function applyColormap() {
  const preset = vtkColorMaps.getPresetByName(colormap.value)
  if (preset) lut.applyColorMap(preset)
  lut.setMappingRange(range.value[0], range.value[1])
  lut.updateRange()
  render()
}

async function loadSurface() {
  const b = bundle.value
  if (!b || !domain.value || !grw) return
  const s = await b.surface(domain.value)
  if (!s) return
  const cells = new Uint32Array((s.triangles.length / 3) * 4)
  for (let i = 0, j = 0; i < s.triangles.length; i += 3, j += 4) {
    cells[j] = 3
    cells[j + 1] = s.triangles[i]!
    cells[j + 2] = s.triangles[i + 1]!
    cells[j + 3] = s.triangles[i + 2]!
  }
  surface = vtkPolyData.newInstance()
  surface.getPoints().setData(s.points, 3)
  surface.getPolys().setData(cells)
  const mapper = vtkMapper.newInstance({ interpolateScalarsBeforeMapping: true, useLookupTableScalarRange: true })
  mapper.setInputData(surface)
  mapper.setLookupTable(lut)
  const actor = vtkActor.newInstance()
  actor.setMapper(mapper)
  surfaceActor = actor
  actor.getProperty().setOpacity(opacity.value)
  const renderer = grw.getRenderer()
  renderer.removeAllViewProps()
  renderer.addActor(actor)

  particles = vtkPolyData.newInstance()
  const pmapper = vtkMapper.newInstance({ scalarVisibility: false })
  pmapper.setInputData(particles)
  particleActor = vtkActor.newInstance()
  particleActor.setMapper(pmapper)
  particleActor.getProperty().setColor(0.95, 0.2, 0.2)
  particleActor.getProperty().setPointSize(3)
  renderer.addActor(particleActor)
  obliqueView()
}

function obliqueView() {
  const renderer = grw?.getRenderer()
  if (!renderer) return
  renderer.resetCamera()
  const camera = renderer.getActiveCamera()
  camera.azimuth(35)
  camera.elevation(25)
  camera.orthogonalizeViewUp()
  renderer.resetCamera()
  render()
}

async function updateRange() {
  const b = bundle.value
  if (!b || !selected.value) return
  if (rangeMode.value === 'global') range.value = await b.range(selected.value)
}

async function drawRow() {
  const b = bundle.value
  if (!b || !selected.value || !surface) return
  const token = ++renderToken
  busy.value = true
  try {
    const values = await b.row(selected.value, row.value)
    let pts: Float64Array | null = null
    if (showParticles.value && b.particleSpecies.length) {
      const all = await Promise.all(b.particleSpecies.map(sp => b.particles(sp, row.value)))
      const n = all.reduce((acc, a) => acc + a.length, 0)
      pts = new Float64Array(n)
      let o = 0
      for (const a of all) {
        pts.set(a, o)
        o += a.length
      }
    }
    if (token !== renderToken) return // a newer frame was requested meanwhile
    surface.getPointData().setScalars(vtkDataArray.newInstance({ name: selected.value.name, values: Float32Array.from(values), numberOfComponents: 1 }))
    surface.modified()
    if (rangeMode.value === 'frame') {
      let lo = Infinity
      let hi = -Infinity
      for (const v of values) {
        if (Number.isFinite(v)) {
          if (v < lo) lo = v
          if (v > hi) hi = v
        }
      }
      range.value = Number.isFinite(lo) ? [lo, hi === lo ? lo + 1e-12 : hi] : [0, 1]
    }
    if (particles && particleActor) {
      const p = pts ?? new Float64Array()
      const n = p.length / 3
      const verts = new Uint32Array(n * 2)
      for (let i = 0; i < n; i++) {
        verts[2 * i] = 1
        verts[2 * i + 1] = i
      }
      particles.getPoints().setData(Float32Array.from(p), 3)
      particles.getVerts().setData(verts)
      particles.modified()
      particleActor.setVisibility(showParticles.value)
    }
    applyColormap()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    if (token === renderToken) busy.value = false
  }
}

onMounted(async () => {
  try {
    bundle.value = await Bundle.open(httpStore(datasetFilesUrl(props.dataset.id), authFetch))
    if (!domains.value.length) {
      error.value = 'This bundle has no web surface (written before the web extension); use the Statistics view.'
      return
    }
    grw = vtkGenericRenderWindow.newInstance({ background: [1, 1, 1] })
    grw.setContainer(container.value!)
    grw.resize()
    domain.value = domains.value[0]
    variable.value = variables.value[0]?.name
    row.value = Math.max(0, times.value.length - 1)
  } catch (e) {
    error.value = (e as Error).message
  }
})

onBeforeUnmount(() => {
  grw?.delete()
  grw = null
})

useResizeObserver(container, () => {
  grw?.resize()
  render()
})

watch(domain, async () => {
  await loadSurface()
  if (!variables.value.some(v => v.name === variable.value)) variable.value = variables.value[0]?.name
  await updateRange()
  await drawRow()
})
watch(variable, async () => {
  await updateRange()
  await drawRow()
})
watch(rangeMode, async () => {
  await updateRange()
  await drawRow()
})
watch([row, showParticles], drawRow)
watch(colormap, applyColormap)
watch(opacity, (o) => {
  surfaceActor?.getProperty().setOpacity(o)
  render()
})

// Play through the rows; a live run also refreshes its manifest and follows the newest row.
useIntervalFn(() => {
  if (!playing.value || busy.value || !times.value.length) return
  row.value = (row.value + 1) % times.value.length
}, 300)
useIntervalFn(async () => {
  const b = bundle.value
  if (!b?.live) return
  const atEnd = row.value === b.times.length - 1
  if (await b.refresh()) {
    await updateRange()
    if (atEnd) row.value = b.times.length - 1
  }
}, 5000)

function resetCamera() {
  obliqueView()
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <UAlert v-if="error" color="warning" variant="subtle" :description="error" />
    <div v-if="bundle && domains.length" class="flex flex-wrap items-center gap-3">
      <USelect v-model="domain" :items="domains" class="w-36" />
      <USelect v-model="variable" :items="variables.map(v => v.name)" class="w-40" />
      <USelect v-model="colormap" :items="COLORMAPS" class="w-48" />
      <USelect v-model="rangeMode" :items="[{ label: 'Range: whole run', value: 'global' }, { label: 'Range: this frame', value: 'frame' }]" class="w-44" />
      <USelect v-model="opacity" :items="[{ label: 'Opaque', value: 1 }, { label: 'Translucent', value: 0.45 }, { label: 'Faint', value: 0.15 }]" class="w-36" />
      <USwitch v-if="bundle.particleSpecies.length" v-model="showParticles" label="Particles" />
      <UButton icon="i-lucide-scan" variant="ghost" color="neutral" title="Reset camera" @click="resetCamera" />
      <span class="text-xs text-muted tabular-nums ml-auto">{{ range[0].toPrecision(3) }} – {{ range[1].toPrecision(3) }}</span>
    </div>
    <div ref="container" class="relative w-full h-[60vh] rounded border border-default overflow-hidden" :class="{ hidden: !domains.length }" />
    <div v-if="bundle && times.length" class="flex items-center gap-3">
      <UButton :icon="playing ? 'i-lucide-pause' : 'i-lucide-play'" variant="soft" color="neutral" :disabled="times.length < 2" @click="playing = !playing" />
      <USlider v-model="row" :min="0" :max="Math.max(0, times.length - 1)" :step="1" class="flex-1" />
      <span class="text-sm tabular-nums w-40 text-right">
        t = {{ times[row]?.toPrecision(4) }} ({{ row + 1 }}/{{ times.length }})
        <UIcon v-if="busy" name="i-lucide-loader-circle" class="animate-spin size-3" />
      </span>
      <UBadge v-if="bundle.live" color="info" variant="subtle">running</UBadge>
    </div>
  </div>
</template>
