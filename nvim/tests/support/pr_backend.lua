-- Simulated GitHub boundary for real Differ UI tests, also used by the Herdr
-- fixture. Every sidecar request is intercepted: no test can publish to GitHub.
local M = {}

function M.install()
	local sidecar = require("differ.sidecar")
	local original = sidecar.request
	local state = { threads = {}, submissions = {}, opened = {}, failures = {} }
	local old, new = {}, {}
	for i = 1, 70 do
		old[i], new[i] = "context " .. i, "context " .. i
	end
	old[5], new[5] = "before first", "after first"
	old[55], new[55] = "before second", "after second"
	state.old_text, state.new_text = table.concat(old, "\n") .. "\n", table.concat(new, "\n") .. "\n"
	sidecar.request = function(method, args, callback)
		local result
		if method == "list_prs" then
			result = { { number = 17, title = "Fixture PR review", author = "reviewer", head_ref = "review-test" } }
		elseif method == "get_pr" then
			state.opened[#state.opened + 1] = vim.deepcopy(args)
			result = {
				title = "Fixture PR review",
				author = "reviewer",
				state = "OPEN",
				base_sha = string.rep("a", 40),
				head_sha = string.rep("b", 40),
				head_ref = "review-test",
				files = { { path = "example.txt", status = "modified", additions = 2, deletions = 2 } },
			}
		elseif method == "get_file_versions" then
			result = { base = { content = state.old_text }, head = { content = state.new_text } }
		elseif method == "get_threads" then
			result = vim.deepcopy(state.threads)
		elseif method == "start_review" then
			state.review_id = state.review_id or "fixture-pending-review"
			result = { review_id = state.review_id }
		elseif method == "get_pending_review" then
			result = { review_id = state.review_id }
		elseif method == "post_comment" then
			local comment = {
				node_id = "comment-" .. (#state.threads + 1),
				author = "reviewer",
				body = args.body,
				created_at = "2026-09-05T12:00:00Z",
			}
			if args.in_reply_to then
				for _, thread in ipairs(state.threads) do
					if thread.thread_id == args.in_reply_to then
						thread.comments[#thread.comments + 1] = comment
						thread.newest_comment = comment
					end
				end
			else
				state.threads[#state.threads + 1] = {
					thread_id = "thread-" .. (#state.threads + 1),
					path = args.path,
					side = args.side,
					line = args.line,
					start_line = args.start_line,
					is_pending = args.review_id ~= nil,
					comments = { comment },
					newest_comment = comment,
				}
			end
			result = { review_id = args.review_id }
		elseif method == "submit_review" then
			state.submissions[#state.submissions + 1] = vim.deepcopy(args)
			state.review_id = nil
			for _, thread in ipairs(state.threads) do
				thread.is_pending = false
			end
			result = {}
		else
			state.failures[#state.failures + 1] = method
			vim.schedule(function()
				callback({ code = "test_blocked", message = "Unexpected sidecar request: " .. method })
			end)
			return
		end
		vim.schedule(function()
			callback(nil, result)
		end)
	end
	return state, function()
		sidecar.request = original
	end
end

return M
