"""
Voice Control Launcher for Windows 11
=====================================

Press a global hotkey (default Win+Alt+V), speak a single command, and the tool
launches the mapped application or opens the mapped URL.

Everything runs offline using the Vosk speech-recognition engine. Commands are
defined in config.json. See README.md for setup.
"""

import ctypes
import difflib
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import webbrowser
import winsound
from ctypes import wintypes
from pathlib import Path

import numpy as np
import sounddevice as sd
from vosk import KaldiRecognizer, Model, SetLogLevel

# Silence Vosk's very chatty native logging (grammar/vocab notes go to stderr).
SetLogLevel(-1)

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
SAMPLE_RATE = 16000

# A lock so overlapping hotkey presses can't start two listening sessions at once.
_listening_lock = threading.Lock()


# --------------------------------------------------------------------------- #
# Audio feedback (stdlib winsound — no dependency)
# --------------------------------------------------------------------------- #
def beep_listening() -> None:
    winsound.Beep(880, 120)


def beep_success() -> None:
    winsound.Beep(1200, 90)
    winsound.Beep(1600, 110)


def beep_failure() -> None:
    winsound.Beep(400, 250)


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def load_config() -> dict:
    if not CONFIG_PATH.exists():
        sys.exit(f"[error] Config not found: {CONFIG_PATH}")
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            config = json.load(fh)
    except json.JSONDecodeError as exc:
        sys.exit(f"[error] config.json is not valid JSON: {exc}")

    config.setdefault("hotkey", "windows+alt+v")
    config.setdefault("model_path", "models/vosk-model-small-en-us-0.15")
    config.setdefault("input_device", None)
    config.setdefault("listen_timeout", 5)
    config.setdefault("match_threshold", 0.75)
    config.setdefault("use_grammar", True)
    # When an "app" command is already running, focus its window (and maximize)
    # instead of starting a second instance. Per-command "allow_multiple": true
    # opts out; "process_name" overrides which process to look for.
    config.setdefault("focus_if_running", True)
    config.setdefault("maximize_on_focus", True)
    config.setdefault("commands", [])
    return config


def normalize(text: str) -> str:
    """Lowercase, strip punctuation, drop [unk] tokens, collapse whitespace."""
    text = text.lower().strip()
    text = re.sub(r"\[unk\]", " ", text)          # Vosk's unknown-word marker
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\bunk\b", " ", text)          # after punctuation stripping
    return re.sub(r"\s+", " ", text).strip()


def validate_commands(commands: list) -> None:
    """Warn (don't crash) about app targets that don't resolve to a real path."""
    for cmd in commands:
        if cmd.get("type") != "app":
            continue
        target = cmd.get("target", "")
        # Bare executable names (e.g. notepad.exe) are resolved via PATH at launch.
        looks_like_path = os.path.isabs(target) or os.sep in target or "/" in target
        if looks_like_path and not Path(target).exists():
            phrases = ", ".join(cmd.get("phrases", []))
            print(f"[warn] App path does not exist: {target}  (for: {phrases})")


def build_grammar(commands: list) -> str:
    """A JSON list of every phrase, plus [unk], to constrain recognition."""
    phrases = set()
    for cmd in commands:
        for phrase in cmd.get("phrases", []):
            norm = normalize(phrase)
            if norm:
                phrases.add(norm)
    return json.dumps(sorted(phrases) + ["[unk]"])


# --------------------------------------------------------------------------- #
# Command matching
# --------------------------------------------------------------------------- #
def match_command(heard: str, commands: list, threshold: float):
    """
    Return the best-matching command for the recognized text, or None.

    Strategy: exact phrase match, then "phrase fully contained in the utterance",
    then a fuzzy ratio fallback (difflib) so slightly-misheard phrases resolve.

    Note we deliberately do NOT treat "utterance is a subset of the phrase" as a
    match: a stray "open" (e.g. from "open [unk]") must not silently launch the
    first "open ..." command — better to report no match than the wrong action.
    """
    heard = normalize(heard)
    if not heard:
        return None

    best_cmd = None
    best_score = 0.0

    for cmd in commands:
        for phrase in cmd.get("phrases", []):
            norm = normalize(phrase)
            if not norm:
                continue
            if heard == norm:
                return cmd  # exact win
            if norm in heard:  # full phrase spoken, possibly with extra words
                score = 0.9
            else:
                score = difflib.SequenceMatcher(None, heard, norm).ratio()
            if score > best_score:
                best_score, best_cmd = score, cmd

    if best_cmd is not None and best_score >= threshold:
        return best_cmd
    return None


# --------------------------------------------------------------------------- #
# Window focusing (Win32 via ctypes — no extra dependency)
# --------------------------------------------------------------------------- #
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# Explicit prototypes are required on 64-bit Windows: handles are pointer-sized,
# and without these ctypes would truncate them to 32-bit ints.
_ULONG_PTR = ctypes.c_size_t
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.IsWindowVisible.restype = wintypes.BOOL
_user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
_user32.GetWindow.restype = wintypes.HWND
_user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
_user32.GetWindowTextLengthW.restype = ctypes.c_int
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.EnumWindows.restype = wintypes.BOOL
_user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.ShowWindow.restype = wintypes.BOOL
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]
_user32.SetForegroundWindow.restype = wintypes.BOOL
_user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, _ULONG_PTR]
_user32.keybd_event.restype = None
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
]
_kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL

SW_RESTORE = 9
SW_MAXIMIZE = 3
GW_OWNER = 4
VK_MENU = 0x12  # Alt
KEYEVENTF_KEYUP = 0x0002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _exe_name_for_pid(pid: int):
    """Return the executable base name (e.g. 'dbeaver.exe') for a process id."""
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buf))
        if _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value.rsplit("\\", 1)[-1]
    finally:
        _kernel32.CloseHandle(handle)
    return None


def find_windows_for_exe(exe_basename: str):
    """Top-level visible, titled windows owned by a process with this exe name."""
    wanted = exe_basename.lower()
    hwnds = []

    def _cb(hwnd, _lparam):
        if not _user32.IsWindowVisible(hwnd):
            return True
        if _user32.GetWindow(hwnd, GW_OWNER):  # skip owned (tool) windows
            return True
        if _user32.GetWindowTextLengthW(hwnd) == 0:
            return True
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        name = _exe_name_for_pid(pid.value)
        if name and name.lower() == wanted:
            hwnds.append(hwnd)
        return True

    _user32.EnumWindows(_WNDENUMPROC(_cb), 0)
    return hwnds


def activate_window(hwnd, maximize: bool) -> None:
    """Restore/maximize a window and bring it to the foreground reliably."""
    _user32.ShowWindow(hwnd, SW_MAXIMIZE if maximize else SW_RESTORE)
    # The Alt tap satisfies Windows' foreground-lock rule so SetForegroundWindow
    # works even though our process isn't the current foreground app.
    _user32.keybd_event(VK_MENU, 0, 0, 0)
    _user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    _user32.SetForegroundWindow(hwnd)


# --------------------------------------------------------------------------- #
# Actions
# --------------------------------------------------------------------------- #
def execute(cmd: dict, focus_if_running: bool, maximize: bool) -> bool:
    ctype = cmd.get("type")
    target = cmd.get("target", "")
    try:
        if ctype == "url":
            webbrowser.open(target)
            print(f"[open] {target}")
            return True
        if ctype == "app":
            # Reuse an already-open window instead of spawning a new instance.
            if focus_if_running and not cmd.get("allow_multiple", False):
                exe = cmd.get("process_name") or os.path.basename(target)
                if exe.lower().endswith(".exe"):
                    hwnds = find_windows_for_exe(exe)
                    if hwnds:
                        activate_window(hwnds[0], maximize)
                        print(f"[focus] {exe} already running -> foreground")
                        return True
            try:
                os.startfile(target)  # handles .exe, .lnk, folders, PATH lookup
            except OSError:
                subprocess.Popen(target, shell=False)
            print(f"[launch] {target}")
            return True
        print(f"[warn] Unknown command type: {ctype!r}")
        return False
    except Exception as exc:  # noqa: BLE001 - never let one action kill the app
        print(f"[error] Failed to run {target!r}: {exc}")
        return False


# --------------------------------------------------------------------------- #
# Microphone selection & capture
# --------------------------------------------------------------------------- #
def resolve_device(spec):
    """Turn a config 'input_device' (None | int index | name substring) into an index."""
    if spec is None or spec == "":
        default_in = sd.default.device[0]
        return default_in if default_in is not None and default_in >= 0 else None
    if isinstance(spec, int):
        return spec
    spec_low = str(spec).lower()
    for i, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0 and spec_low in dev["name"].lower():
            return i
    raise ValueError(f"No input device matching {spec!r}")


def select_capture(device):
    """
    Decide the capture sample rate for a device.

    Prefer 16 kHz (Vosk's rate) when the host API supports it — no resampling
    needed. Otherwise fall back to the device's native rate and resample later
    (e.g. WDM-KS, which won't convert sample rates itself).
    """
    info = sd.query_devices(device if device is not None else sd.default.device[0])
    idx = info["index"]
    native = int(info["default_samplerate"])
    for sr in (SAMPLE_RATE, native):
        try:
            sd.check_input_settings(device=idx, samplerate=sr, channels=1, dtype="int16")
            return idx, sr, info["name"]
        except Exception:
            continue
    return idx, native, info["name"]


def resample_to_16k(int16_bytes: bytes, src_sr: int) -> bytes:
    """Linear-resample mono int16 PCM from src_sr to 16 kHz (good enough for ASR)."""
    if src_sr == SAMPLE_RATE:
        return int16_bytes
    audio = np.frombuffer(int16_bytes, dtype=np.int16)
    if audio.size == 0:
        return b""
    n_out = int(round(audio.size * SAMPLE_RATE / src_sr))
    if n_out <= 0:
        return b""
    x_old = np.arange(audio.size)
    x_new = np.linspace(0, audio.size - 1, n_out)
    out = np.interp(x_new, x_old, audio.astype(np.float32))
    return out.astype(np.int16).tobytes()


# --------------------------------------------------------------------------- #
# Listening
# --------------------------------------------------------------------------- #
def build_recognizer(model: Model, grammar: str, use_grammar: bool) -> KaldiRecognizer:
    """
    Create the recognizer once, up front.

    Building it here (rather than per keypress) is faster and surfaces Vosk's
    'Ignoring word missing in vocabulary' warnings at startup — those name any
    command word the offline model cannot recognize, so you can fix config.json.
    The recognizer is reused across commands via Reset(); the listening lock
    guarantees only one command runs at a time, so this stays thread-safe.
    """
    if use_grammar:
        try:
            return KaldiRecognizer(model, SAMPLE_RATE, grammar)
        except Exception:  # grammar unsupported for some model builds
            return KaldiRecognizer(model, SAMPLE_RATE)
    return KaldiRecognizer(model, SAMPLE_RATE)


def listen_once(
    rec: KaldiRecognizer,
    timeout: float,
    device,
    capture_sr: int,
) -> str:
    """Capture from the mic until a phrase is recognized or timeout elapses."""
    rec.Reset()

    # Callback-based capture works across all Windows host APIs (MME, WASAPI,
    # WDM-KS); the blocking read API is not supported by every device.
    audio_q: "queue.Queue[bytes]" = queue.Queue()

    def callback(indata, frames, time_info, status):  # noqa: ARG001
        audio_q.put(bytes(indata))

    with sd.RawInputStream(
        samplerate=capture_sr,
        blocksize=int(capture_sr * 0.25),
        dtype="int16",
        channels=1,
        device=device,
        callback=callback,
    ):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data = audio_q.get(timeout=0.1)
            except queue.Empty:
                continue
            data = resample_to_16k(data, capture_sr)
            if rec.AcceptWaveform(data):
                text = json.loads(rec.Result()).get("text", "").strip()
                if text:
                    return text
        # Timed out mid-utterance: take whatever partial was accumulated.
        return json.loads(rec.FinalResult()).get("text", "").strip()


def make_activate_handler(rec: KaldiRecognizer, config: dict, device, capture_sr: int):
    commands = config["commands"]
    timeout = float(config["listen_timeout"])
    threshold = float(config["match_threshold"])
    focus_if_running = bool(config["focus_if_running"])
    maximize = bool(config["maximize_on_focus"])

    def on_activate():
        # Ignore repeat presses while already listening.
        if not _listening_lock.acquire(blocking=False):
            return
        try:
            print("\n[listening] speak now...")
            beep_listening()
            heard = listen_once(rec, timeout, device, capture_sr)
            if not heard:
                print("[heard] (nothing)")
                beep_failure()
                return
            print(f"[heard] {heard!r}")
            cmd = match_command(heard, commands, threshold)
            if cmd is None:
                print("[no match] tune the phrases in config.json if this recurs.")
                beep_failure()
                return
            if execute(cmd, focus_if_running, maximize):
                beep_success()
            else:
                beep_failure()
        except Exception as exc:  # noqa: BLE001 - keep the resident app alive
            print(f"[error] {exc}")
            beep_failure()
        finally:
            _listening_lock.release()

    return on_activate


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    import keyboard  # imported here so config errors surface before the hook

    config = load_config()

    model_path = (BASE_DIR / config["model_path"]).resolve()
    if not model_path.exists():
        sys.exit(
            f"[error] Vosk model not found at {model_path}\n"
            f"        Run:  python download_model.py"
        )

    print(f"[init] loading model: {model_path.name} ...")
    model = Model(str(model_path))
    grammar = build_grammar(config["commands"])

    validate_commands(config["commands"])

    # Build the recognizer now. Vosk prints a WARNING here for any command word
    # missing from the model's vocabulary (e.g. brand names like 'dbeaver').
    print("[init] preparing recognizer (watch for 'missing in vocabulary' warnings) ...")
    rec = build_recognizer(model, grammar, config["use_grammar"])
    print(
        "[hint] If a word above is 'missing in vocabulary', the model can't hear it.\n"
        "       Re-map that command to ordinary English words in config.json\n"
        "       (e.g. say 'open database' to launch DBeaver)."
    )

    try:
        device = resolve_device(config["input_device"])
        device, capture_sr, dev_name = select_capture(device)
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"[error] No usable microphone: {exc}")
    resample_note = "" if capture_sr == SAMPLE_RATE else f" (resampling {capture_sr}->16000 Hz)"
    print(f"[mic] using: {dev_name}{resample_note}")

    hotkey = config["hotkey"]
    on_activate = make_activate_handler(rec, config, device, capture_sr)

    try:
        keyboard.add_hotkey(hotkey, on_activate)
    except Exception as exc:  # noqa: BLE001
        sys.exit(
            f"[error] Could not register hotkey {hotkey!r}: {exc}\n"
            f"        Try running the console as Administrator."
        )

    print(f"[ready] Press {hotkey.upper()} to give a command.  Ctrl+C to quit.")
    print(f"[ready] {len(config['commands'])} command(s) loaded.")
    try:
        keyboard.wait()  # block forever; hotkey callbacks run on their own thread
    except KeyboardInterrupt:
        print("\n[exit] bye")


if __name__ == "__main__":
    main()
