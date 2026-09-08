local M = {}

local Continuous = require("config.differ_continuous")

local function notify(message, level)
	vim.notify("Differ continuous review: " .. message, level or vim.log.levels.INFO)
end

local function each_bounded(items, limit, worker)
	local next_index, active = 1, 0
	local function pump()
		while active < limit and next_index <= #items do
			local item = items[next_index]
			next_index = next_index + 1
			active = active + 1
			worker(item, function()
				active = active - 1
				vim.schedule(pump)
			end)
		end
	end
	pump()
end

local function flatten(panel)
	local sections = {}
	for _, group in ipairs(panel.sections or {}) do
		for _, entry in ipairs(group.entries or {}) do
			sections[#sections + 1] = {
				entry = entry,
				key = (entry.staged and "staged\0" or "unstaged\0") .. entry.path,
				staged_hunks = {},
			}
		end
	end
	return sections
end

local function section_key(entry)
	return (entry.staged and "staged\0" or "unstaged\0") .. entry.path
end

local function reconcile_sections(previous, incoming)
	local exact, by_path, used = {}, {}, {}
	for _, section in ipairs(previous) do
		exact[section.key] = exact[section.key] or {}
		table.insert(exact[section.key], section)
		by_path[section.entry.path] = by_path[section.entry.path] or {}
		table.insert(by_path[section.entry.path], section)
	end
	local function take(candidates)
		for _, section in ipairs(candidates or {}) do
			if not used[section] then
				used[section] = true
				return section
			end
		end
	end
	local reconciled = {}
	for _, fresh in ipairs(incoming) do
		local key = section_key(fresh.entry)
		local section = take(exact[key]) or take(by_path[fresh.entry.path]) or fresh
		section.entry = fresh.entry
		section.key = key
		reconciled[#reconciled + 1] = section
	end
	return reconciled
end

local function same_model_content(left, right)
	return left
		and right
		and left.path == right.path
		and left.old_text == right.old_text
		and left.new_text == right.new_text
		and left.binary == right.binary
		and left.notice == right.notice
end

local function list(root, args, callback)
	require("differ.git").list_async(root, args, callback)
end

local function list_head(root, callback)
	list(root, {}, callback)
end

local function list_main(root, callback)
	list(root, { "main..." }, callback)
end

local function load_model(root, pair, section, _, callback)
	require("differ.git").model_async(pair, root, section.entry, callback)
end

local function current_hunk(view)
	local section = view:active_section()
	if not (section and section.model) then
		return
	end
	local row = vim.api.nvim_win_get_cursor(view.winid)[1]
	local item = view.columns[1].map.lines[row]
	return section, item and item.hunk
end

local function apply_patch(root, text, reverse, target)
	local ok, err = require("differ.git").apply_patch(root, text, reverse, target)
	if not ok then
		notify("Git apply failed: " .. tostring(err or ""), vim.log.levels.ERROR)
	end
	return ok
end

local function set_entry_staged(root, entry, staged)
	return require("differ.git").set_staged(root, entry, staged)
end

local function staging_handlers(root, panel, on_hunk_action)
	local patch = require("differ.git.patch")
	local git = require("differ.git")
	local function set_file_staged(entry, staged)
		local ok = set_entry_staged(root, entry, staged)
		if ok then
			panel:reload()
		end
		return ok
	end
	local function stage_offset(section, index)
		local offset = 0
		for previous = 1, index - 1 do
			if section.staged_hunks[previous] then
				local hunk = section.model.hunks[previous]
				offset = offset + hunk.new_count - hunk.old_count
			end
		end
		return offset
	end
	local function unstage_offset(section, index)
		local offset = 0
		for previous = 1, index - 1 do
			if not section.staged_hunks[previous] then
				local hunk = section.model.hunks[previous]
				offset = offset + hunk.old_count - hunk.new_count
			end
		end
		return offset
	end
	local function stage(view, want_staged, whole_file)
		local section = view:active_section()
		if not (section and section.model) then
			return notify("the current file is still loading", vim.log.levels.WARN)
		end
		if whole_file or section.entry.status ~= "M" or #section.model.hunks == 0 then
			if section.entry.staged == want_staged then
				return notify("file is already " .. (want_staged and "staged" or "unstaged"))
			end
			return set_file_staged(section.entry, want_staged)
		end
		local _, index = current_hunk(view)
		if not index then
			return notify("place the cursor on a hunk", vim.log.levels.WARN)
		end
		local is_staged = section.staged_hunks[index] == true
		if is_staged == want_staged then
			return notify("hunk is already " .. (want_staged and "staged" or "unstaged"))
		end
		local hunk, model = section.model.hunks[index], section.model
		local offset = stage_offset(section, index)
		local text = patch.hunk(model.path, hunk, model.old_text, model.new_text, offset, "old")
		if apply_patch(root, text, not want_staged, "index") and view:is_alive() then
			section.staged_hunks[index] = want_staged
			on_hunk_action({
				path = section.entry.path,
				staged = want_staged,
				index_line = hunk.old_start + offset,
				side = want_staged and "new" or "old",
				preferred_kind = want_staged and (hunk.new_count > 0 and "new" or "old")
					or (hunk.old_count > 0 and "old" or "new"),
			})
			panel.dotfiles_refresh()
			notify(want_staged and "hunk staged" or "hunk unstaged")
		end
	end
	local function discard(view)
		local section = view:active_section()
		if not (section and section.model) then
			return notify("the current file is still loading", vim.log.levels.WARN)
		end
		if section.entry.status ~= "M" or #section.model.hunks == 0 then
			local label = section.entry.previous_path
					and (section.entry.path .. " (restoring " .. section.entry.previous_path .. ")")
				or section.entry.path
			if vim.fn.confirm("Discard changes to " .. label .. "?", "&Yes\n&No", 2) ~= 1 then
				return
			end
			if git.discard(root, section.entry) then
				panel:reload()
			end
			return
		end
		local _, index = current_hunk(view)
		if not index then
			return notify("place the cursor on a hunk", vim.log.levels.WARN)
		end
		local model, hunk = section.model, section.model.hunks[index]
		if vim.fn.confirm(("Revert hunk %d in %s?"):format(index, model.path), "&Yes\n&No", 2) ~= 1 then
			return
		end
		local text = patch.hunk(
			model.path,
			hunk,
			model.old_text,
			model.new_text,
			section.entry.staged and unstage_offset(section, index) or 0,
			"new"
		)
		if section.entry.staged then
			-- A staged source can differ from the live file (including formatting).
			-- Verify the worktree patch before changing the index, so a known
			-- conflict does not turn a failed discard into an unintended unstage.
			local checked = vim
				.system({ "git", "apply", "--check", "--reverse", "--unidiff-zero", "--whitespace=nowarn", "-" }, {
					cwd = root,
					stdin = text,
					text = true,
				})
				:wait()
			if checked.code ~= 0 then
				return notify(
					"Cannot discard from the changed working file: " .. vim.trim(checked.stderr or ""),
					vim.log.levels.ERROR
				)
			end
			if apply_patch(root, text, true, "index") then
				if not apply_patch(root, text, true, "worktree") then
					notify(
						model.path .. ": reverted from the index; the worktree copy changed since and remains unstaged",
						vim.log.levels.WARN
					)
				end
				panel:reload()
			end
		elseif apply_patch(root, text, true, "worktree") then
			panel:reload()
		end
	end
	return stage, discard
end

local function create_view(panel, win, opts)
	if not (win and vim.api.nvim_win_is_valid(win)) then
		return
	end
	panel.dotfiles_base_on_close = panel.dotfiles_base_on_close or panel.on_close
	local base_close = panel.dotfiles_base_on_close
	local view
	view = Continuous.View.new({
		winid = win,
		root = opts.root,
		sections = opts.sections,
		compact = opts.compact,
		defer_filetype = opts.defer_filetype,
		on_section = opts.on_section,
		on_stage = opts.on_stage,
		on_discard = opts.on_discard,
		on_refresh = opts.on_refresh,
		on_set_source = opts.on_set_source,
		on_close = opts.on_view_close,
		extra_keymaps = opts.extra_keymaps,
	})
	view:open()
	panel.origin_win = win
	panel.on_select = function(entry)
		return view:jump_entry(entry)
	end
	panel.on_close = function()
		view:close()
		if base_close then
			base_close()
		end
	end
	return view
end

local function replace_view(panel, opts)
	local native = opts.native
	local column = native and native.columns and native.columns[1]
	local win = column and column.winid
	if not (win and vim.api.nvim_win_is_valid(win)) then
		return
	end
	native:close(win)
	return create_view(panel, win, opts)
end

local function local_review(panel, root, mode, compact, base)
	local sections = flatten(panel)
	local pending_hunk_action
	local stage, discard = staging_handlers(root, panel, function(action)
		pending_hunk_action = action
	end)
	local view_opts = {
		root = root,
		sections = sections,
		compact = compact,
		on_stage = mode == "HEAD" and stage or nil,
		on_discard = mode == "HEAD" and discard or nil,
		on_refresh = function()
			panel:reload()
		end,
	}
	local view = create_view(panel, panel.origin_win, view_opts)
	if not view then
		return
	end
	panel.dotfiles_continuous_view = view
	local function restore_hunk_action(section)
		local action = pending_hunk_action
		if
			not action
			or section.entry.path ~= action.path
			or section.entry.staged ~= action.staged
			or not section.model
		then
			return
		end
		local best, best_distance
		for index, hunk in ipairs(section.model.hunks) do
			local start = action.side == "new" and hunk.new_start or hunk.old_start
			local count = action.side == "new" and hunk.new_count or hunk.old_count
			local first = count > 0 and start or start + 1
			local last = first + math.max(count, 1) - 1
			local distance = action.index_line < first and (first - action.index_line)
				or (action.index_line > last and (action.index_line - last) or 0)
			if not best_distance or distance < best_distance then
				best, best_distance = index, distance
			end
			if distance == 0 then
				break
			end
		end
		if best and view:focus_section_hunk(section, best, action.preferred_kind) then
			pending_hunk_action = nil
		end
	end
	view.on_rerender = function(changed_section)
		if changed_section then
			restore_hunk_action(changed_section)
		end
	end
	local function comparison_pair(source)
		return mode == "main" and source or nil
	end
	local load_generation = 0
	local function pair_for(section, pair)
		if mode ~= "HEAD" then
			return pair
		end
		return section.entry.staged
				and {
					old = { kind = "rev", rev = "HEAD", label = "HEAD" },
					new = { kind = "index", label = "INDEX" },
				}
			or { old = { kind = "index", label = "INDEX" }, new = { kind = "worktree", label = "WORKTREE" } }
	end
	local function load(pair)
		load_generation = load_generation + 1
		local generation = load_generation
		local loading_sections = vim.list_slice(sections)
		for _, section in ipairs(loading_sections) do
			section.render_generation = (section.render_generation or 0) + 1
		end
		each_bounded(loading_sections, 64, function(section, done)
			if generation ~= load_generation or not view:is_alive() or not view:has_section(section) then
				return done()
			end
			local previous_model = section.model
			load_model(root, pair_for(section, pair), section, nil, function(model, err)
				if generation ~= load_generation or not view:is_alive() or not view:has_section(section) then
					return done()
				end
				if model then
					section.staged_hunks = {}
					local additions, deletions = 0, 0
					for index, hunk in ipairs(model.hunks) do
						section.staged_hunks[index] = section.entry.staged == true
						additions = additions + hunk.new_count
						deletions = deletions + hunk.old_count
					end
					section.entry.additions, section.entry.deletions = additions, deletions
					section.additions, section.deletions = additions, deletions
					if same_model_content(previous_model, model) and section.map and section.lines then
						section.model = model
						view:update_section_metadata(section)
						restore_hunk_action(section)
					else
						view:set_model(section, model)
					end
				else
					view:set_error(section, err)
					notify(err, vim.log.levels.ERROR)
				end
				done()
			end)
		end)
	end

	local function refresh_sections(merge_base)
		if not view:is_alive() then
			return
		end
		local anchor = view:snapshot_logical_position()
		local previous = sections
		local reconciled = reconcile_sections(previous, flatten(panel))
		local structural_change = #previous ~= #reconciled
		if not structural_change then
			for index, section in ipairs(reconciled) do
				if previous[index] ~= section then
					structural_change = true
					break
				end
			end
		end
		sections = reconciled
		view.sections = sections
		if structural_change then
			view:render()
			view:restore_logical_position(anchor)
		end
		load(comparison_pair(merge_base))
	end
	panel.dotfiles_sections_changed = refresh_sections
	load(comparison_pair(base))
	return view
end

function M.open_local(opts, callback)
	local root, mode = opts.root, opts.mode
	local list = mode == "main" and list_main or list_head
	list(root, function(sections, err, base)
		if opts.valid and not opts.valid() then
			return callback()
		end
		if not sections then
			notify(err or "unable to list changes", vim.log.levels.ERROR)
			return callback()
		end
		local total = 0
		for _, section in ipairs(sections) do
			total = total + #section.entries
		end
		if total == 0 then
			notify("no changes for this source")
			return callback()
		end

		local tab = require("differ.util.tab")
		local return_tab, session_tab = tab.open_session()
		local panel
		local listing_generation = 0
		local function refresh()
			listing_generation = listing_generation + 1
			local generation = listing_generation
			list(root, function(updated, refresh_err, refreshed_base)
				if generation ~= listing_generation or not (panel and panel:is_alive()) then
					return
				end
				if not updated then
					return notify(refresh_err or "unable to refresh changes", vim.log.levels.ERROR)
				end
				local count = 0
				for _, section in ipairs(updated) do
					count = count + #section.entries
				end
				if count == 0 then
					notify("no changes left")
					return panel:close()
				end
				base = refreshed_base or base
				panel:set_sections(updated)
				if panel.dotfiles_sections_changed then
					panel.dotfiles_sections_changed(base)
				end
			end)
		end
		local actions
		if mode == "HEAD" then
			local git = require("differ.git")
			actions = {
				stage = function(entry)
					return set_entry_staged(root, entry, true)
				end,
				unstage = function(entry)
					return set_entry_staged(root, entry, false)
				end,
				stage_all = function()
					git.stage_all(root)
				end,
				unstage_all = function()
					git.unstage_all(root)
				end,
				discard = function(entry)
					git.discard(root, entry)
				end,
				reload = function()
					return panel.sections
				end,
			}
		end

		local config = require("differ").get_config()
		local panel_config = config.panel or {}
		panel = require("differ.panel")
			.new({
				sections = sections,
				root = vim.fn.fnamemodify(root, ":~"),
				footer = mode == "main" and "main..." or "HEAD",
				actions = actions,
				on_external_change = refresh,
				on_staged = function()
					refresh()
				end,
				on_select = function()
					return true
				end,
				on_close = function()
					tab.close_session(session_tab)
				end,
				keymaps = config.keymaps.panel,
				listing = panel_config.listing,
				position = panel_config.position,
				height = panel_config.height,
				width = panel_config.width,
				icons = false,
				progress = panel_config.progress,
			})
			:open()
		panel.dotfiles_refresh = refresh
		panel.return_tab = return_tab
		local view = local_review(panel, root, mode, opts.compact, base)
		if not view then
			panel:close()
			return callback()
		end
		panel:focus_first_unstaged()
		panel:select(true)
		callback(panel, view)
	end)
end

function M.adopt_pr(session)
	if not (session and session.panel and session.view) then
		return
	end
	if session.dotfiles_continuous_view then
		if session.dotfiles_continuous_view:is_alive() then
			return session.dotfiles_continuous_view
		end
		session.dotfiles_continuous_view = nil
	end
	local native = session.view
	if native.dotfiles_continuous then
		return
	end
	local panel = session.panel
	panel.dotfiles_native_on_select = panel.dotfiles_native_on_select or panel.on_select
	local native_select = panel.dotfiles_native_on_select
	local sections = {}
	for _, entry in ipairs(session.entries or {}) do
		sections[#sections + 1] = { entry = entry, key = entry.path, staged_hunks = {} }
	end
	local config = require("differ").get_config()
	local function same_spec(left, right)
		return vim.deep_equal(left, right)
	end
	local extra_keymaps = {}
	for _, mapping in ipairs(session.diff_extra_keymaps or {}) do
		-- Native PR editing calls View:edit_beside/edit_tab. The continuous view
		-- deliberately owns source navigation through gf/t instead.
		if
			not same_spec(mapping.spec, config.keymaps.diff.edit_file)
			and not same_spec(mapping.spec, config.keymaps.diff.goto_file)
		then
			extra_keymaps[#extra_keymaps + 1] = mapping
		end
	end
	local refresh_pr
	local view
	view = replace_view(session.panel, {
		native = native,
		root = session.root,
		sections = sections,
		defer_filetype = true,
		extra_keymaps = extra_keymaps,
		on_set_source = function(model)
			if refresh_pr then
				refresh_pr(model)
			end
		end,
		on_view_close = function(closed)
			if session.dotfiles_continuous_view == closed then
				session.dotfiles_continuous_view = nil
			end
			if session.view == closed then
				session.view = nil
			end
			if panel:is_alive() then
				panel.on_select = native_select
			end
		end,
	})
	if not view then
		return
	end
	view.dotfiles_continuous = true
	session.view = view
	session.dotfiles_continuous_view = view
	local function apply_pending_focus(section)
		local focus = session.pending_focus
		if not (focus and section and section.map and focus.path == section.entry.path) then
			return
		end
		local index = focus.side == "LEFT" and section.map.from_old or section.map.from_new
		local local_row = index and require("differ.pr.threads").anchor_row(index, focus.line)
		if local_row and view:is_open() then
			session.pending_focus = nil
			vim.api.nvim_win_set_cursor(view.winid, { section.body_first + local_row - 1, 0 })
			view:_activate(section)
		end
	end
	local overlay_scheduled, changed_for_focus = false, {}
	view.on_rerender = function(changed_section)
		if changed_section then
			changed_for_focus[changed_section] = true
		end
		if overlay_scheduled then
			return
		end
		overlay_scheduled = true
		vim.defer_fn(function()
			overlay_scheduled = false
			if session.view ~= view or not view:is_alive() then
				return
			end
			require("differ.pr.threads").apply(session)
			for section in pairs(changed_for_focus) do
				apply_pending_focus(section)
			end
			changed_for_focus = {}
		end, 16)
	end
	session.panel.on_select = function(entry)
		local landed = view:jump_entry(entry)
		apply_pending_focus(view:active_section())
		return landed
	end
	local generation = 0
	refresh_pr = function(incoming_model)
		generation = generation + 1
		local current_generation = generation
		local refs = { base = session.pr_meta.base_sha, head = session.pr_meta.head_sha }
		local function current()
			return session.view == view
				and session.dotfiles_continuous_view == view
				and view:is_alive()
				and current_generation == generation
				and refs.base == session.pr_meta.base_sha
				and refs.head == session.pr_meta.head_sha
		end
		for _, section in ipairs(sections) do
			section.render_generation = (section.render_generation or 0) + 1
		end
		if incoming_model then
			local section = view:section_for_path(incoming_model.path)
			if section then
				view:set_model(section, incoming_model)
				view:jump_section(section)
			end
		end
		each_bounded(sections, 6, function(section, done)
			if not current() then
				return done()
			end
			require("differ.pr").load_model(session, section.entry, function(model, err)
				if not current() then
					return done()
				end
				if not model then
					if err ~= "stale PR source" then
						require("differ.pr").notify_err(err)
					end
					return done()
				end
				view:set_model(section, model)
				done()
			end)
		end)
	end
	refresh_pr()
	require("differ.pr.threads").refresh(session)
	return view
end

return M
