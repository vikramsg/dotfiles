import pytest

from opencode_resume.terminals import Foreground, Terminal


@pytest.fixture
def opencode():
    def make(address, shell_pid, *, folder="/work", argv=("opencode",), reported=()):
        return Terminal(address, shell_pid, Foreground("opencode.exe", tuple(argv), folder), tuple(reported))

    return make


@pytest.fixture
def shell():
    def make(address, shell_pid, *, folder="/work"):
        return Terminal(address, shell_pid, Foreground("zsh", ("zsh", "-l"), folder), ())

    return make


@pytest.fixture
def busy():
    def make(address, shell_pid, *argv):
        return Terminal(address, shell_pid, Foreground(argv[0], tuple(argv), "/work"), ())

    return make
