-- dotfiles.nav-wrap — Neovim side
--
-- <C-h/j/k/l> moves between Neovim splits. At a split edge it hands off to the
-- shared focus-wrap.sh helper, which moves Herdr pane focus and wraps around at
-- pane edges. When not inside Herdr it falls back to tmux (if any) or plain
-- wincmd.

local source = debug.getinfo(1, "S").source:sub(2)
local plugin_root = vim.fn.fnamemodify(source, ":h:h")
local focus_wrap = plugin_root .. "/focus-wrap.sh"

local function nav(wincmd, dir)
	local prev = vim.api.nvim_get_current_win()
	vim.cmd("wincmd " .. wincmd)
	if vim.api.nvim_get_current_win() ~= prev then
		return
	end
	if vim.env.HERDR_PANE_ID and vim.env.HERDR_PANE_ID ~= "" then
		vim.fn.system({ focus_wrap, dir })
	elseif vim.env.TMUX and vim.env.TMUX ~= "" then
		local tmux = { left = "Left", down = "Down", up = "Up", right = "Right" }
		pcall(vim.cmd, "TmuxNavigate" .. tmux[dir])
	end
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
