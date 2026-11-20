"""Enterprise Oracle Accounts Payable · Desktop Application Launcher.

Runs the AP suite in dedicated standalone desktop application window mode.
"""

import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

PORT = int(os.environ.get("PORT", "8765"))
URL = f"http://127.0.0.1:{PORT}"


def is_running():
    try:
        with urllib.request.urlopen(f"{URL}/openapi.json", timeout=1):
            return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def find_browser():
    candidates = [
        # Windows
        os.path.expandvars(
            r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
        ),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        # Linux / macOS
        shutil.which("microsoft-edge"),
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("brave-browser"),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def main():
    if not is_running():
        print(f"Booting AP server daemon on {URL}...")
        env = os.environ.copy()
        env["AP_CONFIG"] = os.path.abspath(r".runtime\app.json")
        server_cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            "ap.api:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
            "--no-access-log",
        ]
        subprocess.Popen(server_cmd, env=env)
        for _ in range(15):
            time.sleep(1)
            if is_running():
                break

    browser = find_browser()
    if browser:
        print(f"Launching Oracle AP Desktop Window via {browser}...")
        subprocess.run([browser, f"--app={URL}", "--window-size=1280,850"], check=True)
    else:
        import webbrowser

        webbrowser.open(URL)


if __name__ == "__main__":
    main()
