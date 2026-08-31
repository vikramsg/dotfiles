# WebKit UI API

Macflow injects `window.macflow` into each configured local WebKit surface.

```text
app.js
  -> window.macflow
  -> WebKit message bridge
  -> native implementation
```

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

## Boundaries

```text
MacflowCore
└── File discovery and sorting

MacflowUI
├── WKWebView and API injection
├── Theme injection
└── Native drag mechanics

Macflow executable
├── Request validation and dispatch
├── File open and reveal
└── Surface lifecycle
```
