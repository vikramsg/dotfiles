## Essentials

### Using build scripts defined in `package.json`

```bash
npm run <script defined in package.json>

## For example
npm run build # If build is a script name in package.json
```

### Building Typescript

Node does not directly run Typescript.
So we have to build/compile into Javascript and then node runs it.

The following will build using the TypeScript compiler.
File locations and config are defined in the config file.
```bash
tsc -p sandbox/tsconfig.json
```


