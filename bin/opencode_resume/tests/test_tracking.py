from opencode_resume.sessions import SavedSession, load, save, track


def look(saved, *terminals, finished=(), boot="boot-1"):
    return track(saved, {terminal.address: terminal for terminal in terminals}, set(finished), boot)


def saved_session(shell_pid=100, session="ses_a", folder="/repo", command="opencode"):
    return SavedSession(
        boot="boot-1", shell_pid=shell_pid, opencode_pid=shell_pid + 1, session=session, folder=folder, command=command
    )


def test_session_seen_while_working_is_kept_once_opencode_is_idle(opencode):
    saved = look({}, opencode("t1", 100, folder="/repo", reported=["ses_a"]))
    saved = look(saved, opencode("t1", 100, folder="/repo"))

    assert saved == {"t1": saved_session()}


def test_restored_terminal_keeps_the_session_waiting_to_resume(opencode, shell):
    saved = look({}, opencode("t1", 100, reported=["ses_a"]))

    assert look(saved, shell("t1", 200)) == saved


def test_shell_restored_after_a_reboot_with_the_old_pid_keeps_the_session(opencode, shell):
    saved = look({}, opencode("t1", 100, reported=["ses_a"]))

    assert look(saved, shell("t1", 100), boot="boot-2") == saved


def test_terminal_not_listed_yet_after_a_reboot_keeps_the_session(opencode):
    saved = look({}, opencode("t1", 100, reported=["ses_a"]))

    assert look(saved, boot="boot-2") == saved


def test_quitting_opencode_forgets_its_session(opencode, shell):
    saved = look({}, opencode("t1", 100, reported=["ses_a"]))

    assert look(saved, shell("t1", 100)) == {}


def test_finished_terminal_forgets_its_session(opencode):
    saved = look({}, opencode("t1", 100, reported=["ses_a"]))

    assert look(saved, finished=["t1"]) == {}


def test_resumed_opencode_is_tracked_under_its_new_shell(opencode, shell):
    saved = look({}, opencode("t1", 100, reported=["ses_a"]))
    saved = look(saved, shell("t1", 200))
    saved = look(saved, opencode("t1", 200, argv=("opencode2", "--session", "ses_a")))

    assert saved == {"t1": saved_session(shell_pid=200, folder="/work", command="opencode2")}


def test_resumed_opencode_that_switched_sessions_keeps_the_new_one_once_idle(opencode):
    argv = ("opencode", "--session", "ses_a")
    saved = look({}, opencode("t1", 200, argv=argv))
    saved = look(saved, opencode("t1", 200, argv=argv, reported=["ses_b"]))
    saved = look(saved, opencode("t1", 200, argv=argv))

    assert saved["t1"].session == "ses_b"


def test_new_opencode_in_a_restored_terminal_replaces_the_old_session(opencode, shell):
    saved = look({}, opencode("t1", 100, reported=["ses_a"]))
    saved = look(saved, shell("t1", 200))

    assert look(saved, opencode("t1", 200)) == {}


def test_opencode_resume_running_in_a_restored_terminal_keeps_the_session(opencode, busy):
    saved = look({}, opencode("t1", 100, reported=["ses_a"]))

    assert look(saved, busy("t1", 200, "opencode-resume", "status")) == saved


def test_switching_sessions_follows_the_one_reported(opencode):
    saved = look({}, opencode("t1", 100, reported=["ses_a"]))

    assert look(saved, opencode("t1", 100, reported=["ses_b"]))["t1"].session == "ses_b"


def test_saved_sessions_survive_a_round_trip_through_the_state_file(tmp_path):
    saved = {"t1": saved_session()}
    state_file = tmp_path / "state" / "sessions.json"

    save(state_file, saved)

    assert load(state_file) == saved
    assert load(tmp_path / "missing.json") == {}


def test_each_herdr_core_session_has_its_own_state_file(monkeypatch, tmp_path):
    from opencode_resume.sessions import default_state_file

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.delenv("HC_SESSION", raising=False)
    main_window = default_state_file()
    monkeypatch.setenv("HC_SESSION", "agent-test")

    assert default_state_file() != main_window


def test_new_opencode_started_on_another_session_in_the_same_shell_replaces_the_old_one(opencode):
    saved = look({}, opencode("t1", 100, reported=["ses_a"]))

    saved = look(saved, opencode("t1", 100, opencode_pid=300, argv=("opencode", "--session", "ses_b")))

    assert saved["t1"].session == "ses_b"
