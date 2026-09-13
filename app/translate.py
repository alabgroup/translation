"""Translation backend.

Argos Translate runs fully offline, so a service keeps working without
internet once the language packages are installed. The Translator interface
is deliberately small so another backend can be swapped in later.
"""

import argostranslate.package
from argostranslate.translate import get_installed_languages

import config


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
            self._translations[name] = source.get_translation(target)

        print(f"[argos] ready: {', '.join(self._translations)}")
        return self

    def translate(self, text):
        """Return {language name: translated text} for one line of source text."""
        return {name: t.translate(text) for name, t in self._translations.items()}
