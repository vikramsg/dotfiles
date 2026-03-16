import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
ZSH_HELPER = REPO_ROOT / "zsh/.zsh_screenshot"


def write_fake_screenshot(bin_dir: Path, source_file: Path, log_file: Path, *, home_dir: Path | None = None) -> Path:
    script = bin_dir / "screenshot"
    shell_safe_source = str(source_file)
    if home_dir is not None:
        shell_safe_source = str(source_file).replace(str(home_dir), "~", 1).replace(" ", "\\ ")
    script.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$*" >> "{log_file}"\n'
        'if [ "$1 $2" = "clipboard list" ]; then\n'
        '  printf "~/Screenshots/one.png\\n~/Screenshots/two.png\\n"\n'
        'elif [ "$1 $2 $3" = "clipboard copy --index" ]; then\n'
        '  if [ "$4" = "1" ]; then\n'
        f'    printf "%s\\n" "{shell_safe_source}"\n'
        '  else\n'
        '    printf "~/Screenshots/item-%s.png\\n" "$4"\n'
        '  fi\n'
        'else\n'
        '  exit 1\n'
        'fi\n'
    )
    script.chmod(0o755)
    return script


def run_ss_command(helper_file: Path, command: str, *, path: str, home_dir: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "zsh",
            "-f",
            "-c",
            f'source "{helper_file}" && {command}',
        ],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": path, **({"HOME": str(home_dir)} if home_dir is not None else {})},
    )


def test_ss_ls_delegates_to_screenshot_clipboard_list(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_file = tmp_path / "calls.log"
    source_file = tmp_path / "source.png"
    source_file.write_text("image")
    write_fake_screenshot(bin_dir, source_file, log_file)

    result = run_ss_command(ZSH_HELPER, "ss ls", path=f"{bin_dir}:{os.environ['PATH']}")

    assert result.stdout.splitlines() == ["~/Screenshots/one.png", "~/Screenshots/two.png"]
    assert log_file.read_text().splitlines() == ["clipboard list"]


def test_ss_numeric_index_copies_and_prints_that_history_item(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_file = tmp_path / "calls.log"
    source_file = tmp_path / "source.png"
    source_file.write_text("image")
    write_fake_screenshot(bin_dir, source_file, log_file)

    result = run_ss_command(ZSH_HELPER, "ss 2", path=f"{bin_dir}:{os.environ['PATH']}")

    assert result.stdout.strip() == "~/Screenshots/item-2.png"
    assert log_file.read_text().splitlines() == ["clipboard copy --index 2"]


def test_ss_cp_copies_item_one_to_requested_destination(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_file = tmp_path / "calls.log"
    home_dir = tmp_path / "home"
    source_file = home_dir / "Screenshots/source one.png"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("image")
    destination_dir = tmp_path / "dest"
    destination_dir.mkdir()
    write_fake_screenshot(bin_dir, source_file, log_file, home_dir=home_dir)

    result = run_ss_command(
        ZSH_HELPER,
        f'ss cp "{destination_dir}"',
        path=f"{bin_dir}:{os.environ['PATH']}",
        home_dir=home_dir,
    )

    copied_file = destination_dir / source_file.name
    assert copied_file.read_text() == "image"
    assert result.stdout.strip() == f"copying ~/Screenshots/source\\ one.png -> {destination_dir}"
    assert log_file.read_text().splitlines() == ["clipboard copy --index 1"]
