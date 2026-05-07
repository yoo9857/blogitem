"""CliLlmClient — subprocess 기반 LLM 호출 (claude / codex CLI)."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from blogitem.ai.cli_client import (
    CliLlmClient,
    CliLlmError,
    _looks_quota_exceeded,
    _looks_retryable,
    claude_cli_client,
    codex_cli_client,
    find_cli,
)


def _completed(
    *, returncode: int = 0, stdout: str = "응답", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["dummy"], returncode=returncode, stdout=stdout, stderr=stderr
    )


# ── 핵심 동작 ──────────────────────────────────────────────────────────────────


class TestComplete:
    def test_returns_response_text(self) -> None:
        client = CliLlmClient(
            bin_path="C:/fake/claude.exe",
            extra_args=["--print"],
            stdin_mode=True,
        )
        with patch("subprocess.run", return_value=_completed(stdout="hello world")) as m:
            resp = client.complete(system="sys", user="u")

        assert resp.text == "hello world"
        # 전달 인자 확인 — extra_args 가 포함되어야 함
        call_args = m.call_args
        assert call_args.args[0] == ["C:/fake/claude.exe", "--print"]
        # stdin_mode=True → input 으로 전달
        assert "sys" in call_args.kwargs["input"]
        assert "u" in call_args.kwargs["input"]

    def test_stdin_mode_false_uses_positional(self) -> None:
        client = CliLlmClient(
            bin_path="/fake/codex",
            extra_args=["exec"],
            stdin_mode=False,
            strip_ansi=True,
        )
        with patch("subprocess.run", return_value=_completed(stdout="ok")) as m:
            client.complete(system="s", user="u")

        # 마지막 인자가 prompt 문자열
        argv = m.call_args.args[0]
        assert argv[0] == "/fake/codex"
        assert argv[1] == "exec"
        assert "s" in argv[-1] and "u" in argv[-1]
        # input 은 None
        assert m.call_args.kwargs.get("input") is None

    def test_strip_ansi(self) -> None:
        client = CliLlmClient(
            bin_path="/x/codex",
            extra_args=["exec"],
            stdin_mode=False,
            strip_ansi=True,
        )
        with patch(
            "subprocess.run",
            return_value=_completed(stdout="\x1b[31m빨강\x1b[0m 끝"),
        ):
            resp = client.complete(system="", user="u")
        assert resp.text == "빨강 끝"

    def test_model_arg_appended_when_provided(self) -> None:
        client = CliLlmClient(
            bin_path="/x/claude",
            extra_args=["--print"],
            default_model="claude-opus-4-7",
            stdin_mode=True,
        )
        with patch("subprocess.run", return_value=_completed()) as m:
            client.complete(system="", user="u")
        argv = m.call_args.args[0]
        assert "--model" in argv
        assert "claude-opus-4-7" in argv

    def test_no_model_arg_when_disabled(self) -> None:
        client = CliLlmClient(
            bin_path="/x/cli",
            extra_args=["run"],
            default_model="ignored",
            model_arg=None,
            stdin_mode=False,
        )
        with patch("subprocess.run", return_value=_completed()) as m:
            client.complete(system="", user="u")
        argv = m.call_args.args[0]
        assert "--model" not in argv
        assert "ignored" not in argv

    def test_explicit_model_overrides_default(self) -> None:
        client = CliLlmClient(
            bin_path="/x/claude",
            default_model="opus",
            stdin_mode=True,
        )
        with patch("subprocess.run", return_value=_completed()) as m:
            client.complete(system="", user="u", model="haiku")
        argv = m.call_args.args[0]
        idx = argv.index("--model")
        assert argv[idx + 1] == "haiku"

    def test_empty_user_rejected(self) -> None:
        client = CliLlmClient(bin_path="/x/c", stdin_mode=True)
        with pytest.raises(ValueError, match="user"):
            client.complete(system="s", user="")


# ── 에러 분기 ──────────────────────────────────────────────────────────────────


class TestErrorMapping:
    def test_nonzero_exit_raises(self) -> None:
        client = CliLlmClient(bin_path="/x/c", stdin_mode=True)
        with patch(
            "subprocess.run",
            return_value=_completed(returncode=1, stderr="bad input"),
        ):
            with pytest.raises(CliLlmError) as exc:
                client.complete(system="", user="u")
        assert exc.value.exit_code == 1
        assert exc.value.retryable is False
        assert "bad input" in str(exc.value)

    def test_5xx_marked_retryable_via_stderr(self) -> None:
        client = CliLlmClient(bin_path="/x/c", stdin_mode=True)
        with patch(
            "subprocess.run",
            return_value=_completed(returncode=1, stderr="server returned 503"),
        ):
            with pytest.raises(CliLlmError) as exc:
                client.complete(system="", user="u")
        assert exc.value.retryable is True

    def test_rate_limit_retryable(self) -> None:
        client = CliLlmClient(bin_path="/x/c", stdin_mode=True)
        with patch(
            "subprocess.run",
            return_value=_completed(returncode=1, stderr="Rate limit exceeded; try again"),
        ):
            with pytest.raises(CliLlmError) as exc:
                client.complete(system="", user="u")
        assert exc.value.retryable is True

    def test_timeout_marked_retryable(self) -> None:
        client = CliLlmClient(bin_path="/x/c", stdin_mode=True, timeout_sec=5)
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="x", timeout=5),
        ):
            with pytest.raises(CliLlmError) as exc:
                client.complete(system="", user="u")
        assert exc.value.retryable is True
        assert "5s" in str(exc.value)

    def test_binary_not_found_not_retryable(self) -> None:
        client = CliLlmClient(bin_path="/nope/c", stdin_mode=True)
        with patch("subprocess.run", side_effect=FileNotFoundError("nope")):
            with pytest.raises(CliLlmError) as exc:
                client.complete(system="", user="u")
        assert exc.value.retryable is False

    def test_empty_response_marked_retryable(self) -> None:
        client = CliLlmClient(bin_path="/x/c", stdin_mode=True)
        with patch("subprocess.run", return_value=_completed(stdout="   \n")):
            with pytest.raises(CliLlmError) as exc:
                client.complete(system="", user="u")
        assert exc.value.retryable is True


# ── retryable 휴리스틱 ────────────────────────────────────────────────────────


class TestLooksRetryable:
    def test_rate_limit_keywords(self) -> None:
        assert _looks_retryable("Rate limit exceeded")
        assert _looks_retryable("HTTP 429 too many")
        assert _looks_retryable("Network error")
        assert _looks_retryable("Connection refused")

    def test_5xx(self) -> None:
        assert _looks_retryable("503 service unavailable")
        assert _looks_retryable("502 bad gateway")

    def test_unknown_not_retryable(self) -> None:
        assert not _looks_retryable("some random error")
        assert not _looks_retryable("authentication failed")

    def test_empty_returns_false(self) -> None:
        assert not _looks_retryable("")


# ── PowerShell wrapper (.ps1) ─────────────────────────────────────────────────


class TestPowerShellWrapper:
    def test_ps1_wrapped_with_powershell(self) -> None:
        """Windows .ps1 파일은 powershell -File 로 감싸 실행."""
        client = CliLlmClient(
            bin_path="C:/foo/codex.ps1",
            extra_args=["exec"],
            stdin_mode=False,
        )
        with patch("os.name", "nt"), patch(
            "subprocess.run", return_value=_completed(stdout="ok")
        ) as m:
            client.complete(system="", user="u")
        argv = m.call_args.args[0]
        assert argv[0] == "powershell"
        assert "-File" in argv
        assert "C:/foo/codex.ps1" in argv
        # extra_args 도 같이 전달
        assert "exec" in argv


# ── 팩토리 ──────────────────────────────────────────────────────────────────────


class TestFactories:
    def test_claude_factory_raises_when_missing(self) -> None:
        with patch("blogitem.ai.cli_client.find_cli", return_value=None):
            with pytest.raises(FileNotFoundError, match="claude"):
                claude_cli_client()

    def test_codex_factory_raises_when_missing(self) -> None:
        with patch("blogitem.ai.cli_client.find_cli", return_value=None):
            with pytest.raises(FileNotFoundError, match="codex"):
                codex_cli_client()

    def test_claude_factory_uses_stdin_mode(self) -> None:
        with patch(
            "blogitem.ai.cli_client.find_cli", return_value="/fake/claude"
        ):
            client = claude_cli_client(default_model="opus")
        # 핵심 설정 확인 — extra_args 에 --print 포함
        assert "--print" in client._extra_args
        assert client._stdin_mode is True

    def test_codex_factory_uses_positional(self) -> None:
        with patch(
            "blogitem.ai.cli_client.find_cli", return_value="/fake/codex"
        ):
            client = codex_cli_client()
        assert "exec" in client._extra_args
        # 첫 호출 hang 방지 플래그 — sandbox 승인 프롬프트 회피
        assert "--skip-git-repo-check" in client._extra_args
        assert "--sandbox" in client._extra_args
        assert "read-only" in client._extra_args
        assert "--color" in client._extra_args
        assert "never" in client._extra_args
        assert client._stdin_mode is False
        assert client._strip_ansi is True


class TestFindCli:
    def test_returns_path_when_found(self) -> None:
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            assert find_cli("claude") == "/usr/local/bin/claude"

    def test_returns_none_when_missing(self) -> None:
        with patch("shutil.which", return_value=None), patch("os.name", "posix"):
            assert find_cli("nope") is None


# ── output_file_arg (codex --output-last-message 패턴) ────────────────────────


class TestOutputFile:
    def test_response_read_from_output_file(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """``output_file_arg`` 설정 시 stdout 무시하고 파일에서 응답 읽어야 함."""
        client = CliLlmClient(
            bin_path="/x/codex",
            extra_args=["exec"],
            stdin_mode=False,
            output_file_arg="--output-last-message",
        )

        captured_args: list[list[str]] = []

        def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
            captured_args.append(cmd)
            # cmd 안의 --output-last-message 다음 인자가 임시 파일 경로
            idx = cmd.index("--output-last-message")
            file_path = cmd[idx + 1]
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("clean response\n")
            return _completed(stdout="banner garbage [should be ignored]")

        with patch("subprocess.run", side_effect=fake_run):
            resp = client.complete(system="", user="prompt")

        assert resp.text == "clean response"
        # 임시 파일이 정리됐는지
        idx = captured_args[0].index("--output-last-message")
        tmp_file = captured_args[0][idx + 1]
        from pathlib import Path
        assert not Path(tmp_file).exists()

    def test_output_file_unlinked_even_on_error(self) -> None:
        client = CliLlmClient(
            bin_path="/x/codex",
            extra_args=["exec"],
            stdin_mode=False,
            output_file_arg="--output-last-message",
        )

        captured_paths: list[str] = []

        def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
            idx = cmd.index("--output-last-message")
            captured_paths.append(cmd[idx + 1])
            return _completed(returncode=1, stderr="server returned 503")

        with patch("subprocess.run", side_effect=fake_run):
            with pytest.raises(CliLlmError):
                client.complete(system="", user="u")

        from pathlib import Path
        assert captured_paths
        assert not Path(captured_paths[0]).exists()


# ── 사용량 한도 본문 ──────────────────────────────────────────────────────────


class TestQuotaExceeded:
    def test_detects_usage_limit(self) -> None:
        assert _looks_quota_exceeded("ERROR: You've hit your usage limit. Upgrade to Pro.")
        assert _looks_quota_exceeded("Monthly limit reached")
        assert _looks_quota_exceeded("Quota exceeded")

    def test_clean_text_not_quota(self) -> None:
        assert not _looks_quota_exceeded("Hello world")
        assert not _looks_quota_exceeded("")

    def test_quota_text_raises_permanent_error(self) -> None:
        client = CliLlmClient(
            bin_path="/x/c",
            stdin_mode=True,
        )
        # codex 처럼 exit 0 + 본문에 ERROR 박는 케이스
        with patch(
            "subprocess.run",
            return_value=_completed(stdout="ERROR: You've hit your usage limit"),
        ):
            with pytest.raises(CliLlmError) as exc:
                client.complete(system="", user="u")
        assert exc.value.retryable is False
        assert "limit" in str(exc.value).lower()


class TestCodexFactoryOutputFile:
    def test_codex_factory_uses_output_last_message(self) -> None:
        with patch(
            "blogitem.ai.cli_client.find_cli", return_value="/fake/codex"
        ):
            client = codex_cli_client()
        assert client._output_file_arg == "--output-last-message"
