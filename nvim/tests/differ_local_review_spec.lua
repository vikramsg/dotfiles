local M = {}

local function git(root, ...)
	local args = { "git", "-C", root, "-c", "user.name=Review Test", "-c", "user.email=review@test.invalid" }
	vim.list_extend(args, { ... })
	local result = vim.system(args, { text = true }):wait()
	assert(result.code == 0, result.stderr)
	return vim.trim(result.stdout or "")
end

local function repository(ignored)
	local root = vim.fn.resolve(vim.fn.tempname())
	vim.fn.mkdir(root, "p")
	git(root, "init", "--initial-branch=main")
	vim.fn.writefile({ "one", "two" }, root .. "/example.txt")
	if ignored then
		vim.fn.writefile({ ".agents/reviews" }, root .. "/.gitignore")
	end
	git(root, "add", ".")
	git(root, "commit", "-m", "initial")
	return root
end

local function decoded(path)
	return vim.json.decode(table.concat(vim.fn.readfile(path), "\n"))
end

local function notes(session, mode)
	return session.document.comparisons[mode or session.mode].notes
end

local function stored_note(id, comparison)
	return {
		id = id,
		body = id,
		path = "example.txt",
		source_range = { start = { side = "new", line = 1 }, ["end"] = { side = "new", line = 1 } },
		source_context = { comparison = comparison or "HEAD", line_text = "one" },
		anchor_status = "current",
		created_at = "2026-01-01T00:00:00Z",
		updated_at = "2026-01-01T00:00:00Z",
	}
end

local function validate_with_jsonschema(instance_path, invalid)
	local cwd = vim.fn.getcwd()
	local result = vim.system({
		"uv",
		"run",
		"--script",
		cwd .. "/tests/support/validate_json_schema.py",
		cwd .. "/schemas/differ-review.schema.json",
		instance_path,
	}, { text = true }):wait()
	if invalid then
		assert(result.code ~= 0 and result.stderr:find("ValidationError", 1, true), result.stderr)
	else
		assert(result.code == 0, result.stderr)
	end
end

local function load_in_fresh_nvim(root)
	local output = vim.fn.tempname()
	local code = string.format(
		"local s=require('config.differ_local_review').new_session(%q,'HEAD'); assert(s.document,s.load_error); vim.fn.writefile({vim.json.encode(s.document)},%q)",
		root,
		output
	)
	local result = vim.system({ "nvim", "--headless", "-u", "init.lua", "+lua " .. code, "+qa" }, {
		cwd = vim.fn.getcwd(),
		text = true,
	}):wait()
	assert(result.code == 0, result.stderr)
	local document = decoded(output)
	vim.fn.delete(output)
	return document
end

function M.run()
	local local_review = require("config.differ_local_review")
	local store = local_review.store
	local root = repository(true)
	local second_root = repository(true)
	local nonignored_root = repository(false)
	local tracked_root = repository(false)
	local corrupt_root = repository(true)
	local concurrency_root = repository(true)
	local validation_root = repository(true)
	local ownership_root = repository(true)
	local roots = {
		root,
		second_root,
		nonignored_root,
		tracked_root,
		corrupt_root,
		concurrency_root,
		validation_root,
		ownership_root,
	}
	local original_buf = vim.api.nvim_get_current_buf()
	local buf = vim.api.nvim_create_buf(false, true)
	local win = vim.api.nvim_get_current_win()
	vim.api.nvim_win_set_buf(win, buf)

	local map = {
		lines = { { kind = "old", old = 4 }, { kind = "new", new = 7 }, { kind = "new", new = 8 } },
		from_old = { [4] = 1 },
		from_new = { [7] = 2, [8] = 3 },
	}
	vim.api.nvim_buf_set_lines(buf, 0, -1, false, { "deleted source", "replacement", "next" })
	local column = { bufnr = buf, winid = win, side = "unified", map = map }
	local view = {
		model = { root = root, path = "example.txt" },
		layout = "stacked",
		columns = { column },
		column_for = function()
			return column
		end,
	}

	local differ = require("differ")
	local compose = require("differ.ui.compose")
	local sidecar = require("differ.sidecar")
	local original_active_view, original_compose_open = differ.active_view, compose.open
	local original_request, original_select = sidecar.request, vim.ui.select
	local original_confirm, original_line = vim.fn.confirm, vim.fn.line
	local original_feedkeys, original_write, original_rename = vim.api.nvim_feedkeys, vim.uv.fs_write, vim.uv.fs_rename
	local original_home = vim.env.HOME
	local captured, sidecar_calls = nil, 0
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
		assert(store.relative_path(session.identity):match("^%.agents/reviews/review%-%x%x%x%x%x%x%x%x%x%x%x%x%.json$"))
		local_review.assign(vim.api.nvim_get_current_tabpage(), session, "HEAD")
		vim.t.dotfiles_differ_review = { root = root, mode = "HEAD", local_session_id = session.id }
		assert(#notes(session) == 0 and not session.existed)

		vim.api.nvim_win_set_cursor(win, { 1, 0 })
		local_review.comment()
		assert(captured and captured.on_submit)
		captured.on_submit("Deleted-line note")
		assert(session.existed and vim.fn.filereadable(session.path) == 1)
		local snapshot = decoded(session.path)
		assert(snapshot.schema_version == 2 and #snapshot.comparisons.HEAD.notes == 1)
		assert(snapshot.comparisons.HEAD.notes[1].source_context.line_text == "deleted source")
		assert(vim.deep_equal(snapshot.comparisons.HEAD.notes[1].source_range, {
			start = { side = "old", line = 4 },
			["end"] = { side = "old", line = 4 },
		}))

		validate_with_jsonschema(session.path)
		assert(store.validate(snapshot))

		-- Cancelling a composer performs no mutation and does not touch the saved file.
		local before_cancel = table.concat(vim.fn.readfile(session.path), "\n")
		local before_cancel_stat = (vim.uv or vim.loop).fs_stat(session.path)
		local before_cancel_count = #notes(session)
		local_review.comment()
		if captured.on_cancel then
			captured.on_cancel()
		end
		assert(#notes(session) == before_cancel_count)
		assert(table.concat(vim.fn.readfile(session.path), "\n") == before_cancel)
		local after_cancel_stat = (vim.uv or vim.loop).fs_stat(session.path)
		assert(after_cancel_stat.size == before_cancel_stat.size)
		assert(vim.deep_equal(after_cancel_stat.mtime, before_cancel_stat.mtime))

		-- Both comparisons persist independently in the same branch document.
		local_review.select_mode(session, "main")
		assert(#notes(session) == 0)
		vim.api.nvim_win_set_cursor(win, { 2, 0 })
		local_review.comment()
		captured.on_submit("Main comparison note")
		assert(#notes(session, "main") == 1)
		local_review.select_mode(session, "HEAD")
		assert(#notes(session) == 1)
		local fresh_document = load_in_fresh_nvim(root)
		assert(#fresh_document.comparisons.HEAD.notes == 1)
		assert(#fresh_document.comparisons.main.notes == 1)
		validate_with_jsonschema(session.path)

		-- An upward cross-side range captures the resolved endpoint, not the cursor row.
		vim.fn.line = function(mark)
			return mark == "v" and 2 or 1
		end
		vim.api.nvim_feedkeys = function() end
		local_review.comment_range()
		captured.on_submit("Replacement range")
		vim.fn.line, vim.api.nvim_feedkeys = original_line, original_feedkeys
		assert(#notes(session) == 2 and notes(session)[2].source_context.line_text == "replacement")

		-- Exact source context prevents a moved/mismatched anchor attaching elsewhere.
		vim.api.nvim_buf_set_lines(buf, 0, 1, false, { "unrelated source" })
		local_review.render(session, view)
		assert(notes(session)[1].anchor_status == "outdated")
		assert(notes(session)[2].anchor_status == "outdated", "cross-side ranges must validate the starting source")
		assert(decoded(session.path).comparisons.HEAD.notes[2].anchor_status == "outdated")
		for _, mark in ipairs(vim.api.nvim_buf_get_extmarks(buf, -1, 0, -1, {})) do
			assert(mark[2] ~= 0, "the outdated note must not render on its former row")
		end
		vim.api.nvim_buf_set_lines(buf, 0, 1, false, { "deleted source" })
		local_review.render(session, view)
		assert(notes(session)[1].anchor_status == "current")

		-- Delayed composers and selectors cannot cross comparison or branch ownership.
		local_review.comment()
		local delayed_submit = captured.on_submit
		local before = table.concat(vim.fn.readfile(session.path), "\n")
		git(root, "switch", "-c", "topic")
		delayed_submit("stale branch save")
		assert(table.concat(vim.fn.readfile(session.path), "\n") == before)
		assert(#notes(session) == 2)
		git(root, "switch", "main")

		vim.api.nvim_win_set_cursor(win, { 2, 0 })
		local_review.comment()
		captured.on_submit("Second note on replacement")
		vim.ui.select = function(items, _, callback)
			local_review.select_mode(session, "main")
			callback(items[1])
		end
		captured = nil
		local_review.select_mode(session, "HEAD")
		local_review.edit()
		assert(captured == nil, "stale selection unexpectedly opened a composer")
		assert(#notes(session, "HEAD") == 3, "stale selection mutated HEAD notes")
		local_review.select_mode(session, "HEAD")

		local complete_selection
		vim.ui.select = function(items, _, callback)
			complete_selection = function()
				callback(items[1])
			end
		end
		local_review.edit()
		git(root, "switch", "topic")
		captured = nil
		complete_selection()
		assert(captured == nil and #notes(session, "HEAD") == 3)
		git(root, "switch", "main")

		-- Edit and delete mutate the persisted branch document through controlled callbacks.
		vim.ui.select = function(items, _, callback)
			callback(items[#items])
		end
		local_review.edit()
		captured.on_submit("Edited replacement note")
		assert(notes(session, "HEAD")[3].body == "Edited replacement note")
		vim.ui.select = function(items, _, callback)
			callback(items[1])
		end
		vim.fn.confirm = function()
			return 1
		end
		local_review.delete()
		assert(#notes(session, "HEAD") == 2 and #decoded(session.path).comparisons.HEAD.notes == 2)

		-- Branch and repository identities select separate files; returning resumes.
		git(root, "switch", "topic")
		local topic = local_review.new_session(root, "HEAD")
		assert(topic.path ~= session.path and #notes(topic) == 0 and #notes(topic, "main") == 0)
		git(root, "switch", "main")
		local returned = local_review.new_session(root, "HEAD")
		assert(returned.path == session.path and #notes(returned) == 2 and #notes(returned, "main") == 1)
		vim.fn.writefile({ "one", "two", "commit does not change branch identity" }, root .. "/example.txt")
		git(root, "add", "example.txt")
		git(root, "commit", "-m", "advance branch")
		local after_commit = local_review.new_session(root, "HEAD")
		assert(after_commit.path == returned.path and #notes(after_commit) == 2)
		local other = local_review.new_session(second_root, "HEAD")
		assert(other.path ~= session.path and other.root ~= session.root)

		-- A short-hash collision cannot load or overwrite a document owned by
		-- another branch identity, even when it occupies the resolved filename.
		local owned = local_review.new_session(ownership_root, "HEAD")
		table.insert(notes(owned), stored_note("owned-review"))
		assert(local_review.export(owned))
		local wrong_owner = decoded(owned.path)
		wrong_owner.branch.name = "some-other-branch"
		vim.fn.writefile({ vim.json.encode(wrong_owner) }, owned.path)
		local collision = local_review.new_session(ownership_root, "HEAD")
		assert(collision.load_error and collision.document == nil)
		local collision_bytes = table.concat(vim.fn.readfile(owned.path), "\n")
		assert(not local_review.export(collision))
		assert(table.concat(vim.fn.readfile(owned.path), "\n") == collision_bytes)

		-- Detached HEAD uses the commit itself as a stable, separate identity.
		local commit = git(second_root, "rev-parse", "HEAD")
		git(second_root, "checkout", "--detach", commit)
		local detached = local_review.new_session(second_root, "HEAD")
		assert(detached.identity.kind == "detached" and detached.path ~= other.path)

		-- Reset mutates both comparisons and persists an empty, resumable document.
		session = returned
		local_review.assign(vim.api.nvim_get_current_tabpage(), session, "HEAD")
		vim.t.dotfiles_differ_review.local_session_id = session.id
		vim.fn.confirm = function()
			return 1
		end
		local_review.reset()
		assert(#notes(session, "HEAD") == 0 and #notes(session, "main") == 0)
		assert(#notes(local_review.new_session(root, "HEAD"), "HEAD") == 0)

		-- Malformed and unsupported branch files are protected from mutation.
		local corrupt_identity = assert(store.current_identity(corrupt_root))
		local corrupt_path = assert(store.resolve_path(corrupt_root, corrupt_identity))
		vim.fn.mkdir(vim.fs.dirname(corrupt_path), "p")
		vim.fn.writefile({ "{ broken" }, corrupt_path)
		local corrupt = local_review.new_session(corrupt_root, "HEAD")
		assert(corrupt.load_error and corrupt.document == nil)
		local saved = local_review.export(corrupt)
		assert(not saved and vim.deep_equal(vim.fn.readfile(corrupt_path), { "{ broken" }))
		vim.fn.writefile({ vim.json.encode({ schema_version = 99 }) }, corrupt_path)
		corrupt = local_review.new_session(corrupt_root, "HEAD")
		assert(corrupt.load_error and decoded(corrupt_path).schema_version == 99)

		-- Optimistic fingerprints reject writes from stale sessions without merging.
		local first_absent = local_review.new_session(concurrency_root, "HEAD")
		local second_absent = local_review.new_session(concurrency_root, "HEAD")
		assert(first_absent.fingerprint == false and second_absent.fingerprint == false)
		table.insert(notes(first_absent), stored_note("first-writer"))
		assert(local_review.export(first_absent))
		assert(type(first_absent.fingerprint) == "string")
		local first_bytes = table.concat(vim.fn.readfile(first_absent.path), "\n")
		table.insert(notes(second_absent), stored_note("stale-absent-writer"))
		local stale_ok, stale_err = local_review.export(second_absent)
		assert(not stale_ok and stale_err:find("reopen", 1, true))
		assert(table.concat(vim.fn.readfile(first_absent.path), "\n") == first_bytes)
		assert(#notes(second_absent) == 1, "a refused save must retain its in-memory draft")

		local deleting_session = local_review.new_session(concurrency_root, "HEAD")
		local resurrection_session = local_review.new_session(concurrency_root, "HEAD")
		deleting_session.document.comparisons.HEAD.notes = {}
		assert(local_review.export(deleting_session))
		local deleted_bytes = table.concat(vim.fn.readfile(deleting_session.path), "\n")
		stale_ok, stale_err = local_review.export(resurrection_session)
		assert(not stale_ok and stale_err:find("reopen", 1, true))
		assert(table.concat(vim.fn.readfile(deleting_session.path), "\n") == deleted_bytes)
		assert(#notes(resurrection_session) == 1, "the stale note remains in memory without being resurrected")

		local externally_changed = local_review.new_session(concurrency_root, "HEAD")
		vim.fn.writefile({ "{ externally malformed" }, externally_changed.path)
		stale_ok, stale_err = local_review.export(externally_changed)
		assert(not stale_ok and stale_err:find("reopen", 1, true))
		assert(vim.deep_equal(vim.fn.readfile(externally_changed.path), { "{ externally malformed" }))

		-- Runtime validation rejects unknown keys and malformed values before replacing a valid file.
		local validation_session = local_review.new_session(validation_root, "HEAD")
		table.insert(notes(validation_session), stored_note("validation-note"))
		assert(local_review.export(validation_session))
		validate_with_jsonschema(validation_session.path)
		-- The standalone contract must reject comparison swaps and misplaced notes,
		-- just as loading those documents would reject them at runtime.
		local invalid_schema_path = validation_root .. "/invalid-review.json"
		local swapped = vim.deepcopy(validation_session.document)
		swapped.comparisons.HEAD, swapped.comparisons.main = swapped.comparisons.main, swapped.comparisons.HEAD
		vim.fn.writefile({ vim.json.encode(swapped) }, invalid_schema_path)
		assert(not store.validate(swapped))
		validate_with_jsonschema(invalid_schema_path, true)
		local misplaced = vim.deepcopy(validation_session.document)
		misplaced.comparisons.HEAD.notes[1].source_context.comparison = "main..."
		vim.fn.writefile({ vim.json.encode(misplaced) }, invalid_schema_path)
		assert(not store.validate(misplaced))
		validate_with_jsonschema(invalid_schema_path, true)
		local valid_bytes = table.concat(vim.fn.readfile(validation_session.path), "\n")
		local valid_fingerprint = validation_session.fingerprint
		local missing_expected, missing_expected_err =
			store.save(validation_root, validation_session.identity, vim.deepcopy(validation_session.document))
		assert(not missing_expected and missing_expected_err:find("reopen", 1, true))
		assert(table.concat(vim.fn.readfile(validation_session.path), "\n") == valid_bytes)
		local invalid_documents = {}
		local function invalid(mutator)
			local document = vim.deepcopy(validation_session.document)
			mutator(document)
			table.insert(invalid_documents, document)
		end
		invalid(function(document)
			document.unknown = true
		end)
		invalid(function(document)
			document.branch.unknown = true
		end)
		invalid(function(document)
			document.comparisons.unknown = {}
		end)
		invalid(function(document)
			document.comparisons.HEAD.unknown = true
		end)
		invalid(function(document)
			document.comparisons.HEAD.notes[1].unknown = true
		end)
		invalid(function(document)
			document.comparisons.HEAD.notes[1].source_range.unknown = true
		end)
		invalid(function(document)
			document.comparisons.HEAD.notes[1].source_range.start.unknown = true
		end)
		invalid(function(document)
			document.comparisons.HEAD.notes[1].source_context.unknown = true
		end)
		invalid(function(document)
			document.comparisons.HEAD.notes[1].id = ""
		end)
		invalid(function(document)
			document.branch.head = ""
		end)
		for _, field in ipairs({ "line_text", "range_text", "start_line_text" }) do
			invalid(function(document)
				document.comparisons.HEAD.notes[1].source_context[field] = 42
			end)
		end
		for _, document in ipairs(invalid_documents) do
			local invalid_ok = store.save(validation_root, validation_session.identity, document, valid_fingerprint)
			assert(not invalid_ok)
			assert(table.concat(vim.fn.readfile(validation_session.path), "\n") == valid_bytes)
		end
		local future_context = vim.deepcopy(validation_session.document)
		future_context.comparisons.HEAD.notes[1].source_context.range_text = "one\ntwo"
		future_context.comparisons.HEAD.notes[1].source_context.start_line_text = "one"
		assert(store.validate(future_context))

		-- Nonignored and tracked destinations are rejected without replacement.
		local rejected = local_review.new_session(nonignored_root, "HEAD")
		local saved_ok, reason = local_review.export(rejected)
		assert(not saved_ok and reason:find("not ignored", 1, true) and vim.fn.filereadable(rejected.path) == 0)
		local tracked = local_review.new_session(tracked_root, "HEAD")
		vim.fn.mkdir(vim.fs.dirname(tracked.path), "p")
		vim.fn.writefile({ "tracked snapshot" }, tracked.path)
		git(tracked_root, "add", "-f", store.relative_path(tracked.identity))
		git(tracked_root, "commit", "-m", "track review")
		vim.fn.writefile({ ".agents/reviews" }, tracked_root .. "/.gitignore")
		git(tracked_root, "add", ".gitignore")
		git(tracked_root, "commit", "-m", "ignore reviews")
		saved_ok, reason = local_review.export(tracked)
		assert(not saved_ok and reason:find("not ignored", 1, true))
		assert(vim.deep_equal(vim.fn.readfile(tracked.path), { "tracked snapshot" }))

		-- Symlink confinement and atomic write/short-write protection remain intact.
		local identity = assert(store.current_identity(root))
		local second_identity = assert(store.current_identity(second_root))
		assert(vim.uv.fs_symlink(root .. "/.agents", second_root .. "/.agents"))
		assert(not store.resolve_path(second_root, second_identity))
		assert(vim.uv.fs_unlink(second_root .. "/.agents"))
		vim.fn.mkdir(second_root .. "/.agents/reviews", "p")
		local second_path = assert(store.resolve_path(second_root, second_identity))
		assert(vim.uv.fs_symlink(session.path, second_path))
		assert(not store.resolve_path(second_root, second_identity))

		local before_failure = table.concat(vim.fn.readfile(session.path), "\n")
		local written = store.write_snapshot(session.path, { invalid = function() end })
		assert(not written and table.concat(vim.fn.readfile(session.path), "\n") == before_failure)
		local writes = 0
		vim.uv.fs_write = function(fd, data, offset)
			writes = writes + 1
			if writes == 1 then
				return original_write(fd, data:sub(1, 8), offset)
			end
			return nil, "simulated disk full"
		end
		written = store.write_snapshot(session.path, session.document)
		vim.uv.fs_write = original_write
		assert(not written and table.concat(vim.fn.readfile(session.path), "\n") == before_failure)
		vim.uv.fs_write = function(fd, data, offset)
			return original_write(fd, data:sub(1, 8), offset)
		end
		written = store.write_snapshot(session.path, session.document)
		vim.uv.fs_write = original_write
		assert(written and store.validate(decoded(session.path)))
		local before_rename_failure = table.concat(vim.fn.readfile(session.path), "\n")
		vim.uv.fs_rename = function()
			return nil, "simulated rename failure"
		end
		written = store.write_snapshot(session.path, session.document)
		vim.uv.fs_rename = original_rename
		assert(not written and table.concat(vim.fn.readfile(session.path), "\n") == before_rename_failure)

		-- Synthetic output metadata is never a file operation target or navigation row.
		vim.env.HOME = vim.fs.dirname(root)
		local display_root = vim.fn.fnamemodify(root, ":~")
		assert(display_root:sub(1, 2) == "~/")
		local panel = require("differ.panel").new({
			sections = {
				{ title = "Files", entries = { { path = "example.txt", status = "M", additions = 1, deletions = 0 } } },
			},
			on_select = function()
				error("output must not route through file selection")
			end,
			root = display_root,
		})
		local git_review = require("config.git_review")
		session.panel = panel
		git_review.attach_review_panel(panel, session)
		vim.env.HOME = original_home
		local output_count = 0
		for _, meta in ipairs(panel.meta) do
			if meta.kind == "review_output" then
				output_count = output_count + 1
				assert(meta.entry == nil)
			end
		end
		assert(output_count == 1 and panel.file_total == 1 and panel:_file_row(#panel.meta, "next") ~= nil)
		panel.winid = win
		vim.api.nvim_win_set_buf(win, panel.bufnr)
		for row, meta in ipairs(panel.meta) do
			if meta.kind == "review_output" then
				vim.api.nvim_win_set_cursor(win, { row, 0 })
				break
			end
		end
		local output_buf = vim.api.nvim_create_buf(false, true)
		vim.b[output_buf].dotfiles_differ_review_output = session.path
		vim.api.nvim_buf_set_lines(output_buf, 0, -1, false, { "stale" })
		git_review.refresh_review_output(session)
		assert(vim.api.nvim_buf_get_lines(output_buf, 0, 1, false)[1] ~= "stale")
		vim.api.nvim_buf_delete(output_buf, { force = true })
		-- A saved document rejected by the loader must remain available for inspection.
		-- Its protected state prevents mutation, not access to its actual file.
		git_review.attach_review_panel(panel, corrupt)
		assert(panel.meta[#panel.meta].path == corrupt.path and panel.file_total == 1)
		assert(not local_review.export(corrupt) and decoded(corrupt.path).schema_version == 99)
		panel.winid = nil
		vim.api.nvim_win_set_buf(win, buf)
		panel:close()

		-- Changing only the middle of a same-side range must invalidate the saved
		-- anchor, including the read-only output's document, without a comment edit.
		local anchor_root = repository(true)
		roots[#roots + 1] = anchor_root
		view.model = { root = anchor_root, path = "example.txt", new_text = "first\nmiddle\nlast\n" }
		map.lines = { { kind = "new", new = 1 }, { kind = "new", new = 2 }, { kind = "new", new = 3 } }
		map.from_old, map.from_new = {}, { [1] = 1, [2] = 2, [3] = 3 }
		vim.api.nvim_buf_set_lines(buf, 0, -1, false, { "first", "middle", "last" })
		local range_session = local_review.new_session(anchor_root, "HEAD")
		local_review.assign(vim.api.nvim_get_current_tabpage(), range_session, "HEAD")
		vim.t.dotfiles_differ_review = { root = anchor_root, mode = "HEAD", local_session_id = range_session.id }
		vim.fn.line = function(mark)
			return mark == "v" and 3 or 1
		end
		vim.api.nvim_feedkeys = function() end
		local_review.comment_range()
		captured.on_submit("Review the entire range")
		vim.fn.line, vim.api.nvim_feedkeys = original_line, original_feedkeys
		assert(notes(range_session)[1].source_context.range_text == "first\nmiddle\nlast")
		local range_output = vim.api.nvim_create_buf(false, true)
		vim.b[range_output].dotfiles_differ_review_output = range_session.path
		view.model.new_text = "first\nchanged middle\nlast\n"
		vim.api.nvim_buf_set_lines(buf, 1, 2, false, { "changed middle" })
		local_review.render(range_session, view)
		assert(notes(range_session)[1].anchor_status == "outdated")
		assert(decoded(range_session.path).comparisons.HEAD.notes[1].anchor_status == "outdated")
		local visible_document =
			vim.json.decode(table.concat(vim.api.nvim_buf_get_lines(range_output, 0, -1, false), "\n"))
		assert(visible_document.comparisons.HEAD.notes[1].anchor_status == "outdated")
		view.model.new_text = "first\nmiddle\nlast\n"
		vim.api.nvim_buf_set_lines(buf, 1, 2, false, { "middle" })
		local_review.render(range_session, view)
		assert(decoded(range_session.path).comparisons.HEAD.notes[1].anchor_status == "current")
		vim.api.nvim_buf_delete(range_output, { force = true })
		assert(sidecar_calls == 0)
	end, debug.traceback)

	differ.active_view, compose.open = original_active_view, original_compose_open
	sidecar.request, vim.ui.select = original_request, original_select
	vim.fn.confirm, vim.fn.line = original_confirm, original_line
	vim.api.nvim_feedkeys, vim.uv.fs_write = original_feedkeys, original_write
	vim.uv.fs_rename = original_rename
	vim.env.HOME = original_home
	vim.t.dotfiles_differ_review = nil
	if vim.api.nvim_buf_is_valid(buf) then
		vim.api.nvim_win_set_buf(win, original_buf)
		vim.api.nvim_buf_delete(buf, { force = true })
	end
	for _, path in ipairs(roots) do
		vim.fn.delete(path, "rf")
	end
	assert(ok, err)
	print("Differ local review: persistence, ownership, schema, and output isolation passed")
end

return M
