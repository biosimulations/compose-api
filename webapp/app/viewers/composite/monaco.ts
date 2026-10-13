import * as monaco from 'monaco-editor/editor/editor.api'
// editor.api is the bare editor: each feature registers itself. These are the ones the viewer and the editor use
// (hover and suggest show the language server's answers; gotoError steps through the checker's markers with F8).
import 'monaco-editor/features/hover/register.js'
// the completion widget: Monaco's `features/suggest` registers only inline completions, so import its controller
import 'monaco-editor/editor/contrib/suggest/browser/suggestController.js'
import 'monaco-editor/features/snippet/register.js'
import 'monaco-editor/features/find/register.js'
import 'monaco-editor/features/folding/register.js'
import 'monaco-editor/features/bracketMatching/register.js'
import 'monaco-editor/features/comment/register.js'
import 'monaco-editor/features/contextmenu/register.js'
import 'monaco-editor/features/clipboard/register.js'
import 'monaco-editor/features/gotoError/register.js'
import 'monaco-editor/features/wordHighlighter/register.js'
import EditorWorker from 'monaco-editor/editor/editor.worker.js?worker'
import monarch from 'process-bigraph-lang/monarch'
import type { Diagnostic } from 'process-bigraph-lang'

/**
 * Monaco for `.pblang` text: the language registered once with process-bigraph-lang's Monarch tokenizer, and the
 * checker's findings as markers. The read-only viewer checks on the main thread; the editor connects the language
 * server (`process-bigraph-lang/worker`) through ./languageClient.ts for diagnostics, hover and completion. The viewer
 * also shows the submitted document's JSON, and answers hovers on both from its run's interface manifest (`setHover`).
 */

export const LANGUAGE = 'pblang'
/** A submitted document's JSON, shown read-only: tokens only (Monaco's JSON language service is not bundled). */
export const JSON_LANGUAGE = 'pbg-json'
let registered = false

/** Hover answers per model (the viewer's text and document), so the editor's language-server hover is not doubled. */
type HoverLookup = (model: monaco.editor.ITextModel, position: monaco.Position) => monaco.languages.Hover | null
const hovers = new Map<string, HoverLookup>()

export function setHover(model: monaco.editor.ITextModel, lookup: HoverLookup): monaco.IDisposable {
  const key = model.uri.toString()
  hovers.set(key, lookup)
  return { dispose: () => hovers.delete(key) }
}

export function registerLanguage(): typeof monaco {
  if (registered) return monaco
  registered = true
  const env = self as unknown as { MonacoEnvironment?: monaco.Environment }
  env.MonacoEnvironment = { getWorker: () => new EditorWorker() }
  monaco.languages.register({ id: LANGUAGE, extensions: ['.pblang', '.pbl'] })
  monaco.languages.setMonarchTokensProvider(LANGUAGE, monarch as unknown as monaco.languages.IMonarchLanguage)
  // process-bigraph-lang/language-configuration is JSON with comments, which a bundler's JSON import rejects
  monaco.languages.setLanguageConfiguration(LANGUAGE, {
    comments: { lineComment: '//', blockComment: ['/*', '*/'] },
    brackets: [['{', '}'], ['[', ']'], ['(', ')']],
    autoClosingPairs: [
      { open: '{', close: '}' },
      { open: '[', close: ']' },
      { open: '(', close: ')' },
      { open: '"', close: '"' }
    ]
  })
  monaco.languages.register({ id: JSON_LANGUAGE })
  monaco.languages.setMonarchTokensProvider(JSON_LANGUAGE, {
    tokenizer: {
      root: [
        [/"(?:[^"\\]|\\.)*"(?=\s*:)/, 'type'],
        [/"(?:[^"\\]|\\.)*"/, 'string'],
        [/-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?/, 'number'],
        [/\b(?:true|false|null)\b/, 'keyword'],
        [/[{}[\],:]/, 'delimiter']
      ]
    }
  })
  monaco.languages.setLanguageConfiguration(JSON_LANGUAGE, { brackets: [['{', '}'], ['[', ']']] })
  for (const language of [LANGUAGE, JSON_LANGUAGE]) {
    monaco.languages.registerHoverProvider(language, {
      provideHover: (model, position) => hovers.get(model.uri.toString())?.(model, position) ?? null
    })
  }
  return monaco
}

/** The string literal under a position on its line, with its range; null outside one. */
export function stringAt(model: monaco.editor.ITextModel, position: monaco.Position): { value: string, range: monaco.IRange } | null {
  const line = model.getLineContent(position.lineNumber)
  for (const m of line.matchAll(/"(?:[^"\\]|\\.)*"/g)) {
    const start = m.index + 1
    const end = start + m[0].length
    if (position.column >= start && position.column <= end) {
      let value: string
      try {
        value = JSON.parse(m[0]) as string
      } catch {
        return null
      }
      return { value, range: { startLineNumber: position.lineNumber, startColumn: start, endLineNumber: position.lineNumber, endColumn: end } }
    }
  }
  return null
}

const SEVERITY: Record<Diagnostic['severity'], monaco.MarkerSeverity> = {
  error: monaco.MarkerSeverity.Error,
  warning: monaco.MarkerSeverity.Warning,
  info: monaco.MarkerSeverity.Info,
  hint: monaco.MarkerSeverity.Hint
}

/** The checker's findings as Monaco markers (its ranges are zero-based; Monaco's are one-based). */
export function toMarkers(diagnostics: Diagnostic[]): monaco.editor.IMarkerData[] {
  return diagnostics.map(d => ({
    severity: SEVERITY[d.severity],
    code: d.code,
    message: d.path ? `${d.message} (${d.path})` : d.message,
    startLineNumber: d.range.start.line + 1,
    startColumn: d.range.start.character + 1,
    endLineNumber: d.range.end.line + 1,
    endColumn: d.range.end.character + 1
  }))
}
