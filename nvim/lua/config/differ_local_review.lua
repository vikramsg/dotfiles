local M = {}

local store = require("config.differ_local_review_store")
local namespace
local next_session_id = 0
local next_note_id = 0
local sessions_by_tab = {}

local function notify(message, level)
	vim.notify("Differ local review: " .. message, level or vim.log.levels.INFO)
end

local function now()
	return os.date("!%Y-%m-%dT%H:%M:%SZ")
end

local function notes_for(session)
	if not session.document then
		return {}
	end
	return session.document.comparisons[session.mode].notes
end

function M.snapshot(session)
	return session.document and vim.deepcopy(session.document) or nil
end

function M.export(session)
	if session.load_error or not session.document then
		return nil, session.load_error or "review data is unavailable"
	end
	local ok, result, new_fingerprint =
		store.save(session.root, session.identity, session.document, session.fingerprint)
	if ok then
		session.path = result
		session.fingerprint = new_fingerprint
		session.existed = true
		require("config.git_review").refresh_review_output(session)
	end
	return ok, result
end

local function export_after_change(session)
	local ok, result = M.export(session)
	if not ok then
		notify("saved in memory, but export failed: " .. tostring(result), vim.log.levels.ERROR)
		return false
	end
	notify(
		string.format(
			"saved %d local %s to %s",
			#notes_for(session),
			#notes_for(session) == 1 and "note" or "notes",
			vim.fn.fnamemodify(session.path, ":~:.")
		)
	)
	return true
end

function M.new_session(root, mode)
	next_session_id = next_session_id + 1
	local document, load_error, state = store.load(root)
	local session = {
		id = next_session_id,
		root = store.canonical_root(root) or vim.fs.normalize(root),
		mode = mode,
		document = document,
		identity = state and state.identity,
		path = state and state.path,
		fingerprint = state and state.fingerprint,
		existed = state and state.existed or false,
		load_error = load_error,
	}
	if load_error then
		notify("review file was not loaded and will not be overwritten: " .. load_error, vim.log.levels.ERROR)
	end
	return session
end

function M.select_mode(session, mode)
	session.mode = mode
end

function M.assign(tab, session, mode)
	for candidate in pairs(sessions_by_tab) do
		if not vim.api.nvim_tabpage_is_valid(candidate) then
			sessions_by_tab[candidate] = nil
		end
	end
	M.select_mode(session, mode)
	sessions_by_tab[tab] = session
end

function M.session_for_tab(tab)
	return sessions_by_tab[tab or vim.api.nvim_get_current_tabpage()]
end

function M.owns_current_branch(session)
	if not (session and session.identity) then
		return false
	end
	local identity = store.current_identity(session.root)
	return identity ~= nil and store.same_identity(session.identity, identity)
end

local function current_context()
	local review = vim.t.dotfiles_differ_review
	local session = review and M.session_for_tab()
	local view = require("differ").active_view()
	if not (session and view and view.model and view.model.root) then
		return nil
	end
	local view_root = (vim.uv or vim.loop).fs_realpath(view.model.root) or vim.fs.normalize(view.model.root)
	if view_root ~= session.root then
		return nil
	end
	if session.load_error or not session.document then
		notify("review data is protected: " .. tostring(session.load_error), vim.log.levels.ERROR)
		return nil
	end
	if not M.owns_current_branch(session) then
		notify("branch changed; close and reopen the review", vim.log.levels.WARN)
		return nil
	end
	return session, view
end

local function active_column(view)
	local win = vim.api.nvim_get_current_win()
	local buf = vim.api.nvim_win_get_buf(win)
	for _, column in ipairs(view.columns or {}) do
		if column.bufnr == buf then
			return column, win
		end
	end
end

local function source_point(side, line)
	return { side = side == "LEFT" and "old" or "new", line = line }
end

local function source_range(anchor)
	return {
		start = source_point(anchor.start_side or anchor.side, anchor.start_line or anchor.line),
		["end"] = source_point(anchor.side, anchor.line),
	}
end

local function compose_note(session, view, anchor, anchor_win, existing, source_context)
	local mode = existing and "Edit" or "New"
	local comparison_mode = session.mode
	local path = view.model.path
	require("differ.ui.compose").open({
		title = mode .. " LOCAL note → branch review JSON",
		initial = existing and existing.body or nil,
		layout = view.layout,
		anchor_win = anchor_win,
		on_submit = function(body)
			if body == "" then
				return notify("empty note discarded", vim.log.levels.WARN)
			end
			-- The composer may outlive its review tab. Never mutate another session.
			local active = vim.t.dotfiles_differ_review
			if
				not active
				or M.session_for_tab() ~= session
				or session.mode ~= comparison_mode
				or not M.owns_current_branch(session)
			then
				return notify("review changed before the note was saved", vim.log.levels.WARN)
			end
			if existing and not vim.tbl_contains(notes_for(session), existing) then
				return notify("note was deleted before the edit was saved", vim.log.levels.WARN)
			end
			local timestamp = now()
			if existing then
				existing.body = body
				existing.updated_at = timestamp
			else
				next_note_id = next_note_id + 1
				local note = {
					id = string.format("local-%d-%d-%d", vim.fn.getpid(), vim.uv.hrtime(), next_note_id),
					body = body,
					path = path,
					source_range = source_range(anchor),
					source_context = source_context,
					anchor_status = "current",
					created_at = timestamp,
					updated_at = timestamp,
				}
				table.insert(notes_for(session), note)
			end
			M.render(session, view, false)
			export_after_change(session)
		end,
	})
end

local function anchor_for_gesture(view, first, last)
	local column, win = active_column(view)
	if not column then
		return nil, nil, "place the cursor in the diff to comment"
	end
	local comments = require("differ.pr.comment")
	local anchor, err
	if last then
		anchor, err = comments.range_anchor(column.map, first, last, column.side)
	else
		anchor, err = comments.row_anchor(column.map, first, column.side)
	end
	return anchor, win, err
end

local function source_text(view, side, first, last)
	local text = view.model[side .. "_text"]
	if type(text) == "string" then
		local lines = vim.split(text, "\n", { plain = true })
		if lines[#lines] == "" then
			table.remove(lines)
		end
		if last > #lines then
			return nil
		end
		return table.concat(vim.list_slice(lines, first, last), "\n")
	end
	-- Controlled views and sources without full text can still resolve visible lines.
	local column = view:column_for(side)
	if not column then
		return nil
	end
	local index = side == "old" and column.map.from_old or column.map.from_new
	local lines = {}
	for line = first, last do
		local row = index[line]
		if not row then
			return nil
		end
		lines[#lines + 1] = vim.api.nvim_buf_get_lines(column.bufnr, row - 1, row, false)[1]
	end
	return table.concat(lines, "\n")
end

local function capture_context(view, anchor, mode)
	local range = source_range(anchor)
	local start, finish = range.start, range["end"]
	return {
		comparison = mode == "main" and "main..." or "HEAD",
		line_text = source_text(view, finish.side, finish.line, finish.line),
		start_line_text = source_text(view, start.side, start.line, start.line),
		range_text = start.side == finish.side and source_text(view, start.side, start.line, finish.line) or nil,
	}
end

function M.comment()
	local session, view = current_context()
	if not session then
		return notify("open a local Differ review first", vim.log.levels.WARN)
	end
	local row = vim.api.nvim_win_get_cursor(0)[1]
	local anchor, win, err = anchor_for_gesture(view, row)
	if not anchor then
		return notify(err or "no commentable line here", vim.log.levels.WARN)
	end
	compose_note(session, view, anchor, win, nil, capture_context(view, anchor, session.mode))
end

function M.comment_range()
	local session, view = current_context()
	if not session then
		return notify("open a local Differ review first", vim.log.levels.WARN)
	end
	local first, last = vim.fn.line("v"), vim.fn.line(".")
	vim.api.nvim_feedkeys(vim.api.nvim_replace_termcodes("<Esc>", true, false, true), "n", false)
	local anchor, win, err = anchor_for_gesture(view, first, last)
	if not anchor then
		return notify(err or "no commentable line here", vim.log.levels.WARN)
	end
	-- Range helpers normalize upward selections and can skip filler/meta rows.
	-- Capture the resolved source endpoint, not the cursor's raw rendered row.
	compose_note(session, view, anchor, win, nil, capture_context(view, anchor, session.mode))
end

local function note_anchor(note, view)
	local start = note.source_range.start
	local finish = note.source_range["end"]
	local column = view:column_for(finish.side)
	local index = column and (finish.side == "old" and column.map.from_old or column.map.from_new)
	local row = index and index[finish.line]
	local context = note.source_context
	local actual = source_text(view, finish.side, finish.line, finish.line)
	local actual_start = source_text(view, start.side, start.line, start.line)
	local mismatch = actual == nil
		or actual_start == nil
		or (context.line_text ~= nil and actual ~= context.line_text)
		or (context.start_line_text ~= nil and actual_start ~= context.start_line_text)
		or (context.range_text ~= nil and source_text(view, start.side, start.line, finish.line) ~= context.range_text)
	if mismatch then
		if note.anchor_status ~= "outdated" then
			notify(string.format("outdated anchor: %s:%d", note.path, finish.line), vim.log.levels.WARN)
		end
		note.anchor_status = "outdated"
		return column, nil
	end
	local verified = context.line_text ~= nil
	if start.side == finish.side and start.line ~= finish.line then
		verified = verified and context.range_text ~= nil
	elseif start.side ~= finish.side then
		verified = verified and context.start_line_text ~= nil
	end
	note.anchor_status = verified and "current" or "unverified"
	return column, row
end

local function notes_under_cursor(session, view)
	local buf, row = vim.api.nvim_get_current_buf(), vim.api.nvim_win_get_cursor(0)[1]
	local matches = {}
	for _, note in ipairs(notes_for(session)) do
		if note.path == view.model.path then
			local column, anchor_row = note_anchor(note, view)
			if column and column.bufnr == buf and anchor_row == row then
				matches[#matches + 1] = note
			end
		end
	end
	return matches
end

local function choose_note(notes, prompt, callback)
	if #notes == 0 then
		return notify("no local note under the cursor", vim.log.levels.WARN)
	elseif #notes == 1 then
		return callback(notes[1])
	end
	vim.ui.select(notes, {
		prompt = prompt,
		format_item = function(note)
			return note.body:match("[^\n]*") or ""
		end,
	}, function(note)
		if note then
			callback(note)
		end
	end)
end

function M.edit()
	local session, view = current_context()
	if not session then
		return
	end
	local win = vim.api.nvim_get_current_win()
	local comparison_mode = session.mode
	choose_note(notes_under_cursor(session, view), "Edit which local note?", function(note)
		if
			current_context() ~= session
			or session.mode ~= comparison_mode
			or not vim.tbl_contains(notes_for(session), note)
		then
			return
		end
		local finish = note.source_range["end"]
		local anchor = {
			side = finish.side == "old" and "LEFT" or "RIGHT",
			line = finish.line,
		}
		local start = note.source_range.start
		if start.side ~= finish.side or start.line ~= finish.line then
			anchor.start_side = start.side == "old" and "LEFT" or "RIGHT"
			anchor.start_line = start.line
		end
		compose_note(session, view, anchor, win, note, note.source_context)
	end)
end

function M.delete()
	local session, view = current_context()
	if not session then
		return
	end
	local comparison_mode = session.mode
	choose_note(notes_under_cursor(session, view), "Delete which local note?", function(note)
		if
			current_context() ~= session
			or session.mode ~= comparison_mode
			or not vim.tbl_contains(notes_for(session), note)
		then
			return
		end
		if vim.fn.confirm('Delete local note? "' .. (note.body:match("[^\n]*") or "") .. '"', "&Yes\n&No", 2) ~= 1 then
			return
		end
		if current_context() ~= session or session.mode ~= comparison_mode then
			return
		end
		for index, candidate in ipairs(notes_for(session)) do
			if candidate == note then
				table.remove(notes_for(session), index)
				break
			end
		end
		M.render(session, view, false)
		export_after_change(session)
	end)
end

function M.copy_review_path()
	local session = M.session_for_tab()
	if not session or not session.path then
		return notify("open a local Differ review first", vim.log.levels.WARN)
	end
	if not M.owns_current_branch(session) then
		return notify("branch changed; close and reopen the review", vim.log.levels.WARN)
	end
	if vim.fn.filereadable(session.path) ~= 1 then
		return notify("branch review has not been saved yet", vim.log.levels.WARN)
	end
	vim.fn.setreg("+", session.path)
	notify("copied " .. session.path)
end

function M.reset()
	local session, view = current_context()
	if not session then
		return
	end
	if session.load_error or not session.document then
		return notify("cannot reset protected review data: " .. tostring(session.load_error), vim.log.levels.ERROR)
	end
	if vim.fn.confirm("Reset all local notes for this branch?", "&Yes\n&No", 2) ~= 1 then
		return
	end
	if not M.owns_current_branch(session) then
		return notify("branch changed; close and reopen the review", vim.log.levels.WARN)
	end
	session.document.comparisons.HEAD.notes = {}
	session.document.comparisons.main.notes = {}
	M.render(session, view, false)
	local ok, err = M.export(session)
	if not ok then
		return notify("reset in memory, but save failed: " .. tostring(err), vim.log.levels.ERROR)
	end
	notify("reset branch review")
end

local function render_note(note, view, column, row)
	local thread = {
		thread_id = note.id,
		comments = { { author = "local", body = note.body, created_at = note.updated_at } },
	}
	local start, finish = note.source_range.start, note.source_range["end"]
	if start.side == finish.side and start.line < finish.line then
		local index = finish.side == "old" and column.map.from_old or column.map.from_new
		for line = start.line, finish.line do
			local range_row = index[line]
			if range_row then
				vim.api.nvim_buf_set_extmark(column.bufnr, namespace, range_row - 1, 0, {
					line_hl_group = "differThreadRange",
				})
			end
		end
	end
	if view.layout == "split" then
		vim.api.nvim_buf_set_extmark(column.bufnr, namespace, row - 1, 0, {
			virt_text = {
				{
					note.anchor_status == "unverified" and " 📝 LOCAL (unverified)" or " 📝 LOCAL",
					"differThreadPending",
				},
			},
			virt_text_pos = "eol",
		})
		return
	end
	local rows = require("differ.ui.thread").build(thread, {
		reltime = function(timestamp)
			return timestamp
		end,
	})
	-- Keep the destination explicit without hard-coding a branch-dependent filename.
	local label = note.anchor_status == "unverified" and "LOCAL (unverified anchor)" or "LOCAL"
	table.insert(rows, 1, { { label .. " → branch review JSON", "differThreadPending" } })
	vim.api.nvim_buf_set_extmark(column.bufnr, namespace, row - 1, 0, {
		virt_lines = rows,
		virt_lines_above = false,
	})
end

function M.render(session, view, persist_status)
	if not (session and view and view.model and view.columns) then
		return
	end
	namespace = namespace or vim.api.nvim_create_namespace("dotfiles.differ.local-review")
	for _, column in ipairs(view.columns) do
		if vim.api.nvim_buf_is_valid(column.bufnr) then
			vim.api.nvim_buf_clear_namespace(column.bufnr, namespace, 0, -1)
		end
	end
	if not M.owns_current_branch(session) then
		return
	end
	local status_changed = false
	for _, note in ipairs(notes_for(session)) do
		if note.path == view.model.path then
			local previous_status = note.anchor_status
			local column, row = note_anchor(note, view)
			status_changed = status_changed or previous_status ~= note.anchor_status
			if column and row then
				render_note(note, view, column, row)
			end
		end
	end
	-- Persist evaluated status once per render, so the JSON and diff agree. Mutation
	-- callers already publish the complete document after rendering.
	if status_changed and persist_status ~= false and session.existed then
		local ok, err = M.export(session)
		if not ok then
			notify("could not save anchor status: " .. tostring(err), vim.log.levels.WARN)
		end
	end
end

function M.attach(session, view)
	if not (session and view) then
		return
	end
	if view.dotfiles_local_review_session == session then
		M.render(session, view)
		return
	end
	view.dotfiles_local_review_session = session
	local previous_rerender = view.on_rerender
	view.on_rerender = function()
		if previous_rerender then
			previous_rerender()
		end
		if view.dotfiles_local_review_session == session then
			M.render(session, view)
		end
	end
	M.render(session, view)
end

M.write_snapshot = store.write_snapshot
M.store = store

return M
