.PHONY: check test hello hello-world single-agent scenario

SCENARIO ?= cli-v2/scenarios/hello-world

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-35s\033[0m %s\n", $$1, $$2}'

check:
	npm --prefix .. run check:sandbox:v2

test:
	npm --prefix .. run test:sandbox:v2

hello: ## Run hello world bypassing agent
	npm --prefix .. run sandbox:v2 -- hello

hello-world: ## Ask agent to print hello world
	npm --prefix .. run sandbox:v2 -- hello-world

single-agent:
	npm --prefix .. run sandbox:v2 -- single-agent $(ARGS)

scenario:
	npm --prefix .. run sandbox:v2 -- scenario $(abspath $(SCENARIO)) $(ARGS)
