import asyncio
import json
import os
import signal
import socket
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol


class ChildProcess(Protocol):
    pid: int


ProcessFactory = Callable[..., Awaitable[ChildProcess]]
ReadinessProbe = Callable[[list[int]], bool]
XReadinessProbe = Callable[[int], bool]
AsyncSleep = Callable[[float], Awaitable[None]]


class AuthDesktopController:
    def __init__(
        self,
        *,
        runtime_dir: Path,
        profile_dir: Path,
        login_url: str | None,
        login_state: Callable[[], str | None],
        browser_stopped: Callable[[], bool],
        browser_executable: str = "google-chrome",
        novnc_port: int = 16080,
        process_factory: ProcessFactory = asyncio.create_subprocess_exec,
        getpgid: Callable[[int], int] = os.getpgid,
        killpg: Callable[[int, int], None] = os.killpg,
        x_readiness_probe: XReadinessProbe | None = None,
        readiness_probe: ReadinessProbe | None = None,
        process_alive: Callable[[int], bool] | None = None,
        process_group_alive: Callable[[int], bool] | None = None,
        graceful_browser_close: Callable[[], Awaitable[None]] | None = None,
        sleep: AsyncSleep = asyncio.sleep,
        readiness_attempts: int = 100,
        shutdown_attempts: int = 50,
    ) -> None:
        self._runtime_dir = runtime_dir
        self._profile_dir = profile_dir
        self._login_url = login_url
        self._login_state = login_state
        self._browser_stopped = browser_stopped
        self._browser_executable = browser_executable
        self._novnc_port = novnc_port
        self._process_factory = process_factory
        self._getpgid = getpgid
        self._killpg = killpg
        self._process_alive = process_alive or _pid_alive
        self._process_group_alive = process_group_alive or _group_alive
        self._graceful_browser_close = (
            graceful_browser_close or _close_desktop_browser
        )
        self._x_readiness_probe = x_readiness_probe or (
            lambda pid: self._process_alive(pid)
            and Path("/tmp/.X11-unix/X99").exists()
        )
        self._readiness_probe = readiness_probe or (
            lambda pids: _desktop_ready(
                pids, self._process_alive, self._novnc_port
            )
        )
        self._sleep = sleep
        self._readiness_attempts = readiness_attempts
        self._shutdown_attempts = shutdown_attempts
        self.lock = asyncio.Lock()
        self._loop = asyncio.new_event_loop()
        self._pid_file = runtime_dir / "auth-desktop.json"

    def start(self) -> None:
        self._loop.run_until_complete(self._start())

    async def _start(self) -> None:
        async with self.lock:
            if self._login_state() != "auth_required":
                raise RuntimeError("login state must be auth_required")
            if not self._browser_stopped():
                raise RuntimeError("browser worker must be stopped")
            if self._pid_file.exists():
                state = json.loads(self._pid_file.read_text())
                pids = state["pids"]
                groups = state["process_groups"]
                living_groups = [
                    group for group in groups if self._process_group_alive(group)
                ]
                if (
                    len(pids) == len(groups)
                    and len(living_groups) == len(groups)
                    and self._readiness_probe(pids)
                ):
                    return
                if living_groups:
                    raise RuntimeError("authentication desktop is already active")
                self._pid_file.unlink()

            self._runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._profile_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            display_environment = {**os.environ, "DISPLAY": ":99"}
            commands = [
                (("Xvfb", ":99", "-screen", "0", "1280x800x24"), {}),
                (("fluxbox",), {"env": display_environment}),
                (
                    (
                        self._browser_executable,
                        f"--user-data-dir={self._profile_dir}",
                        "--no-first-run",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--remote-debugging-address=127.0.0.1",
                        "--remote-debugging-port=19222",
                        *(tuple([self._login_url]) if self._login_url else ()),
                    ),
                    {"env": display_environment},
                ),
                (
                    (
                        "x11vnc",
                        "-display",
                        ":99",
                        "-localhost",
                        "-rfbport",
                        "15900",
                        "-forever",
                        "-shared",
                        "-nopw",
                    ),
                    {},
                ),
                (
                    (
                        "websockify",
                        "--web",
                        "/usr/share/novnc/",
                        f"127.0.0.1:{self._novnc_port}",
                        "127.0.0.1:15900",
                    ),
                    {},
                ),
            ]
            pids: list[int] = []
            groups: list[int] = []
            processes: list[tuple[str, ChildProcess]] = []
            try:
                x_command, x_options = commands[0]
                x_process = await self._process_factory(
                    *x_command, start_new_session=True, **x_options
                )
                pids.append(x_process.pid)
                groups.append(self._getpgid(x_process.pid))
                processes.append((x_command[0], x_process))
                await self._wait_for_x(x_process)

                for command, options in commands[1:]:
                    process = await self._process_factory(
                        *command, start_new_session=True, **options
                    )
                    pids.append(process.pid)
                    groups.append(self._getpgid(process.pid))
                    processes.append((command[0], process))
                await self._wait_until_ready(processes, pids)
                self._pid_file.write_text(
                    json.dumps({"process_groups": groups, "pids": pids})
                )
                self._pid_file.chmod(0o600)
            except Exception:
                await self._terminate(groups)
                raise

    def stop(self) -> None:
        self._loop.run_until_complete(self._stop())

    async def _stop(self) -> None:
        async with self.lock:
            if not self._pid_file.exists():
                return
            state = json.loads(self._pid_file.read_text())
            pids = state["pids"]
            groups = state["process_groups"]
            if len(pids) != len(groups):
                raise RuntimeError("invalid authentication desktop PID metadata")
            await self._graceful_browser_close()
            await self._terminate(groups)
            self._pid_file.unlink()

    async def _wait_for_x(self, process: ChildProcess) -> None:
        for _ in range(self._readiness_attempts):
            self._raise_for_exited_child([("Xvfb", process)])
            if self._x_readiness_probe(process.pid):
                self._raise_for_exited_child([("Xvfb", process)])
                return
            await self._sleep(0.1)
        self._raise_for_exited_child([("Xvfb", process)])
        raise RuntimeError("Xvfb did not become ready")

    async def _wait_until_ready(
        self,
        processes: list[tuple[str, ChildProcess]],
        pids: list[int],
    ) -> None:
        for _ in range(self._readiness_attempts):
            self._raise_for_exited_child(processes)
            if self._readiness_probe(pids):
                self._raise_for_exited_child(processes)
                return
            await self._sleep(0.1)
        self._raise_for_exited_child(processes)
        raise RuntimeError("authentication desktop did not become ready")

    @staticmethod
    def _raise_for_exited_child(
        processes: list[tuple[str, ChildProcess]],
    ) -> None:
        for name, process in processes:
            returncode = getattr(process, "returncode", None)
            if returncode is not None:
                raise RuntimeError(f"{name} exited during startup ({returncode})")

    async def _terminate(self, groups: list[int]) -> None:
        self._signal_groups(groups, signal.SIGTERM)
        remaining = await self._wait_for_groups(groups)
        if remaining:
            self._signal_groups(remaining, signal.SIGKILL)
            remaining = await self._wait_for_groups(remaining)
        if remaining:
            raise RuntimeError(
                "authentication desktop process groups did not stop: "
                + ", ".join(str(group) for group in remaining)
            )

    async def _wait_for_groups(self, groups: list[int]) -> list[int]:
        remaining = list(groups)
        for _ in range(self._shutdown_attempts):
            remaining = [
                group
                for group in remaining
                if self._process_group_alive(group)
            ]
            if not remaining:
                return []
            await self._sleep(0.1)
        return [
            group
            for group in remaining
            if self._process_group_alive(group)
        ]

    def _signal_groups(self, groups: list[int], sig: int) -> None:
        for group in reversed(groups):
            try:
                self._killpg(group, sig)
            except ProcessLookupError:
                pass


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _group_alive(group: int) -> bool:
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _desktop_ready(
    pids: list[int], process_alive: Callable[[int], bool], novnc_port: int
) -> bool:
    if not pids or not all(process_alive(pid) for pid in pids):
        return False
    if not Path("/tmp/.X11-unix/X99").exists():
        return False
    return _port_ready(15900) and _port_ready(novnc_port)


def _port_ready(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.05):
            return True
    except OSError:
        return False


async def _close_desktop_browser() -> None:
    try:
        from playwright.async_api import async_playwright

        playwright = await async_playwright().start()
        try:
            browser = await playwright.chromium.connect_over_cdp(
                "http://127.0.0.1:19222"
            )
            await browser.close()
        finally:
            await playwright.stop()
    except Exception:
        return
