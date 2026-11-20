from opencode_resume.terminals import Foreground, Terminal


def opencode(address, shell_pid, *, folder="/work", argv=("opencode",), reported=()):
    return Terminal(address, shell_pid, Foreground("opencode.exe", tuple(argv), folder), tuple(reported))


def shell(address, shell_pid, *, folder="/work"):
    return Terminal(address, shell_pid, Foreground("zsh", ("zsh", "-l"), folder), ())


def busy(address, shell_pid, program="vim"):
    return Terminal(address, shell_pid, Foreground(program, (program,), "/work"), ())
