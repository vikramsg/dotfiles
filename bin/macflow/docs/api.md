# Macflow APIs

Macflow has two APIs:

- [HTTP Actions API](http-api.md): external processes perform macOS actions
  through the loopback server.
- [WebKit UI API](ui-api.md): configured HTML/JavaScript surfaces request
  native capabilities through `window.macflow`.

The HTTP API controls Macflow from outside the app. The UI API is available
only inside a Macflow-hosted `WKWebView`.
