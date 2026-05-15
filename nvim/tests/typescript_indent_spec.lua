local M = {}

local function assert_lines(expected)
	local actual = vim.api.nvim_buf_get_lines(0, 0, -1, false)
	assert(
		vim.deep_equal(actual, expected),
		string.format("expected lines:\n%s\nactual lines:\n%s", vim.inspect(expected), vim.inspect(actual))
	)
end

local function assert_contains(value, needle, description)
	assert(
		value:find(needle, 1, true) ~= nil,
		string.format("%s should contain %q, got %q", description, needle, value)
	)
end

local function feed(keys)
	vim.api.nvim_feedkeys(vim.keycode(keys), "xt", false)
end

local function open_buffer(extension, expected_filetype, lines)
	local path = vim.fn.tempname() .. extension
	assert(vim.fn.writefile(lines, path) == 0, "failed to write " .. path)
	vim.cmd("edit " .. vim.fn.fnameescape(path))
	assert(
		vim.bo.filetype == expected_filetype,
		string.format("expected %s filetype, got %s", expected_filetype, vim.bo.filetype)
	)
	return path
end

local function open_typescript_buffer(lines)
	return open_buffer(".ts", "typescript", lines)
end

local function open_typescriptreact_buffer(lines)
	return open_buffer(".tsx", "typescriptreact", lines)
end

local function assert_typescript_indent_options(expected_filetype)
	assert(vim.bo.filetype == expected_filetype, "buffer should be " .. expected_filetype)
	assert(vim.bo.shiftwidth == 4, "test should keep repo shiftwidth at 4")
	assert(vim.bo.indentexpr == "v:lua.dotfiles_typescript_indentexpr()", "dotfiles indentexpr should be active")
	assert_contains(vim.bo.formatoptions, "o", "formatoptions")
	assert_contains(vim.bo.formatoptions, "r", "formatoptions")
	assert_contains(vim.bo.comments, "//", "comments")
end

local function test_open_line_preserves_indented_comment()
	open_typescript_buffer({
		"if (enabled) {",
		"  // first comment",
		"}",
	})
	assert_typescript_indent_options("typescript")

	vim.api.nvim_win_set_cursor(0, { 2, 0 })
	feed("osecond comment<Esc>")

	assert_lines({
		"if (enabled) {",
		"  // first comment",
		"  // second comment",
		"}",
	})
end

local function test_open_line_preserves_custom_comment_indent()
	open_typescript_buffer({
		"   // first comment",
	})
	assert_typescript_indent_options("typescript")

	vim.api.nvim_win_set_cursor(0, { 1, 0 })
	feed("osecond comment<Esc>")

	assert_lines({
		"   // first comment",
		"   // second comment",
	})
end

local function test_insert_enter_preserves_comment_indent()
	open_typescript_buffer({
		"if (enabled) {",
		"  // first comment",
		"}",
	})
	assert_typescript_indent_options("typescript")

	vim.api.nvim_win_set_cursor(0, { 2, #"  // first comment" })
	feed("A<CR>second comment<Esc>")

	assert_lines({
		"if (enabled) {",
		"  // first comment",
		"  // second comment",
		"}",
	})
end

local function test_reindent_preserves_comment_indent()
	open_typescript_buffer({
		"if (enabled) {",
		"  // first comment",
		"}",
	})
	assert_typescript_indent_options("typescript")

	vim.api.nvim_win_set_cursor(0, { 2, 0 })
	feed("==")

	assert_lines({
		"if (enabled) {",
		"    // first comment",
		"}",
	})
end

local function test_reindent_standalone_comment_uses_typescript_indent()
	open_typescript_buffer({
		"if (enabled) {",
		"// standalone comment",
		"}",
	})
	assert_typescript_indent_options("typescript")

	vim.api.nvim_win_set_cursor(0, { 2, 0 })
	feed("==")

	assert_lines({
		"if (enabled) {",
		"    // standalone comment",
		"}",
	})
end

local function test_reindent_misindented_comment_continuation_aligns_to_previous_comment()
	open_typescript_buffer({
		"if (enabled) {",
		"  // first comment",
		"// second comment",
		"}",
	})
	assert_typescript_indent_options("typescript")

	vim.api.nvim_win_set_cursor(0, { 3, 0 })
	feed("==")

	assert_lines({
		"if (enabled) {",
		"  // first comment",
		"  // second comment",
		"}",
	})
end

local function test_open_line_after_block_uses_typescript_indent()
	open_typescript_buffer({
		"if (enabled) {",
		"}",
	})
	assert_typescript_indent_options("typescript")

	vim.api.nvim_win_set_cursor(0, { 1, 0 })
	feed("ovalue<Esc>")

	assert_lines({
		"if (enabled) {",
		"    value",
		"}",
	})
end

local function test_open_line_after_jsdoc_opener_aligns_star_body()
	open_typescript_buffer({
		"/**",
		" */",
	})
	assert_typescript_indent_options("typescript")

	vim.api.nvim_win_set_cursor(0, { 1, 0 })
	feed("oOpenCode sandbox CLI<Esc>")

	assert_lines({
		"/**",
		" * OpenCode sandbox CLI",
		" */",
	})
end

local function test_open_line_after_jsdoc_opener_with_trailing_text_aligns_star_body()
	open_typescript_buffer({
		"/** summary",
		" */",
	})
	assert_typescript_indent_options("typescript")

	vim.api.nvim_win_set_cursor(0, { 1, 0 })
	feed("omore detail<Esc>")

	assert_lines({
		"/** summary",
		" * more detail",
		" */",
	})
end

local function test_insert_enter_after_jsdoc_opener_with_trailing_text_aligns_star_body()
	open_typescript_buffer({
		"/** summary",
		" */",
	})
	assert_typescript_indent_options("typescript")

	vim.api.nvim_win_set_cursor(0, { 1, #"/** summary" })
	feed("A<CR>more detail<Esc>")

	assert_lines({
		"/** summary",
		" * more detail",
		" */",
	})
end

local function test_open_line_after_jsdoc_body_aligns_to_previous_star_body()
	open_typescript_buffer({
		"/**",
		" * first line",
		" */",
	})
	assert_typescript_indent_options("typescript")

	vim.api.nvim_win_set_cursor(0, { 2, 0 })
	feed("osecond line<Esc>")

	assert_lines({
		"/**",
		" * first line",
		" * second line",
		" */",
	})
end

local function test_reindent_block_comment_star_from_column_zero_aligns_to_previous_body_line()
	open_typescript_buffer({
		"/**",
		" * previous",
		"* bad",
		" */",
	})
	assert_typescript_indent_options("typescript")

	vim.api.nvim_win_set_cursor(0, { 3, 0 })
	feed("==")

	assert_lines({
		"/**",
		" * previous",
		" * bad",
		" */",
	})
end

local function test_reindent_block_comment_star_from_deep_indent_aligns_to_previous_body_line()
	open_typescript_buffer({
		"/**",
		" * previous",
		"         * too deep",
		" */",
	})
	assert_typescript_indent_options("typescript")

	vim.api.nvim_win_set_cursor(0, { 3, 0 })
	feed("==")

	assert_lines({
		"/**",
		" * previous",
		" * too deep",
		" */",
	})
end

local function test_open_line_after_nested_jsdoc_opener_aligns_star_body()
	open_typescript_buffer({
		"if (enabled) {",
		"  /**",
		"   */",
		"}",
	})
	assert_typescript_indent_options("typescript")

	vim.api.nvim_win_set_cursor(0, { 2, 0 })
	feed("onested detail<Esc>")

	assert_lines({
		"if (enabled) {",
		"  /**",
		"   * nested detail",
		"   */",
		"}",
	})
end

local function test_open_line_after_nested_jsdoc_opener_with_trailing_text_aligns_star_body()
	open_typescript_buffer({
		"if (enabled) {",
		"  /** summary",
		"   */",
		"}",
	})
	assert_typescript_indent_options("typescript")

	vim.api.nvim_win_set_cursor(0, { 2, 0 })
	feed("onested detail<Esc>")

	assert_lines({
		"if (enabled) {",
		"  /** summary",
		"   * nested detail",
		"   */",
		"}",
	})
end

local function test_typescriptreact_open_line_preserves_indented_comment()
	open_typescriptreact_buffer({
		"const value = (",
		"  // first comment",
		"  <div />",
		")",
	})
	assert_typescript_indent_options("typescriptreact")

	vim.api.nvim_win_set_cursor(0, { 2, 0 })
	feed("osecond comment<Esc>")

	assert_lines({
		"const value = (",
		"  // first comment",
		"  // second comment",
		"  <div />",
		")",
	})
end

local function test_typescriptreact_reindent_block_comment_star_aligns_to_previous_body_line()
	open_typescriptreact_buffer({
		"/**",
		" * previous",
		"* tsx continuation",
		" */",
	})
	assert_typescript_indent_options("typescriptreact")

	vim.api.nvim_win_set_cursor(0, { 3, 0 })
	feed("==")

	assert_lines({
		"/**",
		" * previous",
		" * tsx continuation",
		" */",
	})
end

local function test_typescriptreact_open_line_after_jsdoc_opener_with_trailing_text_aligns_star_body()
	open_typescriptreact_buffer({
		"/** summary",
		" */",
	})
	assert_typescript_indent_options("typescriptreact")

	vim.api.nvim_win_set_cursor(0, { 1, 0 })
	feed("otsx detail<Esc>")

	assert_lines({
		"/** summary",
		" * tsx detail",
		" */",
	})
end

local function test_closed_single_line_block_comment_delegates_to_typescript_indent()
	open_typescript_buffer({
		"if (enabled) {",
		"  /** summary */",
		"* not a continuation",
		"}",
	})
	assert_typescript_indent_options("typescript")
	vim.b.dotfiles_typescript_indentexpr = "7"

	vim.api.nvim_win_set_cursor(0, { 3, 0 })
	feed("==")

	assert_lines({
		"if (enabled) {",
		"  /** summary */",
		"       * not a continuation",
		"}",
	})
end

local function test_line_after_closed_block_comment_delegates_to_typescript_indent()
	open_typescript_buffer({
		"/**",
		" */",
		"* outside block comment",
	})
	assert_typescript_indent_options("typescript")
	vim.b.dotfiles_typescript_indentexpr = "6"

	vim.api.nvim_win_set_cursor(0, { 3, 0 })
	feed("==")

	assert_lines({
		"/**",
		" */",
		"      * outside block comment",
	})
end

local function test_line_after_inline_closed_star_body_delegates_to_typescript_indent()
	open_typescript_buffer({
		"/**",
		" * summary */",
		"* outside block comment",
	})
	assert_typescript_indent_options("typescript")
	vim.b.dotfiles_typescript_indentexpr = "5"

	vim.api.nvim_win_set_cursor(0, { 3, 0 })
	feed("==")

	assert_lines({
		"/**",
		" * summary */",
		"     * outside block comment",
	})
end

local function run_case(fn)
	local ok, err = pcall(fn)
	vim.cmd("silent! noautocmd setlocal nomodified")
	vim.cmd("silent! bdelete!")
	if not ok then
		error(err, 0)
	end
end

function M.run()
	run_case(test_open_line_preserves_indented_comment)
	run_case(test_open_line_preserves_custom_comment_indent)
	run_case(test_insert_enter_preserves_comment_indent)
	run_case(test_reindent_preserves_comment_indent)
	run_case(test_reindent_standalone_comment_uses_typescript_indent)
	run_case(test_reindent_misindented_comment_continuation_aligns_to_previous_comment)
	run_case(test_open_line_after_block_uses_typescript_indent)
	run_case(test_open_line_after_jsdoc_opener_aligns_star_body)
	run_case(test_open_line_after_jsdoc_opener_with_trailing_text_aligns_star_body)
	run_case(test_insert_enter_after_jsdoc_opener_with_trailing_text_aligns_star_body)
	run_case(test_open_line_after_jsdoc_body_aligns_to_previous_star_body)
	run_case(test_reindent_block_comment_star_from_column_zero_aligns_to_previous_body_line)
	run_case(test_reindent_block_comment_star_from_deep_indent_aligns_to_previous_body_line)
	run_case(test_open_line_after_nested_jsdoc_opener_aligns_star_body)
	run_case(test_open_line_after_nested_jsdoc_opener_with_trailing_text_aligns_star_body)
	run_case(test_typescriptreact_open_line_preserves_indented_comment)
	run_case(test_typescriptreact_reindent_block_comment_star_aligns_to_previous_body_line)
	run_case(test_typescriptreact_open_line_after_jsdoc_opener_with_trailing_text_aligns_star_body)
	run_case(test_closed_single_line_block_comment_delegates_to_typescript_indent)
	run_case(test_line_after_closed_block_comment_delegates_to_typescript_indent)
	run_case(test_line_after_inline_closed_star_body_delegates_to_typescript_indent)
	return true
end

return M
