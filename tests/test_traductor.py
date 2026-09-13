"""Pruebas sin interfaz ni conexión externa para el traductor NWN:EE."""

import importlib.util
import importlib
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "Traductor NWNEE v5.4.py"
SPEC = importlib.util.spec_from_file_location("nwn_translator", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeGoogleTranslator:
    calls = 0

    def __init__(self, source, target):
        self.source = source
        self.target = target

    def translate(self, text):
        type(self).calls += 1
        return f"{self.source}>{self.target}:{text}"


class FakeChatBox:
    def __init__(self):
        self.configurations = []

    def tag_config(self, *args, **kwargs):
        self.configurations.append((args, kwargs))

    def index(self, _value):
        return "1.0"

    def tag_names(self, _index):
        return ("speaker_1",)


class FakeRoot:
    def __init__(self):
        self.clipboard = None

    def clipboard_clear(self):
        self.clipboard = ""

    def clipboard_append(self, text):
        self.clipboard = text

    def update_idletasks(self):
        pass


class ChatParserTests(unittest.TestCase):
    def setUp(self):
        self.parser = MODULE.ChatParser()

    def test_parsea_hablante_y_elimina_marcado(self):
        line = "<c=red>[DM] Aria: [Common] Hello there</c>"
        self.assertEqual(
            self.parser.parse(line),
            ("Aria", "Hello there"),
        )

    def test_ignora_ooc_y_enlaces(self):
        self.assertIsNone(self.parser.parse("[OOC] no traducir"))
        self.assertIsNone(self.parser.parse("https://example.com"))


class TranslationEngineTests(unittest.TestCase):
    def test_google_reutiliza_el_cache(self):
        core = importlib.import_module(MODULE.TranslationEngine.__module__)
        original = core.GoogleTranslator
        core.GoogleTranslator = FakeGoogleTranslator
        FakeGoogleTranslator.calls = 0
        try:
            engine = MODULE.TranslationEngine()
            engine.set_google()
            self.assertEqual(engine.translate("hello", "en", "es"), "en>es:hello")
            self.assertEqual(engine.translate("hello", "en", "es"), "en>es:hello")
            self.assertEqual(FakeGoogleTranslator.calls, 1)
        finally:
            core.GoogleTranslator = original


class SpeakerTests(unittest.TestCase):
    def make_app(self):
        app = MODULE.TranslatorApp.__new__(MODULE.TranslatorApp)
        app.pal = MODULE.Palette()
        app.speaker_tag_map = {}
        app.speaker_color_map = {}
        app.speaker_display_map = {}
        app.next_speaker_color = 0
        app.invisible_mode = True
        app.chat_box = FakeChatBox()
        app.root = FakeRoot()
        app.log_message = lambda *_args: None
        return app

    def test_nombre_mantiene_color_y_doble_clic_lo_copia(self):
        app = self.make_app()
        tag = app._get_speaker_tag("Aria", 1)
        for number in range(2, 32):
            app._get_speaker_tag(f"Jugador {number}", number)

        self.assertEqual(app._get_speaker_tag("  aria ", 33), tag)
        self.assertNotIn("#FFF7DA", app.speaker_color_map.values())
        app.copy_speaker_from_click(types.SimpleNamespace(x=10, y=10))
        self.assertEqual(app.root.clipboard, "Aria")


if __name__ == "__main__":
    unittest.main()
