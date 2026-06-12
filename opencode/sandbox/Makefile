.PHONY: check test hello hello-world single-agent scenario

SCENARIO ?= cli-v2/scenarios/hello-world

check:
	npm --prefix .. run check:sandbox:v2

test:
	npm --prefix .. run test:sandbox:v2

hello:
	npm --prefix .. run sandbox:v2 -- hello

hello-world:
	npm --prefix .. run sandbox:v2 -- hello-world

single-agent:
	npm --prefix .. run sandbox:v2 -- single-agent $(ARGS)

scenario:
	npm --prefix .. run sandbox:v2 -- scenario $(abspath $(SCENARIO)) $(ARGS)
