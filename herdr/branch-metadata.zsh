#!/usr/bin/env zsh

[[ ${HERDR_ENV:-} == 1 && -n ${HERDR_WORKSPACE_ID:-} ]] || return 0

autoload -Uz add-zsh-hook

typeset -g _HERDR_BRANCH_LABEL_LAST

_herdr_publish_branch_label() {
	local workspace_id=$1
	local repo_root=$2
	local herdr_bin=${HERDR_BIN_PATH:-herdr}
	local branch label=""

	if [[ -n $repo_root ]]; then
		branch=$(git -C "$repo_root" branch --show-current 2>/dev/null) || branch=""
		[[ -n $branch ]] && label=" $branch"
	fi

	if [[ -n $label ]]; then
		"$herdr_bin" workspace report-metadata "$workspace_id" \
			--source dotfiles.branch-label --token "branch_label=$label" >/dev/null 2>&1
	else
		"$herdr_bin" workspace report-metadata "$workspace_id" \
			--source dotfiles.branch-label --clear-token branch_label >/dev/null 2>&1
	fi
}

_herdr_report_all_branch_labels() {
	local herdr_bin=${HERDR_BIN_PATH:-herdr}
	local workspace_id repo_root

	while IFS=$'\t' read -r workspace_id repo_root; do
		if [[ -z $repo_root ]]; then
			repo_root=$(
				"$herdr_bin" pane list --workspace "$workspace_id" 2>/dev/null |
					jq -r '[.result.panes[] | .cwd // .foreground_cwd | select(. != null)][0] // empty'
			) || repo_root=""
		fi
		_herdr_publish_branch_label "$workspace_id" "$repo_root"
	done < <(
		"$herdr_bin" workspace list 2>/dev/null |
			jq -r '.result.workspaces[] | [.workspace_id, (.worktree.checkout_path // "")] | @tsv'
	)
}

_herdr_report_branch_label() {
	local herdr_bin=${HERDR_BIN_PATH:-herdr}
	local repo_root branch label=""

	repo_root=$(
		"$herdr_bin" workspace get "$HERDR_WORKSPACE_ID" 2>/dev/null |
			jq -r '.result.workspace.worktree.checkout_path // empty'
	) || return 0
	if [[ -z $repo_root ]]; then
		repo_root=$(
			"$herdr_bin" pane current --current 2>/dev/null |
				jq -r '.result.pane.cwd // .result.pane.foreground_cwd // empty'
		) || repo_root=""
	fi

	if [[ -n $repo_root ]]; then
		branch=$(git -C "$repo_root" branch --show-current 2>/dev/null) || branch=""
		[[ -n $branch ]] && label=" $branch"
	fi

	[[ $label == $_HERDR_BRANCH_LABEL_LAST ]] && return 0

	if [[ -n $label ]]; then
		"$herdr_bin" workspace report-metadata "$HERDR_WORKSPACE_ID" \
			--source dotfiles.branch-label --token "branch_label=$label" >/dev/null 2>&1
	else
		"$herdr_bin" workspace report-metadata "$HERDR_WORKSPACE_ID" \
			--source dotfiles.branch-label --clear-token branch_label >/dev/null 2>&1
	fi

	_HERDR_BRANCH_LABEL_LAST=$label
}

add-zsh-hook precmd _herdr_report_branch_label
_herdr_report_all_branch_labels
