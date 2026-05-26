local M = {}

local function assert_contains(haystack, needle, context)
	assert(vim.tbl_contains(haystack, needle), context .. " missing " .. needle .. " in " .. vim.inspect(haystack))
end

local function assert_query_compiles(lang, query)
	local ok, err = pcall(vim.treesitter.query.get, lang, query)
	assert(ok, string.format("%s %s query should compile\n%s", lang, query, err))
end

local function assert_file_opens(path)
	local ok, err = pcall(function()
		vim.cmd("edit " .. vim.fn.fnameescape(path))
		vim.cmd("redraw!")
		vim.wait(100, function()
			return false
		end, 10)
	end)
	assert(ok, "opening " .. path .. " should not throw\n" .. tostring(err))
end

function M.run()
	assert(vim.fn.executable("tree-sitter") == 1, "tree-sitter CLI is required; run `just brew`")

	local treesitter = require("nvim-treesitter")
	assert(type(treesitter.setup) == "function", "nvim-treesitter main setup API should exist")
	assert(type(treesitter.install) == "function", "nvim-treesitter main install API should exist")
	assert(type(treesitter.get_installed) == "function", "nvim-treesitter main get_installed API should exist")
	assert(type(treesitter.update) == "function", "nvim-treesitter main update API should exist")

	local old_api_ok = pcall(require, "nvim-treesitter.configs")
	assert(not old_api_ok, "nvim-treesitter main should not use the removed nvim-treesitter.configs API")

	local installed = treesitter.get_installed("parsers")
	assert_contains(installed, "lua", "installed parsers")
	assert_contains(installed, "markdown", "installed parsers")
	assert_contains(installed, "markdown_inline", "installed parsers")

	local lua_parsers = vim.api.nvim_get_runtime_file("parser/lua.so", true)
	assert(#lua_parsers > 0, "lua parser should be available on runtimepath")
	assert(
		not lua_parsers[1]:match("/lazy/nvim%-treesitter/parser/lua%.so$"),
		"stale parser from plugin checkout must not shadow installed Lua parser: " .. vim.inspect(lua_parsers)
	)

	assert_query_compiles("lua", "highlights")
	assert_query_compiles("markdown", "highlights")
	assert_query_compiles("markdown_inline", "highlights")

	assert_file_opens(vim.fn.getcwd() .. "/init.lua")

	local temp_dir = vim.fn.tempname()
	assert(vim.fn.mkdir(temp_dir, "p") == 1, "failed to create temp dir: " .. temp_dir)
	local markdown = temp_dir .. "/sample.md"
	assert(vim.fn.writefile({ "# Heading", "", "- item" }, markdown) == 0, "failed to write temp markdown")
	assert_file_opens(markdown)
	vim.fn.delete(temp_dir, "rf")
end

return M
