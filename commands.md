# Commands 

## ripgrep (rg)
Used primarily for searching **inside** files.

### Find Filenames
To list files matching a pattern (without searching content):
```bash
rg --files -g "*.pdf" ~/
```

### Search Content in Specific Files
To search for text inside files matching a specific extension:
```bash
rg "search_text" -g "*.pdf" ~/
```

### Key Flags
- `-g`: **Glob**. Filters which files to include/exclude (e.g., `-g "*.js"` or `-g "!*.log"`).
- `--files`: Tells `rg` to list files instead of searching their contents.


## brew

### Cleaning

```bash
# Dry run
brew cleanup

brew cleanup -n

```
### Additional Helpful Command: `autoremove`

While `cleanup` handles old versions and cache, 
it does not remove unused dependencies. 

To remove those, use:

```bash
brew autoremove

```
