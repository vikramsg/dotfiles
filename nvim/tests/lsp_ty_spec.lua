local M = {}

local function assert_contains(list, value, context)
	assert(type(list) == "table", context .. " should be a table")
	assert(vim.tbl_contains(list, value), context .. " missing " .. value .. " in " .. vim.inspect(list))
end

local function stop_ty_clients()
	for _, client in ipairs(vim.lsp.get_clients({ name = "ty" })) do
		vim.lsp.stop_client(client.id, true)
	end
	vim.wait(1000, function()
		return #vim.lsp.get_clients({ name = "ty" }) == 0
	end, 50)
end

local function write_file(path, lines)
	local parent = vim.fs.dirname(path)
	if parent and parent ~= "" then
		vim.fn.mkdir(parent, "p")
	end
	assert(vim.fn.writefile(lines, path) == 0, "failed to write " .. path)
end

local function make_fake_ty(bin_dir, marker)
	local ty_path = bin_dir .. "/ty"
	write_file(ty_path, {
		"#!/bin/sh",
		"printf '%s\\n' \"$@\" > " .. vim.fn.shellescape(marker),
		"sleep 30",
	})
	local chmod = vim.system({ "chmod", "+x", ty_path }):wait()
	assert(chmod.code == 0, "failed to chmod fake ty: " .. tostring(chmod.stderr))
	return ty_path
end

function M.run()
	assert(vim.lsp.is_enabled("ty"), "ty LSP config should be enabled")

	local cfg = vim.lsp.config.ty
	assert(vim.deep_equal(cfg.cmd, { "ty", "server" }), "ty should run `ty server`: " .. vim.inspect(cfg.cmd))
	assert_contains(cfg.filetypes, "python", "ty filetypes")
	assert_contains(cfg.root_markers, "pyproject.toml", "ty root markers")
	assert(cfg.settings and cfg.settings.ty, "ty settings should exist")
	assert(
		cfg.settings.ty.completions and cfg.settings.ty.completions.autoImport == true,
		"ty auto-import completions should be enabled"
	)
	assert(cfg.settings.ty.experimental == nil, "ty should not use stale experimental settings")

	stop_ty_clients()

	local temp_dir = vim.fn.tempname()
	local bin_dir = temp_dir .. "/bin"
	local project_dir = temp_dir .. "/project"
	local marker = temp_dir .. "/ty-invoked"
	assert(vim.fn.mkdir(bin_dir, "p") == 1, "failed to create fake bin dir")
	assert(vim.fn.mkdir(project_dir, "p") == 1, "failed to create temp project")
	make_fake_ty(bin_dir, marker)
	write_file(project_dir .. "/pyproject.toml", { "[project]", 'name = "ty-smoke"' })
	write_file(project_dir .. "/main.py", { "print('hello')" })

	local old_path = vim.env.PATH
	vim.env.PATH = bin_dir .. ":" .. old_path

	vim.cmd("edit " .. vim.fn.fnameescape(project_dir .. "/main.py"))
	assert(
		vim.wait(3000, function()
			return vim.fn.filereadable(marker) == 1
		end, 50),
		"opening a Python file should start `ty server`"
	)

	local args = table.concat(vim.fn.readfile(marker), " ")
	assert(args == "server", "ty should be invoked with `server` argument, got: " .. args)

	stop_ty_clients()
	vim.env.PATH = old_path
	vim.fn.delete(temp_dir, "rf")
end

return M
