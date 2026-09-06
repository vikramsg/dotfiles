local M = {}

local function git(root, ...)
	local args = { "git", "-C", root, "-c", "user.name=Review Test", "-c", "user.email=review@test.invalid" }
	vim.list_extend(args, { ... })
	local result = vim.system(args, { text = true }):wait()
	assert(result.code == 0, result.stderr)
end

local function repository(ignored)
	local root = vim.fn.resolve(vim.fn.tempname())
	vim.fn.mkdir(root, "p")
	git(root, "init", "--initial-branch=main")
	if ignored then
		assert(vim.fn.writefile({ ".agents/reviews" }, root .. "/.gitignore") == 0)
		git(root, "add", ".gitignore")
		git(root, "commit", "-m", "ignore review exports")
	end
	return root
end

local function exported(root)
	local path = root .. "/.agents/reviews/differ-review.json"
	return vim.json.decode(table.concat(vim.fn.readfile(path), "\n")), path
end

function M.run()
	local local_review = require("config.differ_local_review")
	local root = repository(true)
	local second_root = repository(true)
	local nonignored_root = repository(false)
	local tracked_root = repository(false)
	local original_buf = vim.api.nvim_get_current_buf()
	local buf = vim.api.nvim_create_buf(false, true)
	local win = vim.api.nvim_get_current_win()
	vim.api.nvim_win_set_buf(win, buf)

	local map = {
		lines = {
			{ kind = "old", old = 4 },
			{ kind = "new", new = 7 },
			{ kind = "new", new = 8 },
		},
		from_old = { [4] = 1 },
		from_new = { [7] = 2, [8] = 3 },
	}
	local column = { bufnr = buf, winid = win, side = "unified", map = map }
	local view = {
		model = { root = root, path = "deleted.txt" },
		layout = "stacked",
		columns = { column },
		column_for = function(_, _)
			return column
		end,
	}

	local differ = require("differ")
	local compose = require("differ.ui.compose")
	local sidecar = require("differ.sidecar")
	local original_active_view = differ.active_view
	local original_compose_open = compose.open
	local original_request = sidecar.request
	local original_select = vim.ui.select
	local original_confirm = vim.fn.confirm
	local original_line = vim.fn.line
	local original_feedkeys = vim.api.nvim_feedkeys
	local original_write = vim.uv.fs_write
	local captured
	local sidecar_calls = 0

	differ.active_view = function()
		return view
	end
	compose.open = function(opts)
		captured = opts
		return { close = function() end }
	end
	sidecar.request = function()
		sidecar_calls = sidecar_calls + 1
	end

	local ok, err = xpcall(function()
		local session = local_review.new_session(root, "HEAD")
		local_review.assign(vim.api.nvim_get_current_tabpage(), session, "HEAD")
		vim.t.dotfiles_differ_review = { root = root, mode = "HEAD", local_session_id = session.id }

		-- A normal comment on a deletion records the old-side source coordinate.
		vim.api.nvim_win_set_cursor(win, { 1, 0 })
		captured = nil
		local_review.comment()
		assert(captured and captured.on_submit, "comment should provide a submit callback")
		captured.on_submit("Deleted-line note")
		local snapshot, output = exported(root)
		assert(#snapshot.notes == 1 and snapshot.notes[1].path == "deleted.txt")
		assert(vim.deep_equal(snapshot.notes[1].source_range, {
			start = { side = "old", line = 4 },
			["end"] = { side = "old", line = 4 },
		}))

		-- Invoke the visual entry point directly with controlled marks: no key driving.
		vim.fn.line = function(mark)
			return mark == "v" and 1 or 2
		end
		vim.api.nvim_feedkeys = function() end
		captured = nil
		local_review.comment_range()
		captured.on_submit("Replacement range")
		vim.fn.line = original_line
		vim.api.nvim_feedkeys = original_feedkeys
		snapshot = exported(root)
		assert(#snapshot.notes == 2)
		assert(vim.deep_equal(snapshot.notes[2].source_range, {
			start = { side = "old", line = 4 },
			["end"] = { side = "new", line = 7 },
		}))

		-- Repoint the controlled view to an untracked file and add another note.
		view.model.path = "untracked.txt"
		map.lines = { { kind = "new", new = 1 } }
		map.from_old, map.from_new = {}, { [1] = 1 }
		vim.api.nvim_win_set_cursor(win, { 1, 0 })
		local_review.comment()
		captured.on_submit("Untracked-file note")
		snapshot = exported(root)
		assert(#snapshot.notes == 3 and snapshot.notes[3].path == "untracked.txt")
		assert(snapshot.notes[3].source_range.start.side == "new" and snapshot.notes[3].source_range.start.line == 1)

		-- A cancelled composer performs no mutation and does not rewrite the export.
		local before_cancel = table.concat(vim.fn.readfile(output), "\n")
		local before_cancel_stat = (vim.uv or vim.loop).fs_stat(output)
		local before_count = #local_review.snapshot(session).notes
		local_review.comment()
		if captured.on_cancel then
			captured.on_cancel()
		end
		assert(#local_review.snapshot(session).notes == before_count)
		assert(table.concat(vim.fn.readfile(output), "\n") == before_cancel)
		local after_cancel_stat = (vim.uv or vim.loop).fs_stat(output)
		assert(after_cancel_stat.size == before_cancel_stat.size)
		assert(vim.deep_equal(after_cancel_stat.mtime, before_cancel_stat.mtime))

		-- Add a second note at one anchor, then select it for editing and the first for deletion.
		local_review.comment()
		captured.on_submit("Second untracked note")
		vim.ui.select = function(items, _, callback)
			callback(items[2])
		end
		local_review.edit()
		captured.on_submit("Second untracked note, edited")
		snapshot = exported(root)
		assert(#snapshot.notes == 4 and snapshot.notes[4].body == "Second untracked note, edited")

		-- Composers and note pickers must not complete against a different comparison.
		local before_delayed = table.concat(vim.fn.readfile(output), "\n")
		local expected_notes = vim.deepcopy(local_review.snapshot(session).notes)
		vim.fn.confirm = function()
			error("a stale selection must not reach deletion confirmation")
		end
		for _, action in ipairs({ local_review.comment, local_review.edit }) do
			action()
			local_review.select_mode(session, "main")
			captured.on_submit("Stale HEAD callback")
			assert(#local_review.snapshot(session).notes == 0)
			local_review.select_mode(session, "HEAD")
			assert(vim.deep_equal(local_review.snapshot(session).notes, expected_notes))
			assert(table.concat(vim.fn.readfile(output), "\n") == before_delayed)
		end
		for _, action in ipairs({ local_review.edit, local_review.delete }) do
			local complete_selection
			vim.ui.select = function(items, _, callback)
				complete_selection = function()
					callback(items[1])
				end
			end
			captured = nil
			action()
			local_review.select_mode(session, "main")
			complete_selection()
			assert(not captured and #local_review.snapshot(session).notes == 0)
			local_review.select_mode(session, "HEAD")
			assert(vim.deep_equal(local_review.snapshot(session).notes, expected_notes))
			assert(table.concat(vim.fn.readfile(output), "\n") == before_delayed)
		end
		vim.ui.select = function(items, _, callback)
			callback(items[1])
		end
		vim.fn.confirm = function()
			return 1
		end
		local_review.delete()
		snapshot = exported(root)
		assert(#snapshot.notes == 3)
		assert(snapshot.notes[3].body == "Second untracked note, edited")

		-- Comparisons and repositories own independent note collections.
		local_review.select_mode(session, "main")
		assert(
			#local_review.snapshot(session).notes == 0 and local_review.snapshot(session).comparison.spec == "main..."
		)
		local_review.select_mode(session, "HEAD")
		assert(#local_review.snapshot(session).notes == 3)
		local other_session = local_review.new_session(second_root, "HEAD")
		assert(#local_review.snapshot(other_session).notes == 0 and other_session.root ~= session.root)

		assert(sidecar_calls == 0, "local review operations must make zero sidecar requests")

		-- A nonignored destination is rejected before any file is created.
		local rejected, reason = local_review.export(local_review.new_session(nonignored_root, "HEAD"))
		assert(not rejected and reason:find("not ignored", 1, true))
		assert(vim.fn.filereadable(nonignored_root .. "/.agents/reviews/differ-review.json") == 0)

		-- Git ignores do not make an already tracked export safe to overwrite.
		vim.fn.mkdir(tracked_root .. "/.agents/reviews", "p")
		local tracked_output = tracked_root .. "/.agents/reviews/differ-review.json"
		assert(vim.fn.writefile({ "tracked snapshot" }, tracked_output) == 0)
		git(tracked_root, "add", tracked_output)
		git(tracked_root, "commit", "-m", "track review snapshot")
		assert(vim.fn.writefile({ ".agents/reviews" }, tracked_root .. "/.gitignore") == 0)
		git(tracked_root, "add", ".gitignore")
		git(tracked_root, "commit", "-m", "ignore future review snapshots")
		rejected, reason = local_review.export(local_review.new_session(tracked_root, "HEAD"))
		assert(not rejected and reason:find("not ignored", 1, true))
		assert(vim.deep_equal(vim.fn.readfile(tracked_output), { "tracked snapshot" }))

		-- Neither an ancestor nor the destination may redirect an export elsewhere.
		assert(vim.uv.fs_symlink(root .. "/.agents", second_root .. "/.agents"))
		local escaped = local_review.resolve_export_path(second_root)
		assert(not escaped, "an ancestor symlink must not escape the reviewed repository")
		assert(vim.uv.fs_unlink(second_root .. "/.agents"))
		vim.fn.mkdir(second_root .. "/.agents/reviews", "p")
		assert(vim.uv.fs_symlink(output, second_root .. "/.agents/reviews/differ-review.json"))
		escaped = local_review.resolve_export_path(second_root)
		assert(not escaped, "the export must not overwrite a symbolic-link destination")

		-- Encoding/write failure leaves the last complete snapshot untouched.
		local before_failure = table.concat(vim.fn.readfile(output), "\n")
		local written = local_review.write_snapshot(output, { invalid = function() end })
		assert(not written)
		assert(table.concat(vim.fn.readfile(output), "\n") == before_failure)
		local after_failure = exported(root)
		assert(#after_failure.notes == 3 and after_failure.notes[3].body == "Second untracked note, edited")

		-- A short write followed by failure must not publish a truncated document.
		local writes = 0
		vim.uv.fs_write = function(fd, data, offset)
			writes = writes + 1
			if writes == 1 then
				return original_write(fd, data:sub(1, 8), offset)
			end
			return nil, "simulated disk full"
		end
		written = local_review.write_snapshot(output, local_review.snapshot(session))
		vim.uv.fs_write = original_write
		assert(not written and table.concat(vim.fn.readfile(output), "\n") == before_failure)

		-- Successful short writes are completed before publishing the new snapshot.
		vim.uv.fs_write = function(fd, data, offset)
			return original_write(fd, data:sub(1, 8), offset)
		end
		written = local_review.write_snapshot(output, local_review.snapshot(session))
		vim.uv.fs_write = original_write
		assert(written and vim.deep_equal(exported(root).notes, after_failure.notes))

		local blocker = nonignored_root .. "/file-instead-of-directory"
		vim.fn.writefile({ "original" }, blocker)
		written = local_review.write_snapshot(blocker .. "/snapshot.json", {})
		assert(not written and vim.deep_equal(vim.fn.readfile(blocker), { "original" }))
	end, debug.traceback)

	differ.active_view = original_active_view
	compose.open = original_compose_open
	sidecar.request = original_request
	vim.ui.select = original_select
	vim.fn.confirm = original_confirm
	vim.fn.line = original_line
	vim.api.nvim_feedkeys = original_feedkeys
	vim.uv.fs_write = original_write
	vim.t.dotfiles_differ_review = nil
	if vim.api.nvim_buf_is_valid(buf) then
		vim.api.nvim_win_set_buf(win, original_buf)
		vim.api.nvim_buf_delete(buf, { force = true })
	end
	for _, path in ipairs({ root, second_root, nonignored_root, tracked_root }) do
		vim.fn.delete(path, "rf")
	end
	assert(ok, err)
	print("Differ local review: note state, anchors, export safety, and backend isolation passed")
end

return M
