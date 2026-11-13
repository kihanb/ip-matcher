"""Desktop entry point for IP Matcher."""

from __future__ import annotations

import argparse
import ctypes
import os
import subprocess
import sys
import threading
from pathlib import Path

from ip_matcher.browser_launcher import find_browser_executable
from ip_matcher.config import DATA_DIR
from ip_matcher.server import AppController, create_http_server
from ip_matcher.tray import TrayController


def _ensure_valid_streams() -> None:
    """Prevent crashes under pythonw.exe where sys.stdout/sys.stderr may be None."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        log_file = open(DATA_DIR / "app.log", "a", encoding="utf-8")
    except OSError:
        log_file = open(os.devnull, "w", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = log_file
    if sys.stderr is None:
        sys.stderr = log_file


def _relaunch_without_console_if_standalone() -> bool:
    """If launched via python.exe in its own standalone console window, switch to pythonw.exe."""
    if os.name != "nt":
        return False
    exe = Path(sys.executable)
    if exe.name.lower() != "python.exe":
        return False
    pythonw = exe.with_name("pythonw.exe")
    if not pythonw.exists():
        return False
    try:
        arr = (ctypes.c_uint32 * 4)()
        count = ctypes.windll.kernel32.GetConsoleProcessList(arr, 4)
        if count != 1:
            return False
    except Exception:
        return False

    subprocess.Popen(
        [str(pythonw), os.path.abspath(__file__), *sys.argv[1:]],
        close_fds=True,
    )
    return True


def launch_desktop_app(force_browser_mode: bool = False) -> int:
    controller = AppController()
    http_server = create_http_server(controller, port=0)
    port = http_server.server_address[1]
    url = f"http://127.0.0.1:{port}/"

    server_thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    server_thread.start()
    controller.start_watcher()

    if not force_browser_mode:
        try:
            import webview

            window_holder: dict[str, webview.Window] = {}
            quitting = {"flag": False}

            def show_window() -> None:
                win = window_holder.get("win")
                if win:
                    try:
                        win.show()
                        win.restore()
                    except Exception:
                        pass

            def quit_app() -> None:
                quitting["flag"] = True
                tray.stop()
                controller.stop_watcher()
                http_server.shutdown()
                win = window_holder.get("win")
                if win:
                    try:
                        win.destroy()
                    except Exception:
                        pass
                os._exit(0)

            tray = TrayController(
                on_show=show_window,
                on_sync_now=lambda: threading.Thread(
                    target=controller.apply_current_target, daemon=True
                ).start(),
                on_restore_prev=lambda: threading.Thread(
                    target=lambda: controller.restore_snapshot("latest"), daemon=True
                ).start(),
                on_quit=quit_app,
            )
            controller.status_callbacks.append(tray.update_status)

            win = webview.create_window(
                title="IP Matcher — سپر هوشمند هماهنگی سیستم",
                url=url,
                width=1260,
                height=830,
                min_size=(940, 640),
                text_select=True,
            )
            window_holder["win"] = win

            def on_closing() -> bool:
                if (
                    not quitting["flag"]
                    and controller.settings.minimize_to_tray
                    and tray.available
                ):
                    win.hide()
                    return False  # Cancel close -> minimize to tray
                quit_app()
                return True

            win.events.closing += on_closing
            if tray.available:
                tray.start()

            webview.start(gui="edgechromium")
            return 0
        except Exception as exc:
            print(f"[IP Matcher] WebView fallback ({exc}); launching Edge app window...")

    # Fallback: launch Edge/Chrome in standalone App Window mode
    _, exe_path = find_browser_executable()
    if exe_path:
        proc = subprocess.Popen(
            [exe_path, f"--app={url}", "--window-size=1260,830"]
        )
        try:
            proc.wait()
        except KeyboardInterrupt:
            pass
    else:
        import webbrowser

        webbrowser.open(url)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass

    controller.stop_watcher()
    http_server.shutdown()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="IP Matcher Desktop Shield")
    parser.add_argument(
        "--browser-only",
        action="store_true",
        help="Open UI using Edge/Chrome --app window instead of pywebview",
    )
    parser.add_argument(
        "--console",
        action="store_true",
        help="Keep console window attached for diagnostics",
    )
    parser.add_argument(
        "--elevated",
        action="store_true",
        help="Internal flag used after UAC elevation",
    )
    args = parser.parse_args()
    if not args.console and _relaunch_without_console_if_standalone():
        return 0
    _ensure_valid_streams()
    return launch_desktop_app(force_browser_mode=args.browser_only)


if __name__ == "__main__":
    raise SystemExit(main())
