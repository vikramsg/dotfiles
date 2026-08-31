# WebKit UI API

Macflow injects `window.macflow` into each configured local WebKit surface.

```text
[Config]
show_surface("screenshots-web")

  -> [Macflow / Swift]
     Creates WKWebView
     Registers the native "macflow" message handler
     Supplies JavaScript defining window.macflow

  -> [WebKit]
     Executes that JavaScript
     Loads index.html and app.js

  -> [app.js]
     Calls window.macflow.files.list(...)

  -> [WebKit]
     Sends "files.list" to the registered Swift handler

  -> [Macflow / Swift]
     Lists files and resolves the JavaScript Promise
```

Creating `window.macflow` only exposes functions; native work begins when
`app.js` calls one.

## Contract

```ts
interface FileItem {
  name: string
  path: string
  modifiedAt: number
  thumbnail: string
}

interface Macflow {
  configuration: unknown
  theme: Record<string, string>

  files: {
    list(options: {
      directory: string
      extensions: string[]
      limit: number
    }): Promise<FileItem[]>
    open(path: string): Promise<boolean>
    reveal(path: string): Promise<boolean>
    prepareDrag(path: string): Promise<boolean>
  }

  surface: {
    dismiss(): Promise<boolean>
  }

  diagnostics: {
    log(message: string): Promise<boolean>
  }
}
```

Calls reject their promise when validation or the native operation fails.
`prepareDrag` must be called from the item's pointer-down handler.

## Implementation

| API call | Native implementation |
| --- | --- |
| `files.list(...)` | `WebSurfaceController` validates input and uses `MacflowCore.FileCatalog` |
| `files.open(path)` | `WebSurfaceController` calls `NSWorkspace.open` |
| `files.reveal(path)` | `WebSurfaceController` asks Finder to reveal the file |
| `files.prepareDrag(path)` | `WebSurfacePanel` starts an AppKit file drag |
| `surface.dismiss()` | `WebSurfaceController` closes the shared surface session |
