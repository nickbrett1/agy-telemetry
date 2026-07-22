import os
import sys
import json
import urllib.request
import urllib.error

STATUSLINE_URL = "https://raw.githubusercontent.com/nickbrett1/agy-telemetry/main/scripts/statusline.py"

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
    except Exception as e:
        print(f"Error downloading statusline script: {e}")
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
    settings["statusLine"] = {
        "type": "command",
        "command": f"python3 {statusline_path}"
    }
    
    try:
        with open(settings_path, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2)
        print("Successfully updated settings.json!")
    except Exception as e:
        print(f"Error writing to settings.json: {e}")
        sys.exit(1)
        
    print("\nInstallation successful! 🎉")
    print("Telemetry is now configured to push traces to Arize Phoenix running on 'nas:6006'.")
    print("To verify, run: agy")

if __name__ == "__main__":
    main()
