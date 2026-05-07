"""CLI 기반 LLM 클라이언트 — claude / codex CLI 를 subprocess 로 호출.

사용 시나리오:
    · 사용자가 ChatGPT Plus / Claude Max 구독 보유 → CLI 인증된 상태에서
      blogitem 이 ``subprocess.run`` 으로 호출하면 추가 비용 0.
    · LlmClient Protocol 호환 — 기존 파이프라인 코드 변경 없이 갈아끼움.

Windows 함정 처리:
    · npm 글로벌 설치 CLI 는 ``.cmd`` / ``.ps1`` 두 종류 wrapper 생성.
    · ``shutil.which`` 가 ``.PS1`` 을 PATHEXT 에 포함 안 하면 못 찾음.
    · ``.ps1`` 발견 시 ``powershell -File`` 로 명시 실행.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import TYPE_CHECKING

from blogitem.ai.base import LlmResponse

if TYPE_CHECKING:
    from collections.abc import Sequence


# ANSI escape — codex 등 TUI CLI 출력에 섞인 색상 코드 제거용
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


class CliLlmError(RuntimeError):
    """CLI 기반 LLM 호출 실패."""

    def __init__(self, message: str, *, exit_code: int = 0, retryable: bool = False) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.retryable = retryable


# ── 핵심 클라이언트 ────────────────────────────────────────────────────────────


class CliLlmClient:
    """LLM CLI subprocess 래퍼.

    Args:
        bin_path: 실행 파일 경로 (절대경로 권장). ``.ps1`` 도 자동 처리.
        default_model: ``--model`` 인자에 넘길 기본 모델명. None 이면 미전달.
        extra_args: bin 뒤에 항상 붙는 인자 (예: ``["--print"]`` / ``["exec"]``).
        model_arg: 모델 지정 플래그명 (없으면 None).
        stdin_mode: True 면 프롬프트를 stdin 으로, False 면 마지막 positional 인자.
        strip_ansi: True 면 stdout 의 ANSI 컬러 코드 제거.
        timeout_sec: subprocess 타임아웃 (초).
        output_file_arg: 설정되면 임시 파일을 만들어 ``{output_file_arg} <path>`` 로
            전달, 호출 후 해당 파일에서 응답 읽음. codex 의 ``--output-last-message``
            처럼 stdout 에 banner/log 가 섞이는 CLI 에서 깨끗한 응답 추출용.
    """

    def __init__(
        self,
        *,
        bin_path: str,
        default_model: str | None = None,
        extra_args: Sequence[str] | None = None,
        model_arg: str | None = "--model",
        stdin_mode: bool = True,
        strip_ansi: bool = False,
        timeout_sec: int = 600,
        output_file_arg: str | None = None,
    ) -> None:
        if not bin_path:
            raise ValueError("bin_path required")
        self._bin_path = bin_path
        self._default_model = default_model
        self._extra_args = list(extra_args or [])
        self._model_arg = model_arg
        self._stdin_mode = stdin_mode
        self._strip_ansi = strip_ansi
        self._timeout = timeout_sec
        self._output_file_arg = output_file_arg

    def complete(
        self,
        *,
        system: str,
        user: str,
        model: str | None = None,
        max_tokens: int = 4096,  # noqa: ARG002 — CLI 는 토큰 제한 인자 없음
        temperature: float = 1.0,  # noqa: ARG002 — 동일
        on_line: callable | None = None,
    ) -> LlmResponse:
        """단일 메시지 호출. system + user 를 한 프롬프트로 합쳐 CLI 에 전달.

        Args:
            on_line: 콜백. 설정 시 ``subprocess.Popen`` 으로 라인 단위 stdout 을
                스트리밍 — 호출자(UI)가 실시간 표시 가능. None 이면 ``subprocess.run``
                blocking + 일괄 캡처 (테스트/단순 호출 호환).
        """
        if not user:
            raise ValueError("user prompt required")
        if on_line is not None:
            return self._complete_streaming(system=system, user=user, model=model, on_line=on_line)

        prompt = self._compose_prompt(system, user)
        chosen_model = model or self._default_model

        # output_file_arg 설정 시 임시 파일 생성. 응답 추출 후 정리 (try/finally).
        output_file_path: str | None = None
        if self._output_file_arg:
            import tempfile

            fd, output_file_path = tempfile.mkstemp(suffix=".txt", prefix="blogitem-cli-")
            os.close(fd)

        try:
            cmd = self._build_command(
                model=chosen_model,
                prompt=prompt,
                output_file=output_file_path,
            )
            try:
                result = subprocess.run(
                    cmd,
                    input=prompt if self._stdin_mode else None,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self._timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as e:
                raise CliLlmError(
                    f"CLI timeout after {self._timeout}s",
                    exit_code=0,
                    retryable=True,
                ) from e
            except FileNotFoundError as e:
                raise CliLlmError(
                    f"CLI binary not found: {self._bin_path}",
                    exit_code=0,
                    retryable=False,
                ) from e
            except OSError as e:
                raise CliLlmError(
                    f"CLI exec failed: {type(e).__name__}",
                    exit_code=0,
                    retryable=True,
                ) from e

            if result.returncode != 0:
                err_msg = (result.stderr or result.stdout or "").strip()[:500]
                # 인증 오류 / rate limit 추론 — exit code 만으로는 부족하지만 메시지로 분기
                retryable = _looks_retryable(err_msg)
                raise CliLlmError(
                    f"CLI exit {result.returncode}: {err_msg or '(no stderr)'}",
                    exit_code=result.returncode,
                    retryable=retryable,
                )

            # 응답 텍스트 추출 — output_file 이 있으면 거기서, 없으면 stdout 에서.
            if output_file_path is not None:
                try:
                    with open(output_file_path, encoding="utf-8") as f:
                        text = f.read()
                except OSError as e:
                    raise CliLlmError(
                        f"output file read failed: {type(e).__name__}",
                        exit_code=0,
                        retryable=False,
                    ) from e
            else:
                text = result.stdout or ""
                if self._strip_ansi:
                    text = _ANSI_RE.sub("", text)

            text = text.strip()

            # CLI 가 본문에 ERROR/limit 메시지를 응답처럼 출력하는 경우 감지 + 영구 실패로 분류
            if _looks_quota_exceeded(text):
                raise CliLlmError(
                    f"CLI quota/limit hit: {text[:200]}",
                    exit_code=0,
                    retryable=False,
                )

            if not text:
                raise CliLlmError(
                    "CLI returned empty response",
                    exit_code=0,
                    retryable=True,
                )

            return LlmResponse(
                text=text,
                model=chosen_model or "cli",
                # CLI 는 사용량 정보 안 줌 — 0 으로 남기고 호출 측은 비용 추적 못 함
                input_tokens=0,
                output_tokens=0,
            )
        finally:
            if output_file_path is not None:
                try:
                    os.unlink(output_file_path)
                except OSError:
                    pass

    # ── 스트리밍 호출 (subprocess.Popen) ───────────────────────────────────

    def _complete_streaming(
        self,
        *,
        system: str,
        user: str,
        model: str | None,
        on_line: callable,
    ) -> LlmResponse:
        """라인 단위 스트리밍 호출.

        ``subprocess.Popen`` 으로 stdout 을 라인 단위 읽으며 ``on_line`` 콜백 호출.
        UI 가 실시간으로 진행 상태 표시 가능.

        ``output_file_arg`` 사용 시: 파일에서 최종 응답 읽음 (스트리밍 동안엔 콜백
        으로 진행 표시). 사용 안 하면 누적 stdout 을 응답으로 사용.

        시간 초과 / 에러는 ``CliLlmError`` raise.
        """
        import subprocess
        import time

        prompt = self._compose_prompt(system, user)
        chosen_model = model or self._default_model

        output_file_path: str | None = None
        if self._output_file_arg:
            import tempfile

            fd, output_file_path = tempfile.mkstemp(suffix=".txt", prefix="blogitem-cli-")
            os.close(fd)

        cmd = self._build_command(
            model=chosen_model, prompt=prompt, output_file=output_file_path
        )

        captured: list[str] = []
        proc: subprocess.Popen[str] | None = None
        try:
            try:
                proc = subprocess.Popen(  # noqa: S603 — cmd 는 우리가 빌드, prompt 만 외부
                    cmd,
                    stdin=subprocess.PIPE if self._stdin_mode else subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,  # 진행 메시지가 stderr 로 나오는 CLI 도 있음
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,  # line-buffered
                )
            except FileNotFoundError as e:
                raise CliLlmError(
                    f"CLI binary not found: {self._bin_path}",
                    exit_code=0,
                    retryable=False,
                ) from e
            except OSError as e:
                raise CliLlmError(
                    f"CLI exec failed: {type(e).__name__}",
                    exit_code=0,
                    retryable=True,
                ) from e

            if self._stdin_mode and proc.stdin is not None:
                try:
                    proc.stdin.write(prompt)
                    proc.stdin.close()
                except OSError:
                    pass

            assert proc.stdout is not None
            deadline = time.time() + self._timeout

            while True:
                line = proc.stdout.readline()
                if not line:
                    if proc.poll() is not None:
                        break
                    if time.time() > deadline:
                        proc.terminate()
                        raise CliLlmError(
                            f"CLI timeout after {self._timeout}s",
                            exit_code=0,
                            retryable=True,
                        )
                    time.sleep(0.05)
                    continue

                rendered = line.rstrip("\n")
                if self._strip_ansi:
                    rendered = _ANSI_RE.sub("", rendered)
                captured.append(line)
                try:
                    on_line(rendered)
                except Exception:  # noqa: BLE001 — UI 콜백 실패는 호출 흐름 깨면 안 됨
                    pass

                if time.time() > deadline:
                    proc.terminate()
                    raise CliLlmError(
                        f"CLI timeout after {self._timeout}s",
                        exit_code=0,
                        retryable=True,
                    )

            try:
                returncode = proc.wait(timeout=5)
            except subprocess.TimeoutExpired as e:
                proc.kill()
                raise CliLlmError(
                    "CLI failed to exit cleanly", exit_code=0, retryable=True
                ) from e

            if returncode != 0:
                tail = "".join(captured[-20:]).strip()[:500]
                retryable = _looks_retryable(tail)
                raise CliLlmError(
                    f"CLI exit {returncode}: {tail or '(no output)'}",
                    exit_code=returncode,
                    retryable=retryable,
                )

            # 응답 텍스트 — output_file 이면 거기서, 아니면 누적 stdout.
            if output_file_path is not None:
                try:
                    with open(output_file_path, encoding="utf-8") as f:
                        text = f.read()
                except OSError as e:
                    raise CliLlmError(
                        f"output file read failed: {type(e).__name__}",
                        exit_code=0,
                        retryable=False,
                    ) from e
            else:
                text = "".join(captured)
                if self._strip_ansi:
                    text = _ANSI_RE.sub("", text)

            text = text.strip()

            if _looks_quota_exceeded(text):
                raise CliLlmError(
                    f"CLI quota/limit hit: {text[:200]}",
                    exit_code=0,
                    retryable=False,
                )

            if not text:
                raise CliLlmError(
                    "CLI returned empty response",
                    exit_code=0,
                    retryable=True,
                )

            return LlmResponse(
                text=text,
                model=chosen_model or "cli",
                input_tokens=0,
                output_tokens=0,
            )
        finally:
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
            if output_file_path is not None:
                try:
                    os.unlink(output_file_path)
                except OSError:
                    pass

    # ── 내부 ────────────────────────────────────────────────────────────────

    @staticmethod
    def _compose_prompt(system: str, user: str) -> str:
        """system + user 를 단일 프롬프트로 결합.

        대부분 CLI 는 system / user 를 별도로 받지 못함. 명시적 구분선으로 분리.
        """
        if not system:
            return user
        return (
            f"{system}\n"
            f"\n"
            f"---\n"
            f"\n"
            f"{user}"
        )

    def _build_command(
        self,
        *,
        model: str | None,
        prompt: str,
        output_file: str | None = None,
    ) -> list[str]:
        """argv 빌드. ``.ps1`` 은 powershell wrapper 로 감쌈.

        ``prompt`` 는 stdin_mode=False 일 때만 마지막 positional 로 추가.
        ``output_file`` 이 설정되면 ``{output_file_arg} <path>`` 도 추가.
        """
        argv: list[str] = [*self._extra_args]
        if model and self._model_arg:
            argv.extend([self._model_arg, model])
        if output_file and self._output_file_arg:
            argv.extend([self._output_file_arg, output_file])
        if not self._stdin_mode:
            argv.append(prompt)

        if os.name == "nt" and self._bin_path.lower().endswith(".ps1"):
            return [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                self._bin_path,
                *argv,
            ]
        return [self._bin_path, *argv]


# ── 팩토리: 알려진 CLI 별 설정 ─────────────────────────────────────────────────


def find_cli(name: str) -> str | None:
    """``shutil.which`` + Windows .cmd/.exe/.ps1 폴백."""
    path = shutil.which(name)
    if path:
        return path
    if os.name == "nt":
        for ext in (".cmd", ".exe", ".bat", ".ps1"):
            path = shutil.which(name + ext)
            if path:
                return path
    return None


def claude_cli_client(
    *,
    default_model: str | None = None,
    timeout_sec: int = 600,
) -> CliLlmClient:
    """Anthropic ``claude`` CLI 래퍼.

    invocation: ``claude --print --output-format text [--model X]`` (stdin 으로 프롬프트).
    """
    bin_path = find_cli("claude")
    if bin_path is None:
        raise FileNotFoundError(
            "`claude` CLI not on PATH — install: "
            "https://docs.claude.com/claude-code"
        )
    return CliLlmClient(
        bin_path=bin_path,
        default_model=default_model,
        extra_args=["--print", "--output-format", "text"],
        model_arg="--model",
        stdin_mode=True,
        strip_ansi=False,
        timeout_sec=timeout_sec,
    )


def codex_cli_client(
    *,
    default_model: str | None = None,
    timeout_sec: int = 600,
) -> CliLlmClient:
    """OpenAI ``codex`` CLI 래퍼.

    invocation:
        ``codex exec --skip-git-repo-check --sandbox read-only --color never
          [--model X] "prompt"``

    필수 플래그 이유:
        · ``--skip-git-repo-check`` — git repo 외부 실행 허용.
        · ``--sandbox read-only`` — 텍스트 생성만, 파일 쓰기/명령 실행 차단.
          기본값 ``workspace-write`` 는 첫 호출 시 승인 프롬프트로 hang.
        · ``--color never`` — 출력의 ANSI 색상 코드 제거 (파싱 안정성).
    """
    bin_path = find_cli("codex")
    if bin_path is None:
        raise FileNotFoundError(
            "`codex` CLI not on PATH — install: `npm i -g @openai/codex`"
        )
    return CliLlmClient(
        bin_path=bin_path,
        default_model=default_model,
        extra_args=[
            "exec",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--color",
            "never",
        ],
        model_arg="--model",
        stdin_mode=False,
        strip_ansi=True,
        timeout_sec=timeout_sec,
        # codex 는 stdout 에 banner/meta/log 가 섞임 →
        # --output-last-message 로 어시스턴트 응답만 깨끗한 파일에 받음.
        output_file_arg="--output-last-message",
    )


# ── 휴리스틱 ──────────────────────────────────────────────────────────────────


def _looks_retryable(stderr: str) -> bool:
    """CLI stderr 메시지로 재시도 가능 여부 추론. 보수적 — 모르면 False."""
    if not stderr:
        return False
    lower = stderr.lower()
    retryable_markers = (
        "rate limit",
        "rate-limit",
        "429",
        "timeout",
        "temporarily",
        "try again",
        "503",
        "502",
        "504",
        "network",
        "connection",
    )
    return any(m in lower for m in retryable_markers)


def _looks_quota_exceeded(text: str) -> bool:
    """CLI 본문에 사용량 한도 초과 표시가 있는지 — codex 등 일부 CLI 가
    exit 0 + 본문에 ERROR 를 박는 패턴 감지."""
    if not text:
        return False
    lower = text.lower()
    quota_markers = (
        "usage limit",
        "you've hit your usage",
        "quota exceeded",
        "credits exceeded",
        "monthly limit",
    )
    return any(m in lower for m in quota_markers)
