import asyncio
import os
import re
import shutil
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol

import anthropic
from anthropic.types import TextBlock
from moonlighter.core.config import llm_backend, moonlighter_home
from moonlighter.core.metrics import record_call


class LLMCaller(Protocol):
    """LLM caller protocol: accepts prompt, model, and optional cache_prefix."""

    async def __call__(self, prompt: str, model: str, cache_prefix: str | None = None) -> str: ...


# Signals that the LLM exhausted its quota/spend limit — worth aborting the
# scan and retrying later, instead of treating it as a per-job error.
SPEND_LIMIT_MARKERS = (
    "spend limit",
    "session limit",
    "quota",
    "rate limit",
    "too many requests",
    "overloaded",
    "429",
    "usage limit",
)

# Word-boundary match so markers only fire on real tokens: bare substring
# matching let "quota" match inside "quotation" and "429" match inside "4290",
# false-positive-aborting the whole scan on unrelated JSON/network errors.
_SPEND_LIMIT_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(marker) for marker in SPEND_LIMIT_MARKERS) + r")\b"
)


def is_spend_limit(exc: Exception) -> bool:
    """True if the exception indicates the LLM's quota/spend limit was exhausted."""
    msg = str(exc).lower()
    return bool(_SPEND_LIMIT_PATTERN.search(msg))


def make_caller(config: dict[str, Any]) -> LLMCaller:
    """Return the appropriate LLM caller based on config['llm_backend'].

    llm_backend: "cli"     → uses the `claude -p` CLI (no API key required)
    llm_backend: "api"     → uses the Anthropic Python SDK (requires ANTHROPIC_API_KEY)
    llm_backend: "cursor"  → uses the Cursor `agent --print` CLI (`agent login`)
    Default: "cli". Anything else raises ConfigError rather than silently
    selecting a backend the user did not ask for.
    """
    backend = llm_backend(config)
    if backend == "cli":
        return _call_cli
    if backend == "cursor":
        return _call_cursor
    return make_api_caller()


# Sandbox posture validated empirically (canary experiment, 2026-07-09 —
# specs/2026-07-09-s2-canary-experiment-results.md): without this, the default
# `-p` reads any file on disk with no permission prompt, sees 168 account MCP
# tools, and injects the operator's global CLAUDE.md into every job evaluation.
# --bare NEVER goes here: it disables OAuth/keychain, the subscription auth
# the entire 'cli' backend exists to use.
_CLI_SANDBOX_ARGS: tuple[str, ...] = (
    "--safe-mode",
    "--no-session-persistence",
    "--tools",
    "",
    "--strict-mcp-config",
    "--mcp-config",
    '{"mcpServers":{}}',
)


def _cli_workdir() -> Path:
    """Dedicated, neutral cwd for the CLI subprocess — never the repository
    (S-02): a cwd with nothing of value for a compromised agent to explore."""
    workdir = moonlighter_home() / "cli-workdir"
    workdir.mkdir(parents=True, exist_ok=True)
    workdir.chmod(0o700)
    return workdir


async def _call_cli(prompt: str, model: str, cache_prefix: str | None = None) -> str:
    """Call Claude via the installed `claude` CLI subprocess, sandboxed.

    Uses the active Claude Code session — no API key needed.
    The `model` parameter is ignored (CLI uses whichever model the session provides).
    The cache_prefix is concatenated before the prompt (the CLI doesn't expose cache_control);
    the actual caching effect only exists in the api backend.

    The prompt goes over STDIN, never argv (S-01): this removes the exposure in
    `ps` and makes argument injection structurally impossible (there's no prompt
    in argv to become a flag). The subprocess runs with an explicit set of
    lockdown flags (S-02/S-14/S-15) and in a neutral cwd outside the repository.
    """
    full = f"{cache_prefix}\n\n{prompt}" if cache_prefix is not None else prompt
    # Strip ANTHROPIC_API_KEY so the CLI uses the claude.ai session (subscription)
    # instead of the API key (which requires separate API credits).
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    exe = shutil.which("claude")
    if exe is None:
        raise RuntimeError(
            "the `claude` CLI was not found on PATH. Install it, or put it on PATH — "
            "this project uses the CLI backend (the claude.ai subscription), not an API key."
        )
    start = perf_counter()
    try:
        proc = await asyncio.create_subprocess_exec(
            exe,
            *_CLI_SANDBOX_ARGS,
            "-p",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=str(_cli_workdir()),
        )
        stdout, stderr = await proc.communicate(input=full.encode())
        if proc.returncode != 0:
            detail = stderr.decode().strip() or stdout.decode().strip()
            raise RuntimeError(f"claude CLI exited with code {proc.returncode}: {detail[:300]}")
        return stdout.decode()
    finally:
        record_call(perf_counter() - start)


# Ask mode is read-only. Sandbox stays on, the workspace is trusted without a
# prompt, and nothing here is --force / --yolo / --approve-mcps: a scoring
# subprocess must not gain write, shell, or MCP approval.
_CURSOR_SANDBOX_ARGS: tuple[str, ...] = (
    "--print",
    "--output-format",
    "text",
    "--mode",
    "ask",
    "--sandbox",
    "enabled",
    "--trust",
)


def _cursor_executable() -> str | None:
    """`agent` on PATH, otherwise the older `cursor-agent` binary name."""
    return shutil.which("agent") or shutil.which("cursor-agent")


async def _call_cursor(prompt: str, model: str, cache_prefix: str | None = None) -> str:
    """Call Cursor via the installed `agent` CLI, sandboxed.

    Same contract as `_call_cli`: prompt over STDIN (never argv), neutral cwd,
    and `model` ignored. Config models are Anthropic ids (`claude-sonnet-4-6`,
    `claude-haiku-4-5-...`); the Cursor CLI rejects them, so the account's model
    is used instead. `cache_prefix` is concatenated before the prompt — the CLI
    has no cache_control.

    `--workspace` is the same 0700 directory `_call_cli` uses, so the subprocess
    does not inherit this repository's MCP servers and re-enter moonlighter.
    """
    full = f"{cache_prefix}\n\n{prompt}" if cache_prefix is not None else prompt
    exe = _cursor_executable()
    if exe is None:
        raise RuntimeError(
            "the `agent` CLI was not found on PATH (also looked for `cursor-agent`). "
            "Install the Cursor CLI and run `agent login`."
        )
    workdir = str(_cli_workdir())
    start = perf_counter()
    try:
        proc = await asyncio.create_subprocess_exec(
            exe,
            *_CURSOR_SANDBOX_ARGS,
            "--workspace",
            workdir,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workdir,
        )
        stdout, stderr = await proc.communicate(input=full.encode())
        if proc.returncode != 0:
            detail = stderr.decode().strip() or stdout.decode().strip()
            raise RuntimeError(f"agent CLI exited with code {proc.returncode}: {detail[:300]}")
        return stdout.decode()
    finally:
        record_call(perf_counter() - start)


def make_api_caller(max_tokens: int = 2048) -> LLMCaller:
    """Return an async caller that uses the Anthropic Python SDK.

    Requires ANTHROPIC_API_KEY in the environment.
    """
    client = anthropic.AsyncAnthropic()

    async def _call(prompt: str, model: str, cache_prefix: str | None = None) -> str:
        # When cache_prefix is provided, sends two blocks: the static prefix
        # with ephemeral cache_control (marked for caching on Anthropic's side)
        # followed by the dynamic prompt. Without a prefix, sends a plain string (backcompat).
        if cache_prefix is not None:
            content: Any = [
                {"type": "text", "text": cache_prefix, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": prompt},
            ]
        else:
            content = prompt
        start = perf_counter()
        input_tokens = output_tokens = 0
        try:
            message = await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": content}],
            )
            input_tokens = message.usage.input_tokens
            output_tokens = message.usage.output_tokens
            block = message.content[0]
            if not isinstance(block, TextBlock):
                raise RuntimeError("unexpected model response (non-text block)")
            return block.text
        finally:
            record_call(
                perf_counter() - start, input_tokens=input_tokens, output_tokens=output_tokens
            )

    return _call
