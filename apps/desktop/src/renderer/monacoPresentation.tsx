import * as monaco from "monaco-editor";

export const V3_MONACO_SCROLLBAR_OPTIONS: monaco.editor.IEditorScrollbarOptions = Object.freeze({
  vertical: "visible",
  horizontal: "visible",
  verticalHasArrows: false,
  horizontalHasArrows: false,
  verticalScrollbarSize: 7,
  horizontalScrollbarSize: 7,
  verticalSliderSize: 5,
  horizontalSliderSize: 5,
  arrowSize: 0,
  useShadows: false,
  handleMouseWheel: true,
  alwaysConsumeMouseWheel: false,
  scrollByPage: false
});

let themeRegistered = false;

export function ensureV3MonacoTheme(): void {
  if (themeRegistered) return;
  monaco.editor.defineTheme("v3-quant", {
    base: "vs-dark",
    inherit: true,
    rules: [
      { token: "comment", foreground: "697188" },
      { token: "keyword", foreground: "67C9F3" },
      { token: "number", foreground: "78D6AF" },
      { token: "string", foreground: "D8B56D" }
    ],
    colors: {
      "editor.background": "#0D1017",
      "editor.foreground": "#D9DEE9",
      "editorLineNumber.foreground": "#525A70",
      "editorLineNumber.activeForeground": "#99A3B8",
      "editor.selectionBackground": "#173B52",
      "editor.lineHighlightBackground": "#111722",
      "editorCursor.foreground": "#5CC8F5",
      "editorScrollbarSlider.background": "#8E9BB24A",
      "editorScrollbarSlider.hoverBackground": "#AAB6CA75",
      "editorScrollbarSlider.activeBackground": "#C2CAD9A3",
      "diffEditor.insertedTextBackground": "#183D3055",
      "diffEditor.removedTextBackground": "#512B3355"
    }
  });
  themeRegistered = true;
}
