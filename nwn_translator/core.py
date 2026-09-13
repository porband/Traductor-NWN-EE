"""Lógica sin interfaz: parseo, traducción y tema visual."""

import re
import threading
import time

try:
    from deep_translator import GoogleTranslator
except ImportError:
    GoogleTranslator = None

try:
    import deepl
except ImportError:
    deepl = None


class ChatParser:
    NWN_MARKUP_PATTERN = re.compile(r"</?c[^>]*>|</?[biu][^>]*>|<br\s*/?>", re.IGNORECASE)
    IGNORE_PATTERNS = [
        re.compile(r"^Messages for:", re.IGNORECASE), re.compile(r"^-{3,}$"),
        re.compile(r"^={3,}$"), re.compile(r"^\*+$"), re.compile(r"^\s*$"),
    ]
    OOC_PATTERNS = [re.compile(r"\[OOC\]", re.IGNORECASE), re.compile(r"^OOC:", re.IGNORECASE)]
    URL_PATTERN = re.compile(r"^(https?://|www\.)", re.IGNORECASE)
    # Los grupos capturan solo el nombre limpio del hablante (sin la hora
    # ni las etiquetas de canal entre corchetes que agrega el juego), para
    # que lo que se muestra en pantalla y lo que se copia sea lo mismo.
    SPEAKER_PATTERN = re.compile(r"^\[.*?\]\s*(.*?):\s*\[.*?\]\s*(.*)$")
    SIMPLE_SPEAKER_PATTERN = re.compile(r"^(.*?):\s*(.*)$")

    def should_ignore(self, line):
        return any(pattern.search(line) for pattern in self.IGNORE_PATTERNS)

    @classmethod
    def clean_markup(cls, text):
        if not text:
            return text
        return re.sub(r"[ \t]{2,}", " ", cls.NWN_MARKUP_PATTERN.sub("", text)).strip()

    def should_translate(self, text):
        text = self.clean_markup(text)
        return bool(text and not any(p.search(text) for p in self.OOC_PATTERNS)
                    and not self.URL_PATTERN.match(text.strip()) and any(ch.isalnum() for ch in text))

    def _is_plausible_speaker(self, speaker):
        value = speaker.rstrip(":").strip()
        if not value or len(value) > 80:
            return False
        low = value.lower()
        return (not low.startswith(("[system", "messages for", "server", "client", "error", "warning"))
                and not any(url in low for url in ("http://", "https://", "www."))
                and any(ch.isalpha() for ch in value))

    def parse(self, line):
        clean = self.clean_markup(line.strip())
        if self.should_ignore(clean) or not self.should_translate(clean):
            return None
        for pattern in (self.SPEAKER_PATTERN, self.SIMPLE_SPEAKER_PATTERN):
            match = pattern.match(clean)
            if match:
                speaker, text = match.group(1).strip(), match.group(2).strip()
                if self._is_plausible_speaker(speaker) and self.should_translate(text):
                    return speaker, text
                return None, clean
        return None, clean


class TranslationEngine:
    def __init__(self):
        self.mode = "Google"
        self.deepl_translator = None
        self.google_translators = {}
        self.cache = {}
        self.cache_lock = threading.Lock()
        self.max_cache_entries = 1000

    def clear_cache(self):
        with self.cache_lock:
            self.cache.clear()

    def get_cache_size(self):
        with self.cache_lock:
            return len(self.cache)

    def set_google(self):
        if GoogleTranslator is None:
            raise RuntimeError("La biblioteca 'deep-translator' no esta instalada.\nEjecuta: python -m pip install deep-translator")
        self.mode, self.deepl_translator = "Google", None
        with self.cache_lock:
            self.google_translators.clear()

    def set_deepl(self, api_key):
        if deepl is None:
            raise RuntimeError("La biblioteca 'deepl' no esta instalada.\nEjecuta: python -m pip install deepl")
        api_key = api_key.strip()
        if not api_key:
            raise RuntimeError("La API Key de DeepL esta vacia.")
        translator = deepl.Translator(api_key)
        translator.get_usage()
        self.deepl_translator, self.mode = translator, "DeepL"

    def translate(self, text, source_lang, target_lang, use_cache=True):
        if not text or not text.strip():
            return text
        cache_key = (text, source_lang, target_lang, self.mode)
        if use_cache:
            with self.cache_lock:
                cached = self.cache.get(cache_key)
            if cached is not None:
                return cached
        last_error = None
        for attempt in range(3):
            try:
                if self.mode == "DeepL":
                    if not self.deepl_translator:
                        raise RuntimeError("DeepL no esta configurado.")
                    target = "ES" if target_lang.lower().startswith("es") else "EN-US"
                    translated = self.deepl_translator.translate_text(text, target_lang=target).text
                else:
                    with self.cache_lock:
                        google = self.google_translators.get((source_lang, target_lang))
                    if google is None:
                        google = GoogleTranslator(source=source_lang, target=target_lang)
                        with self.cache_lock:
                            google = self.google_translators.setdefault((source_lang, target_lang), google)
                    translated = google.translate(text)
                if use_cache:
                    with self.cache_lock:
                        if len(self.cache) >= self.max_cache_entries:
                            self.cache.pop(next(iter(self.cache)), None)
                        self.cache[cache_key] = translated
                return translated
            except Exception as error:
                last_error = error
                time.sleep(0.3 * (2 ** attempt))
        raise RuntimeError(f"fallo la traduccion tras 3 intentos: {last_error}")


class Palette:
    # Tema "grafito": capas de gris neutro inspiradas en macOS en modo oscuro
    # (systemGray6/5/4), con violeta suave como unico acento de marca en vez
    # del azul generico de cualquier dashboard.
    bg = "#1C1C1E"          # systemGray6 dark: fondo de ventana
    bg_panel = "#242426"    # systemGray5 dark: paneles y superficies
    bg_input = "#323234"    # systemGray4 dark: campos de entrada
    border = "#3D3D40"      # separador sutil entre superficies
    text_main = "#F5F5F7"   # label primario, casi blanco
    text_dim = "#98989D"    # label secundario, gris medio
    accent = "#A78BFA"      # violeta suave: acciones principales
    accent_hover = "#BFA6FF"
    accent_text = "#1C1C1E"  # texto oscuro legible sobre el acento claro
    selection = "#4B4470"    # fondo de seleccion de texto, coherente con el acento

    # Colores claros y diferenciables para los nombres de personajes.
    # Se asignan de forma estable durante la sesion a cada hablante distinto.
    speaker_colors = (
        "#7BD6D0",  # turquesa
        "#FF9B8E",  # coral
        "#A9D18E",  # verde salvia
        "#F2C27B",  # ambar
        "#C4A7FF",  # violeta claro
        "#FFB36B",  # naranja suave
        "#8DD7F7",  # celeste
        "#F3A7C5",  # rosa
        "#CEE58B",  # lima suave
        "#AEBBFF",  # lavanda
    )
    speaker = "#AEBBFF"          # color de respaldo para el nombre
    spanish = "#F5F5F7"          # texto traducido: alto contraste, es lo principal
    english = "#98989D"          # original: referencia secundaria, mas discreto
    system = "#98989D"
    warning = "#F2C27B"
    error = "#FF6961"
    outgoing = "#D2C3FF"
    separator = "#2A2A2D"

    # En modo invisible el fondo desaparece, pero los nombres conservan sus
    # colores para poder identificar a cada hablante sobre el terreno.
    overlay_text = "#F5F5F7"
