'use client'

import { useMemo } from 'react'

import { FORMAT_TEXT_COMMAND } from '@payloadcms/richtext-lexical/lexical'
import { LexicalComposer } from '@payloadcms/richtext-lexical/lexical/react/LexicalComposer'
import { ContentEditable } from '@payloadcms/richtext-lexical/lexical/react/LexicalContentEditable'
import { LexicalErrorBoundary } from '@payloadcms/richtext-lexical/lexical/react/LexicalErrorBoundary'
import { HistoryPlugin } from '@payloadcms/richtext-lexical/lexical/react/LexicalHistoryPlugin'
import { ListPlugin } from '@payloadcms/richtext-lexical/lexical/react/LexicalListPlugin'
import { OnChangePlugin } from '@payloadcms/richtext-lexical/lexical/react/LexicalOnChangePlugin'
import { useLexicalComposerContext } from '@payloadcms/richtext-lexical/lexical/react/LexicalComposerContext'
import { RichTextPlugin } from '@payloadcms/richtext-lexical/lexical/react/LexicalRichTextPlugin'
import { HeadingNode, QuoteNode } from '@payloadcms/richtext-lexical/lexical/rich-text'
import { AutoLinkNode, LinkNode } from '@payloadcms/richtext-lexical/lexical/link'
import { INSERT_ORDERED_LIST_COMMAND, INSERT_UNORDERED_LIST_COMMAND, ListItemNode, ListNode } from '@payloadcms/richtext-lexical/lexical/list'

type EditableRichTextEditorProps = {
  value: unknown
  onChange: (value: unknown) => void
  placeholder?: string
}

type TextFormat = 'bold' | 'italic' | 'underline' | 'strikethrough'

const hasLexicalRoot = (value: unknown) => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const root = (value as Record<string, unknown>).root
  return Boolean(root && typeof root === 'object' && !Array.isArray(root))
}

const Toolbar = () => {
  const [editor] = useLexicalComposerContext()
  const format = (value: TextFormat) => editor.dispatchCommand(FORMAT_TEXT_COMMAND, value)

  return (
    <div className="helloada-rich-editor-toolbar" role="toolbar" aria-label="Rich text formatting">
      <button type="button" onClick={() => format('bold')} aria-label="Bold"><strong>B</strong></button>
      <button type="button" onClick={() => format('italic')} aria-label="Italic"><em>I</em></button>
      <button type="button" onClick={() => format('underline')} aria-label="Underline"><u>U</u></button>
      <span aria-hidden="true" />
      <button type="button" onClick={() => editor.dispatchCommand(INSERT_UNORDERED_LIST_COMMAND, undefined)} aria-label="Bulleted list">•</button>
      <button type="button" onClick={() => editor.dispatchCommand(INSERT_ORDERED_LIST_COMMAND, undefined)} aria-label="Numbered list">1.</button>
    </div>
  )
}

export function EditableRichTextEditor({ value, onChange, placeholder = 'Write the page copy…' }: EditableRichTextEditorProps) {
  const initialEditorState = useMemo(
    () => hasLexicalRoot(value) ? JSON.stringify(value) : undefined,
    [value],
  )

  return (
    <div className="helloada-rich-editor">
      <LexicalComposer
        initialConfig={{
          editorState: initialEditorState,
          namespace: 'HelloAdaEditableContent',
          nodes: [AutoLinkNode, HeadingNode, LinkNode, ListItemNode, ListNode, QuoteNode],
          onError: (error) => console.error('HelloAda rich text editor error', error),
          theme: {
            list: { listitem: 'helloada-rich-editor-listitem', nested: { listitem: 'helloada-rich-editor-listitem' }, ol: 'helloada-rich-editor-ol', ul: 'helloada-rich-editor-ul' },
            text: { bold: 'helloada-rich-editor-bold', italic: 'helloada-rich-editor-italic', underline: 'helloada-rich-editor-underline' },
          },
        }}
      >
        <Toolbar />
        <div className="helloada-rich-editor-canvas">
          <RichTextPlugin
            contentEditable={<ContentEditable aria-label={placeholder} className="helloada-rich-editor-content" />}
            placeholder={<div className="helloada-rich-editor-placeholder">{placeholder}</div>}
            ErrorBoundary={LexicalErrorBoundary}
          />
        </div>
        <HistoryPlugin />
        <ListPlugin />
        <OnChangePlugin ignoreSelectionChange onChange={(editorState) => onChange(editorState.toJSON())} />
      </LexicalComposer>
    </div>
  )
}
