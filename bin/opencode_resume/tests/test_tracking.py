from factories import opencode, shell

from opencode_resume.sessions import SavedSession, load, save, track


def look(saved, *terminals, boot="boot-1"):
    return track(saved, {terminal.address: terminal for terminal in terminals}, boot)


def test_session_seen_while_working_is_kept_once_opencode_is_idle():
    saved = look({}, opencode("t1", 100, folder="/repo", reported=["ses_a"]))
    saved = look(saved, opencode("t1", 100, folder="/repo"))

    assert saved == {
        "t1": SavedSession(boot="boot-1", shell_pid=100, session="ses_a", folder="/repo", command="opencode")
    }


def test_restored_terminal_keeps_the_session_waiting_to_resume():
    saved = look({}, opencode("t1", 100, reported=["ses_a"]))

    assert look(saved, shell("t1", 200)) == saved


def test_shell_restored_after_a_reboot_with_the_old_pid_keeps_the_session():
    saved = look({}, opencode("t1", 100, reported=["ses_a"]))

    assert look(saved, shell("t1", 100), boot="boot-2") == saved


def test_quitting_opencode_forgets_its_session():
    saved = look({}, opencode("t1", 100, reported=["ses_a"]))

    assert look(saved, shell("t1", 100)) == {}


def test_closed_terminal_forgets_its_session():
    saved = look({}, opencode("t1", 100, reported=["ses_a"]))

    assert look(saved) == {}


def test_resumed_opencode_is_tracked_under_its_new_shell():
    saved = look({}, opencode("t1", 100, reported=["ses_a"]))
    saved = look(saved, shell("t1", 200))
    saved = look(saved, opencode("t1", 200, argv=("opencode2", "--session", "ses_a")))

    assert saved == {
        "t1": SavedSession(boot="boot-1", shell_pid=200, session="ses_a", folder="/work", command="opencode2")
    }


def test_new_opencode_in_a_restored_terminal_replaces_the_old_session():
    saved = look({}, opencode("t1", 100, reported=["ses_a"]))
    saved = look(saved, shell("t1", 200))

    assert look(saved, opencode("t1", 200)) == {}


def test_switching_sessions_follows_the_one_reported():
    saved = look({}, opencode("t1", 100, reported=["ses_a"]))

    assert look(saved, opencode("t1", 100, reported=["ses_b"]))["t1"].session == "ses_b"


def test_saved_sessions_survive_a_round_trip_through_the_state_file(tmp_path):
    saved = {"t1": SavedSession(boot="boot-1", shell_pid=100, session="ses_a", folder="/repo", command="opencode")}
    state_file = tmp_path / "state" / "sessions.json"

    save(state_file, saved)

    assert load(state_file) == saved
    assert load(tmp_path / "missing.json") == {}
