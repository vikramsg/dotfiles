local M = {}

local render = require("differ.render")
local LineMap = require("differ.render.linemap")
local paint = require("differ.ui.paint")
local statuscolumn = require("differ.ui.statuscolumn")

local diff_namespace = vim.api.nvim_create_namespace("dotfiles.differ.continuous.diff")
local header_namespace = vim.api.nvim_create_namespace("dotfiles.differ.continuous.header")
local views = {}
local sequence = 0
local render_module = debug.getinfo(render.render, "S").source:sub(2)
local plugin_lua = vim.fs.dirname(vim.fs.dirname(vim.fs.dirname(render_module)))
local worker_package_path = plugin_lua .. "/?.lua;" .. plugin_lua .. "/?/init.lua"

local function notify(message, level)
	vim.notify("Differ continuous review: " .. message, level or vim.log.levels.INFO)
end

local function section_counts(section)
	local entry = section.entry or {}
	return entry.additions or 0, entry.deletions or 0
end

local function section_state(section)
	if section.entry.staged == nil then
		return ""
	end
	return (section.entry.staged and "STAGED" or (section.entry.status == "?" and "UNTRACKED" or "UNSTAGED")) .. " · "
end

local function section_at(view, row)
	local candidate
	for _, section in ipairs(view.sections) do
		if section.first and section.first <= row then
			candidate = section
		else
			break
		end
	end
	return candidate
end

local View = {}
View.__index = View

function View:_line_at(row)
	local section = section_at(self, row)
	if not section or row == section.first or row > section.last then
		return { kind = "meta" }
	end
	return (section.map and section.map.lines[row - section.body_first + 1]) or { kind = "meta" }
end

function View.current()
	return views[vim.api.nvim_get_current_buf()]
end

function View.new(opts)
	sequence = sequence + 1
	local buf = vim.api.nvim_create_buf(false, true)
	vim.bo[buf].buftype = "nofile"
	-- Side-by-side inspection temporarily swaps this buffer out of its window.
	-- Keep it loaded until View:close() explicitly owns its teardown.
	vim.bo[buf].bufhidden = "hide"
	vim.bo[buf].swapfile = false
	vim.bo[buf].modifiable = false
	vim.api.nvim_buf_set_name(buf, "differ://continuous/" .. sequence)
	local self = setmetatable({
		bufnr = buf,
		winid = opts.winid,
		root = opts.root,
		sections = opts.sections,
		context = opts.context or 3,
		compact = opts.compact ~= false,
		defer_filetype = opts.defer_filetype == true,
		deep_diff = require("differ").get_config().deep_diff,
		layout = "stacked",
		on_section = opts.on_section,
		on_close = opts.on_close,
		on_stage = opts.on_stage,
		on_discard = opts.on_discard,
		on_refresh = opts.on_refresh,
		on_set_source = opts.on_set_source,
		extra_keymaps = opts.extra_keymaps,
		id = sequence,
	}, View)
	for index, section in ipairs(self.sections) do
		section.index = index
	end
	local map = { lines = {}, from_old = {}, from_new = {} }
	map.lines = setmetatable({}, {
		__index = function(_, row)
			return self:_line_at(row)
		end,
	})
	self.columns = { { bufnr = buf, winid = opts.winid, side = "unified", map = map } }
	views[buf] = self
	return self
end

function View:is_open()
	if self:is_continuous_visible() then
		return true
	end
	for _, inspected in pairs(self.inspection or {}) do
		if inspected.win and vim.api.nvim_win_is_valid(inspected.win) then
			return true
		end
	end
	return false
end

function View:is_continuous_visible()
	return self.winid and vim.api.nvim_win_is_valid(self.winid) and vim.api.nvim_win_get_buf(self.winid) == self.bufnr
end

function View:is_alive()
	return vim.api.nvim_buf_is_valid(self.bufnr)
end

function View:active_section()
	if self.layout == "split" or not self:is_continuous_visible() then
		return self.active or self.sections[1]
	end
	return section_at(self, vim.api.nvim_win_get_cursor(self.winid)[1]) or self.sections[1]
end

function View:_activate(section)
	if not section or (self.active == section and self.model == section.model) then
		return
	end
	self.active = section
	self.model = section.model
	local column = self.columns[1]
	column.map.from_old, column.map.from_new = {}, {}
	if section.map then
		for line, row in pairs(section.map.from_old) do
			column.map.from_old[line] = section.body_first + row - 1
		end
		for line, row in pairs(section.map.from_new) do
			column.map.from_new[line] = section.body_first + row - 1
		end
	end
	if self.on_section then
		self.on_section(section, self)
	end
	vim.cmd("redrawstatus")
end

function View:column_for(side)
	if self.layout ~= "split" then
		self:_activate(self:active_section())
	end
	for _, column in ipairs(self.columns) do
		if column.side == side or column.side == "unified" then
			return column
		end
	end
end

function View:section_for_path(path)
	for _, section in ipairs(self.sections) do
		if section.entry.path == path then
			return section
		end
	end
end

function View:each_section(callback)
	for _, section in ipairs(self.sections) do
		if section.model and section.map then
			callback(section)
		end
	end
end

-- Keep source coordinates local to a file, projecting only reverse lookups into
-- the shared buffer. Both local notes and GitHub threads use this view of a file.
function View:project_section(section)
	local function shifted(index)
		return setmetatable({}, {
			__index = function(_, line)
				local row = index[line]
				return row and section.body_first + row - 1
			end,
		})
	end
	local parent = self.columns[1]
	local column = {
		bufnr = parent.bufnr,
		winid = parent.winid,
		side = "unified",
		map = {
			lines = parent.map.lines,
			from_old = shifted(section.map.from_old),
			from_new = shifted(section.map.from_new),
		},
	}
	return {
		section = section,
		model = section.model,
		layout = "stacked",
		columns = { column },
		column_for = function()
			return column
		end,
	}
end

function View:has_section(target)
	for _, section in ipairs(self.sections) do
		if section == target then
			return true
		end
	end
	return false
end

function View:snapshot_logical_position()
	local section, line, col = self:source_position()
	if not section then
		return
	end
	return {
		path = section.entry.path,
		staged = section.entry.staged,
		key = section.key,
		index = section.index,
		line = line,
		col = col,
	}
end

function View:restore_logical_position(anchor)
	if not anchor then
		return
	end
	if not self:is_continuous_visible() then
		self.pending_logical_position = anchor
		return
	end
	local target
	for _, section in ipairs(self.sections) do
		if section.entry.path == anchor.path and section.entry.staged == anchor.staged then
			target = section
			break
		end
	end
	if not target then
		for _, section in ipairs(self.sections) do
			if section.entry.path == anchor.path then
				target = section
				break
			end
		end
	end
	target = target or self.sections[math.min(anchor.index or 1, #self.sections)]
	if not target then
		return
	end
	local row = target.first
	if anchor.line and target.map then
		row = target.map.from_new[anchor.line] and (target.body_first + target.map.from_new[anchor.line] - 1) or row
	end
	vim.api.nvim_win_set_cursor(self.winid, { row, anchor.col or 0 })
	self:_activate(target)
end

function View:update_section_metadata(section)
	if not self:has_section(section) then
		return
	end
	section.additions, section.deletions = section_counts(section)
	self:_paint_header(section)
	if self.active == section then
		self.model = section.model
	end
end

function View:focus_section_hunk(section, hunk_index, preferred_kind)
	if not (self:is_continuous_visible() and section and section.map) then
		return false
	end
	local fallback
	for local_row, item in ipairs(section.map.lines) do
		if item.hunk == hunk_index and (item.kind == "old" or item.kind == "new") then
			fallback = fallback or local_row
			if item.kind == preferred_kind then
				local row = section.body_first + local_row - 1
				vim.api.nvim_win_set_cursor(self.winid, { row, 0 })
				self:_activate(section)
				return true
			end
		end
	end
	if fallback then
		vim.api.nvim_win_set_cursor(self.winid, { section.body_first + fallback - 1, 0 })
		self:_activate(section)
		return true
	end
	return false
end

function View:_snapshot()
	local section = self:active_section()
	local row, col = unpack(vim.api.nvim_win_get_cursor(self.winid))
	local offset = section and section.first and row - section.first or 0
	return section and section.key, offset, col
end

function View:_restore(key, offset, col)
	for _, section in ipairs(self.sections) do
		if section.key == key and section.first then
			local row = math.min(section.last, section.first + offset)
			pcall(vim.api.nvim_win_set_cursor, self.winid, { row, col })
			return
		end
	end
end

function View:_paint_header(section)
	local row = section.first - 1
	vim.api.nvim_buf_clear_namespace(self.bufnr, header_namespace, row, row + 1)
	vim.api.nvim_buf_set_extmark(self.bufnr, header_namespace, row, 0, {
		end_row = row + 1,
		end_col = 0,
		hl_group = "DotfilesDifferFileHeader",
		hl_eol = true,
		priority = 250,
	})
	vim.api.nvim_buf_set_extmark(self.bufnr, header_namespace, row, 1, {
		end_col = 1 + #section.entry.path,
		hl_group = "DotfilesDifferFilePath",
		priority = 260,
		virt_text = {
			{
				string.format("  %s+%d -%d ", section_state(section), section.additions, section.deletions),
				"DotfilesDifferFileCount",
			},
		},
		virt_text_pos = "eol",
	})
end

function View:_paint_line(section, index)
	local item = section.map.lines[index]
	local row = section.body_first + index - 2
	local line_hl = item.kind == "old" and "differLineDelete" or (item.kind == "new" and "differLineAdd" or nil)
	if line_hl then
		vim.api.nvim_buf_set_extmark(self.bufnr, diff_namespace, row, 0, {
			end_row = row + 1,
			end_col = 0,
			hl_group = line_hl,
			hl_eol = true,
			priority = 100,
		})
	end
	local word_hl = item.kind == "old" and "differWordDelete" or (item.kind == "new" and "differWordAdd" or nil)
	if word_hl then
		for _, span in ipairs(item.spans or {}) do
			vim.api.nvim_buf_set_extmark(self.bufnr, diff_namespace, row, span.col_start, {
				end_col = span.col_end,
				hl_group = word_hl,
				priority = 200,
			})
		end
	end
end

function View:_paint_section(section)
	if not section.map then
		return
	end
	local first, last = section.body_first - 1, section.last
	vim.api.nvim_buf_clear_namespace(self.bufnr, diff_namespace, first, last)
	for index = 1, #section.map.lines do
		self:_paint_line(section, index)
	end
end

function View:_paint_section_bounded(section, on_done)
	if not section.map then
		return on_done()
	end
	section.paint_generation = (section.paint_generation or 0) + 1
	local generation, index = section.paint_generation, 1
	local function paint_batch()
		if not self:is_alive() or not self:has_section(section) or section.paint_generation ~= generation then
			return
		end
		local started = (vim.uv or vim.loop).hrtime()
		repeat
			self:_paint_line(section, index)
			index = index + 1
		until index > #section.map.lines or ((vim.uv or vim.loop).hrtime() - started) / 1e6 >= 8
		if index <= #section.map.lines then
			vim.defer_fn(paint_batch, 1)
		else
			on_done()
		end
	end
	vim.defer_fn(paint_batch, 1)
end

function View:_paint_sections_bounded(sections, on_done)
	local section_index, line_index = 1, 1
	local function paint_batch()
		if not self:is_alive() then
			return
		end
		local started = (vim.uv or vim.loop).hrtime()
		repeat
			local section = sections[section_index]
			if not section then
				return on_done()
			end
			if section.map and line_index <= #section.map.lines then
				self:_paint_line(section, line_index)
				line_index = line_index + 1
			else
				section_index, line_index = section_index + 1, 1
			end
		until ((vim.uv or vim.loop).hrtime() - started) / 1e6 >= 8
		vim.defer_fn(paint_batch, 1)
	end
	vim.defer_fn(paint_batch, 1)
end

function View:render()
	if not vim.api.nvim_buf_is_valid(self.bufnr) then
		return
	end
	local key, offset, col
	if self:is_continuous_visible() then
		key, offset, col = self:_snapshot()
	end
	local lines = {}
	for section_index, section in ipairs(self.sections) do
		section.index = section_index
		local add, del = section_counts(section)
		section.first = #lines + 1
		lines[#lines + 1] = string.format(" %s", section.entry.path)
		section.body_first = #lines + 1
		local output
		if section.lines then
			vim.list_extend(lines, section.lines)
		elseif section.model then
			output = render.render(section.model, {
				layout = "stacked",
				context = self.context,
				deep_diff = self.deep_diff,
			}).columns[1]
			section.map = output.map
			section.folds = output.folds
			section.lines = output.lines
			vim.list_extend(lines, section.lines)
		else
			section.lines = { section.error and ("  Error: " .. section.error) or "  Loading diff…" }
			vim.list_extend(lines, section.lines)
		end
		section.last = #lines
		section.additions, section.deletions = add, del
		lines[#lines + 1] = ""
	end

	vim.bo[self.bufnr].modifiable = true
	vim.api.nvim_buf_set_lines(self.bufnr, 0, -1, false, lines)
	vim.bo[self.bufnr].modifiable = false
	vim.api.nvim_buf_clear_namespace(self.bufnr, diff_namespace, 0, -1)
	vim.api.nvim_buf_clear_namespace(self.bufnr, header_namespace, 0, -1)
	local paintable, paint_lines = {}, 0
	for _, section in ipairs(self.sections) do
		if section.model then
			self:_paint_header(section)
		end
		if section.map then
			paintable[#paintable + 1] = section
			paint_lines = paint_lines + #section.map.lines
		end
	end
	self:_apply_folds()
	if key then
		self:_restore(key, offset, col)
	end
	self:_activate(self:active_section())
	local function rendered()
		if self.on_rerender then
			self.on_rerender()
		end
	end
	if paint_lines >= 5000 then
		self:_paint_sections_bounded(paintable, rendered)
	else
		for _, section in ipairs(paintable) do
			self:_paint_section(section)
		end
		rendered()
	end
end

function View:set_error(section, message)
	if not (self:is_alive() and section.body_first) then
		return
	end
	section.error = message
	vim.bo[self.bufnr].modifiable = true
	vim.api.nvim_buf_set_lines(self.bufnr, section.body_first - 1, section.body_first, false, { "  Error: " .. message })
	vim.bo[self.bufnr].modifiable = false
end

function View:_apply_folds()
	if not self:is_continuous_visible() then
		return
	end
	vim.api.nvim_win_call(self.winid, function()
		vim.wo.foldmethod = "manual"
		vim.cmd("silent! normal! zE")
		for _, section in ipairs(self.sections) do
			if section.map and section.model then
				for _, fold in ipairs(section.folds or {}) do
					local first = section.body_first + fold.first - 1
					local last = section.body_first + fold.last - 1
					if last > first then
						vim.cmd(("silent! %d,%dfold"):format(first, last))
					end
				end
			end
		end
		vim.cmd(self.compact and "silent! normal! zM" or "silent! normal! zR")
	end)
end

function View:_apply_section_folds(section)
	if not self:is_continuous_visible() then
		return
	end
	vim.api.nvim_win_call(self.winid, function()
		vim.wo.foldmethod = "manual"
		for _, fold in ipairs(section.folds or {}) do
			local first = section.body_first + fold.first - 1
			local last = section.body_first + fold.last - 1
			if last > first then
				vim.cmd(("silent! %d,%dfold"):format(first, last))
				if not self.compact then
					vim.cmd(("silent! %dfoldopen"):format(first))
				end
			end
		end
	end)
end

function View:set_model(section, model)
	if not self:is_alive() then
		return
	end
	section.model = model
	section.render_generation = (section.render_generation or 0) + 1
	local generation = section.render_generation
	local function ready(output, err)
		if not self:is_alive() or section.render_generation ~= generation then
			return
		end
		if not output then
			return self:set_error(section, err or "diff rendering failed")
		end
		section.output = output.columns[1]
		self:_queue_section(section)
	end
	local rows = 0
	for _, hunk in ipairs(model.hunks or {}) do
		rows = rows + hunk.old_count + hunk.new_count
	end
	-- Full-context rows also cost work, even when a large file has one small hunk.
	if rows >= 5000 or #model.old_text + #model.new_text >= 256 * 1024 then
		local payload = vim.mpack.encode({
			model = model,
			opts = { layout = "stacked", context = self.context, deep_diff = self.deep_diff },
		})
		local work
		work = (vim.uv or vim.loop).new_work(function(encoded, lua_path)
			package.path = lua_path
			local ok, result = pcall(function()
				local input = vim.mpack.decode(encoded)
				local output = require("differ.render").render(input.model, input.opts)
				local column = output.columns[1]
				local records, spans = {}, {}
				local codes = { context = "c", old = "o", new = "n", meta = "m" }
				for index, item in ipairs(column.map.lines) do
					records[index] = table.concat({
						codes[item.kind],
						tostring(item.old or 0),
						tostring(item.new or 0),
						tostring(item.hunk or 0),
					}, ",")
					if item.spans then
						spans[index] = item.spans
					end
				end
				return {
					lines = table.concat(column.lines, "\0"),
					map = table.concat(records, "\n"),
					spans = spans,
					folds = column.folds,
				}
			end)
			return vim.mpack.encode({ ok = ok, result = result })
		end, function(encoded)
			vim.schedule(function()
				section.render_work = nil
				local result = vim.mpack.decode(encoded)
				if not result.ok then
					return ready(nil, tostring(result.result))
				end
				local raw, map, lines = result.result, LineMap.new(), {}
				local line_offset, map_offset, index = 1, 1, 1
				local kinds = { c = "context", o = "old", n = "new", m = "meta" }
				local function build_map()
					if not self:is_alive() or section.render_generation ~= generation then
						return
					end
					local started = (vim.uv or vim.loop).hrtime()
					repeat
						local line_end = raw.lines:find("\0", line_offset, true)
						if line_end then
							lines[index] = raw.lines:sub(line_offset, line_end - 1)
							line_offset = line_end + 1
						else
							lines[index] = raw.lines:sub(line_offset)
							line_offset = #raw.lines + 1
						end
						local map_end = raw.map:find("\n", map_offset, true)
						local record = raw.map:sub(map_offset, map_end and map_end - 1 or -1)
						map_offset = map_end and map_end + 1 or (#raw.map + 1)
						local kind, old, new, hunk = record:match("^(%a),(%d+),(%d+),(%d+)$")
						map:push({
							kind = kinds[kind],
							old = tonumber(old) ~= 0 and tonumber(old) or nil,
							new = tonumber(new) ~= 0 and tonumber(new) or nil,
							hunk = tonumber(hunk) ~= 0 and tonumber(hunk) or nil,
							spans = raw.spans[index],
						})
						index = index + 1
					until map_offset > #raw.map or ((vim.uv or vim.loop).hrtime() - started) / 1e6 >= 8
					if map_offset <= #raw.map then
						vim.defer_fn(build_map, 1)
					else
						ready({ columns = { { lines = lines, map = map, folds = raw.folds } } })
					end
				end
				build_map()
			end)
		end)
		section.render_work = work
		work:queue(payload, worker_package_path)
		return
	end
	ready(render.render(model, {
		layout = "stacked",
		context = self.context,
		deep_diff = self.deep_diff,
	}))
end

function View:_queue_section(section)
	section.queued_render_generation = section.render_generation
	self.pending_sections = self.pending_sections or {}
	if not self.pending_sections[section] then
		self.pending_sections[section] = true
		self.render_queue = self.render_queue or {}
		self.render_queue[#self.render_queue + 1] = section
	end
	if self.render_scheduled then
		return
	end
	local function flush_batch()
		self.render_scheduled = false
		if not self:is_alive() then
			return
		end
		local batch = {}
		local started = (vim.uv or vim.loop).hrtime()
		repeat
			local next_section = table.remove(self.render_queue, 1)
			if not next_section then
				break
			end
			self.pending_sections[next_section] = nil
			if self:has_section(next_section) and next_section.queued_render_generation == next_section.render_generation then
				batch[#batch + 1] = next_section
			end
		until #batch >= 4 or ((vim.uv or vim.loop).hrtime() - started) / 1e6 >= 8
		table.sort(batch, function(left, right)
			return left.index < right.index
		end)
		local run = {}
		for _, section in ipairs(batch) do
			if #run > 0 and section.index ~= run[#run].index + 1 then
				self:_update_run(run)
				run = {}
			end
			run[#run + 1] = section
		end
		if #run > 0 then
			self:_update_run(run)
		end
		if #self.render_queue > 0 then
			self.render_scheduled = true
			vim.defer_fn(flush_batch, 1)
		end
	end
	self.render_scheduled = true
	vim.defer_fn(flush_batch, 2)
end

function View:_update_run(changed)
	local first_changed, last_changed = changed[1], changed[#changed]
	if not (first_changed and first_changed.model and first_changed.body_first and last_changed.last) then
		return self:render()
	end
	local visible = self:is_continuous_visible()
	local key, offset, col
	if visible then
		key, offset, col = self:_snapshot()
	end
	local old_start, old_end = first_changed.body_first - 1, last_changed.last
	for _, section in ipairs(changed) do
		local output = section.output
		if not output then
			return
		end
		section.map, section.folds, section.lines = output.map, output.folds, output.lines
		section.output = nil
	end
	local replacement = {}
	for index = first_changed.index, last_changed.index do
		local section = self.sections[index]
		if index > first_changed.index then
			replacement[#replacement + 1] = ""
			replacement[#replacement + 1] = " " .. section.entry.path
		end
		vim.list_extend(replacement, section.lines)
	end
	vim.api.nvim_buf_clear_namespace(self.bufnr, diff_namespace, old_start, old_end)
	vim.bo[self.bufnr].modifiable = true
	vim.api.nvim_buf_set_lines(self.bufnr, old_start, old_end, false, replacement)
	vim.bo[self.bufnr].modifiable = false
	if self.defer_filetype and vim.bo[self.bufnr].filetype ~= "differdiff" then
		self.defer_filetype = false
		vim.bo[self.bufnr].filetype = "differdiff"
	end
	local row = 1
	for _, section in ipairs(self.sections) do
		section.first = row
		section.body_first = row + 1
		section.last = section.body_first + #section.lines - 1
		row = section.last + 2
	end
	for _, section in ipairs(changed) do
		self:_paint_header(section)
		if visible then
			self:_apply_section_folds(section)
		end
	end
	if visible then
		self:_restore(key, offset, col)
		self:_activate(self:active_section())
	end
	for _, section in ipairs(changed) do
		self:_paint_section_bounded(section, function()
			if self.on_rerender then
				self.on_rerender(section)
			end
		end)
	end
end

function View:set_source(model)
	if self.on_set_source then
		return self.on_set_source(model)
	end
	return self:jump_path(model.path)
end

function View:jump_path(path)
	local section = self:section_for_path(path)
	return self:jump_section(section)
end

function View:jump_entry(entry)
	for _, section in ipairs(self.sections) do
		if section.entry == entry then
			return self:jump_section(section)
		end
	end
	for _, section in ipairs(self.sections) do
		if section.entry.path == entry.path and section.entry.staged == entry.staged then
			return self:jump_section(section)
		end
	end
	return self:jump_path(entry.path)
end

function View:jump_section(section)
	if not (section and section.first and self:is_continuous_visible()) then
		return false
	end
	vim.api.nvim_set_current_win(self.winid)
	vim.api.nvim_win_set_cursor(self.winid, { section.first, 0 })
	self:_activate(section)
	return true
end

function View:jump_file(direction)
	local active = self:active_section()
	local index = 1
	for candidate, section in ipairs(self.sections) do
		if section == active then
			index = candidate
			break
		end
	end
	index = direction == "next" and index + 1 or index - 1
	if index < 1 or index > #self.sections then
		return notify(direction == "next" and "no next file" or "no previous file")
	end
	self:jump_section(self.sections[index])
end

function View:jump_hunk(direction)
	local row = vim.api.nvim_win_get_cursor(self.winid)[1]
	local step = direction == "next" and 1 or -1
	local edge = direction == "next" and vim.api.nvim_buf_line_count(self.bufnr) or 1
	for i = row + step, edge, step do
		local item = self:_line_at(i)
		local before = self:_line_at(i - 1)
		if item and item.hunk and (not before or before.hunk ~= item.hunk) then
			vim.api.nvim_win_set_cursor(self.winid, { i, 0 })
			return
		end
	end
	return notify(direction == "next" and "no next hunk" or "no previous hunk")
end

function View:toggle_context()
	local key, offset, col
	if self:is_continuous_visible() then
		key, offset, col = self:_snapshot()
	end
	self.compact = not self.compact
	local tab = vim.api.nvim_win_get_tabpage(self.winid)
	vim.t[tab].dotfiles_differ_compact = self.compact
	-- Context toggles only open/close the existing folds; rebuilding every file's
	-- fold definitions here makes a changeset-wide toggle needlessly expensive.
	for _, column in ipairs(self.columns) do
		vim.api.nvim_win_call(column.winid, function()
			vim.cmd(self.compact and "silent! normal! zM" or "silent! normal! zR")
		end)
	end
	if key then
		self:_restore(key, offset, col)
	end
end

function View:_apply_inspection_folds()
	for _, inspected in pairs(self.inspection or {}) do
		local win = inspected.win
		if win and vim.api.nvim_win_is_valid(win) then
			vim.api.nvim_win_call(win, function()
				vim.wo.foldmethod = "manual"
				vim.cmd("silent! normal! zE")
				for _, fold in ipairs(inspected.column.folds or {}) do
					if fold.last > fold.first then
						vim.cmd(("silent! %d,%dfold"):format(fold.first, fold.last))
					end
				end
				vim.cmd(self.compact and "silent! normal! zM" or "silent! normal! zR")
			end)
		end
	end
end

function View:source_position()
	local inspected = self.inspection and self.inspection[vim.api.nvim_get_current_buf()]
	if not inspected and self.layout == "split" then
		for _, candidate in pairs(self.inspection or {}) do
			if candidate.column.side == "new" then
				inspected = candidate
				break
			end
			inspected = inspected or candidate
		end
	end
	if inspected then
		local row, col = unpack(vim.api.nvim_win_get_cursor(inspected.win))
		local target_map = inspected.column.side == "old" and inspected.new_column.map or inspected.column.map
		local line = require("differ.nav").file_line(target_map, row)
		local item = inspected.column.map.lines[row]
		return inspected.section, line, item and item.new == line and col or 0
	end
	local section = self:active_section()
	if not (section and section.model) then
		return
	end
	if not section.map then
		return section, nil, 0
	end
	self:_activate(section)
	local row, col = unpack(vim.api.nvim_win_get_cursor(self.winid))
	local local_row = math.max(1, math.min(#section.map.lines, row - section.body_first + 1))
	local item = section.map.lines[local_row]
	local line = require("differ.nav").file_line(section.map, local_row)
	return section, line, item and item.new == line and col or 0
end

function View:selection_in_one_section(first, last)
	if self.layout == "split" and self.inspection then
		local inspected = self.inspection[vim.api.nvim_get_current_buf()]
		local lo, hi = math.min(first, last), math.max(first, last)
		local lines = inspected and inspected.column.map.lines
		return lines ~= nil and lo >= 1 and hi <= #lines and lines[lo].kind ~= "meta" and lines[hi].kind ~= "meta"
	end
	local left, right = section_at(self, math.min(first, last)), section_at(self, math.max(first, last))
	return left ~= nil
		and left == right
		and math.min(first, last) >= left.body_first
		and math.max(first, last) <= left.last
end

function View:inspect_split()
	local section = self:active_section()
	if not (section and section.model) then
		return
	end
	local return_win, return_cursor = self.winid, vim.api.nvim_win_get_cursor(self.winid)
	local output = render.render(section.model, {
		layout = "split",
		context = self.context,
		deep_diff = self.deep_diff,
	}).columns
	local wins, bufs = {}, {}
	self.inspection = {}
	self.aggregate_columns = self.columns
	self.columns = {}
	self.layout = "split"
	self.model = section.model
	for index, column in ipairs(output) do
		if index == 1 then
			vim.api.nvim_set_current_win(return_win)
		else
			vim.cmd("rightbelow vsplit")
		end
		local win, buf = vim.api.nvim_get_current_win(), vim.api.nvim_create_buf(false, true)
		vim.api.nvim_win_set_buf(win, buf)
		vim.bo[buf].buftype, vim.bo[buf].bufhidden, vim.bo[buf].filetype = "nofile", "wipe", "differdiff"
		vim.api.nvim_buf_set_lines(buf, 0, -1, false, column.lines)
		vim.bo[buf].modifiable = false
		paint.apply(buf, diff_namespace, column)
		statuscolumn.set(buf, statuscolumn.format(column))
		vim.wo[win].statuscolumn = '%!v:lua.require("differ.ui.statuscolumn").render()'
		vim.wo[win].winbar = string.format(" %s · %s", section.entry.path:gsub("%%", "%%%%"), column.side:upper())
		views[buf] = self
		self.inspection[buf] = { section = section, column = column, new_column = output[#output], win = win }
		self.columns[#self.columns + 1] = {
			bufnr = buf,
			winid = win,
			map = column.map,
			side = column.side,
			folds = column.folds,
		}
		wins[#wins + 1], bufs[#bufs + 1] = win, buf
	end
	local function close()
		for _, buf in ipairs(bufs) do
			views[buf] = nil
			statuscolumn.clear(buf)
		end
		self.inspection = nil
		self.columns = self.aggregate_columns
		self.aggregate_columns = nil
		self.layout = "stacked"
		for _, win in ipairs(wins) do
			if win ~= return_win and vim.api.nvim_win_is_valid(win) then
				pcall(vim.api.nvim_win_close, win, true)
			end
		end
		if vim.api.nvim_win_is_valid(return_win) then
			vim.api.nvim_set_current_win(return_win)
			vim.api.nvim_win_set_buf(return_win, self.bufnr)
			pcall(vim.api.nvim_win_set_cursor, return_win, return_cursor)
			self:_apply_folds()
			if self.pending_logical_position then
				local anchor = self.pending_logical_position
				self.pending_logical_position = nil
				self:restore_logical_position(anchor)
			end
			if self.on_rerender then
				self.on_rerender()
			end
		end
	end
	for _, buf in ipairs(bufs) do
		local bind = require("differ.util.keymap").bind
		for _, mapping in ipairs(self.extra_keymaps or {}) do
			bind(buf, mapping.spec, mapping.fn, mapping.desc, mapping.mode)
		end
		vim.keymap.set("n", "t", close, { buffer = buf, desc = "Return to Continuous Diff" })
		vim.keymap.set("n", "q", function()
			close()
			require("differ.command").close()
		end, { buffer = buf, desc = "Close Continuous Review" })
		vim.keymap.set("n", "]f", function()
			close()
			self:jump_file("next")
			self:inspect_split()
		end, { buffer = buf, desc = "Next File Section" })
		vim.keymap.set("n", "[f", function()
			close()
			self:jump_file("prev")
			self:inspect_split()
		end, { buffer = buf, desc = "Previous File Section" })
	end
	self:_apply_inspection_folds()
	if self.on_rerender then
		self.on_rerender()
	end
end

function View:_setup()
	vim.api.nvim_win_set_buf(self.winid, self.bufnr)
	if not self.defer_filetype then
		vim.bo[self.bufnr].filetype = "differdiff"
	end
	vim.wo[self.winid].number = false
	vim.wo[self.winid].relativenumber = false
	vim.wo[self.winid].signcolumn = "no"
	vim.wo[self.winid].wrap = false
	vim.wo[self.winid].statuscolumn = '%!v:lua.require("config.differ_continuous").statuscolumn()'
	vim.wo[self.winid].winbar = '%!v:lua.require("config.differ_continuous").winbar()'
	local map = function(mode, lhs, fn, desc)
		vim.keymap.set(mode, lhs, fn, { buffer = self.bufnr, desc = desc })
	end
	map("n", "]", function()
		self:jump_hunk("next")
	end, "Next Hunk Across Files")
	map("n", "[", function()
		self:jump_hunk("prev")
	end, "Previous Hunk Across Files")
	map("n", "]f", function()
		self:jump_file("next")
	end, "Next File Section")
	map("n", "[f", function()
		self:jump_file("prev")
	end, "Previous File Section")
	map("n", "T", function()
		self:toggle_context()
	end, "Toggle Compact/Full Context")
	map("n", "t", function()
		self:inspect_split()
	end, "Inspect Current File Side-by-Side")
	map("n", "R", function()
		if self.on_refresh then
			self.on_refresh()
		end
	end, "Refresh Continuous Review")
	map("n", "s", function()
		if self.on_stage then
			self.on_stage(self, true)
		end
	end, "Stage Current Hunk")
	map("n", "u", function()
		if self.on_stage then
			self.on_stage(self, false)
		end
	end, "Unstage Current Hunk")
	map("n", "S", function()
		if self.on_stage then
			self.on_stage(self, true, true)
		end
	end, "Stage Current File")
	map("n", "U", function()
		if self.on_stage then
			self.on_stage(self, false, true)
		end
	end, "Unstage Current File")
	map("n", "X", function()
		if self.on_discard then
			self.on_discard(self)
		end
	end, "Discard Current Hunk")
	map("n", "q", function()
		require("differ.command").close()
	end, "Close Continuous Review")
	map("n", "dd", function()
		require("differ.command").panel()
	end, "Toggle File Tree")
	local bind = require("differ.util.keymap").bind
	for _, mapping in ipairs(self.extra_keymaps or {}) do
		bind(self.bufnr, mapping.spec, mapping.fn, mapping.desc, mapping.mode)
	end
	local group = vim.api.nvim_create_augroup("dotfiles-differ-continuous-" .. self.id, { clear = true })
	self.augroup = group
	vim.api.nvim_create_autocmd("CursorMoved", {
		group = group,
		buffer = self.bufnr,
		callback = function()
			self:_activate(self:active_section())
		end,
	})
end

function View:open()
	self:_setup()
	self:render()
	for _, section in ipairs(self.sections) do
		if section.map then
			local first = require("differ.nav").first_hunk(section.map)
			if first then
				vim.api.nvim_win_set_cursor(self.winid, { section.body_first + first - 1, 0 })
				break
			end
		end
	end
	self:_activate(self:active_section())
	return self
end

function View:close(keep_win)
	if self.closed then
		return
	end
	self.closed = true
	views[self.bufnr] = nil
	for buf, inspected in pairs(self.inspection or {}) do
		views[buf] = nil
		statuscolumn.clear(buf)
		local win = inspected.win
		if win and vim.api.nvim_win_is_valid(win) and vim.api.nvim_win_get_buf(win) == buf then
			if win == keep_win then
				local placeholder = vim.api.nvim_create_buf(false, true)
				vim.bo[placeholder].bufhidden = "wipe"
				vim.api.nvim_win_set_buf(win, placeholder)
			else
				pcall(vim.api.nvim_win_close, win, true)
			end
		end
		if vim.api.nvim_buf_is_valid(buf) then
			pcall(vim.api.nvim_buf_delete, buf, { force = true })
		end
	end
	self.inspection = nil
	if self.augroup then
		pcall(vim.api.nvim_del_augroup_by_id, self.augroup)
	end
	statuscolumn.clear(self.bufnr)
	if self.winid and vim.api.nvim_win_is_valid(self.winid) and vim.api.nvim_win_get_buf(self.winid) == self.bufnr then
		local placeholder = vim.api.nvim_create_buf(false, true)
		vim.bo[placeholder].bufhidden = "wipe"
		vim.api.nvim_win_set_buf(self.winid, placeholder)
	end
	if vim.api.nvim_buf_is_valid(self.bufnr) then
		pcall(vim.api.nvim_buf_delete, self.bufnr, { force = true })
	end
	if self.on_close then
		self.on_close(self, keep_win)
	end
end

function M.current()
	return View.current()
end

function M.for_buf(buf)
	return views[buf]
end

function M.winbar()
	local win = vim.g.statusline_winid
	if not (win and vim.api.nvim_win_is_valid(win)) then
		win = vim.api.nvim_get_current_win()
	end
	local buf = vim.api.nvim_win_get_buf(win)
	local view = views[buf]
	local inspected = view and view.inspection and view.inspection[buf]
	local section = inspected and inspected.section or (view and section_at(view, vim.api.nvim_win_get_cursor(win)[1]))
	if not section then
		return ""
	end
	local state = section_state(section)
	local width = math.max(vim.api.nvim_win_get_width(win) - 18 - vim.fn.strdisplaywidth(state), 8)
	local path = section.entry.path
	if vim.fn.strdisplaywidth(path) > width then
		path = "…" .. path:sub(-(width - 1))
	end
	return " " .. path:gsub("%%", "%%%%") .. string.format("  %s+%d -%d", state, section.additions, section.deletions)
end

function M.statuscolumn()
	if vim.v.virtnum ~= 0 then
		return ""
	end
	local win = vim.g.statusline_winid
	if not (win and vim.api.nvim_win_is_valid(win)) then
		return ""
	end
	local view = views[vim.api.nvim_win_get_buf(win)]
	local item = view and view:_line_at(vim.v.lnum)
	if not item then
		return ""
	end
	local old = item.old and tostring(item.old) or ""
	local new = item.new and tostring(item.new) or ""
	return string.format("%5s %5s ", old, new)
end

function M.setup_highlights()
	vim.api.nvim_set_hl(0, "DotfilesDifferFileHeader", { link = "DiffText", default = true })
	vim.api.nvim_set_hl(0, "DotfilesDifferFilePath", { bold = true, fg = "#ffffff", default = true })
	vim.api.nvim_set_hl(0, "DotfilesDifferFileCount", { link = "Title", default = true })
end

M.View = View

return M
