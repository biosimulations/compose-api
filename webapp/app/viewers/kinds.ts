import type { Dataset } from '~/composables/useApi'

// What kind of thing a dataset is, for the viewers that are registered against it (registry.ts) and for the pages
// that pick datasets out by kind. Pure, so its tests need no Nuxt.

export const media = (d: Dataset) => d.media_type ?? ''
export const isTable = (d: Dataset) => /csv|tab-separated|tsv/.test(media(d)) || /\.(csv|tsv)$/i.test(d.path)
export const isText = (d: Dataset) => media(d).startsWith('text/') || /json|yaml|xml/.test(media(d))
export const isBundle = (d: Dataset) => d.kind === 'results-bundle'
export const isImage = (d: Dataset) => media(d).startsWith('image/')
// a Plotly figure a run wrote (biosim-toolkit's SED-ML Plots step: plots/<sedml>/<plot>.plotly.json)
export const isPlotlyFigure = (d: Dataset) => /\.plotly\.json$/i.test(d.path) || /plotly/.test(media(d))
// the submitted composite: a process-bigraph document (.pbg or .json), or an OMEX archive holding one or more
export const isComposite = (d: Dataset) =>
  d.kind === 'input' && (/json|zip/.test(media(d)) || /\.(pbg|json|omex)$/i.test(d.path))

/** An output a visualization is registered for (a figure, an image, a results bundle's 3D view and statistics): what
 * a simulation's Figures tab shows. A table or text has a viewer too, but is not a figure. */
export const isFigure = (d: Dataset) => d.kind !== 'input' && (isPlotlyFigure(d) || isImage(d) || isBundle(d))

const isArchive = (d: Dataset) => /zip|x-tar|gzip/.test(media(d)) || /\.(zip|omex|tar|tgz|tar\.gz)$/i.test(d.path)
const isDirectory = (d: Dataset) => /zarr/.test(media(d))

/** What a dataset is at a glance, for the icon in the first column of a datasets table: the icon names the same
 * things the simulation page's tabs and the viewers do (the Input tab's, the Figures tab's, the composite viewer's). */
export function datasetGlyph(d: Dataset): { icon: string, label: string } {
  if (d.kind === 'input') return { icon: 'i-lucide-file-input', label: 'Simulation input' }
  if (isPlotlyFigure(d)) return { icon: 'i-lucide-chart-spline', label: 'Figure' }
  if (isImage(d)) return { icon: 'i-lucide-image', label: 'Image' }
  if (isBundle(d)) return { icon: 'i-lucide-box', label: 'Results bundle' }
  if (d.kind === 'log') return { icon: 'i-lucide-file-terminal', label: 'Log' }
  if (isTable(d)) return { icon: 'i-lucide-table', label: 'Table' }
  if (isDirectory(d)) return { icon: 'i-lucide-folder', label: 'Directory' }
  if (isArchive(d)) return { icon: 'i-lucide-file-archive', label: 'Archive' }
  if (/\.pbg$/i.test(d.path)) return { icon: 'i-lucide-workflow', label: 'Composite document' }
  if (/\.pblang$/i.test(d.path)) return { icon: 'i-lucide-file-code', label: 'pblang' }
  if (/xml/.test(media(d))) return { icon: 'i-lucide-file-code', label: 'XML' }
  if (/json/.test(media(d))) return { icon: 'i-lucide-braces', label: 'JSON' }
  if (isText(d)) return { icon: 'i-lucide-file-text', label: 'Text' }
  return { icon: 'i-lucide-file', label: 'File' }
}
