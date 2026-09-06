local M = {}

local function wait(message, predicate)
	assert(vim.wait(5000, predicate, 20), message)
end

local function keys(text)
	vim.v.errmsg = ""
	vim.api.nvim_feedkeys(vim.api.nvim_replace_termcodes(text, true, false, true), "mx", false)
	assert(vim.v.errmsg == "", vim.v.errmsg)
end

local function mapped(lhs)
	local map = vim.fn.maparg(lhs, "n", false, true)
	return map.buffer == 1
end

local function text()
	return table.concat(vim.api.nvim_buf_get_lines(0, 0, -1, false), "\n")
end

local function diff_ready()
	wait("PR diff and scoped mappings should be ready", function()
		return vim.bo.filetype == "differdiff" and mapped(" ps") and mapped(" pr")
	end)
end

local function compose(body)
	wait("comment/summary composer should open", function()
		return vim.bo.filetype == "markdown"
	end)
	keys("<Esc>")
	vim.api.nvim_buf_set_lines(0, 0, -1, false, { body })
	keys("<CR>")
end

local function focus_line(target)
	if vim.bo.filetype == "differpanel" then
		keys("<C-w>l")
	end
	for row, line in ipairs(vim.api.nvim_buf_get_lines(0, 0, -1, false)) do
		if line == target then
			vim.api.nvim_win_set_cursor(0, { row, 0 })
			return
		end
	end
	error("diff should contain " .. target)
end

function M.run()
	require("lazy").load({ plugins = { "differ.nvim" } })
	local state, restore_backend = require("tests.support.pr_backend").install()
	local input, select, notify = vim.ui.input, vim.ui.select, vim.notify
	local cwd, initial = vim.fn.getcwd(), vim.api.nvim_get_current_tabpage()
	local root = vim.fn.tempname()
	vim.fn.mkdir(root, "p")
	local function git(...)
		local args = { "git", "-C", root, "-c", "user.name=Review Test", "-c", "user.email=review@test.invalid" }
		vim.list_extend(args, { ... })
		local res = vim.system(args, { text = true }):wait()
		assert(res.code == 0, res.stderr)
	end
	local tabs, buffers = {}, {}
	for _, tab in ipairs(vim.api.nvim_list_tabpages()) do
		tabs[tab] = true
	end
	for _, buf in ipairs(vim.api.nvim_list_bufs()) do
		buffers[buf] = true
	end
	local notices = {}
	vim.notify = function(msg)
		notices[#notices + 1] = tostring(msg)
	end
	local ok, err = xpcall(function()
		git("init", "--initial-branch=main")
		git("remote", "add", "origin", "https://github.com/fixture/review.git")
		vim.fn.writefile({ "before first" }, root .. "/example.txt")
		git("add", ".")
		git("commit", "-m", "initial")
		vim.fn.writefile({ "after first" }, root .. "/example.txt")
		vim.cmd("tabnew")
		vim.cmd("cd " .. vim.fn.fnameescape(root))
		local editor = vim.api.nvim_get_current_tabpage()
		for _, lhs in ipairs({ " pl", " pr", " ps", "ga", "gp" }) do
			assert(vim.fn.maparg(lhs, "n") == "", "ordinary buffers should not get " .. lhs)
		end
		keys(" gd")
		wait("local diff should have PR launchers", function()
			return mapped(" pl") and mapped(" pr")
		end)
		assert(not mapped(" ps"), "submit must not be installed on local diffs")
		keys("g?")
		assert(
			text():find("Space pl", 1, true) and not text():find("Space ps", 1, true),
			"local help should show only relevant PR actions"
		)
		keys("<Esc>")
		local before = #state.opened
		vim.ui.input = function(_, cb)
			cb(nil)
		end
		keys(" pr")
		assert(#state.opened == before, "cancelling must not open a PR")
		vim.ui.input = function(_, cb)
			cb("17 | quit")
		end
		keys(" pr")
		assert(
			#state.opened == before and notices[#notices]:find("positive PR number"),
			"invalid PR input should be rejected"
		)
		vim.ui.input = function(_, cb)
			cb("17")
		end
		keys(" pr")
		diff_ready()
		wait("review should start as a draft", function()
			return state.review_id ~= nil
		end)
		assert(state.opened[#state.opened].number == 17, "prompt should select the requested PR")
		vim.ui.input = function()
			error("active PR must not prompt again")
		end
		keys(" pr")
		diff_ready()
		keys("g?")
		assert(
			text():find("Space ps", 1, true)
				and text():find("Esc then Enter", 1, true)
				and text():find("post immediately", 1, true),
			"PR help should include submit, save, and draft warning"
		)
		keys("<Esc>")
		-- Anchor on the known new-side changed line, not its rendered row number.
		focus_line("after first")
		keys("c")
		compose("Please handle timeouts")
		wait("saved comment should remain a pending draft", function()
			return #state.threads == 1
		end)
		assert(
			state.threads[1].is_pending and state.threads[1].line == 5 and state.threads[1].path == "example.txt",
			"comment should retain its source anchor and draft state"
		)
		wait("thread should render before replying", function()
			local s = require("differ.pr").current_session()
			return s.thread_anchors and #s.thread_anchors > 0
		end)
		focus_line("after first")
		assert(mapped("gp"), "PR diff should have the native reply mapping")
		keys("gp")
		compose("Additional detail")
		wait("reply should join the existing thread", function()
			return #state.threads[1].comments == 2
		end)
		focus_line("after first")
		keys("Vjga")
		compose("Range note")
		wait("range comment should be saved", function()
			return #state.threads == 2
		end)
		assert(
			state.threads[2].start_line == 5 and state.threads[2].line == 6,
			"visual comment should anchor the selected range"
		)
		vim.ui.select = function(_, _, cb)
			cb(nil)
		end
		keys(" ps")
		assert(#state.submissions == 0, "cancelled submission must preserve drafts")
		vim.ui.select = function(items, _, cb)
			assert(
				vim.deep_equal(items, { "COMMENT", "APPROVE", "REQUEST_CHANGES" }),
				"submit should offer all three verdicts"
			)
			cb("COMMENT")
		end
		keys(" ps")
		compose("Review summary")
		wait("review summary should be submitted to the simulated backend", function()
			return #state.submissions == 1
		end)
		assert(
			state.submissions[1].body == "Review summary" and state.submissions[1].event == "COMMENT",
			"submission should include summary and chosen verdict"
		)
		local prtab = vim.api.nvim_get_current_tabpage()
		vim.api.nvim_set_current_tabpage(editor)
		for _, lhs in ipairs({ " pl", " pr", " ps", "ga", "gp" }) do
			assert(vim.fn.maparg(lhs, "n") == "", "PR mappings must not leak to editor: " .. lhs)
		end
		vim.api.nvim_set_current_tabpage(prtab)
		-- Tree mappings and list picker also use the real plugin UI/entry points.
		local panel = require("differ.pr").current_session().panel
		vim.api.nvim_set_current_win(panel.winid)
		wait("tree should have submit and launchers", function()
			return mapped(" ps") and mapped(" pl")
		end)
		vim.ui.select = function(items, opts, cb)
			assert(opts.prompt == "Select a pull request", "pl should open the PR picker")
			cb(items[1])
		end
		keys(" pl")
		diff_ready()
		assert(
			#state.failures == 0,
			"all test requests must use the simulated backend: " .. vim.inspect(state.failures)
		)
	end, debug.traceback)
	pcall(require("differ").close)
	for _, tab in ipairs(vim.api.nvim_list_tabpages()) do
		if not tabs[tab] then
			vim.api.nvim_set_current_tabpage(tab)
			vim.cmd("tabclose!")
		end
	end
	vim.api.nvim_set_current_tabpage(initial)
	vim.cmd("cd " .. vim.fn.fnameescape(cwd))
	for _, buf in ipairs(vim.api.nvim_list_bufs()) do
		if not buffers[buf] then
			pcall(vim.api.nvim_buf_delete, buf, { force = true })
		end
	end
	vim.ui.input, vim.ui.select, vim.notify = input, select, notify
	restore_backend()
	vim.fn.delete(root, "rf")
	assert(ok, err)
	print("Differ PR controls: scope, prompts, draft comments/replies, range anchors, and submission passed")
end

return M
