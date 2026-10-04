"""Translation backend.

Argos Translate runs fully offline, so a service keeps working without
internet once the language packages are installed. The Translator interface
is deliberately small so another backend can be swapped in later.
"""

import re
import threading
from pathlib import Path

import argostranslate.package
from argostranslate.translate import get_installed_languages

import config


def _installed_languages_by_code():
    """Argos languages present on disk, keyed by language code."""
    return {lang.code: lang for lang in get_installed_languages()}


def _keep_stanza_offline():
    """Stop stanza re-fetching its resource index on every translation run.

    Argos splits sentences with stanza but never passes a download_method, so
    stanza's default re-downloads a ~434 KB resources.json on every process
    start - even though the models are already on disk. On a service with no
    internet that turns the first spoken sentence into a hung request.

    REUSE_RESOURCES, not NONE: each Argos package has its own stanza directory,
    so a newly installed language has nothing cached yet and NONE leaves it
    unable to tokenise at all. REUSE_RESOURCES reads what is already there and
    downloads only when a package is genuinely new.
    """
    try:
        import stanza
        from stanza.pipeline.core import DownloadMethod
    except ImportError:
        return

    if getattr(stanza.Pipeline, "_offline_forced", False):
        return

    original = stanza.Pipeline

    def offline_pipeline(*args, **kwargs):
        method = (DownloadMethod.DOWNLOAD_RESOURCES if _refreshing_stanza
                  else DownloadMethod.REUSE_RESOURCES)
        kwargs.setdefault("download_method", method)
        return original(*args, **kwargs)

    offline_pipeline._offline_forced = True
    stanza.Pipeline = offline_pipeline


# Argos packages ship a resources.json that current stanza cannot read, so a
# freshly installed language fails to tokenise with KeyError: 'packages'. The
# languages that work only do so because an earlier run happened to download a
# usable one. Refresh it once per new package, then reuse it from then on.
_refreshing_stanza = False


def _refresh_stanza_resources(code):
    """Drop a new package's stale bundled resource index so stanza replaces it."""
    for package in argostranslate.package.get_installed_packages():
        if package.from_code != config.SOURCE_LANG or package.to_code != code:
            continue
        stale = Path(package.package_path) / "stanza" / "resources.json"
        if stale.exists():
            stale.unlink()
            print(f"[argos] refreshing stanza resources for {code}")
        return


class Translator:
    def __init__(self):
        self._translations = {}
        self._lock = threading.Lock()
        self.status = {}        # language name -> "installing" | "ready" | error text

    def available(self):
        """Every language Argos can translate English into.

        Reads the local package index when one is cached; refreshing it needs
        the network, so a failure here is reported rather than raised.
        """
        installed = {lang.code for lang in get_installed_languages()}
        try:
            packages = argostranslate.package.get_available_packages()
        except Exception:
            packages = []
        if not packages:
            try:
                argostranslate.package.update_package_index()
                packages = argostranslate.package.get_available_packages()
            except Exception as error:
                return [], f"Could not reach the Argos package index: {error}"

        seen, options = set(), []
        for package in packages:
            if package.from_code != config.SOURCE_LANG or package.to_code in seen:
                continue
            seen.add(package.to_code)
            options.append({
                "code": package.to_code,
                "name": package.to_name,
                "downloaded": package.to_code in installed,
                "active": package.to_code in config.TARGET_LANGS.values(),
            })
        return sorted(options, key=lambda o: o["name"]), None

    def add_language(self, name, code):
        """Install if needed, then start translating into it.

        Downloads can take a minute, so this is meant to be called on a
        worker thread; `status` reports progress to the control page.
        """
        self.status[name] = "installing"
        try:
            installed = _installed_languages_by_code()
            if code not in installed:
                argostranslate.package.update_package_index()
                package = next(
                    (p for p in argostranslate.package.get_available_packages()
                     if p.from_code == config.SOURCE_LANG and p.to_code == code),
                    None,
                )
                if package is None:
                    raise RuntimeError(f"Argos has no {config.SOURCE_LANG} -> {code} package")
                argostranslate.package.install_from_path(package.download())
                installed = _installed_languages_by_code()

            source = installed.get(config.SOURCE_LANG)
            target = installed.get(code)
            if source is None or target is None:
                raise RuntimeError(f"{code} did not install correctly")
            translation = source.get_translation(target)
            if translation is None:
                raise RuntimeError(f"No {config.SOURCE_LANG} -> {code} path after install")

            # Warm up off the audio thread, refreshing stanza's resource index
            # for this package so the first real sentence does not hit it.
            global _refreshing_stanza
            _refresh_stanza_resources(code)
            _refreshing_stanza = True
            try:
                translation.translate("Amen.")
            finally:
                _refreshing_stanza = False
            with self._lock:
                self._translations[name] = translation
                config.TARGET_LANGS[name] = code
            self.status[name] = "ready"
            print(f"[argos] added {name} ({code})")
        except Exception as error:
            self.status[name] = f"failed: {error}"
            print(f"[argos] could not add {name}: {error}")
            raise

    def remove_language(self, name):
        """Stop translating into a language. The package stays on disk."""
        with self._lock:
            self._translations.pop(name, None)
            config.TARGET_LANGS.pop(name, None)
        self.status.pop(name, None)
        print(f"[argos] removed {name}")

    def install_missing_packages(self):
        """Download any Argos language packages we do not have yet."""
        installed = _installed_languages_by_code()
        missing = [code for code in config.TARGET_LANGS.values() if code not in installed]

        if missing:
            print(f"[argos] downloading language packages: {', '.join(missing)}")
            argostranslate.package.update_package_index()
            available = argostranslate.package.get_available_packages()
            for code in missing:
                package = next(
                    (
                        pkg for pkg in available
                        if pkg.from_code == config.SOURCE_LANG and pkg.to_code == code
                    ),
                    None,
                )
                if package is None:
                    raise RuntimeError(
                        f"Argos has no {config.SOURCE_LANG} -> {code} package available"
                    )
                argostranslate.package.install_from_path(package.download())
            installed = _installed_languages_by_code()

        source = installed.get(config.SOURCE_LANG)
        if source is None:
            raise RuntimeError(f"Source language {config.SOURCE_LANG!r} is not installed")

        for name, code in config.TARGET_LANGS.items():
            target = installed.get(code)
            if target is None:
                raise RuntimeError(f"Target language {code!r} is not installed")
            # get_translation returns None when the language exists but no
            # direct en->X path does. Catch it now: left unchecked it surfaces
            # as an AttributeError on the first sentence spoken.
            translation = source.get_translation(target)
            if translation is None:
                raise RuntimeError(
                    f"No {config.SOURCE_LANG} -> {code} translation path installed "
                    f"for {name}. Install the argostranslate package for it."
                )
            self._translations[name] = translation

        _keep_stanza_offline()

        # Load the sentence splitter and translation models now, while the
        # operator is still at the laptop, rather than on the first sentence
        # of the service.
        for name, translation in self._translations.items():
            translation.translate("Amen.")

        print(f"[argos] ready: {', '.join(self._translations)}")
        return self

    def translate(self, text):
        """Return {language name: translated text} for one line of source text."""
        with self._lock:
            active = list(self._translations.items())
        return {
            name: _apply_fixes(name, translation.translate(text))
            for name, translation in active
        }


def _apply_fixes(language, text):
    """Correct known bad renderings for one language."""
    for pattern, replacement in config.TRANSLATION_FIXES.get(language, ()):
        text = re.sub(pattern, replacement, text)
    return text
