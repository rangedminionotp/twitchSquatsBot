"""Local startup checks; repair only the active virtual environment on request."""
import importlib
import importlib.metadata
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def dependency_errors():
    errors = []
    for module, package, minimum, ceiling in (("requests", "requests", (2, 31), 3),
                                               ("websocket", "websocket-client", (1, 8), 2)):
        try:
            imported = importlib.import_module(module)
            version = tuple(int(x) for x in importlib.metadata.version(package).split('.')[:2])
            if version < minimum or version[0] >= ceiling:
                raise ValueError()
            if module == "websocket" and not hasattr(imported, "create_connection"):
                raise ValueError()
        except (ImportError, importlib.metadata.PackageNotFoundError, ValueError):
            errors.append(package)
    return errors


def check_storage():
    root = Path(os.environ.get("SQUAT_CAPTURE_DATA_DIR", Path.home() / ".squat-capture"))
    try:
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=root) as probe:
            probe.write(b"check")
            probe.flush()
    except OSError:
        return False
    return True


def main():
    errors = dependency_errors()
    if errors and "--repair" in sys.argv:
        if sys.prefix == sys.base_prefix:
            print("Use the project launcher: dependencies must be installed in a virtual environment.")
            return 1
        if subprocess.call([sys.executable, "-m", "pip", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL):
            if subprocess.call([sys.executable, "-m", "ensurepip", "--upgrade"]):
                print("pip is unavailable. On WSL install python3-venv, then recreate the environment without deleting your data.")
                return 1
        result = subprocess.call([sys.executable, "-m", "pip", "install", "-r", str(Path(__file__).resolve().parent.parent / "requirements.txt")])
        if result:
            print("Dependency installation failed. Check your internet connection and retry the launcher.")
            return 1
        # Verify in a fresh process, avoiding cached imports from before repair.
        return subprocess.call([sys.executable, str(Path(__file__))])
    if errors:
        print("Missing or incompatible dependencies: " + ", ".join(errors) + ". Run the project launcher to repair.")
        return 1
    if not check_storage():
        print("Cannot write app data. Check permissions / free disk space for SQUAT_CAPTURE_DATA_DIR.")
        return 1
    print("Startup checks passed: dependencies and data storage. Twitch authorization is checked in the control panel.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
