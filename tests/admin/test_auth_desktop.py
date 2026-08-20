import asyncio
import json
import signal

import pytest


class FakeProcess:
    def __init__(self, pid):
        self.pid = pid
        self.returncode = None


class ProcessFactory:
    def __init__(self):
        self.calls = []
        self.processes = []

    async def __call__(self, *command, **kwargs):
        self.calls.append((command, kwargs))
        process = FakeProcess(3000 + len(self.calls))
        self.processes.append(process)
        return process


async def no_delay(_seconds):
    return None


def make_controller(tmp_path, process_factory, **overrides):
    from dzmm_bot.auth_desktop import AuthDesktopController

    options = {
        "runtime_dir": tmp_path / "runtime",
        "profile_dir": tmp_path / "profile",
        "login_url": "https://chat.example/login",
        "login_state": lambda: "auth_required",
        "browser_stopped": lambda: True,
        "process_factory": process_factory,
        "getpgid": lambda pid: pid + 100,
        "killpg": lambda pgid, sig: None,
        "x_readiness_probe": lambda _pid: True,
        "readiness_probe": lambda _pids: True,
        "process_alive": lambda _pid: False,
        "process_group_alive": lambda _pgid: False,
        "sleep": no_delay,
    }
    options.update(overrides)
    return AuthDesktopController(**options)


def test_start_requires_auth_required_and_stopped_browser(tmp_path):
    factory = ProcessFactory()
    wrong_state = make_controller(
        tmp_path, factory, login_state=lambda: "ready"
    )
    running_browser = make_controller(
        tmp_path, factory, browser_stopped=lambda: False
    )

    with pytest.raises(RuntimeError, match="auth_required"):
        wrong_state.start()
    with pytest.raises(RuntimeError, match="stopped"):
        running_browser.start()

    assert factory.calls == []


def test_start_spawns_isolated_desktop_and_loopback_novnc(tmp_path):
    factory = ProcessFactory()
    controller = make_controller(tmp_path, factory)

    controller.start()

    commands = [call[0] for call in factory.calls]
    assert [command[0] for command in commands] == [
        "Xvfb",
        "fluxbox",
        "google-chrome",
        "x11vnc",
        "websockify",
    ]
    assert all(call[1]["start_new_session"] is True for call in factory.calls)
    chrome = commands[2]
    assert f"--user-data-dir={tmp_path / 'profile'}" in chrome
    assert "--no-sandbox" in chrome
    assert "--remote-debugging-port=19222" in chrome
    assert "https://chat.example/login" in chrome
    x11vnc = commands[3]
    assert "-localhost" in x11vnc
    novnc = commands[4]
    assert "127.0.0.1:16080" in novnc
    assert "127.0.0.1:15900" in novnc

    pid_data = json.loads((tmp_path / "runtime" / "auth-desktop.json").read_text())
    assert pid_data == {
        "process_groups": [3101, 3102, 3103, 3104, 3105],
        "pids": [3001, 3002, 3003, 3004, 3005],
    }


def test_start_uses_the_configured_browser_executable(tmp_path):
    factory = ProcessFactory()
    controller = make_controller(
        tmp_path, factory, browser_executable="/opt/dzmm/chromium"
    )

    controller.start()

    assert factory.calls[2][0][0] == "/opt/dzmm/chromium"


def test_stop_signals_only_recorded_process_groups_and_removes_pid_file(tmp_path):
    factory = ProcessFactory()
    signals = []
    controller = make_controller(
        tmp_path,
        factory,
        killpg=lambda pgid, sig: signals.append((pgid, sig)),
        login_state=lambda: "auth_in_progress",
    )
    pid_file = tmp_path / "runtime" / "auth-desktop.json"
    pid_file.parent.mkdir()
    pid_file.write_text(
        json.dumps({"pids": [10, 20], "process_groups": [110, 120]})
    )

    controller.stop()

    assert signals == [(120, signal.SIGTERM), (110, signal.SIGTERM)]
    assert not pid_file.exists()
    assert factory.calls == []


def test_stop_closes_the_browser_before_terminating_the_desktop(tmp_path):
    factory = ProcessFactory()
    events = []

    async def close_browser():
        events.append("browser")

    controller = make_controller(
        tmp_path,
        factory,
        graceful_browser_close=close_browser,
        killpg=lambda _pgid, _sig: events.append("terminate"),
        login_state=lambda: "auth_in_progress",
    )
    pid_file = tmp_path / "runtime" / "auth-desktop.json"
    pid_file.parent.mkdir()
    pid_file.write_text(json.dumps({"pids": [10], "process_groups": [110]}))

    controller.stop()

    assert events == ["browser", "terminate"]


def test_start_rejects_an_existing_unhealthy_desktop_pid_file(tmp_path):
    factory = ProcessFactory()
    controller = make_controller(
        tmp_path,
        factory,
        process_group_alive=lambda _pgid: True,
        readiness_probe=lambda _pids: False,
    )
    pid_file = tmp_path / "runtime" / "auth-desktop.json"
    pid_file.parent.mkdir()
    pid_file.write_text(json.dumps({"pids": [10], "process_groups": [110]}))

    with pytest.raises(RuntimeError, match="already active"):
        controller.start()

    assert factory.calls == []


def test_start_reuses_an_existing_ready_desktop(tmp_path):
    factory = ProcessFactory()
    controller = make_controller(
        tmp_path,
        factory,
        process_alive=lambda _pid: True,
        process_group_alive=lambda _pgid: True,
        readiness_probe=lambda _pids: True,
    )
    pid_file = tmp_path / "runtime" / "auth-desktop.json"
    pid_file.parent.mkdir()
    pid_file.write_text(json.dumps({"pids": [10], "process_groups": [110]}))

    controller.start()

    assert factory.calls == []
    assert pid_file.exists()


def test_controller_exposes_one_asyncio_lock_for_lifecycle(tmp_path):
    factory = ProcessFactory()
    controller = make_controller(tmp_path, factory)

    assert isinstance(controller.lock, asyncio.Lock)


def test_controller_keeps_its_event_loop_alive_while_desktop_is_running(tmp_path):
    factory = ProcessFactory()
    controller = make_controller(tmp_path, factory)

    controller.start()

    assert not controller._loop.is_closed()


def test_controller_satisfies_the_browser_workers_synchronous_desktop_port(
    tmp_path,
):
    factory = ProcessFactory()
    controller = make_controller(tmp_path, factory)

    result = controller.start()

    assert result is None
    assert len(factory.calls) == 5


def test_start_waits_for_readiness_before_persisting_pid_metadata(tmp_path):
    factory = ProcessFactory()
    pid_file = tmp_path / "runtime" / "auth-desktop.json"
    observations = []

    def readiness_probe(pids):
        observations.append((list(pids), pid_file.exists()))
        return len(observations) == 2

    controller = make_controller(
        tmp_path,
        factory,
        readiness_probe=readiness_probe,
        readiness_attempts=2,
    )

    controller.start()

    assert observations == [
        ([3001, 3002, 3003, 3004, 3005], False),
        ([3001, 3002, 3003, 3004, 3005], False),
    ]
    assert pid_file.exists()


def test_start_waits_for_xvfb_before_spawning_desktop_children(tmp_path):
    factory = ProcessFactory()
    observations = []

    def x_readiness_probe(pid):
        observations.append(
            (pid, [call[0][0] for call in factory.calls])
        )
        return len(observations) == 2

    controller = make_controller(
        tmp_path,
        factory,
        x_readiness_probe=x_readiness_probe,
        readiness_attempts=2,
    )

    controller.start()

    assert observations == [
        (3001, ["Xvfb"]),
        (3001, ["Xvfb"]),
    ]
    assert [call[0][0] for call in factory.calls] == [
        "Xvfb",
        "fluxbox",
        "google-chrome",
        "x11vnc",
        "websockify",
    ]


def test_start_monitors_children_and_cleans_up_if_one_exits(tmp_path):
    factory = ProcessFactory()
    signals = []

    def readiness_probe(_pids):
        factory.processes[2].returncode = 1
        return False

    controller = make_controller(
        tmp_path,
        factory,
        readiness_probe=readiness_probe,
        killpg=lambda pgid, sig: signals.append((pgid, sig)),
    )

    with pytest.raises(RuntimeError, match="google-chrome exited"):
        controller.start()

    assert signals == [
        (3105, signal.SIGTERM),
        (3104, signal.SIGTERM),
        (3103, signal.SIGTERM),
        (3102, signal.SIGTERM),
        (3101, signal.SIGTERM),
    ]
    assert not (tmp_path / "runtime" / "auth-desktop.json").exists()


def test_stop_waits_then_escalates_and_keeps_metadata_until_children_exit(
    tmp_path,
):
    factory = ProcessFactory()
    pid_file = tmp_path / "runtime" / "auth-desktop.json"
    pid_file.parent.mkdir()
    pid_file.write_text(
        json.dumps({"pids": [10, 20], "process_groups": [110, 120]})
    )
    alive = {110: True, 120: False}
    observations = []
    signals = []

    def process_group_alive(pgid):
        observations.append(pid_file.exists())
        return alive[pgid]

    def killpg(pgid, sig):
        signals.append((pgid, sig))
        if sig == signal.SIGKILL and pgid == 110:
            alive[110] = False

    controller = make_controller(
        tmp_path,
        factory,
        process_group_alive=process_group_alive,
        killpg=killpg,
        shutdown_attempts=1,
    )

    controller.stop()

    assert signals == [
        (120, signal.SIGTERM),
        (110, signal.SIGTERM),
        (110, signal.SIGKILL),
    ]
    assert all(observations)
    assert not pid_file.exists()


def test_stop_retains_pid_metadata_when_process_survives_kill(tmp_path):
    factory = ProcessFactory()
    pid_file = tmp_path / "runtime" / "auth-desktop.json"
    pid_file.parent.mkdir()
    pid_file.write_text(json.dumps({"pids": [10], "process_groups": [110]}))
    controller = make_controller(
        tmp_path,
        factory,
        process_group_alive=lambda _pgid: True,
        shutdown_attempts=1,
    )

    with pytest.raises(RuntimeError, match="did not stop"):
        controller.stop()

    assert pid_file.exists()


def test_stop_escalates_when_group_descendant_survives_dead_leader(tmp_path):
    factory = ProcessFactory()
    pid_file = tmp_path / "runtime" / "auth-desktop.json"
    pid_file.parent.mkdir()
    pid_file.write_text(json.dumps({"pids": [10], "process_groups": [110]}))
    group_alive = True
    signals = []

    def killpg(pgid, sig):
        nonlocal group_alive
        signals.append((pgid, sig))
        if sig == signal.SIGKILL:
            group_alive = False

    controller = make_controller(
        tmp_path,
        factory,
        process_alive=lambda _pid: False,
        process_group_alive=lambda _pgid: group_alive,
        killpg=killpg,
        shutdown_attempts=1,
    )

    controller.stop()

    assert signals == [
        (110, signal.SIGTERM),
        (110, signal.SIGKILL),
    ]
    assert not pid_file.exists()
