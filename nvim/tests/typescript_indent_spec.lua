local M = {}

local function assert_equal(actual, expected, context)
	assert(vim.deep_equal(actual, expected), context .. "\n" .. vim.inspect({
		expected = expected,
		actual = actual,
	}))
end

local function with_temp_file(name, lines, callback)
	local temp_dir = vim.fn.tempname()
	assert(vim.fn.mkdir(temp_dir, "p") == 1, "failed to create temp dir: " .. temp_dir)

	local path = temp_dir .. "/" .. name
	assert(vim.fn.writefile(lines, path) == 0, "failed to write temp file: " .. path)

	local ok, err = xpcall(function()
		callback(path)
	end, debug.traceback)

	if vim.api.nvim_buf_is_valid(0) then
		vim.bo.modified = false
	end
	vim.cmd("silent! bwipeout!")
	vim.fn.delete(temp_dir, "rf")

	if not ok then
		error(err)
	end
end

local function assert_file_indents(name, expected_filetype, input, expected, expected_shiftwidth)
	with_temp_file(name, input, function(path)
		vim.cmd("edit " .. vim.fn.fnameescape(path))
		assert(
			vim.bo.filetype == expected_filetype,
			string.format("expected detected filetype %s for %s, got %s", expected_filetype, name, vim.bo.filetype)
		)

		if expected_shiftwidth then
			assert_equal(vim.bo.shiftwidth, expected_shiftwidth, "unexpected shiftwidth for " .. name)
		end

		vim.cmd("normal! gg=G")

		local actual = vim.api.nvim_buf_get_lines(0, 0, -1, false)
		assert_equal(actual, expected, "unexpected indentation for " .. name)
	end)
end

function M.run()
	assert_file_indents("consecutive_line_comments.ts", "typescript", {
		"function withComments() {",
		"const before = computeBefore()",
		"if (before) {",
		"// first comment stays with the block",
		"// second comment does not push code deeper",
		"const after = computeAfter()",
		"return after",
		"}",
		"return before",
		"}",
	}, {
		"function withComments() {",
		"    const before = computeBefore()",
		"    if (before) {",
		"        // first comment stays with the block",
		"        // second comment does not push code deeper",
		"        const after = computeAfter()",
		"        return after",
		"    }",
		"    return before",
		"}",
	})

	assert_file_indents("existing_two_space_comments.ts", "typescript", {
		"function withComments() {",
		"  const before = computeBefore()",
		"  if (before) {",
		"    // first comment stays with the block",
		"    // second comment does not push code deeper",
		"    const after = computeAfter()",
		"    return after",
		"  }",
		"  return before",
		"}",
	}, {
		"function withComments() {",
		"  const before = computeBefore()",
		"  if (before) {",
		"    // first comment stays with the block",
		"    // second comment does not push code deeper",
		"    const after = computeAfter()",
		"    return after",
		"  }",
		"  return before",
		"}",
	}, 2)

	assert_file_indents("existing_two_space_component.tsx", "typescriptreact", {
		"function Component(props: { label: string }) {",
		"  const label = props.label",
		"  if (label) {",
		"    // first TSX comment stays with the block",
		"    // second TSX comment does not push code deeper",
		"    /**",
		"     * documents the displayed label",
		"     */",
		"    const displayed = label.toUpperCase()",
		"    return <section>{displayed}</section>",
		"  }",
		"  return <section>empty</section>",
		"}",
	}, {
		"function Component(props: { label: string }) {",
		"  const label = props.label",
		"  if (label) {",
		"    // first TSX comment stays with the block",
		"    // second TSX comment does not push code deeper",
		"    /**",
		"     * documents the displayed label",
		"     */",
		"    const displayed = label.toUpperCase()",
		"    return <section>{displayed}</section>",
		"  }",
		"  return <section>empty</section>",
		"}",
	}, 2)

	assert_file_indents("jsdoc_block.ts", "typescript", {
		"function withJSDoc() {",
		"    /**",
		"     * describes the next value",
		"     * across multiple lines",
		"     */",
		"const value = computeValue()",
		"return value",
		"}",
	}, {
		"function withJSDoc() {",
		"    /**",
		"     * describes the next value",
		"     * across multiple lines",
		"     */",
		"    const value = computeValue()",
		"    return value",
		"}",
	})

	assert_file_indents("component_comments.tsx", "typescriptreact", {
		"function Component(props: { label: string }) {",
		"const label = props.label",
		"if (label) {",
		"// first TSX comment stays with the block",
		"// second TSX comment does not push code deeper",
		"        /**",
		"         * documents the displayed label",
		"         */",
		"const displayed = label.toUpperCase()",
		"return <section>{displayed}</section>",
		"}",
		"return <section>empty</section>",
		"}",
	}, {
		"function Component(props: { label: string }) {",
		"    const label = props.label",
		"    if (label) {",
		"        // first TSX comment stays with the block",
		"        // second TSX comment does not push code deeper",
		"        /**",
		"         * documents the displayed label",
		"         */",
		"        const displayed = label.toUpperCase()",
		"        return <section>{displayed}</section>",
		"    }",
		"    return <section>empty</section>",
		"}",
	})
end

return M
