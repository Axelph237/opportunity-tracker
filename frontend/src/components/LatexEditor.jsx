import { useEffect, useImperativeHandle, useRef } from 'react'
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import { HighlightStyle, StreamLanguage, syntaxHighlighting } from '@codemirror/language'
import { EditorState, StateEffect, StateField } from '@codemirror/state'
import {
  Decoration,
  EditorView,
  drawSelection,
  highlightActiveLine,
  highlightActiveLineGutter,
  keymap,
  lineNumbers,
} from '@codemirror/view'
import { stex } from '@codemirror/legacy-modes/mode/stex'
import { tags } from '@lezer/highlight'

/**
 * Colours come from the Material tokens on :root rather than a bundled CodeMirror
 * theme, so the editor restyles along with everything else the moment the user
 * picks a new source colour in Settings.
 */
const theme = EditorView.theme({
  '&': {
    height: '100%',
    backgroundColor: 'var(--md-sys-color-surface-container-lowest)',
    color: 'var(--md-sys-color-on-surface)',
    fontSize: '13px',
  },
  '&.cm-focused': { outline: 'none' },
  '.cm-scroller': { fontFamily: 'var(--font-code)', lineHeight: '1.6' },
  '.cm-gutters': {
    backgroundColor: 'var(--md-sys-color-surface-container)',
    color: 'var(--md-sys-color-on-surface-variant)',
    border: 'none',
    borderRight: '1px solid var(--md-sys-color-outline-variant)',
  },
  '.cm-activeLineGutter': {
    backgroundColor: 'var(--md-sys-color-surface-container-high)',
    color: 'var(--md-sys-color-on-surface)',
  },
  '.cm-activeLine': {
    backgroundColor: 'color-mix(in srgb, var(--md-sys-color-primary) 6%, transparent)',
  },
  '.cm-selectionBackground, &.cm-focused .cm-selectionBackground': {
    backgroundColor: 'var(--md-sys-color-secondary-container)',
  },
  '.cm-cursor': { borderLeftColor: 'var(--md-sys-color-primary)' },
  '.cm-content': { padding: '8px 0', caretColor: 'var(--md-sys-color-primary)' },
  // The line an engine error points at. A left bar rather than a red wash, so
  // the text underneath stays readable while you fix it.
  '.cm-errorLine': {
    backgroundColor: 'color-mix(in srgb, var(--md-sys-color-error) 12%, transparent)',
    boxShadow: 'inset 2px 0 0 0 var(--md-sys-color-error)',
  },
})

const highlight = HighlightStyle.define([
  { tag: tags.tagName, color: 'var(--md-sys-color-primary)' },
  { tag: tags.keyword, color: 'var(--md-sys-color-primary)' },
  { tag: tags.atom, color: 'var(--md-sys-color-tertiary)' },
  { tag: tags.bracket, color: 'var(--md-sys-color-on-surface-variant)' },
  { tag: tags.comment, color: 'var(--md-sys-color-on-surface-variant)', fontStyle: 'italic' },
  { tag: tags.string, color: 'var(--md-sys-color-tertiary)' },
  { tag: tags.number, color: 'var(--md-sys-color-tertiary)' },
])

const errorLine = Decoration.line({ class: 'cm-errorLine' })
const setErrorLines = StateEffect.define()

/**
 * Which lines the last compile complained about.
 *
 * Held in editor state rather than recomputed from props on every render,
 * because the marks have to survive each keystroke's transaction: mapping them
 * through the change set keeps a flagged line flagged as text above it moves.
 */
const errorField = StateField.define({
  create: () => Decoration.none,
  update(decorations, transaction) {
    for (const effect of transaction.effects) {
      if (!effect.is(setErrorLines)) continue
      const { doc } = transaction.state
      const ranges = [...new Set(effect.value)]
        .filter((number) => Number.isInteger(number) && number >= 1 && number <= doc.lines)
        .sort((a, b) => a - b)
        .map((number) => errorLine.range(doc.line(number).from))
      return Decoration.set(ranges)
    }
    return decorations.map(transaction.changes)
  },
  provide: (field) => EditorView.decorations.from(field),
})

/**
 * A LaTeX source editor.
 *
 * The document lives in CodeMirror, not in React state: re-creating the view on
 * every keystroke would lose the cursor and the undo history. `value` is only
 * pushed in when it genuinely differs from what is on screen, which is what
 * lets the editor pick up a document the agent rewrote underneath it without
 * stealing the caret mid-word.
 */
export default function LatexEditor({ value, onChange, errorLines, readOnly = false, editorRef }) {
  const host = useRef(null)
  const view = useRef(null)
  // Kept in a ref so a new callback identity each render does not tear down
  // and rebuild the whole editor.
  const onChangeRef = useRef(onChange)
  onChangeRef.current = onChange

  useEffect(() => {
    const editor = new EditorView({
      state: EditorState.create({
        doc: value ?? '',
        extensions: [
          lineNumbers(),
          highlightActiveLine(),
          highlightActiveLineGutter(),
          drawSelection(),
          history(),
          keymap.of([...defaultKeymap, ...historyKeymap, indentWithTab]),
          StreamLanguage.define(stex),
          syntaxHighlighting(highlight),
          EditorView.lineWrapping,
          errorField,
          theme,
          EditorState.readOnly.of(readOnly),
          EditorView.updateListener.of((update) => {
            if (update.docChanged) onChangeRef.current?.(update.state.doc.toString())
          }),
        ],
      }),
      parent: host.current,
    })
    view.current = editor
    return () => {
      editor.destroy()
      view.current = null
    }
    // Mounted once per read-only state; `value` is synced by the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [readOnly])

  useEffect(() => {
    const editor = view.current
    if (!editor || value === undefined || value === null) return
    const current = editor.state.doc.toString()
    if (value === current) return
    editor.dispatch({ changes: { from: 0, to: current.length, insert: value } })
  }, [value])

  useEffect(() => {
    view.current?.dispatch({ effects: setErrorLines.of(errorLines ?? []) })
  }, [errorLines])

  useImperativeHandle(
    editorRef,
    () => ({
      /** Put the caret on a line and scroll it to the middle of the view. */
      goToLine(number) {
        const editor = view.current
        if (!editor || !number) return
        const clamped = Math.max(1, Math.min(number, editor.state.doc.lines))
        const line = editor.state.doc.line(clamped)
        editor.dispatch({
          selection: { anchor: line.from },
          effects: EditorView.scrollIntoView(line.from, { y: 'center' }),
        })
        editor.focus()
      },

      /** Drop text in at the caret, replacing any selection, and leave the
       *  caret after it so the user can keep typing. */
      insertAtCursor(text) {
        const editor = view.current
        if (!editor || !text) return
        const { from, to } = editor.state.selection.main
        editor.dispatch({
          changes: { from, to, insert: text },
          selection: { anchor: from + text.length },
          scrollIntoView: true,
        })
        editor.focus()
      },
    }),
    [],
  )

  return <div ref={host} className="h-full overflow-hidden" />
}
