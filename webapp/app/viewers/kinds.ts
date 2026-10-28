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
