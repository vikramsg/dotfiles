# Stick to your principles

Use this to find and follow the repository's mapped principles for the task at hand, or to check whether existing changes followed them.

1. Run `principles list-principles` to see what principles the repo maps.
2. For each principle that applies to what you're doing, run `principles show-principle ID` and read the mapped passages directly—don't rely on the one-line description alone, and respect each file's own scope.
3. Follow the rules you found, or flag any place the work breaks one (with the principle ID and mapped passage).
4. If `show-principle` lists a `check` command on a relevant member (a shell command stored in `.principles/maps/ID.json`) and it hasn't already been run on these changes, review it if unfamiliar and run it.
