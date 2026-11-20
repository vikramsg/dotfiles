import pytest

from opencode_resume.terminals import Foreground, Terminal


@pytest.fixture
def opencode():
    def make(address, shell_pid, *, opencode_pid=None, folder="/work", argv=("opencode",), reported=()):
        pid = opencode_pid or shell_pid + 1
        return Terminal(address, shell_pid, Foreground(pid, "opencode.exe", tuple(argv), folder), tuple(reported))

    return make


@pytest.fixture
def shell():
    def make(address, shell_pid, *, folder="/work"):
        return Terminal(address, shell_pid, Foreground(shell_pid, "zsh", ("zsh", "-l"), folder), ())

    return make


@pytest.fixture
def busy():
    def make(address, shell_pid, *argv):
        return Terminal(address, shell_pid, Foreground(shell_pid + 1, argv[0], tuple(argv), "/work"), ())

    return make
