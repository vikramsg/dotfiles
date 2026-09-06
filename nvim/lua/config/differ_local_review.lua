local M = {}

local EXPORT_RELATIVE_PATH = ".agents/reviews/differ-review.json"
local REVIEW_DIRECTORY = ".agents/reviews"
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

local function path_inside(parent, child)
	parent, child = vim.fs.normalize(parent), vim.fs.normalize(child)
	return child ~= parent and child:sub(1, #parent + 1) == parent .. "/"
end

local function nearest_existing(path)
	local current = path
	while not (vim.uv or vim.loop).fs_stat(current) do
		local parent = vim.fs.dirname(current)
		if parent == current then
			return current
		end
		current = parent
	end
	return current
end

-- Resolve both existing ancestors before checking containment. This rejects an
-- output directory redirected through a symlink as well as a symlink at the file.
function M.resolve_export_path(root)
	local uv = vim.uv or vim.loop
	local canonical_root = uv.fs_realpath(root)
	if not canonical_root then
		return nil, "repository root does not exist"
	end
	local output = vim.fs.normalize(canonical_root .. "/" .. EXPORT_RELATIVE_PATH)
	local review_root = vim.fs.normalize(canonical_root .. "/" .. REVIEW_DIRECTORY)
	local output_stat = uv.fs_lstat(output)
	if output_stat and output_stat.type == "link" then
		return nil, "export path must not be a symbolic link"
	end

	local review_ancestor = nearest_existing(review_root)
	local canonical_review_ancestor = uv.fs_realpath(review_ancestor)
	local canonical_review =
		vim.fs.normalize(canonical_review_ancestor .. "/" .. vim.fs.relpath(review_ancestor, review_root))
	if not path_inside(canonical_root, canonical_review) then
		return nil, REVIEW_DIRECTORY .. " must stay inside the repository root"
	end

	local output_ancestor = nearest_existing(output)
	local canonical_output_ancestor = uv.fs_realpath(output_ancestor)
	local canonical_output =
		vim.fs.normalize(canonical_output_ancestor .. "/" .. vim.fs.relpath(output_ancestor, output))
	if not path_inside(canonical_review, canonical_output) then
		return nil, "export path must stay inside " .. REVIEW_DIRECTORY
	end
	return canonical_output, canonical_root
end

local function ignored(root)
	local result = vim.system({ "git", "-C", root, "check-ignore", "-q", "--", EXPORT_RELATIVE_PATH }, {
		text = true,
	}):wait()
	return result.code == 0
end

-- Write a complete snapshot beside the destination, sync it, then rename it over
-- the old one. Failures only remove our temporary file; the last snapshot survives.
function M.write_snapshot(path, snapshot)
	local uv = vim.uv or vim.loop
	local made, mkdir_err = pcall(vim.fn.mkdir, vim.fs.dirname(path), "p")
	if not made then
		return nil, tostring(mkdir_err)
	end
	local temporary = string.format("%s.%d.%d.tmp", path, vim.fn.getpid(), uv.hrtime())
	local fd, open_err = uv.fs_open(temporary, "wx", 384)
	if not fd then
		return nil, open_err
	end
	local closed = false
	local ok, err = pcall(function()
		local encoded = vim.json.encode(snapshot) .. "\n"
		local offset = 0
		while offset < #encoded do
			local written, write_err = uv.fs_write(fd, encoded:sub(offset + 1), offset)
			assert(written and written > 0, write_err or "snapshot write made no progress")
			offset = offset + written
		end
		assert(uv.fs_fsync(fd))
		assert(uv.fs_close(fd))
		closed = true
		assert(uv.fs_rename(temporary, path))
	end)
	if not closed then
		pcall(uv.fs_close, fd)
	end
	if not ok then
		pcall(uv.fs_unlink, temporary)
		return nil, tostring(err)
	end
	return true
end

local function comparison(mode)
	if mode == "main" then
		return { spec = "main...", base = "main", target = "working-tree" }
	end
	return { spec = "HEAD", base = "HEAD", target = "working-tree" }
end

local function notes_for(session)
	session.notes[session.mode] = session.notes[session.mode] or {}
	return session.notes[session.mode]
end

function M.snapshot(session)
	local notes = {}
	for _, note in ipairs(notes_for(session)) do
		notes[#notes + 1] = {
			id = note.id,
			body = note.body,
			path = note.path,
			source_range = vim.deepcopy(note.source_range),
			created_at = note.created_at,
			updated_at = note.updated_at,
		}
	end
	return {
		schema_version = 1,
		root = session.root,
		comparison = comparison(session.mode),
		exported_at = now(),
		notes = notes,
	}
end

function M.export(session)
	local path, root_or_err = M.resolve_export_path(session.root)
	if not path then
		return nil, root_or_err
	end
	local root = root_or_err
	if not ignored(root) then
		return nil, EXPORT_RELATIVE_PATH .. " is not ignored by Git"
	end
	local ok, err = M.write_snapshot(path, M.snapshot(session))
	if not ok then
		return nil, err
	end
	return true, path
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
			EXPORT_RELATIVE_PATH
		)
	)
	return true
end

function M.new_session(root, mode)
	next_session_id = next_session_id + 1
	return {
		id = next_session_id,
		root = (vim.uv or vim.loop).fs_realpath(root) or vim.fs.normalize(root),
		mode = mode,
		notes = {},
	}
end

function M.select_mode(session, mode)
	session.mode = mode
	notes_for(session)
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

local function compose_note(session, view, anchor, anchor_win, existing)
	local mode = existing and "Edit" or "New"
	local comparison_mode = session.mode
	local path = view.model.path
	require("differ.ui.compose").open({
		title = mode .. " LOCAL note → " .. EXPORT_RELATIVE_PATH,
		initial = existing and existing.body or nil,
		layout = view.layout,
		anchor_win = anchor_win,
		on_submit = function(body)
			if body == "" then
				return notify("empty note discarded", vim.log.levels.WARN)
			end
			-- The composer may outlive its review tab. Never mutate another session.
			local active = vim.t.dotfiles_differ_review
			if not active or M.session_for_tab() ~= session or session.mode ~= comparison_mode then
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
					id = string.format("local-%d-%d", session.id, next_note_id),
					body = body,
					path = path,
					source_range = source_range(anchor),
					created_at = timestamp,
					updated_at = timestamp,
				}
				table.insert(notes_for(session), note)
			end
			M.render(session, view)
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
	compose_note(session, view, anchor, win)
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
	compose_note(session, view, anchor, win)
end

local function note_anchor(note, view)
	local finish = note.source_range["end"]
	local column = view:column_for(finish.side)
	local index = column and (finish.side == "old" and column.map.from_old or column.map.from_new)
	local row = index and require("differ.pr.threads").anchor_row(index, finish.line)
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
		compose_note(session, view, anchor, win, note)
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
		M.render(session, view)
		export_after_change(session)
	end)
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
			virt_text = { { " 📝 LOCAL", "differThreadPending" } },
			virt_text_pos = "eol",
		})
		return
	end
	local rows = require("differ.ui.thread").build(thread, {
		reltime = function(timestamp)
			return timestamp
		end,
	})
	-- Add an explicit destination to every expanded local note.
	table.insert(rows, 1, { { "LOCAL → " .. EXPORT_RELATIVE_PATH, "differThreadPending" } })
	vim.api.nvim_buf_set_extmark(column.bufnr, namespace, row - 1, 0, {
		virt_lines = rows,
		virt_lines_above = false,
	})
end

function M.render(session, view)
	if not (session and view and view.model and view.columns) then
		return
	end
	namespace = namespace or vim.api.nvim_create_namespace("dotfiles.differ.local-review")
	for _, column in ipairs(view.columns) do
		if vim.api.nvim_buf_is_valid(column.bufnr) then
			vim.api.nvim_buf_clear_namespace(column.bufnr, namespace, 0, -1)
		end
	end
	for _, note in ipairs(notes_for(session)) do
		if note.path == view.model.path then
			local column, row = note_anchor(note, view)
			if column and row then
				render_note(note, view, column, row)
			end
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

M.export_relative_path = EXPORT_RELATIVE_PATH

return M
