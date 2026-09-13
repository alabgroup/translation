"""Translation backend.

Argos Translate runs fully offline, so a service keeps working without
internet once the language packages are installed. The Translator interface
is deliberately small so another backend can be swapped in later.
"""

import re

import argostranslate.package
from argostranslate.translate import get_installed_languages

import config


def _keep_stanza_offline():
    """Stop stanza from fetching its resource index on the first translation.

    Argos splits sentences with stanza but never passes a download_method, so
    stanza's default re-downloads a ~434 KB resources.json on every process
    start - even though the models are already on disk. On a service with no
    internet that turns the first spoken sentence into a hung request.
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
        kwargs.setdefault("download_method", DownloadMethod.NONE)
        return original(*args, **kwargs)

    offline_pipeline._offline_forced = True
    stanza.Pipeline = offline_pipeline


class Translator:
    def __init__(self):
        self._translations = {}

    def install_missing_packages(self):
        """Download any Argos language packages we do not have yet."""
        installed = {lang.code: lang for lang in get_installed_languages()}
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
            installed = {lang.code: lang for lang in get_installed_languages()}

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
        return {
            name: _apply_fixes(name, translation.translate(text))
            for name, translation in self._translations.items()
        }


def _apply_fixes(language, text):
    """Correct known bad renderings for one language."""
    for pattern, replacement in config.TRANSLATION_FIXES.get(language, ()):
        text = re.sub(pattern, replacement, text)
    return text
