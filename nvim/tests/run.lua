local M = {}

local specs = {
	-- Verifies Differ's comparison selection and source navigation with real Git/plugin views.
	"tests.git_review_spec",
	-- Real PR UI with an intercepted sidecar boundary; never writes to GitHub.
	"tests.pr_review_spec",
	-- Verifies the ty LSP configuration and startup command for Python files.
	"tests.lsp_ty_spec",
	-- Verifies Snacks Explorer reveals hidden and ignored files with the required options.
	"tests.snacks_explorer_reveal_spec",
	-- Verifies the nvim-treesitter main API, parsers, queries, and file loading.
	"tests.treesitter_main_spec",
	-- Verifies TypeScript and TSX indentation across comments and nested blocks.
	"tests.typescript_indent_spec",
}

function M.run()
	local failures = {}
	local initial_cwd = vim.fn.getcwd()

	for _, spec in ipairs(specs) do
		local cwd = vim.fn.getcwd()
		package.loaded[spec] = nil
		local ok, mod = pcall(require, spec)
		if not ok then
			failures[#failures + 1] = string.format("%s failed to load\n%s", spec, mod)
		elseif type(mod.run) ~= "function" then
			failures[#failures + 1] = string.format("%s is missing a run() function", spec)
		else
			local passed, err = pcall(mod.run)
			if not passed then
				failures[#failures + 1] = string.format("%s failed\n%s", spec, err)
			end
		end
		vim.cmd("cd " .. vim.fn.fnameescape(cwd))
	end

	vim.cmd("cd " .. vim.fn.fnameescape(initial_cwd))

	if #failures > 0 then
		vim.api.nvim_err_writeln(table.concat(failures, "\n\n"))
		vim.cmd("cquit 1")
	end
	return true
end

return M
