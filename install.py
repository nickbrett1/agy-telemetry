import os
import sys
import json
import urllib.request

STATUSLINE_URL = "https://raw.githubusercontent.com/nickbrett1/agy-telemetry/main/scripts/statusline.py"
PACKAGES = ["opentelemetry-sdk", "opentelemetry-exporter-otlp"]


def _download_via_cli(cmd, tool_name, statusline_path):
    import subprocess
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True
        )
        if result.returncode == 0 and os.path.exists(statusline_path) and os.path.getsize(statusline_path) > 0:
            print(f"Saved statusline script via {tool_name} to {statusline_path}")
            return True
        else:
            print(f"{tool_name} download failed with return code {result.returncode}. Stderr: {result.stderr}")
    except Exception as err:
        print(f"Failed to run {tool_name}: {err}")
    return False


def _pip_install(args, description):
    """Run pip with the given args. Returns True on success."""
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install"] + args,
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        print(f"Successfully installed OpenTelemetry dependencies ({description})!")
        return True
    # Surface the error output so it's visible
    if result.stderr:
        for line in result.stderr.strip().splitlines():
            print(f"  {line}")
    return False


def _install_dependencies(lib_path):
    """
    Try several strategies to install dependencies, in order:
      1. pip install --target <lib_path>  (normal HTTPS)
      2. pip install --target --index-url http://  (no SSL needed - for macOS with broken SSL)
      3. pip install --user  (system-wide, normal HTTPS)
      4. pip install --user --index-url http://  (no SSL needed)
    Returns True if any strategy succeeded.
    """
    print(f"Installing OpenTelemetry dependencies to {lib_path}...")

    # Strategy 1: standard targeted install
    if _pip_install(["--target", lib_path] + PACKAGES, "targeted"):
        return True

    # Strategy 2: HTTP index (no SSL module required - common macOS fix when python3
    # is the Xcode CLI tools version which has no SSL compiled in)
    print("Standard install failed (likely SSL not available in this Python).")
    print("Trying HTTP index URL as fallback (no SSL required)...")
    http_flags = [
        "--index-url", "http://pypi.org/simple/",
        "--trusted-host", "pypi.org",
        "--trusted-host", "files.pythonhosted.org",
    ]
    if _pip_install(["--target", lib_path] + http_flags + PACKAGES, "targeted + http index"):
        return True

    print("Targeted install failed. Trying system-wide pip install --user...")

    # Strategy 3: user install (no --target, goes to site-packages)
    if _pip_install(["--user"] + PACKAGES, "--user"):
        print("  Note: packages installed to user site-packages. Telemetry will use system Python path.")
        return True

    print("Trying system-wide pip install --user with HTTP index...")

    # Strategy 4: user install + HTTP index
    if _pip_install(["--user"] + http_flags + PACKAGES, "--user + http index"):
        print("  Note: packages installed to user site-packages. Telemetry will use system Python path.")
        return True

    return False


def main():
    print("Installing agy telemetry integration...")

    # 1. Locate settings directory
    home = os.path.expanduser("~")
    cli_dir = os.path.join(home, ".gemini", "antigravity-cli")
    alt_dir = os.path.join(home, ".gemini", "antigravity")

    target_dir = cli_dir
    if not os.path.exists(target_dir) and os.path.exists(alt_dir):
        target_dir = alt_dir

    if not os.path.exists(target_dir):
        os.makedirs(target_dir, exist_ok=True)

    settings_path = os.path.join(target_dir, "settings.json")
    statusline_path = os.path.join(target_dir, "statusline.py")

    # 2. Download statusline.py
    print(f"Downloading statusline script from {STATUSLINE_URL}...")
    downloaded = False
    try:
        req = urllib.request.Request(
            STATUSLINE_URL,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=10.0) as response:
            code = response.read().decode('utf-8')

        with open(statusline_path, 'w', encoding='utf-8') as f:
            f.write(code)
        print(f"Saved statusline script to {statusline_path}")
        downloaded = True
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f"urllib download failed ({e}). Attempting download using system curl...")
        downloaded = _download_via_cli(
            ["curl", "-fsSL", STATUSLINE_URL, "-o", statusline_path],
            "curl",
            statusline_path
        )

        if not downloaded:
            print("Attempting download using system wget...")
            downloaded = _download_via_cli(
                ["wget", "-qO", statusline_path, STATUSLINE_URL],
                "wget",
                statusline_path
            )

    if not downloaded:
        print("Error: Could not download statusline script via urllib, curl, or wget.")
        sys.exit(1)

    # 3. Configure settings.json
    print(f"Configuring {settings_path}...")
    settings = {}
    if os.path.exists(settings_path):
        try:
            with open(settings_path, 'r', encoding='utf-8') as f:
                settings = json.load(f)
        except Exception as e:
            print(f"Warning: Could not load existing settings.json ({e}). Creating a new one.")

    # Set statusLine
    python_bin = "python" if sys.platform == "win32" else "python3"
    if sys.platform == "win32":
        statusline_cmd_path = statusline_path.replace(os.sep, "/")
    else:
        # Use ~ for home directory to ensure compatibility across different container users
        try:
            rel_path = os.path.relpath(statusline_path, home)
            statusline_cmd_path = f"~/{rel_path}".replace(os.sep, "/")
        except ValueError:
            statusline_cmd_path = statusline_path.replace(os.sep, "/")

    settings["statusLine"] = {
        "type": "command",
        "command": f"{python_bin} {statusline_cmd_path}"
    }

    try:
        with open(settings_path, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2)
        print("Successfully updated settings.json!")
    except Exception as e:
        print(f"Error writing to settings.json: {e}")
        sys.exit(1)

    # 4. Install OpenTelemetry dependencies
    lib_path = os.path.join(target_dir, "telemetry_lib")
    deps_ok = _install_dependencies(lib_path)

    if deps_ok:
        print("\nInstallation successful! 🎉")
        print("Telemetry is now configured to push traces to Arize Phoenix running on 'nas:6006'.")
        print("To verify, run: agy")
    else:
        print("\n⚠️  Warning: Could not automatically install OpenTelemetry dependencies.")
        print("   Telemetry status line will show 'dep_missing' until they are installed.")
        print("   To fix, try one of the following commands manually:")
        print(f"     {python_bin} -m pip install --target {lib_path} opentelemetry-sdk opentelemetry-exporter-otlp")
        print(f"     {python_bin} -m pip install --user opentelemetry-sdk opentelemetry-exporter-otlp")
        print("   If you see SSL errors, try adding: --trusted-host pypi.org --trusted-host files.pythonhosted.org")
        print("\n   The status line and settings.json have been configured — only telemetry export is affected.")


if __name__ == "__main__":
    main()