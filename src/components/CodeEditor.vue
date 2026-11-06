<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as monaco from 'monaco-editor'
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'

const props = withDefaults(defineProps<{ modelValue: string; language: string; readonly?: boolean }>(), { readonly: false })
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const container = ref<HTMLElement>()
let editor: monaco.editor.IStandaloneCodeEditor | undefined

self.MonacoEnvironment = { getWorker: () => new EditorWorker() }

onMounted(() => {
  if (!container.value) return
  editor = monaco.editor.create(container.value, {
    value: props.modelValue,
    language: props.language === 'c' || props.language === 'cpp' ? 'cpp' : props.language,
    theme: 'cloudcode-dark',
    automaticLayout: true,
    minimap: { enabled: false },
    fontSize: 14,
    lineHeight: 24,
    fontFamily: "'JetBrains Mono', 'SFMono-Regular', Consolas, monospace",
    padding: { top: 20, bottom: 20 },
    scrollBeyondLastLine: false,
    smoothScrolling: true,
    cursorSmoothCaretAnimation: 'on',
    renderLineHighlight: 'all',
    overviewRulerBorder: false,
    hideCursorInOverviewRuler: true,
    scrollbar: { verticalScrollbarSize: 8, horizontalScrollbarSize: 8 },
    readOnly: props.readonly,
  })
  monaco.editor.defineTheme('cloudcode-dark', {
    base: 'vs-dark',
    inherit: true,
    rules: [
      { token: 'comment', foreground: '657D9C', fontStyle: 'italic' },
      { token: 'keyword', foreground: '82B6FF' },
      { token: 'number', foreground: 'F0B46C' },
      { token: 'string', foreground: '96D5B1' },
      { token: 'type', foreground: '70CBDE' },
    ],
    colors: {
      'editor.background': '#101d30',
      'editor.foreground': '#D8E3F2',
      'editor.lineHighlightBackground': '#182a43',
      'editorLineNumber.foreground': '#526B88',
      'editorLineNumber.activeForeground': '#9CB3CD',
      'editorCursor.foreground': '#F2A44E',
      'editor.selectionBackground': '#24518A80',
      'editorIndentGuide.background1': '#263B55',
    },
  })
  monaco.editor.setTheme('cloudcode-dark')
  editor.onDidChangeModelContent(() => emit('update:modelValue', editor?.getValue() ?? ''))
})

watch(() => props.modelValue, (value) => {
  if (editor && value !== editor.getValue()) editor.setValue(value)
})
watch(() => props.language, (language) => {
  const model = editor?.getModel()
  if (model) monaco.editor.setModelLanguage(model, language === 'c' || language === 'cpp' ? 'cpp' : language)
})
watch(() => props.readonly, (value) => editor?.updateOptions({ readOnly: value }))
onBeforeUnmount(() => editor?.dispose())
</script>

<template>
  <div ref="container" class="code-editor" />
</template>

<style scoped>
.code-editor { width: 100%; height: 100%; min-height: 0; overflow: hidden; background: #101d30; }
</style>
