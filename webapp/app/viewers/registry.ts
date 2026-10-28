import type { Component } from 'vue'
import type { Dataset } from '~/composables/useApi'
import { isBundle, isComposite, isImage, isPlotlyFigure, isTable, isText, media } from './kinds'

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

export const VIEWERS: ViewerDef[] = [
  {
    // The submitted composite (a .pbg, or the documents in an OMEX archive) as .pblang text and as a wiring graph.
    id: 'composite',
    label: 'Composite',
    icon: 'i-lucide-workflow',
    match: d => (isComposite(d) ? 10 : 0),
    component: lazy(() => import('./CompositeViewer.vue'))
  },
  {
    id: 'plotly',
    label: 'Figure',
    icon: 'i-lucide-chart-spline',
    match: d => (isPlotlyFigure(d) ? 12 : 0),
    component: lazy(() => import('./PlotlyFigureViewer.vue'))
  },
  {
    id: 'image',
    label: 'Image',
    icon: 'i-lucide-image',
    match: d => (isImage(d) ? 10 : 0),
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
    // Bundles carrying the web extension are drawn in 3D; others still get it offered, and say why it is empty.
    id: 'bundle-surface',
    label: '3D',
    icon: 'i-lucide-box',
    match: d => (isBundle(d) ? (d.attributes?.web ? 10 : 3) : 0),
    component: lazy(() => import('./BundleSurfaceViewer.vue'))
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
