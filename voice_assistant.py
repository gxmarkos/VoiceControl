# xhost +local:docker

#!/usr/bin/env python3
import os
import sys
import subprocess
import json
import pyaudio
from vosk import Model, KaldiRecognizer


CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

def load_config():
    if not os.path.exists(CONFIG_PATH):
        print(f"Config file not found: {CONFIG_PATH}", flush=True)
        return {}
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)

config = load_config()

MODEL_PATH = config.get("model_path", "/app/model")
CHUNK = config.get("chunk", 4096)
FORMAT = pyaudio.paInt16
CHANNELS = config.get("channels", 1)
RATE = config.get("rate", 16000)
INPUT_DEVICE_INDEX = config.get("input_device_index", 0)
COMMANDS = config.get("commands", [])

if not os.path.exists(MODEL_PATH):
    print(f"Model path missing: {MODEL_PATH}", flush=True)
    sys.exit(1)

print("Initializing Vosk model...", flush=True)
model = Model(MODEL_PATH)
rec = KaldiRecognizer(model, RATE)

# Print available audio devices to debug what the container sees
p = pyaudio.PyAudio()
print("Available Audio Devices:", flush=True)
for i in range(p.get_device_count()):
    info = p.get_device_info_by_index(i)
    # Only print devices that have input channels
    if info.get('maxInputChannels') > 0:
        print(f"Index {i}: {info.get('name')}", flush=True)

def handle_command(text):
    print(f"\nRecognized: {text}", flush=True)
    for cmd in COMMANDS:
        for phrase in cmd.get("phrases", []):
            if phrase in text:
                action = cmd.get("action")
                if action:
                    subprocess.run(action, shell=True)
                return

print("Docker Voice Assistant Listening... (Say 'open firefox')", flush=True)

print("Opening microphone stream...", flush=True)
stream_kwargs = {
    "format": FORMAT,
    "channels": CHANNELS,
    "rate": RATE,
    "input": True,
    "frames_per_buffer": CHUNK
}
if INPUT_DEVICE_INDEX is not None:
    stream_kwargs["input_device_index"] = INPUT_DEVICE_INDEX

stream = p.open(**stream_kwargs)

print("Recording... Press Ctrl+C to stop.", flush=True)

try:
    while True:
        data = stream.read(CHUNK, exception_on_overflow=False)
        if rec.AcceptWaveform(bytes(data)):
            result = json.loads(rec.Result())
            text = result.get("text", "")
            if text:
                handle_command(text)
            else:
                print("\n[Vosk] Audio chunk processed, no text recognized.", flush=True)
        else:
            partial_result = json.loads(rec.PartialResult())
            partial = partial_result.get("partial", "")
            if partial:
                print(f"\r[Listening]: {partial}", end="", flush=True)
except KeyboardInterrupt:
    print("\nStopping stream...", flush=True)
except Exception as e:
    print(f"\nAudio stream error: {e}", flush=True)
    sys.exit(1)