local M = {}
local installed = false

function M.setup()
	if installed then
		return
	end
	installed = true
	local threads = require("differ.pr.threads")
	local native_apply = threads.apply
	local namespace = vim.api.nvim_create_namespace("differ.pr.threads")
	-- Native refresh/reply/resolve paths all call this public rendering entry point.
	-- Route by view type while preserving Differ's thread boxes and interaction state.
	threads.apply = function(session)
		local view = session and session.view
		if not (view and view.each_section and view.layout == "stacked") then
			return native_apply(session)
		end
		if not view:is_alive() then
			return
		end
		vim.api.nvim_buf_clear_namespace(view.bufnr, namespace, 0, -1)
		local by_path = {}
		for _, thread in ipairs(session.threads or {}) do
			by_path[thread.path] = by_path[thread.path] or {}
			table.insert(by_path[thread.path], thread)
		end
		local anchors = {}
		local date = require("differ.util.date")
		local relative = require("differ").get_config().relative_dates
		local function reltime(timestamp)
			local epoch = date.parse_iso(timestamp)
			return epoch and date.format(epoch, { relative = relative, time = true }) or timestamp or ""
		end
		view:each_section(function(section)
			local file_threads = by_path[section.entry.path]
			if not file_threads then
				return
			end
			local projection = view:project_section(section)
			local groups = {}
			for _, thread in ipairs(file_threads) do
				local side = threads.side_of(thread)
				local column = projection:column_for(side)
				local index = side == "old" and column.map.from_old or column.map.from_new
				local row = threads.anchor_row(index, threads.anchor_line(thread))
				if row then
					local key = column.bufnr .. ":" .. row
					groups[key] = groups[key] or { key = key, bufnr = column.bufnr, row = row, threads = {} }
					table.insert(groups[key].threads, thread)
				end
			end
			for _, group in pairs(groups) do
				threads.stack_sort(group.threads)
				threads.apply_box(session, projection, group, reltime)
				anchors[#anchors + 1] = group
			end
		end)
		table.sort(anchors, function(left, right)
			return left.row < right.row
		end)
		session.thread_anchors = anchors
		threads.close_peek()
	end
end

return M
