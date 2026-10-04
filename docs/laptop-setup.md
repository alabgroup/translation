# Setting up Passage on a fresh Mac

Step-by-step for a laptop that has never run this before - nothing installed,
not even Xcode tools. Written from an actual from-scratch setup, including
the two gotchas that aren't obvious from the README alone.

Total time: 15-30 minutes, most of it waiting on downloads.

## 1. Command Line Tools

Gives you a working `git`.

```
xcode-select --install
```

A popup appears - click **Install**, accept the license, wait for it to
finish (a few minutes).

## 2. Homebrew

```
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Run this in a real Terminal window, not through any remote/non-interactive
shell - it needs your admin password and a RETURN keypress partway through,
neither of which works over a pipe with no real TTY attached.

Afterwards, add it to your shell so `brew` is just available:

```
eval "$(/opt/homebrew/bin/brew shellenv)"
```

(Homebrew's own installer prints the exact line to add to your shell
profile if you want this permanent.)

## 3. git, GitHub CLI, Python, audio

```
brew install git gh python@3.11 portaudio
```

Then sign in to GitHub (opens a browser for a one-time login code):

```
gh auth login
```

Pick **GitHub.com** → **HTTPS** → **Login with a web browser**. You'll need
access to the `alabgroup` org on the account you log in with.

## 4. Clone and install

```
mkdir -p ~/Projects && cd ~/Projects
gh repo clone alabgroup/translation
cd translation
/opt/homebrew/bin/python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 5. First run - and the one real gotcha

```
python run.py
```

**On a genuinely fresh machine this will very likely fail** the first time,
with an error somewhere in `stanza` when Argos Translate tries to load its
sentence-splitting model - something like `KeyError: 'packages'` or
`FileNotFoundError: ...combined.pt`. This isn't a bug in Passage: the
Spanish/Chinese language packages Argos downloads bundle an old snapshot of
Stanza's model metadata that doesn't match the newer `stanza` version this
repo's dependencies pull in. It's a real version mismatch between two
upstream packages, not something `pip install` can resolve on its own.

The fix - seed a current, compatible model once, then point the installed
Argos packages at it:

```bash
source .venv/bin/activate

# Downloads a current, compatible English tokenizer (~500MB, one-time).
python -c "import stanza; stanza.download('en')"

# Point every installed Argos language package at that compatible model
# instead of the outdated one it shipped with.
python - <<'EOF'
import json
from pathlib import Path

src = Path.home() / "stanza_resources/en/tokenize/combined.pt"
packages_dir = Path.home() / ".local/share/argos-translate/packages"

for pkg in packages_dir.iterdir():
    stanza_dir = pkg / "stanza"
    resources_json = stanza_dir / "resources.json"
    if not resources_json.exists():
        continue
    dest = stanza_dir / "en" / "tokenize" / "combined.pt"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(src.read_bytes())
    data = json.loads(resources_json.read_text())
    data.setdefault("en", {})["packages"] = {"default": {"tokenize": "combined"}}
    resources_json.write_text(json.dumps(data))
    print("patched", pkg.name)
EOF
```

Run `python run.py` again - it should get past that step and print the
control page URL. (This only needs doing once per machine; it doesn't touch
anything in the repo itself, just files Argos already downloaded under
`~/.local/share/argos-translate/`.)

## 6. NDI Camera Extension (if using NDI Virtual Input)

If audio comes in through NDI Virtual Input, macOS blocks the extension
until you approve it manually - reinstalling NDI Tools alone doesn't fix
this. The app itself will say something like *"NDI virtual camera extension
must be installed before use"* even though it is installed; it's actually
sitting unapproved:

1. **System Settings → General → Login Items & Extensions**
2. Click **"By Category"** (not "By App") - the inline toggle only shows up
   there
3. Find **Camera Extensions**, turn on **NDI Camera Extension**
4. Quit and reopen **NDI Virtual Input**

You can check the actual state from Terminal:

```
systemextensionsctl list
```

Anything showing `[activated waiting for user]` needs this same approval
step - true for OBS's own virtual camera too, if you use that.

## 7. Running it for a service

```
cd ~/Projects/translation
source .venv/bin/activate
python run.py
```

Then open `http://localhost:8000/` - pick your audio input, watch the level
meter, and add the OBS Browser Source per the main [README](../README.md#obs-setup).

Everything from here (tuning sliders, OBS setup, troubleshooting) is
covered in the README - this doc is only for getting a blank laptop to that
point.
