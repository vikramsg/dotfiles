-- Headless Neovim test for the dotfiles.nav-wrap editor adapter.
-- Run: nvim --headless -u NONE -l tests/nvim.lua

local here = vim.fn.fnamemodify(debug.getinfo(1, "S").source:sub(2), ":h")
local plugin_root = vim.fn.fnamemodify(here, ":h")
local mock = here .. "/mock-herdr.sh"

local state = vim.fn.tempname()
vim.fn.mkdir(state, "p")
for _, name in ipairs({ "transitions", "calls" }) do
	local f = io.open(state .. "/" .. name, "w")
	f:close()
end

local function read_calls()
	local lines = {}
	for line in io.lines(state .. "/calls") do
		lines[#lines + 1] = line
	end
	return table.concat(lines, "\n")
end

local failures = 0
local function check(name, ok, detail)
	if ok then
		print("ok   " .. name)
	else
		failures = failures + 1
		print("FAIL " .. name .. (detail and ("\n  " .. detail) or ""))
	end
end

vim.fn.setenv("MOCK_STATE_DIR", state)
vim.fn.setenv("HERDR_BIN_PATH", mock)
vim.fn.setenv("HERDR_PANE_ID", "p1")

dofile(plugin_root .. "/editor/nvim.lua")

local function feed(keys)
	vim.api.nvim_feedkeys(vim.api.nvim_replace_termcodes(keys, true, false, true), "x", false)
end

-- Two splits side by side, identified by their screen column.
vim.cmd("silent only")
vim.cmd("vsplit")
local wins = vim.api.nvim_tabpage_list_wins(0)
local left, right
if vim.api.nvim_win_get_position(wins[1])[2] < vim.api.nvim_win_get_position(wins[2])[2] then
	left, right = wins[1], wins[2]
else
	left, right = wins[2], wins[1]
end

-- Moving between the two splits must stay inside Neovim.
vim.api.nvim_set_current_win(left)
feed("<C-l>")
check("split move stays inside Neovim", read_calls() == "", read_calls())

-- From the right-most split, the next move hands off to the wrap helper.
vim.api.nvim_set_current_win(right)
feed("<C-l>")
local calls = read_calls()
check("edge hands off to focus-wrap", calls:match("focus right p1 %-> none") ~= nil, calls)

-- tmux fallback when no Herdr pane is present.
vim.fn.setenv("HERDR_PANE_ID", "")
vim.fn.setenv("TMUX", "/tmp/tmux-1000/default,123,0")
vim.api.nvim_create_user_command("TmuxNavigateRight", function()
	local f = io.open(state .. "/tmux", "a")
	f:write("right\n")
	f:close()
end, {})
vim.api.nvim_set_current_win(right)
feed("<C-l>")
local tmux = io.open(state .. "/tmux", "r")
local tmux_ok = tmux ~= nil and tmux:read("*a"):match("right") ~= nil
if tmux then
	tmux:close()
end
check("tmux fallback calls TmuxNavigateRight", tmux_ok)

if failures > 0 then
	print("\n" .. failures .. " test(s) failed")
	os.exit(1)
end
print("\nall nvim adapter tests passed")
