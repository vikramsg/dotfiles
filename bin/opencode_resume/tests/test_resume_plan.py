from opencode_resume.resume import plan
from opencode_resume.sessions import SavedSession


def saved_session(shell_pid=100, session="ses_a", folder="/repo", command="opencode"):
    return SavedSession(boot="boot-1", shell_pid=shell_pid, session=session, folder=folder, command=command)


def outcomes(saved, *terminals, folders=("/repo", "/other"), boot="boot-1"):
    live = {terminal.address: terminal for terminal in terminals}
    return plan(saved, live, boot, folder_exists=folders.__contains__)


def test_restored_shell_gets_opencode_back_on_its_session_and_folder(shell):
    [outcome] = outcomes({"t1": saved_session(command="opencode2")}, shell("t1", 200))

    assert outcome.command == "cd /repo && opencode2 --session ses_a"
    assert outcome.reason is None


def test_shell_restored_after_a_reboot_with_the_old_pid_is_resumed(shell):
    [outcome] = outcomes({"t1": saved_session()}, shell("t1", 100), boot="boot-2")

    assert outcome.command is not None


def test_terminal_still_running_its_opencode_is_left_alone(opencode):
    assert outcomes({"t1": saved_session()}, opencode("t1", 100)) == []


def test_restored_terminal_running_something_else_is_skipped(busy):
    [outcome] = outcomes({"t1": saved_session()}, busy("t1", 200, "vim"))

    assert outcome.command is None
    assert outcome.reason == "busy running vim"


def test_session_whose_folder_is_gone_is_skipped(shell):
    [outcome] = outcomes({"t1": saved_session(folder="/deleted")}, shell("t1", 200))

    assert outcome.reason == "folder no longer exists"


def test_folder_with_quotes_and_spaces_is_typed_quoted(shell):
    folder = "/it's my repo"
    [outcome] = outcomes({"t1": saved_session(folder=folder)}, shell("t1", 200), folders=(folder,))

    assert outcome.command == "cd '/it'\"'\"'s my repo' && opencode --session ses_a"


def test_folder_with_a_newline_is_skipped(shell):
    folder = "/two\nlines"
    [outcome] = outcomes({"t1": saved_session(folder=folder)}, shell("t1", 200), folders=(folder,))

    assert outcome.command is None


def test_session_open_in_another_terminal_is_not_opened_twice(opencode, shell):
    saved = {"t1": saved_session(), "t2": saved_session(shell_pid=101)}
    first, second = outcomes(saved, shell("t1", 200), shell("t2", 201))

    assert first.command is not None
    assert second.reason == "session already open in another terminal"

    [outcome] = outcomes({"t1": saved_session()}, shell("t1", 200), opencode("t9", 300, reported=["ses_a"]))
    assert outcome.reason == "session already open in another terminal"
