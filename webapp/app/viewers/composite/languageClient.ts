import type * as monaco from 'monaco-editor/editor/editor.api'
import LanguageWorker from 'process-bigraph-lang/worker?worker'
import { SET_MANIFESTS_NOTIFICATION } from 'process-bigraph-lang'
import {
  BrowserMessageReader,
  BrowserMessageWriter,
  CompletionRequest,
  ConfigurationRequest,
  createProtocolConnection,
  DidChangeTextDocumentNotification,
  DidCloseTextDocumentNotification,
  DidOpenTextDocumentNotification,
  ExitNotification,
  HoverRequest,
  InitializedNotification,
  InitializeRequest,
  PublishDiagnosticsNotification,
  RegistrationRequest,
  ShutdownRequest,
  UnregistrationRequest,
  WorkspaceFoldersRequest,
  type CompletionItem,
  type Diagnostic as LspDiagnostic,
  type Hover,
  type InsertReplaceEdit,
  type MarkupContent,
  type ProtocolConnection,
  type Range as LspRange,
  type ServerCapabilities,
  type TextEdit
} from 'vscode-languageserver-protocol/browser'
import { LANGUAGE } from './monaco'

/**
 * process-bigraph-lang's language server (`process-bigraph-lang/worker`) in a web worker, wired to Monaco by hand:
 * the text of each opened model is kept in sync (full text on every change), the server's diagnostics become markers,
 * and Monaco's hover and completion ask the server. `setManifests` gives it the interface manifests of the
 * environment the text will run in (`pblang/setManifests`); it re-checks every open text. monaco-languageclient is not
 * used: it brings VS Code's API layer and pins its own Monaco, for the four messages this needs.
 */
export class PblangLanguageClient {
  private readonly disposables: monaco.IDisposable[] = []
  private readonly versions = new Map<string, number>()
  private markersListener: ((uri: string, count: { error: number, warning: number, info: number }) => void) | null = null

  private constructor(
    private readonly m: typeof monaco,
    private readonly worker: Worker,
    private readonly connection: ProtocolConnection
  ) {}

  static async start(m: typeof monaco): Promise<PblangLanguageClient> {
    const worker = new LanguageWorker()
    const connection = createProtocolConnection(new BrowserMessageReader(worker), new BrowserMessageWriter(worker))
    const client = new PblangLanguageClient(m, worker, connection)
    // requests the server may send the client: it gets no settings, folders or dynamic registrations
    connection.onRequest(ConfigurationRequest.type, ({ items }) => items.map(() => null))
    connection.onRequest(WorkspaceFoldersRequest.type, () => null)
    connection.onRequest(RegistrationRequest.type, () => undefined)
    connection.onRequest(UnregistrationRequest.type, () => undefined)
    connection.onNotification(PublishDiagnosticsNotification.type, ({ uri, diagnostics }) => client.publish(uri, diagnostics))
    connection.listen()
    const { capabilities } = await connection.sendRequest(InitializeRequest.type, {
      processId: null,
      rootUri: null,
      workspaceFolders: null,
      capabilities: {
        textDocument: {
          synchronization: { dynamicRegistration: false },
          hover: { contentFormat: ['markdown', 'plaintext'] },
          completion: { completionItem: { snippetSupport: true, documentationFormat: ['markdown', 'plaintext'] } },
          publishDiagnostics: {}
        }
      }
    })
    await connection.sendNotification(InitializedNotification.type, {})
    client.registerProviders(capabilities)
    return client
  }

  /** Replace the server's manifests (`pbg-interfaces/1`); every open text is checked again. */
  setManifests(manifests: object[]): Promise<void> {
    // a plain copy: postMessage cannot clone a reactive proxy (a manifest held in a Vue ref)
    return this.connection.sendNotification(SET_MANIFESTS_NOTIFICATION, { manifests: JSON.parse(JSON.stringify(manifests)) })
  }

  /** Keep a model's text in sync with the server, which checks it as it changes. */
  open(model: monaco.editor.ITextModel): monaco.IDisposable {
    const uri = model.uri.toString()
    this.versions.set(uri, model.getVersionId())
    void this.connection.sendNotification(DidOpenTextDocumentNotification.type, {
      textDocument: { uri, languageId: LANGUAGE, version: model.getVersionId(), text: model.getValue() }
    })
    const changes = model.onDidChangeContent(() => {
      this.versions.set(uri, model.getVersionId())
      void this.connection.sendNotification(DidChangeTextDocumentNotification.type, {
        textDocument: { uri, version: model.getVersionId() },
        contentChanges: [{ text: model.getValue() }]
      })
    })
    return {
      dispose: () => {
        changes.dispose()
        this.versions.delete(uri)
        void this.connection.sendNotification(DidCloseTextDocumentNotification.type, { textDocument: { uri } })
      }
    }
  }

  /** Called with each text's counts whenever the server publishes its findings. */
  onMarkers(listener: (uri: string, count: { error: number, warning: number, info: number }) => void): void {
    this.markersListener = listener
  }

  async dispose(): Promise<void> {
    for (const d of this.disposables) d.dispose()
    try {
      await this.connection.sendRequest(ShutdownRequest.type)
      await this.connection.sendNotification(ExitNotification.type)
    } catch {
      // the worker is going away regardless
    }
    this.connection.dispose()
    this.worker.terminate()
  }

  // --- server to Monaco ----------------------------------------------------------------------------------------

  private publish(uri: string, diagnostics: LspDiagnostic[]): void {
    const model = this.m.editor.getModel(this.m.Uri.parse(uri))
    if (!model) return
    this.m.editor.setModelMarkers(model, 'pblang', diagnostics.map(d => this.marker(d)))
    this.markersListener?.(uri, {
      error: diagnostics.filter(d => d.severity === 1).length,
      warning: diagnostics.filter(d => d.severity === 2).length,
      info: diagnostics.filter(d => d.severity !== 1 && d.severity !== 2).length
    })
  }

  private marker(d: LspDiagnostic): monaco.editor.IMarkerData {
    const S = this.m.MarkerSeverity
    const path = (d.data as { path?: string } | undefined)?.path
    return {
      severity: d.severity === 1 ? S.Error : d.severity === 2 ? S.Warning : d.severity === 3 ? S.Info : S.Hint,
      code: d.code == null ? undefined : String(d.code),
      message: path ? `${d.message} (${path})` : d.message,
      ...this.range(d.range)
    }
  }

  private range(r: LspRange): monaco.IRange {
    return {
      startLineNumber: r.start.line + 1,
      startColumn: r.start.character + 1,
      endLineNumber: r.end.line + 1,
      endColumn: r.end.character + 1
    }
  }

  private registerProviders(capabilities: ServerCapabilities): void {
    const m = this.m
    if (capabilities.hoverProvider) {
      this.disposables.push(m.languages.registerHoverProvider(LANGUAGE, {
        provideHover: async (model, position) => {
          const hover: Hover | null = await this.connection.sendRequest(HoverRequest.type, {
            textDocument: { uri: model.uri.toString() },
            position: { line: position.lineNumber - 1, character: position.column - 1 }
          })
          if (!hover) return null
          const contents = Array.isArray(hover.contents) ? hover.contents : [hover.contents]
          return {
            contents: contents.map(c => ({ value: typeof c === 'string' ? c : 'kind' in c ? c.value : `\`\`\`${c.language}\n${c.value}\n\`\`\`` })),
            range: hover.range ? this.range(hover.range) : undefined
          }
        }
      }))
    }
    if (capabilities.completionProvider) {
      this.disposables.push(m.languages.registerCompletionItemProvider(LANGUAGE, {
        triggerCharacters: capabilities.completionProvider.triggerCharacters,
        provideCompletionItems: async (model, position) => {
          const result = await this.connection.sendRequest(CompletionRequest.type, {
            textDocument: { uri: model.uri.toString() },
            position: { line: position.lineNumber - 1, character: position.column - 1 }
          })
          const items = Array.isArray(result) ? result : result?.items ?? []
          const word = model.getWordUntilPosition(position)
          const fallback: monaco.IRange = {
            startLineNumber: position.lineNumber,
            endLineNumber: position.lineNumber,
            startColumn: word.startColumn,
            endColumn: word.endColumn
          }
          return {
            incomplete: !Array.isArray(result) && Boolean(result?.isIncomplete),
            suggestions: items.map(item => this.suggestion(item, fallback))
          }
        }
      }))
    }
  }

  private suggestion(item: CompletionItem, fallback: monaco.IRange): monaco.languages.CompletionItem {
    const m = this.m
    const edit = item.textEdit as TextEdit | InsertReplaceEdit | undefined
    const range = !edit ? fallback : 'range' in edit ? this.range(edit.range) : this.range(edit.replace)
    const docs = item.documentation as string | MarkupContent | undefined
    return {
      label: item.label,
      kind: COMPLETION_KIND[item.kind ?? 1] ?? m.languages.CompletionItemKind.Text,
      detail: item.detail,
      documentation: docs == null ? undefined : typeof docs === 'string' ? docs : { value: docs.value },
      insertText: edit?.newText ?? item.insertText ?? item.label,
      insertTextRules: item.insertTextFormat === 2 ? m.languages.CompletionItemInsertTextRule.InsertAsSnippet : undefined,
      range,
      sortText: item.sortText,
      filterText: item.filterText,
      additionalTextEdits: item.additionalTextEdits?.map(e => ({ range: this.range(e.range), text: e.newText }))
    }
  }
}

// LSP CompletionItemKind (1-based) to Monaco's (0-based, ordered differently)
const COMPLETION_KIND: Record<number, monaco.languages.CompletionItemKind> = {
  1: 18 /* Text */,
  2: 0 /* Method */,
  3: 1 /* Function */,
  4: 2 /* Constructor */,
  5: 3 /* Field */,
  6: 4 /* Variable */,
  7: 5 /* Class */,
  8: 7 /* Interface */,
  9: 8 /* Module */,
  10: 9 /* Property */,
  11: 12 /* Unit */,
  12: 13 /* Value */,
  13: 15 /* Enum */,
  14: 17 /* Keyword */,
  15: 28 /* Snippet */,
  16: 19 /* Color */,
  17: 20 /* File */,
  18: 21 /* Reference */,
  19: 23 /* Folder */,
  20: 16 /* EnumMember */,
  21: 14 /* Constant */,
  22: 6 /* Struct */,
  23: 10 /* Event */,
  24: 11 /* Operator */,
  25: 24 /* TypeParameter */
}
