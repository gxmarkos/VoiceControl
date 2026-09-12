FROM python:3.11-slim

# Install system dependencies, PortAudio, and ALSA-PulseAudio bridge
RUN apt-get update && apt-get install -y \
    alsa-utils \
    libasound2-dev \
    libasound2-plugins \
    portaudio19-dev \
    gcc \
    curl \
    unzip \
    i3-wm \
    xdotool \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONUNBUFFERED=1

# Install Python packages for Vosk and audio handling
RUN pip install --no-cache-dir vosk sounddevice requests pyaudio

# Download and extract the Vosk model inside the container build
ARG MODEL_URL
ARG MODEL_DIR

RUN curl -L -o model.zip ${MODEL_URL} && \
    unzip model.zip && \
    mv ${MODEL_DIR} model && \
    rm model.zip
COPY voice_assistant.py /app/voice_assistant.py
COPY config.json /app/config.json

CMD ["python3", "-u", "voice_assistant.py"]