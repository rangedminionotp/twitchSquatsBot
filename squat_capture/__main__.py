"""Run from the project root with python -m squat_capture."""
import sys
from squat_capture.twitch_eventsub_listener import main

if __name__ == "__main__":
    sys.exit(main())
