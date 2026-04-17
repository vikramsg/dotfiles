local M = {}

local specs = {
	"tests.diffview_picker_spec",
}

function M.run()
	local failures = {}

	for _, spec in ipairs(specs) do
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
	end

	if #failures > 0 then
		vim.api.nvim_err_writeln(table.concat(failures, "\n\n"))
		vim.cmd("cquit 1")
	end
	return true
end

return M
