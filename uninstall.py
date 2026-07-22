import os
import json
import shutil

def main():
    print("Uninstalling agy telemetry integration...")
    
    # 1. Locate settings directory
    home = os.path.expanduser("~")
    cli_dir = os.path.join(home, ".gemini", "antigravity-cli")
    alt_dir = os.path.join(home, ".gemini", "antigravity")
    
    target_dirs = [cli_dir, alt_dir]
    
    for target_dir in target_dirs:
        if not os.path.exists(target_dir):
            continue
            
        settings_path = os.path.join(target_dir, "settings.json")
        statusline_path = os.path.join(target_dir, "statusline.py")
        lib_path = os.path.join(target_dir, "telemetry_lib")
        
        # Configure settings.json
        if os.path.exists(settings_path):
            print(f"Removing statusLine configuration from {settings_path}...")
            try:
                with open(settings_path, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                
                if "statusLine" in settings:
                    del settings["statusLine"]
                    
                with open(settings_path, 'w', encoding='utf-8') as f:
                    json.dump(settings, f, indent=2)
                print(f"Successfully updated {settings_path}")
            except Exception as e:
                print(f"Error updating settings.json: {e}")
                
        # Remove files
        if os.path.exists(statusline_path):
            try:
                os.remove(statusline_path)
                print(f"Removed statusline script: {statusline_path}")
            except Exception as e:
                print(f"Error removing statusline script: {e}")
                
        if os.path.exists(lib_path):
            try:
                shutil.rmtree(lib_path)
                print(f"Removed telemetry library directory: {lib_path}")
            except Exception as e:
                print(f"Error removing telemetry library: {e}")
                
    print("\nUninstall complete! 🎉")

if __name__ == "__main__":
    main()
