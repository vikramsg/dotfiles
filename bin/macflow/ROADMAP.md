## API

1. Add a TypeScript plugin so that we can do other stuff like interacting with other CLI's etc

## Done

1. `macflow ui show --file <payload>` takes an A2UI JSON payload and renders it
   natively with AppKit. `POST /v1/ui` is the underlying route.
2. `macflow files list` fills the data model, and surfaces are verified with
   `macflow screenshot capture` plus `macflow input click/keystroke`.

## Apps

1. Port forwarding should be automatic or atleast easy UI for it
2. Brew UI

## Ground rules

1. Always make sure `macflow` can be configured using `XDG_HOME/.config/macflow/config.toml`
