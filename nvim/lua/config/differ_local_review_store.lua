local M = {}

local REVIEW_DIRECTORY = ".agents/reviews"
local SCHEMA_VERSION = 2

local function now()
	return os.date("!%Y-%m-%dT%H:%M:%SZ")
end

local function git(root, ...)
	local command = { "git", "-C", root }
	vim.list_extend(command, { ... })
	local result = vim.system(command, { text = true }):wait()
	if result.code ~= 0 then
		return nil, vim.trim(result.stderr or "git command failed")
	end
	return vim.trim(result.stdout or "")
end

function M.canonical_root(root)
	return (vim.uv or vim.loop).fs_realpath(root)
end

function M.current_identity(root)
	root = M.canonical_root(root)
	if not root then
		return nil, "repository root does not exist"
	end
	local branch = git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
	if branch and branch ~= "" then
		local head = git(root, "rev-parse", "--verify", "HEAD")
		return { kind = "branch", name = branch, head = head ~= "" and head or nil }
	end
	local commit, err = git(root, "rev-parse", "--verify", "HEAD")
	if not commit or commit == "" then
		return nil, err ~= "" and err or "cannot identify detached HEAD"
	end
	return { kind = "detached", commit = commit }
end

function M.same_identity(left, right)
	if not (left and right and left.kind == right.kind) then
		return false
	end
	if left.kind == "branch" then
		return left.name == right.name
	end
	return left.commit == right.commit
end

local function identity_key(identity)
	return identity.kind == "branch" and ("branch\0" .. identity.name) or ("detached\0" .. identity.commit)
end

function M.relative_path(identity)
	return string.format("%s/review-%s.json", REVIEW_DIRECTORY, vim.fn.sha256(identity_key(identity)):sub(1, 12))
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

function M.resolve_path(root, identity)
	local uv = vim.uv or vim.loop
	local canonical_root = M.canonical_root(root)
	if not canonical_root then
		return nil, "repository root does not exist"
	end
	local relative = M.relative_path(identity)
	local output = vim.fs.normalize(canonical_root .. "/" .. relative)
	local review_root = vim.fs.normalize(canonical_root .. "/" .. REVIEW_DIRECTORY)
	local output_stat = uv.fs_lstat(output)
	if output_stat and output_stat.type == "link" then
		return nil, "review path must not be a symbolic link"
	end

	local review_ancestor = nearest_existing(review_root)
	local canonical_review_ancestor = uv.fs_realpath(review_ancestor)
	local canonical_review =
		vim.fs.normalize(canonical_review_ancestor .. "/" .. (vim.fs.relpath(review_ancestor, review_root) or ""))
	if not path_inside(canonical_root, canonical_review) then
		return nil, REVIEW_DIRECTORY .. " must stay inside the repository root"
	end
	local output_ancestor = nearest_existing(output)
	local canonical_output_ancestor = uv.fs_realpath(output_ancestor)
	local canonical_output =
		vim.fs.normalize(canonical_output_ancestor .. "/" .. (vim.fs.relpath(output_ancestor, output) or ""))
	if not path_inside(canonical_review, canonical_output) then
		return nil, "review path must stay inside " .. REVIEW_DIRECTORY
	end
	return canonical_output, canonical_root, relative
end

-- Write beside the destination, sync the complete contents, and only then replace it.
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

local function valid_point(point)
	return type(point) == "table"
		and (point.side == "old" or point.side == "new")
		and type(point.line) == "number"
		and point.line >= 1
		and point.line % 1 == 0
end

local function has_only_keys(value, allowed)
	for key in pairs(value) do
		if not allowed[key] then
			return false
		end
	end
	return true
end

local function valid_note(note)
	if
		type(note) ~= "table"
		or not has_only_keys(note, {
			id = true,
			body = true,
			path = true,
			source_range = true,
			source_context = true,
			anchor_status = true,
			created_at = true,
			updated_at = true,
		})
		or type(note.id) ~= "string"
		or note.id == ""
		or type(note.body) ~= "string"
	then
		return false
	end
	if
		type(note.path) ~= "string"
		or note.path == ""
		or note.path:sub(1, 1) == "/"
		or ("/" .. note.path .. "/"):find("/../", 1, true)
	then
		return false
	end
	if
		type(note.source_range) ~= "table"
		or not has_only_keys(note.source_range, { start = true, ["end"] = true })
		or not valid_point(note.source_range.start)
		or not has_only_keys(note.source_range.start, { side = true, line = true })
	then
		return false
	end
	if
		not valid_point(note.source_range["end"])
		or not has_only_keys(note.source_range["end"], { side = true, line = true })
	then
		return false
	end
	if
		type(note.source_context) ~= "table"
		or not has_only_keys(note.source_context, {
			comparison = true,
			line_text = true,
			range_text = true,
			start_line_text = true,
		})
		or type(note.source_context.comparison) ~= "string"
	then
		return false
	end
	if note.source_context.comparison ~= "HEAD" and note.source_context.comparison ~= "main..." then
		return false
	end
	for _, key in ipairs({ "line_text", "range_text", "start_line_text" }) do
		if note.source_context[key] ~= nil and type(note.source_context[key]) ~= "string" then
			return false
		end
	end
	return (note.anchor_status == "current" or note.anchor_status == "outdated" or note.anchor_status == "unverified")
		and type(note.created_at) == "string"
		and type(note.updated_at) == "string"
end

function M.validate(document)
	if type(document) ~= "table" or document.schema_version ~= SCHEMA_VERSION then
		return nil, "unsupported review schema (expected version 2)"
	end
	if
		not has_only_keys(document, {
			schema_version = true,
			repository_root = true,
			branch = true,
			created_at = true,
			updated_at = true,
			comparisons = true,
		})
	then
		return nil, "unknown review document field"
	end
	if
		type(document.repository_root) ~= "string"
		or document.repository_root == ""
		or type(document.branch) ~= "table"
		or type(document.created_at) ~= "string"
		or type(document.updated_at) ~= "string"
	then
		return nil, "invalid repository or branch metadata"
	end
	if document.branch.kind == "branch" then
		if
			not has_only_keys(document.branch, { kind = true, name = true, head = true })
			or type(document.branch.name) ~= "string"
			or document.branch.name == ""
		then
			return nil, "invalid branch metadata"
		end
		if document.branch.head ~= nil and (type(document.branch.head) ~= "string" or document.branch.head == "") then
			return nil, "invalid branch head metadata"
		end
	elseif document.branch.kind == "detached" then
		if
			not has_only_keys(document.branch, { kind = true, commit = true })
			or type(document.branch.commit) ~= "string"
			or document.branch.commit == ""
		then
			return nil, "invalid detached HEAD metadata"
		end
	else
		return nil, "invalid branch kind"
	end
	if
		type(document.comparisons) ~= "table" or not has_only_keys(document.comparisons, { HEAD = true, main = true })
	then
		return nil, "missing comparisons"
	end
	for _, key in ipairs({ "HEAD", "main" }) do
		local comparison = document.comparisons[key]
		local expected_spec, expected_base = key == "HEAD" and "HEAD" or "main...", key == "HEAD" and "HEAD" or "main"
		if
			type(comparison) ~= "table"
			or not has_only_keys(comparison, { spec = true, base = true, target = true, notes = true })
			or comparison.spec ~= expected_spec
			or comparison.base ~= expected_base
			or comparison.target ~= "working-tree"
			or type(comparison.notes) ~= "table"
			or not vim.islist(comparison.notes)
		then
			return nil, "invalid " .. key .. " comparison"
		end
		for _, note in ipairs(comparison.notes) do
			if not valid_note(note) then
				return nil, "invalid note in " .. key .. " comparison"
			end
			if note.source_context.comparison ~= comparison.spec then
				return nil, "note comparison context does not match " .. key
			end
		end
	end
	return true
end

local function new_document(root, identity)
	local timestamp = now()
	return {
		schema_version = SCHEMA_VERSION,
		repository_root = root,
		branch = vim.deepcopy(identity),
		created_at = timestamp,
		updated_at = timestamp,
		comparisons = {
			HEAD = { spec = "HEAD", base = "HEAD", target = "working-tree", notes = {} },
			main = { spec = "main...", base = "main", target = "working-tree", notes = {} },
		},
	}
end

local function read_bytes(path)
	local uv = vim.uv or vim.loop
	local stat = uv.fs_stat(path)
	if not stat then
		return nil, nil, false
	end
	if stat.type ~= "file" then
		return nil, "review path is not a regular file", true
	end
	local fd, open_err = uv.fs_open(path, "r", 0)
	if not fd then
		return nil, open_err, true
	end
	local bytes, read_err = uv.fs_read(fd, stat.size, 0)
	local closed, close_err = uv.fs_close(fd)
	if not bytes then
		return nil, read_err, true
	end
	if not closed then
		return nil, close_err, true
	end
	return bytes, nil, true
end

local function fingerprint(path)
	local bytes, err, exists = read_bytes(path)
	if not exists then
		return false
	end
	if not bytes then
		return nil, err
	end
	return vim.fn.sha256(bytes)
end

local function read_json(path)
	local bytes, err, exists = read_bytes(path)
	if not bytes then
		return nil, err, exists
	end
	local decoded, document = pcall(vim.json.decode, bytes)
	if not decoded then
		return nil, "malformed review JSON: " .. tostring(document), true, vim.fn.sha256(bytes)
	end
	return document, nil, true, vim.fn.sha256(bytes)
end

local function ignored(root, relative)
	local result = vim.system({ "git", "-C", root, "check-ignore", "-q", "--", relative }, { text = true }):wait()
	return result.code == 0
end

function M.load(root)
	root = M.canonical_root(root)
	if not root then
		return nil, "repository root does not exist"
	end
	local identity, identity_err = M.current_identity(root)
	if not identity then
		return nil, identity_err
	end
	local path, path_err = M.resolve_path(root, identity)
	if not path then
		return nil, path_err
	end
	local document, read_err, exists, loaded_fingerprint = read_json(path)
	if exists then
		if not document then
			return nil,
				read_err,
				{ path = path, identity = identity, fingerprint = loaded_fingerprint, protected = true }
		end
		local valid, validation_err = M.validate(document)
		if not valid then
			return nil,
				validation_err,
				{ path = path, identity = identity, fingerprint = loaded_fingerprint, protected = true }
		end
		if document.repository_root ~= root or not M.same_identity(document.branch, identity) then
			return nil,
				"review ownership does not match its filename",
				{ path = path, identity = identity, fingerprint = loaded_fingerprint, protected = true }
		end
		return document, nil, { path = path, identity = identity, fingerprint = loaded_fingerprint, existed = true }
	end
	return new_document(root, identity), nil, { path = path, identity = identity, fingerprint = false, existed = false }
end

function M.save(root, identity, document, expected_fingerprint)
	if expected_fingerprint == nil then
		return nil, "missing expected review fingerprint; reopen the review"
	end
	root = M.canonical_root(root)
	local current, identity_err = M.current_identity(root)
	if not current then
		return nil, identity_err
	end
	if not M.same_identity(identity, current) then
		return nil, "branch changed; close and reopen the review"
	end
	if document.repository_root ~= root or not M.same_identity(document.branch, identity) then
		return nil, "review ownership changed"
	end
	local valid, validation_err = M.validate(document)
	if not valid then
		return nil, validation_err
	end
	if identity.kind == "branch" then
		document.branch.head = current.head
	end
	document.updated_at = now()
	local path, path_err, relative = M.resolve_path(root, identity)
	if not path then
		return nil, path_err
	end
	if not ignored(root, relative) then
		return nil, relative .. " is not ignored by Git"
	end
	local current_fingerprint, fingerprint_err = fingerprint(path)
	if current_fingerprint == nil then
		return nil, fingerprint_err
	end
	if current_fingerprint ~= expected_fingerprint then
		return nil, "branch review changed on disk; close and reopen the review"
	end
	local written, write_err = M.write_snapshot(path, document)
	if not written then
		return nil, write_err
	end
	local new_fingerprint, fingerprint_err = fingerprint(path)
	if not new_fingerprint then
		return nil, fingerprint_err or "saved review could not be fingerprinted"
	end
	return true, path, new_fingerprint
end

M.schema_version = SCHEMA_VERSION

return M
