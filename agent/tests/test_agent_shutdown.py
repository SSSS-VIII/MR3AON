from threading import Event
from unittest.mock import Mock, patch

from tui.run import request_parent_maa_picli_stop
from utils import agent_lifecycle


def test_native_shutdown_timeout_does_not_block_and_removes_own_socket(tmp_path, monkeypatch):
    release = Event()
    server = Mock()
    server.shut_down.side_effect = lambda: release.wait(2)
    cleanup = Mock()
    monkeypatch.setattr(agent_lifecycle, "_cleanup_socket_file", cleanup)
    try:
        assert not agent_lifecycle.close_agent_server(server, timeout=0.02)
        cleanup.assert_called_once_with()
    finally:
        release.set()


def test_completed_native_shutdown_returns_normally():
    server = Mock()
    with patch.object(agent_lifecycle, "_cleanup_socket_file") as cleanup:
        assert agent_lifecycle.close_agent_server(server)
    server.shut_down.assert_called_once_with()
    cleanup.assert_called_once_with()


def test_failed_native_shutdown_is_not_reported_as_success():
    server = Mock()
    server.shut_down.side_effect = RuntimeError("broken")
    with patch.object(agent_lifecycle, "_cleanup_socket_file"):
        assert not agent_lifecycle.close_agent_server(server)


def test_graceful_stop_signals_only_bound_cli():
    import signal
    with patch("tui.run.find_maa_picli_pids", return_value=[123]), patch("tui.run.os.kill") as kill:
        request_parent_maa_picli_stop()
    kill.assert_called_once_with(123, signal.SIGUSR1)
