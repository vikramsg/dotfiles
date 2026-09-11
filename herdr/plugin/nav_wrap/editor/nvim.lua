-- dotfiles.nav-wrap — Neovim side
--
-- <C-h/j/k/l> moves between Neovim splits. At a split edge it hands off to the
-- shared focus-wrap.sh helper, which moves Herdr pane focus and wraps around at
-- pane edges. When not inside Herdr it falls back to tmux (if any) or plain
-- wincmd.

local source = debug.getinfo(1, "S").source:sub(2)
local plugin_root = vim.fn.fnamemodify(source, ":h:h")
local focus_wrap = plugin_root .. "/focus-wrap.sh"

local tmux_direction = { left = "Left", down = "Down", up = "Up", right = "Right" }

local function cross_out(dir)
	if vim.env.HERDR_PANE_ID and vim.env.HERDR_PANE_ID ~= "" then
		vim.fn.system({ focus_wrap, dir })
		return true
	elseif vim.env.TMUX and vim.env.TMUX ~= "" then
		pcall(vim.cmd, "TmuxNavigate" .. tmux_direction[dir])
		return true
	end
	return false
end

-- Snacks pickers are floating windows. `wincmd` from a float lands on the
-- editor window in any direction, so a left-docked picker would bounce between
-- itself and the editor instead of leaving the pane. Treat its left edge as the
-- Neovim edge so <C-h> crosses out.
local function at_left_docked_picker()
	if not vim.bo.filetype:match("^snacks_picker") then
		return false
	end
	local config = vim.api.nvim_win_get_config(vim.api.nvim_get_current_win())
	return config.relative ~= "" and (config.col or 0) == 0
end

local function nav(wincmd, dir)
	if dir == "left" and at_left_docked_picker() and cross_out(dir) then
		return
	end
	local prev = vim.api.nvim_get_current_win()
	vim.cmd("wincmd " .. wincmd)
	if vim.api.nvim_get_current_win() ~= prev then
		return
	end
	cross_out(dir)
end

local function map(lhs, wincmd, dir, desc)
	vim.keymap.set("n", lhs, function()
		nav(wincmd, dir)
	end, { silent = true, noremap = true, desc = desc })
end

map("<C-h>", "h", "left", "Navigate left (dotfiles.nav-wrap)")
map("<C-j>", "j", "down", "Navigate down (dotfiles.nav-wrap)")
map("<C-k>", "k", "up", "Navigate up (dotfiles.nav-wrap)")
map("<C-l>", "l", "right", "Navigate right (dotfiles.nav-wrap)")
