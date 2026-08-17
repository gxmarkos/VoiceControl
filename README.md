# Voice Control Launcher (Windows 11)

Press a global hotkey, speak a command, and launch an app or open a website —
fully offline, no internet or API keys required.

- **Hotkey:** `Win+Alt+V` (configurable)
- **Speech engine:** [Vosk](https://alphacephei.com/vosk/) (offline, English)
- **Flow:** press hotkey → beep → speak one command → it runs → back to idle

## How it works

You press the hotkey. A short beep tells you the mic is live. You say one command
(e.g. *"goto google"*). The tool matches what you said against the phrases in
`config.json` and either opens a URL or launches an application. A rising two-tone
beep means success; a low tone means it didn't understand.

## Setup

Requires Python 3.9+ (tested on 3.14).

```powershell
# 1. Install dependencies
pip install -r requirements.txt

# 2. Download the offline speech model (~40 MB, one time)
python download_model.py

# 3. Edit config.json with your real application paths (see below)

# 4. Run it
python voice_control.py
#    ...or just double-click run.bat
```

Leave the console window running in the background. Press **Ctrl+C** in it to quit.

## Configuring commands (`config.json`)

```json
{
  "hotkey": "windows+alt+v",
  "model_path": "models/vosk-model-small-en-us-0.15",
  "input_device": null,
  "listen_timeout": 5,
  "match_threshold": 0.75,
  "use_grammar": true,
  "commands": [
    {
      "phrases": ["open database", "open sequel editor"],
      "type": "app",
      "target": "C:\\Program Files\\DBeaver\\dbeaver.exe"
    },
    {
      "phrases": ["goto google", "go to google", "open google"],
      "type": "url",
      "target": "https://google.gr"
    }
  ]
}
```

**Each command:**
- `phrases` — one or more spoken variants that trigger this command.
- `type` — `"app"` to launch a program, or `"url"` to open a website.
- `target` — the full path to the `.exe` (or `.lnk`, or a folder), **or** a URL.
  Bare names on your PATH (like `notepad.exe`) also work.
- `allow_multiple` *(app only, optional)* — `true` forces a new instance every
  time, disabling the focus-existing-window behavior for this command.
- `process_name` *(app only, optional)* — the executable name to look for when
  deciding if the app is already running (e.g. `"javaw.exe"`). Defaults to the
  `.exe` name in `target`. Set this if focusing doesn't find the window because
  the visible window belongs to a different process than the launcher.

### Re-running an app that's already open

By default, saying an app command again does **not** start a second copy — it
finds the app's existing window, maximizes it, and brings it to the front. This is
controlled by `focus_if_running` / `maximize_on_focus` (see settings above). If a
particular app's window can't be found this way, set its `process_name`, or set
`allow_multiple: true` if you actually want a fresh instance each time.

**Top-level settings:**
- `hotkey` — key combo to start listening. Use `keyboard` library syntax, e.g.
  `windows+alt+v`, `ctrl+shift+v`, `ctrl+alt+space`.
- `input_device` — `null` uses your Windows default microphone. To force a
  specific mic, set it to the device's index (a number) or part of its name
  (e.g. `"Microphone"`). Audio is auto-resampled to what the engine needs, so any
  mic sample rate works.
- `focus_if_running` — `true` (default) means: if an app command's program is
  already running, bring its existing window to the front instead of launching a
  second instance.
- `maximize_on_focus` — `true` (default) maximizes the window when focusing it;
  set `false` to just restore + foreground it without maximizing.
- `listen_timeout` — seconds to listen after the beep before giving up.
- `match_threshold` — `0`–`1`; how close the recognized text must be to a phrase
  (higher = stricter). `0.75` is a good default.
- `use_grammar` — `true` biases recognition toward your exact phrases (more
  accurate). If an app name is an unusual word the model doesn't know, set this to
  `false` and rely on fuzzy matching.

To find an app's path: right-click its Start-menu / desktop shortcut → **Properties**
→ copy the **Target** field. Remember to double every backslash in JSON (`\\`).

## Important: use ordinary words, not brand names

The offline model only knows a dictionary of common **English words**. Brand and
product names — *DBeaver*, *pgAdmin*, *VSCode* — are **not** in it, so it can never
transcribe them (it prints `Ignoring word missing in vocabulary: 'dbeaver'` at
startup and hears them as `[unk]`). The trigger phrase and the program are
unrelated, so just pick a phrase made of normal words:

| To launch | Say something like |
|-----------|--------------------|
| DBeaver | "open database", "open sequel editor" |
| pgAdmin | "open postgres" |
| VS Code | "open editor", "open code" |
| Any app | any everyday words you'll remember |

If you press the hotkey and the log shows `[heard] 'open [unk]'`, that's this exact
problem — swap the phrase for real words. When the app starts, watch for any
`missing in vocabulary` warning; it names the words you need to change.

## Tips

- **Odd app names** (like *DBeaver*) can be hard for the model to hear — see the
  section above. Add several `phrases` variants to improve your hit rate.
- **Start automatically at login:** press `Win+R`, type `shell:startup`, Enter, and
  put a shortcut to `run.bat` in that folder.
- **Hotkey doesn't fire?** The `keyboard` library uses a low-level Windows hook; if a
  combo won't register, run the console **as Administrator**.

## Files

| File | Purpose |
|------|---------|
| `voice_control.py` | The resident app. |
| `config.json` | Your hotkey + command mappings (edit this). |
| `download_model.py` | One-time Vosk model downloader. |
| `run.bat` | Convenience launcher. |
| `models/` | Downloaded speech model (git-ignored). |
