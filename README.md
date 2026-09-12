# VoiceControl

VoiceControl is a Dockerized, offline voice assistant for Linux that allows you to control your system using spoken commands. It uses [Vosk](https://alphacephei.com/vosk/) for high-quality, offline speech recognition and is specifically designed to integrate with the `i3` window manager and tools like `xdotool` to execute custom actions based on recognized phrases.

## Purpose

The project listens to your microphone locally (without sending any audio to the cloud) and maps specific spoken phrases to system commands. It runs completely containerized but bridges to your host's PulseAudio and X11/i3 sockets, making it useful for hands-free operations like opening applications, managing windows, or simulating keyboard input via `xdotool`.

## Prerequisites

- Docker and Docker Compose
- PulseAudio (or PipeWire with PulseAudio bridge)
- `i3` window manager (if using the default configured actions)

## Configuration

To make VoiceControl work on your system, you need to configure the following components:

### 1. Model Configuration (`.env`)

The assistant uses Vosk models for speech recognition. The project relies on an `.env` file in the root directory to specify which model to download during the Docker build process.

Other voice models (such as smaller, faster models or different languages) can be found at **[https://alphacephei.com/vosk/models](https://alphacephei.com/vosk/models)**. To use a different model, adjust the variables in your `.env` file accordingly.

Example `.env` configuration:
```env
MODEL_URL=https://alphacephei.com/vosk/models/vosk-model-en-us-0.22.zip
MODEL_DIR=vosk-model-en-us-0.22
```

### 2. Assistant Configuration (`config.json`)

The `config.json` file dictates how the assistant interacts with your audio hardware and defines your custom voice commands.

*   **`input_device_index`**: This is a critical setting. You must set this to the correct microphone input device index as seen *inside the Docker container*. The Python script prints a list of available audio devices to the console when it starts. Check the Docker logs to find the correct index for your microphone and update this field.
*   **`commands`**: An array of objects defining your voice commands.
    *   `phrases`: A list of trigger phrases for the command.
    *   `action`: The shell command to run on the host when the phrase is spoken (e.g., `i3-msg 'exec firefox'`).

### 3. System Permissions

Because the application runs in Docker but controls your local desktop, it maps your host's X11, PulseAudio, and i3 sockets. Depending on your host setup, you may need to explicitly allow the container to connect to your X server:

```bash
xhost +local:docker
```

## Running the Assistant

After adjusting your `.env` and `config.json`, build and run the assistant:

```bash
# Build the container (this will download and extract the Vosk model)
docker-compose build

# Start the assistant
docker-compose up
```

Watch the console output. Once you see `Docker Voice Assistant Listening...`, you can start speaking your configured commands! If it's not recognizing your voice, double-check the `input_device_index` printed in the startup logs.
