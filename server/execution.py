"""Fresh bot subprocess per decision; bounded output, timeouts and compile cache.

This is an executor for trusted code, not an operating-system sandbox.
"""

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from threading import Lock, Thread

from .bots import entry_file, package_path

_PROCESS_SLOT = Lock()


@dataclass
class Execution:
    input: str
    stdout: str = ""
    stderr: str = ""
    duration_ms: float = 0
    exit_code: int | None = None
    status: str = "success"
    diagnostic: str = ""

    def action(self):
        try:
            value = json.loads(self.stdout)
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (ValueError, TypeError):
            self.status = "protocol_error"
            self.diagnostic = "Output must be one JSON object."
            return None


class Executor:
    def __init__(self, settings):
        self.settings = settings
        self.compile_lock = Lock()

    def _environment(self):
        keep = (
            "PATH",
            "SystemRoot",
            "WINDIR",
            "TEMP",
            "TMP",
            "COMSPEC",
            "PATHEXT",
            "LD_LIBRARY_PATH",
        )
        return {key: os.environ[key] for key in keep if key in os.environ} | {
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }

    def _run(self, command, cwd, text, timeout):
        with _PROCESS_SLOT:
            return self._run_exclusive(command, cwd, text, timeout)

    def _run_exclusive(self, command, cwd, text, timeout):
        result = Execution(text)
        start = time.perf_counter()
        process = None
        buffers = [bytearray(), bytearray()]
        exceeded = []

        def terminate():
            if process and process.poll() is None:
                try:
                    if os.name != "nt":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                except ProcessLookupError:
                    pass

        def read(stream, target):
            count = 0
            try:
                while block := stream.read(8192):
                    count += len(block)
                    if len(target) < 65536:
                        target.extend(block[: 65536 - len(target)])
                    if count > 1024 * 1024:
                        exceeded.append(True)
                        terminate()
                        break
            finally:
                stream.close()

        def write():
            try:
                process.stdin.write((text + "\n").encode())
                process.stdin.close()
            except (OSError, ValueError):
                pass

        try:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self._environment(),
                start_new_session=os.name != "nt",
            )
            readers = [
                Thread(target=read, args=(process.stdout, buffers[0]), daemon=True),
                Thread(target=read, args=(process.stderr, buffers[1]), daemon=True),
            ]
            for thread in readers:
                thread.start()
            writer = Thread(target=write, daemon=True)
            writer.start()
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                result.status = "timeout"
                result.diagnostic = "Execution exceeded its time limit."
                terminate()
                process.wait(timeout=3)
            for thread in readers:
                thread.join(timeout=1)
            writer.join(timeout=1)
            result.exit_code = process.returncode
            if exceeded:
                result.status = "execution_error"
                result.diagnostic = "Output exceeded 1 MiB."
            elif result.status == "success" and process.returncode:
                result.status = "runtime_error"
                result.diagnostic = "Process exited with a non-zero code."
        except (OSError, subprocess.SubprocessError):
            terminate()
            result.status = "execution_error"
            result.diagnostic = "Unable to run the bot process."
        finally:
            result.duration_ms = round((time.perf_counter() - start) * 1000, 3)
            result.stdout, result.stderr = [
                bytes(buffer).decode("utf-8", "replace") for buffer in buffers
            ]
        return result

    def _compile(self, directory, entry):
        digest = hashlib.sha256()
        base = directory if directory.is_dir() else directory.parent
        for path in sorted(base.rglob("*")):
            if (
                path.is_file()
                and not path.is_symlink()
                and "__pycache__" not in path.parts
            ):
                digest.update(path.relative_to(base).as_posix().encode())
                digest.update(path.read_bytes())
        # Imported shared headers are runtime bot dependencies, never judge code.
        includes = self.settings.data_dir / "bot-include"
        if includes.exists():
            for path in sorted(includes.rglob("*")):
                if path.is_file():
                    digest.update(path.read_bytes())
        digest.update(b"cpp17-O2-v1")
        binary = (
            self.settings.data_dir
            / "cache"
            / "cpp"
            / digest.hexdigest()
            / ("bot.exe" if os.name == "nt" else "bot")
        )
        with self.compile_lock:
            if not binary.is_file():
                binary.parent.mkdir(parents=True, exist_ok=True)
                result = self._run(
                    [
                        os.environ.get("CXX", "g++"),
                        "-std=c++17",
                        "-O2",
                        str(entry),
                        "-I",
                        str(base),
                        "-I",
                        str(includes),
                        "-o",
                        str(binary),
                    ],
                    base,
                    "",
                    60,
                )
                if result.status != "success":
                    result.status = "compile_error"
                    result.diagnostic = "C++ compilation failed."
                    return None, result
        return binary, None

    def execute(self, version, payload, *, timeout=None):
        text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        try:
            directory = package_path(self.settings, version)
            entry = entry_file(directory, version["language"])
            command = [sys.executable, str(entry)]
            if version["language"] == "cpp":
                binary, error = self._compile(directory, entry)
                if error:
                    error.input = text
                    return error
                command = [str(binary)]
            return self._run(
                command,
                entry.parent,
                text,
                self.settings.step_timeout if timeout is None else timeout,
            )
        except (ValueError, OSError):
            return Execution(
                text,
                status="execution_error",
                diagnostic="Bot package or entry file is unavailable.",
            )
