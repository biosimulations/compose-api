import type { Component } from 'vue'
import type { Dataset } from '~/composables/useApi'

/**
 * Viewers registered against dataset types (docs/plan-viewers.md F2). `match` scores how well a viewer fits a
 * dataset: 0 means it cannot show it, and the highest score is opened first. `component` is an async component, so a
 * viewer and its heavy dependencies (Plotly, zarrita, vtk.js) are a separate chunk, downloaded when first opened.
 */
export interface ViewerDef {
  id: string
  label: string
  icon: string
  match: (d: Dataset) => number
  component: Component
}

const lazy = (loader: () => Promise<Component | { default: Component }>) => defineAsyncComponent(loader)

const media = (d: Dataset) => d.media_type ?? ''
const isTable = (d: Dataset) => /csv|tab-separated|tsv/.test(media(d)) || /\.(csv|tsv)$/i.test(d.path)
const isText = (d: Dataset) => media(d).startsWith('text/') || /json|yaml|xml/.test(media(d))
const isBundle = (d: Dataset) => d.kind === 'results-bundle'

export const VIEWERS: ViewerDef[] = [
  {
    id: 'image',
    label: 'Image',
    icon: 'i-lucide-image',
    match: d => (media(d).startsWith('image/') ? 10 : 0),
    component: lazy(() => import('./ImageViewer.vue'))
  },
  {
    id: 'table',
    label: 'Table',
    icon: 'i-lucide-table',
    match: d => (isTable(d) ? 10 : 0),
    component: lazy(() => import('./TableViewer.vue'))
  },
  {
    id: 'text',
    label: 'Text',
    icon: 'i-lucide-file-text',
    match: d => (isText(d) ? (isTable(d) ? 2 : 5) : 0),
    component: lazy(() => import('./TextViewer.vue'))
  },
  {
    id: 'bundle-stats',
    label: 'Statistics',
    icon: 'i-lucide-chart-line',
    match: d => (isBundle(d) ? 5 : 0),
    component: lazy(() => import('./BundleStatsViewer.vue'))
  }
]

/** The viewers that can show `d`, best first. */
export function viewersFor(d: Dataset): ViewerDef[] {
  return VIEWERS.map(v => ({ v, score: v.match(d) }))
    .filter(x => x.score > 0)
    .sort((a, b) => b.score - a.score)
    .map(x => x.v)
}

/** A directory dataset (a zarr store) has no single file to download. */
export function isDirectoryDataset(d: Dataset): boolean {
  return /zarr/.test(media(d))
}
