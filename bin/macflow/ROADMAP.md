## API

1. Remove individual actions from cli and HTTP endpoints for UI
    - Only have a `macflow ui` that takes JSON input so that we can create instant UI using CLI
    - Let the agent figure out stuff by doing `macflow ui` and then `macflow screenshot capture`.
    - Interactive stuff using `macflow input click` and `macflow input keystroke`
2. Create the JSON UI API
    - JSON body as a payload
3. Add a TypeScript plugin so that we can do other stuff like interacting with other CLI's etc

## Apps

1. Port forwarding should be automatic or atleast easy UI for it
2. Brew UI

## Ground rules

1. Always make sure `macflow` can be configured using `XDG_HOME/.config/macflow/config.toml`
