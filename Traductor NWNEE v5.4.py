"""
Traductor Roleplay - Neverwinter NEE (v5.4)

Fusiona lo mejor de dos implementaciones distintas del mismo proyecto:

  Del "Traductor_NWN_V2_1" (hecho con otra IA):
    - Guardado de la API Key de DeepL con `keyring` (almacen de
      credenciales real del sistema operativo, no un archivo de texto).
    - ChatParser dedicado: ignora lineas de OOC, links y separadores
      del log en vez de intentar traducirlas.
    - Deteccion de rotacion del archivo de log por inodo (si NWN abre
      un log nuevo en otra sesion, la app lo detecta).
    - Limite de mensajes en el chat (trim_chat) para que la ventana no
      crezca sin limite en sesiones largas.
    - Controles extra: seleccionar log manualmente, mantener encima,
      envio automatico, copiar ultima traduccion, limpiar chat.
    - Hilo y lock dedicados para el envio de texto al juego.

  De la version anterior (mejorada por Claude):
    - Reintentos con backoff si la traduccion falla (en vez de fallar
      una sola vez y listo).
    - Lectura del log probando UTF-8 antes de caer a latin-1.
    - Cola thread-safe para actualizar la interfaz.

  Nuevo en esta version:
    - Rediseno visual (paleta y tipografia consistente).
    - "Modo invisible": ventana superpuesta translucida sobre el juego
      donde solo se ven las letras del chat traducido, sin fondo ni
      bordes. Especifico de Windows (usa -transparentcolor de Tk).

Nota sobre canales de chat: NWN:EE no separa el chat por canales en el
log de cliente -- todo el roleplay pasa por el mismo flujo de texto,
asi que no es posible dividir la traduccion "por seccion". Por eso esta
version no incluye esa idea.
"""

import os
import sys
import re
import time
import base64
import queue
import threading
import colorsys
import ctypes
from collections import deque

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# --- Dependencias opcionales, con mensajes de error claros si faltan ---

try:
    from deep_translator import GoogleTranslator
except ImportError:
    GoogleTranslator = None

try:
    import deepl
except ImportError:
    deepl = None

try:
    import pyautogui
except ImportError:
    pyautogui = None

try:
    import pygetwindow as gw
except ImportError:
    gw = None

try:
    import keyring
    KEYRING_OK = True
except ImportError:
    keyring = None
    KEYRING_OK = False

try:
    import keyboard as global_hotkeys
    GLOBAL_HOTKEYS_OK = True
except ImportError:
    global_hotkeys = None
    GLOBAL_HOTKEYS_OK = False


APP_NAME = "Traductor NWN:EE"
APP_VERSION = "5.4.2"
KEYRING_SERVICE = "TraductorNWN"
KEYRING_USER = "deepl_api_key"
MAX_CHAT_MESSAGES = 400
LOG_POLL_INTERVAL = 0.15
DEFAULT_LOG_NAME = "nwclientlog1.txt"

# Config y fallback de guardado (si keyring no esta disponible en el sistema)
APPDATA = os.environ.get("APPDATA", os.path.join(os.path.expanduser("~"), "AppData", "Roaming"))
CONFIG_DIR = os.path.join(APPDATA, "TraductorNWN")
FALLBACK_KEY_FILE = os.path.join(CONFIG_DIR, "perfil_traductor.dat")
_OBFUSCATION_KEY = b"nwn-translator-key"


def resource_path(filename):
    """Obtiene la ruta de un recurso tanto en Python como en un EXE PyInstaller."""
    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, filename)


def ensure_config_dir():
    os.makedirs(CONFIG_DIR, exist_ok=True)


def _obfuscate(text: str) -> bytes:
    raw = text.encode("utf-8")
    xored = bytes(b ^ _OBFUSCATION_KEY[i % len(_OBFUSCATION_KEY)] for i, b in enumerate(raw))
    return base64.b64encode(xored)


def _deobfuscate(data: bytes) -> str:
    xored = base64.b64decode(data)
    raw = bytes(b ^ _OBFUSCATION_KEY[i % len(_OBFUSCATION_KEY)] for i, b in enumerate(xored))
    return raw.decode("utf-8")


def get_user_documents():
    """Busca las posibles carpetas de Documentos de Windows (OneDrive u otras)."""
    user_profile = os.environ.get("USERPROFILE", os.path.expanduser("~"))
    candidates = []
    for sub in (os.path.join("OneDrive", "Documents"), os.path.join("OneDrive", "Documentos"),
                "Documents", "Documentos"):
        candidates.append(os.path.join(user_profile, sub))
    return [c for c in candidates if os.path.isdir(c)]


def find_log_file():
    """Busca automaticamente el log de Neverwinter Nights."""
    for documents in get_user_documents():
        log_dir = os.path.join(documents, "Neverwinter Nights", "logs")
        for name in (DEFAULT_LOG_NAME, "nwclientlog.txt"):
            candidate = os.path.join(log_dir, name)
            if os.path.isfile(candidate):
                return candidate
    return None


LANG_FILE = os.path.join(CONFIG_DIR, "idioma.txt")
TRANSLATE_DIR_FILE = os.path.join(CONFIG_DIR, "direccion_traduccion.txt")

# Todos los textos de la interfaz en los dos idiomas soportados. "otro" en
# los comentarios se refiere siempre al idioma complementario (si mi idioma
# es espanol, el otro es ingles, y viceversa) - asi la direccion de
# traduccion se invierte automaticamente segun lo que elija cada persona.
TEXTS = {
    "es": {
        "engine_prefix": "Motor",
        "engine_google": "GOOGLE",
        "engine_deepl": "DEEPL",
        "invisible_btn": "\U0001F441  Modo invisible (F9)",
        "log_prefix": "LOG",
        "game_prefix": "JUEGO",
        "searching": "buscando...",
        "connected": "conectado",
        "waiting": "esperando...",
        "no_pygetwindow": "sin pygetwindow",
        "send_btn": "Enviar",
        "keep_on_top": "Mantener encima",
        "auto_send": "Envio automatico al juego",
        "select_log_btn": "Seleccionar LOG",
        "copy_last_btn": "Copiar ultimo",
        "clear_chat_btn": "Limpiar chat",
        "pause_btn": "Pausar traduccion",
        "resume_btn": "Reanudar traduccion",
        "config_frame_title": " Motor de traduccion (DeepL opcional) ",
        "deepl_key_label": "DeepL API Key:",
        "activate_deepl_btn": "Activar DeepL",
        "use_google_btn": "Usar Google",
        "my_prefix": "ESP",
        "other_prefix": "ENG",
        "sent_to_game": "Enviado a Neverwinter",
        "auto_send_off": "Envio automatico desactivado",
        "select_log_dialog_title": "Seleccionar log de Neverwinter",
        "log_selected": "LOG seleccionado: {name}",
        "log_selected_msg": "[Sistema]: LOG seleccionado manualmente: {path}\n",
        "name_copied": "[Sistema]: Nombre copiado: {speaker}\n",
        "no_translation_yet": "Todavia no hay una traduccion.",
        "last_translation_copied": "[Sistema]: Ultima traduccion copiada al portapapeles.\n",
        "engine_changed_google": "[Sistema]: Motor cambiado a Google Translate.\n",
        "translation_paused_msg": "[Sistema]: Traduccion pausada. El LOG sigue siendo vigilado, pero los mensajes nuevos no se traduciran.\n",
        "translation_resumed_msg": "[Sistema]: Traduccion reanudada.\n",
        "searching_log_status": "[Sistema]: Buscando el archivo log de Neverwinter...\n",
        "log_detected_status": "LOG de Neverwinter detectado. Traduciendo en tiempo real.\n",
        "log_connected_status": "LOG conectado. Traduccion en tiempo real.\n",
        "log_reset_status": "El LOG se reinicio (nueva sesion de Neverwinter). Reconectando...\n",
        "deepl_key_missing": "Introduce una API Key de DeepL.",
        "deepl_activated_ok": "DeepL activado correctamente.",
        "deepl_activate_failed": "No se pudo activar DeepL: {error}",
        "deepl_auto_ok": "DeepL configurado correctamente.",
        "deepl_auto_failed": "DeepL no pudo activarse automaticamente: {error}",
        "google_activate_failed": "No se pudo activar Google Translate:\n{error}",
        "system_prefix": "Sistema",
        "keyring_read_failed": "[Sistema]: No se pudo leer la config de DeepL via keyring: {error}\n",
        "deepl_save_failed": "No se pudo guardar la API Key: {error}",
        "no_pygetwindow_error": "Falta pygetwindow.\nEjecuta: python -m pip install pygetwindow",
        "no_pyautogui_error": "Falta PyAutoGUI.\nEjecuta: python -m pip install pyautogui",
        "window_not_found_error": "No se encontro la ventana de Neverwinter Nights.\nAbre Neverwinter Nights y vuelve a intentarlo.",
        "hotkey_register_failed": "[Sistema]: No se pudo registrar el atajo global F9 ({error}). Se usara el detector nativo de Windows.\n",
        "hotkey_registered_ok": "[Sistema]: Atajo global F9 activado mediante Windows (sin libreria 'keyboard').\n",
        "hotkey_unavailable": "[Sistema]: Atajo global F9 no disponible en este sistema. F9 funcionara con esta ventana en foco.\n",
        "log_read_error": "Error leyendo el LOG: {error}",
        "queue_full_error": "La cola de traduccion esta llena; se descarto un mensaje.",
        "translate_error": "Error traduciendo '{snippet}': {error}",
        "send_prepare_error": "Error preparando el envio: {error}",
        "lang_picker_title": "Idioma / Language",
        "lang_picker_prompt": "Elegi tu idioma / Choose your language",
        "lang_btn_es": "Espa\u00f1ol",
        "lang_btn_en": "English",
        "lang_toggle_btn": "ES/EN",
    },
    "en": {
        "engine_prefix": "Engine",
        "engine_google": "GOOGLE",
        "engine_deepl": "DEEPL",
        "invisible_btn": "\U0001F441  Invisible mode (F9)",
        "log_prefix": "LOG",
        "game_prefix": "GAME",
        "searching": "searching...",
        "connected": "connected",
        "waiting": "waiting...",
        "no_pygetwindow": "pygetwindow missing",
        "send_btn": "Send",
        "keep_on_top": "Keep on top",
        "auto_send": "Auto-send to game",
        "select_log_btn": "Select LOG",
        "copy_last_btn": "Copy last",
        "clear_chat_btn": "Clear chat",
        "pause_btn": "Pause translation",
        "resume_btn": "Resume translation",
        "config_frame_title": " Translation engine (DeepL optional) ",
        "deepl_key_label": "DeepL API Key:",
        "activate_deepl_btn": "Activate DeepL",
        "use_google_btn": "Use Google",
        "my_prefix": "ENG",
        "other_prefix": "ESP",
        "sent_to_game": "Sent to Neverwinter",
        "auto_send_off": "Auto-send disabled",
        "select_log_dialog_title": "Select the Neverwinter log",
        "log_selected": "LOG selected: {name}",
        "log_selected_msg": "[System]: LOG manually selected: {path}\n",
        "name_copied": "[System]: Name copied: {speaker}\n",
        "no_translation_yet": "There's no translation yet.",
        "last_translation_copied": "[System]: Last translation copied to clipboard.\n",
        "engine_changed_google": "[System]: Engine switched to Google Translate.\n",
        "translation_paused_msg": "[System]: Translation paused. The LOG is still being watched, but new messages won't be translated.\n",
        "translation_resumed_msg": "[System]: Translation resumed.\n",
        "searching_log_status": "[System]: Looking for the Neverwinter log file...\n",
        "log_detected_status": "Neverwinter LOG detected. Translating in real time.\n",
        "log_connected_status": "LOG connected. Real-time translation.\n",
        "log_reset_status": "The LOG was reset (new Neverwinter session). Reconnecting...\n",
        "deepl_key_missing": "Enter a DeepL API Key.",
        "deepl_activated_ok": "DeepL activated successfully.",
        "deepl_activate_failed": "Couldn't activate DeepL: {error}",
        "deepl_auto_ok": "DeepL configured successfully.",
        "deepl_auto_failed": "DeepL couldn't be activated automatically: {error}",
        "google_activate_failed": "Couldn't activate Google Translate:\n{error}",
        "system_prefix": "System",
        "keyring_read_failed": "[System]: Couldn't read the DeepL config via keyring: {error}\n",
        "deepl_save_failed": "Couldn't save the API Key: {error}",
        "no_pygetwindow_error": "pygetwindow is missing.\nRun: python -m pip install pygetwindow",
        "no_pyautogui_error": "PyAutoGUI is missing.\nRun: python -m pip install pyautogui",
        "window_not_found_error": "Couldn't find the Neverwinter Nights window.\nOpen Neverwinter Nights and try again.",
        "hotkey_register_failed": "[System]: Couldn't register the global F9 shortcut ({error}). Using the native Windows detector instead.\n",
        "hotkey_registered_ok": "[System]: Global F9 shortcut enabled via Windows (no 'keyboard' library).\n",
        "hotkey_unavailable": "[System]: Global F9 shortcut not available on this system. F9 will work while this window is focused.\n",
        "log_read_error": "Error reading the LOG: {error}",
        "queue_full_error": "The translation queue is full; a message was dropped.",
        "translate_error": "Error translating '{snippet}': {error}",
        "send_prepare_error": "Error preparing the message to send: {error}",
        "lang_picker_title": "Idioma / Language",
        "lang_picker_prompt": "Elegi tu idioma / Choose your language",
        "lang_btn_es": "Espa\u00f1ol",
        "lang_btn_en": "English",
        "lang_toggle_btn": "ES/EN",
    },
}

# Lista unica de idiomas soportados: (codigo, nombre nativo). Tanto el
# selector de idioma de la interfaz como los dos selectores del traductor
# se arman a partir de esta misma lista, asi que agregar un idioma nuevo
# el dia de manana es una sola linea aca, nada mas.
LANGUAGE_OPTIONS = [
    ("es", "Español"),
    ("en", "English"),
]
LANGUAGE_NAME_BY_CODE = dict(LANGUAGE_OPTIONS)
LANGUAGE_CODE_BY_NAME = {name: code for code, name in LANGUAGE_OPTIONS}
# Abreviatura corta para las etiquetas del chat (ESP/ENG), no depende del
# idioma de la interfaz sino de los idiomas elegidos en el traductor.
LANGUAGE_ABBR = {"es": "ESP", "en": "ENG"}


def load_saved_lang():
    try:
        with open(LANG_FILE, "r", encoding="utf-8") as f:
            value = f.read().strip()
            if value in TEXTS:
                return value
    except Exception:
        pass
    return None


def save_lang(lang):
    try:
        ensure_config_dir()
        with open(LANG_FILE, "w", encoding="utf-8") as f:
            f.write(lang)
    except Exception:
        pass


def load_saved_translate_dir():
    valid_codes = set(LANGUAGE_NAME_BY_CODE)
    try:
        with open(TRANSLATE_DIR_FILE, "r", encoding="utf-8") as f:
            source, _, target = f.read().strip().partition(",")
            if source in valid_codes and target in valid_codes and source != target:
                return source, target
    except Exception:
        pass
    return None


def save_translate_dir(source, target):
    try:
        ensure_config_dir()
        with open(TRANSLATE_DIR_FILE, "w", encoding="utf-8") as f:
            f.write(f"{source},{target}")
    except Exception:
        pass


# ----------------------------------------------------------------------
# Componentes sin interfaz y paleta visual: se mantienen en nwn_translator/
# core.py para poder probarlos y evolucionarlos sin tocar el comportamiento
# de la ventana. La Palette vive ahi como unica fuente de verdad.
# ----------------------------------------------------------------------
from nwn_translator.core import ChatParser, Palette, TranslationEngine


class TranslatorApp:
    def __init__(self, root):
        self.root = root
        self.pal = Palette()

        self.root.title(f"{APP_NAME} v{APP_VERSION}")

        # Icono de la aplicación: se carga desde el mismo .ico usado por
        # PyInstaller. Funciona en desarrollo y dentro del EXE (--add-data).
        self.app_icon_path = resource_path("NWNEE_Traductor_NWN_Style.ico")
        self._apply_app_icon()

        self.root.geometry("860x720")
        # El layout compacto conserva el chat y la caja de escritura; no hace
        # falta reservar el espacio de los controles normales en la medida
        # minima.
        self.root.minsize(360, 180)
        self.root.configure(bg=self.pal.bg)

        # Idioma de la interfaz (botones, etiquetas, mensajes de sistema).
        # En el primer arranque (sin nada guardado) se pregunta con un
        # dialogo; despues queda recordado.
        self.my_lang = load_saved_lang()
        if self.my_lang is None:
            self.my_lang = self._prompt_language()
            save_lang(self.my_lang)

        # Direccion del traductor: de que idioma vienen los mensajes del
        # juego y a que idioma se traduce lo que vos escribis (y viceversa
        # al mandarlo). Es independiente del idioma de la interfaz -
        # podes tener la app en ingles y traducir de espanol a frances,
        # por ejemplo, el dia que se agreguen mas idiomas. Por defecto
        # arranca en el sentido complementario al idioma de la interfaz.
        saved_dir = load_saved_translate_dir()
        if saved_dir:
            self.translate_source_lang, self.translate_target_lang = saved_dir
        else:
            self.translate_target_lang = self.my_lang
            self.translate_source_lang = "en" if self.my_lang == "es" else "es"

        self.engine = TranslationEngine()
        self.parser = ChatParser()
        self.ui_queue = queue.Queue()
        self.translation_queue = queue.Queue(maxsize=200)
        self.send_lock = threading.Lock()
        self.seen_messages = deque(maxlen=250)
        self.seen_message_set = set()
        self.seen_lock = threading.Lock()

        # Cada hablante recibe un color propio durante la sesion.
        # La paleta se genera dinamicamente y no tiene un limite practico.
        self.speaker_tag_map = {}  # nombre normalizado -> tag estable
        self.speaker_color_map = {}  # tag -> color permanente de esa sesion
        self.speaker_display_map = {}  # tag -> nombre con el formato original
        self.next_speaker_color = 0
        self.chat_message_counter = 0

        self.running = True
        self.log_path = find_log_file()
        self.keep_on_top = tk.BooleanVar(value=True)
        self.auto_send = tk.BooleanVar(value=True)
        self.translation_paused = False
        self.invisible_mode = False
        self.compact_mode = False
        self._layout_restore_in_progress = False
        self._last_root_height = 0
        self.last_translation = ""
        self._drag_offset = (0, 0)

        # Proteccion contra dobles activaciones de F9 (binding local + hotkey global)
        # y contra autorepeticion demasiado rapida.
        self._last_f9_time = 0.0
        self._f9_debounce_seconds = 0.45

        ensure_config_dir()
        self.create_styles()
        self.create_interface()

        self.root.attributes("-topmost", self.keep_on_top.get())
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.restore_saved_settings()
        self.start_log_watcher()
        self.translation_thread = threading.Thread(target=self.translation_worker, name="NWN-Translation-Worker", daemon=True)
        self.translation_thread.start()
        self.root.after(50, self.process_ui_queue)

        self.root.bind("<F9>", self._on_local_f9)
        self.root.bind("<Configure>", self._on_window_resize)
        self.setup_global_hotkey()

    # ------------------------------------------------------------------
    # Idioma de la interfaz
    # ------------------------------------------------------------------

    def t(self, key, **kwargs):
        """Devuelve el texto de la interfaz en el idioma elegido por la persona."""
        text = TEXTS[self.my_lang].get(key, key)
        return text.format(**kwargs) if kwargs else text

    def _prompt_language(self):
        """Ventana de bienvenida: se muestra solo si no hay idioma guardado."""
        dialog = tk.Toplevel(self.root)
        dialog.title(TEXTS["es"]["lang_picker_title"])
        dialog.configure(bg=self.pal.bg)
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text=TEXTS["es"]["lang_picker_prompt"],
                 font=("Calibri", 12, "bold"), bg=self.pal.bg, fg=self.pal.text_main
                 ).pack(padx=36, pady=(26, 18))

        choice = {"lang": "es"}

        def pick(lang):
            choice["lang"] = lang
            dialog.destroy()

        btns = tk.Frame(dialog, bg=self.pal.bg)
        btns.pack(pady=(0, 26), padx=36)
        tk.Button(btns, text=TEXTS["es"]["lang_btn_es"], width=12, bg=self.pal.accent,
                  fg=self.pal.accent_text, relief=tk.FLAT, font=("Calibri", 10, "bold"),
                  bd=0, pady=8, cursor="hand2", command=lambda: pick("es")).pack(side=tk.LEFT, padx=6)
        tk.Button(btns, text=TEXTS["es"]["lang_btn_en"], width=12, bg=self.pal.bg_input,
                  fg=self.pal.text_main, relief=tk.FLAT, font=("Calibri", 10, "bold"),
                  bd=0, pady=8, cursor="hand2", command=lambda: pick("en")).pack(side=tk.LEFT, padx=6)

        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (dialog.winfo_width() // 2)
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{max(x, 0)}+{max(y, 0)}")

        self.root.wait_window(dialog)
        return choice["lang"]

    def on_interface_lang_selected(self, event=None):
        """Se dispara al elegir un idioma en el combobox de la interfaz."""
        selected_name = self.interface_lang_combo.get()
        code = LANGUAGE_CODE_BY_NAME.get(selected_name)
        if code is None or code == self.my_lang:
            return
        self.my_lang = code
        save_lang(self.my_lang)
        self._refresh_language_texts()

    def on_translate_lang_selected(self, event=None):
        """Se dispara al elegir un idioma en cualquiera de los dos combos del traductor."""
        source_code = LANGUAGE_CODE_BY_NAME.get(self.source_lang_combo.get())
        target_code = LANGUAGE_CODE_BY_NAME.get(self.target_lang_combo.get())
        if source_code is None or target_code is None or source_code == target_code:
            return
        self.translate_source_lang = source_code
        self.translate_target_lang = target_code
        save_translate_dir(source_code, target_code)

    def swap_translate_direction(self):
        """Botón ⇄: invierte de/hacia que idioma traduce, en cualquier momento."""
        self.translate_source_lang, self.translate_target_lang = (
            self.translate_target_lang, self.translate_source_lang)
        save_translate_dir(self.translate_source_lang, self.translate_target_lang)
        self.source_lang_combo.set(LANGUAGE_NAME_BY_CODE[self.translate_source_lang])
        self.target_lang_combo.set(LANGUAGE_NAME_BY_CODE[self.translate_target_lang])

    def _refresh_language_texts(self):
        self.invisible_btn.config(text=self.t("invisible_btn"))
        self.update_engine_label()
        self.log_status(self._last_log_status_key, self._last_log_status_found, **self._last_log_status_kwargs)
        self.update_game_status(self._last_game_status_is_open, self._last_game_status_note)
        self.send_button.config(text=self.t("send_btn"))
        self.keep_on_top_cb.config(text=self.t("keep_on_top"))
        self.auto_send_cb.config(text=self.t("auto_send"))
        self.select_log_button.config(text=self.t("select_log_btn"))
        self.copy_last_button.config(text=self.t("copy_last_btn"))
        self.clear_chat_button.config(text=self.t("clear_chat_btn"))
        self.pause_button.config(text=self.t("resume_btn") if self.translation_paused else self.t("pause_btn"))
        self.config_frame.config(text=self.t("config_frame_title"))
        self.deepl_key_label.config(text=self.t("deepl_key_label"))
        self.activate_deepl_button.config(text=self.t("activate_deepl_btn"))
        self.use_google_button.config(text=self.t("use_google_btn"))
        self.interface_lang_combo.set(LANGUAGE_NAME_BY_CODE[self.my_lang])

    # ------------------------------------------------------------------
    # Estilos y construccion de la interfaz
    # ------------------------------------------------------------------

    def _apply_app_icon(self):
        """Aplica el icono a la ventana y al icono por defecto de Tk/Windows."""
        try:
            path = resource_path("NWNEE_Traductor_NWN_Style.ico")
            if not os.path.isfile(path):
                return
            self.app_icon_path = path
            self.root.iconbitmap(path)
            try:
                self.root.iconbitmap(default=path)
            except Exception:
                pass
        except Exception:
            # El EXE sigue funcionando aunque Windows/Tk no pueda cargar el icono.
            pass

    def _on_window_resize(self, event=None):
        """Activa un modo compacto cuando la ventana se hace baja.

        En compacto ocultamos opciones secundarias (DeepL/API y controles)
        para reservar espacio al chat y, sobre todo, a la barra de escritura.
        """
        if self.invisible_mode or self._layout_restore_in_progress or event is None or event.widget is not self.root:
            return

        height = event.height
        width = event.width
        compact_dimensions = height <= 610 or width <= 720
        normal_dimensions = height >= 660 and width >= 780
        if compact_dimensions and not self.compact_mode:
            self.compact_mode = True
            self._apply_compact_layout()
        elif normal_dimensions and self.compact_mode:
            self.compact_mode = False
            self._repack_normal_widgets()

    def _apply_compact_layout(self):
        header, translate_bar, controls, config_frame = self._normal_mode_widgets
        input_frame = self._input_frame
        chat_frame = self.chat_box.master

        # Liberar packs actuales.
        for widget in (header, translate_bar, controls, config_frame, chat_frame, input_frame):
            try:
                widget.pack_forget()
            except Exception:
                pass
            try:
                widget.place_forget()
            except Exception:
                pass
        for widget in (self.input_box, self.send_button):
            try:
                widget.pack_forget()
            except Exception:
                pass

        # En una ventana estrecha los indicadores de estado ocupan casi todo
        # el encabezado. Se restauran al volver al modo normal.
        for widget in self._compact_header_widgets:
            try:
                widget.pack_forget()
            except Exception:
                pass

        # En ventana compacta ocultamos tambien el encabezado (titulo +
        # boton de modo invisible): en una ventana chica ese renglon se
        # comia una porcion grande de la pantalla. F9 y el atajo global
        # siguen activando el modo invisible aunque el boton no se vea.
        input_frame.configure(bg=self.pal.bg, height=48)
        input_frame.pack_propagate(False)
        input_frame.pack(side=tk.BOTTOM, padx=10, pady=(0, 8), fill=tk.X)
        self.input_box.pack(
            side=tk.LEFT, fill=tk.X, expand=True, ipady=7, padx=(0, 8)
        )
        self.send_button.pack(side=tk.RIGHT)

        chat_frame.pack(side=tk.TOP, padx=10, pady=4, fill=tk.BOTH, expand=True)
        self.input_box.focus_set()

    def create_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TButton", font=("Calibri", 9), padding=6)
        style.configure("Accent.TButton", background=self.pal.accent, foreground=self.pal.accent_text)
        style.map("Accent.TButton", background=[("active", self.pal.accent_hover)])
        style.configure("TCheckbutton", background=self.pal.bg_panel, foreground=self.pal.text_main,
                         font=("Calibri", 9))
        style.map("TCheckbutton", background=[("active", self.pal.bg_panel)])
        style.configure("TLabelframe", background=self.pal.bg_panel, foreground=self.pal.text_dim,
                         font=("Calibri", 9, "bold"), bordercolor=self.pal.border)
        style.configure("TLabelframe.Label", background=self.pal.bg_panel, foreground=self.pal.text_dim)
        style.configure("TFrame", background=self.pal.bg_panel)
        style.configure("Lang.TCombobox", fieldbackground=self.pal.bg_input, background=self.pal.bg_input,
                         foreground=self.pal.text_main, arrowcolor=self.pal.text_dim,
                         bordercolor=self.pal.border, lightcolor=self.pal.bg_input, darkcolor=self.pal.bg_input,
                         padding=4)
        style.map("Lang.TCombobox", fieldbackground=[("readonly", self.pal.bg_input)],
                  foreground=[("readonly", self.pal.text_main)])
        self.root.option_add("*TCombobox*Listbox.background", self.pal.bg_input)
        self.root.option_add("*TCombobox*Listbox.foreground", self.pal.text_main)
        self.root.option_add("*TCombobox*Listbox.selectBackground", self.pal.accent)
        self.root.option_add("*TCombobox*Listbox.selectForeground", self.pal.accent_text)

    def create_interface(self):
        pal = self.pal

        # --- Encabezado ---
        header = tk.Frame(self.root, bg=pal.bg)
        header.pack(fill=tk.X, padx=14, pady=(12, 6))

        title = tk.Label(header, text=f"{APP_NAME}", font=("Georgia", 15, "bold"),
                          bg=pal.bg, fg=pal.text_main)
        title.pack(side=tk.LEFT)

        self.engine_label = tk.Label(header, text="", font=("Calibri", 9, "bold"),
                                      bg=pal.bg, fg=pal.accent)
        self.engine_label.pack(side=tk.LEFT, padx=(12, 0))

        self.interface_lang_combo = ttk.Combobox(header, style="Lang.TCombobox", state="readonly",
                                                  width=9, font=("Calibri", 9),
                                                  values=[name for _, name in LANGUAGE_OPTIONS])
        self.interface_lang_combo.set(LANGUAGE_NAME_BY_CODE[self.my_lang])
        self.interface_lang_combo.bind("<<ComboboxSelected>>", self.on_interface_lang_selected)
        self.interface_lang_combo.pack(side=tk.RIGHT, padx=(8, 0))

        self.invisible_btn = tk.Button(header, text="",
                                        command=self.toggle_invisible_mode,
                                        bg=pal.bg_panel, fg=pal.text_main, activebackground=pal.border,
                                        activeforeground=pal.text_main, relief=tk.FLAT, font=("Calibri", 9),
                                        padx=10, pady=4, bd=0, cursor="hand2")
        self.invisible_btn.pack(side=tk.RIGHT)

        self.status_label = tk.Label(header, text="", font=("Calibri", 9),
                                      bg=pal.bg, fg=pal.warning)
        self.status_label.pack(side=tk.RIGHT, padx=(0, 14))

        self.game_status_label = tk.Label(header, text="", font=("Calibri", 9),
                                           bg=pal.bg, fg=pal.warning)
        self.game_status_label.pack(side=tk.RIGHT, padx=(0, 14))

        # --- Barra del traductor: de que idioma a que idioma, con boton
        # para invertir al instante (independiente del idioma de la
        # interfaz de arriba). Funciona como Google Translate: elegis los
        # dos idiomas y podes cambiarlos en cualquier momento.
        translate_bar = tk.Frame(self.root, bg=pal.bg)
        translate_bar.pack(fill=tk.X, padx=14, pady=(0, 6))

        self.source_lang_combo = ttk.Combobox(translate_bar, style="Lang.TCombobox", state="readonly",
                                               width=11, font=("Calibri", 9),
                                               values=[name for _, name in LANGUAGE_OPTIONS])
        self.source_lang_combo.set(LANGUAGE_NAME_BY_CODE[self.translate_source_lang])
        self.source_lang_combo.bind("<<ComboboxSelected>>", self.on_translate_lang_selected)
        self.source_lang_combo.pack(side=tk.LEFT)

        self.swap_lang_btn = tk.Button(translate_bar, text="\u21C4", command=self.swap_translate_direction,
                                        bg=pal.bg, fg=pal.accent, activebackground=pal.bg_panel,
                                        activeforeground=pal.accent_hover, relief=tk.FLAT,
                                        font=("Calibri", 12, "bold"), bd=0, padx=10, cursor="hand2")
        self.swap_lang_btn.pack(side=tk.LEFT)

        self.target_lang_combo = ttk.Combobox(translate_bar, style="Lang.TCombobox", state="readonly",
                                               width=11, font=("Calibri", 9),
                                               values=[name for _, name in LANGUAGE_OPTIONS])
        self.target_lang_combo.set(LANGUAGE_NAME_BY_CODE[self.translate_target_lang])
        self.target_lang_combo.bind("<<ComboboxSelected>>", self.on_translate_lang_selected)
        self.target_lang_combo.pack(side=tk.LEFT)

        # --- Chat ---
        chat_frame = tk.Frame(self.root, bg=pal.bg)
        chat_frame.pack(padx=14, pady=6, fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(chat_frame, bg=pal.bg_panel, troughcolor=pal.bg, bd=0)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.chat_box = tk.Text(chat_frame, state='disabled', wrap='word', bg=pal.bg_panel,
                                 fg=pal.text_main, font=("Calibri", 11), relief=tk.FLAT,
                                 yscrollcommand=scrollbar.set, padx=12, pady=10, bd=0,
                                 highlightthickness=1, highlightbackground=pal.border,
                                 highlightcolor=pal.accent, selectbackground=pal.selection,
                                 selectforeground=pal.text_main)
        self.chat_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.chat_box.yview)
        self.chat_box.bind("<Double-Button-1>", self.copy_speaker_from_click)

        self.chat_box.tag_config("aviso", foreground=pal.system, font=("Calibri", 9, "italic"))
        self.chat_box.tag_config("hablante", foreground=pal.speaker, font=("Georgia", 11, "bold"))
        self.chat_box.tag_config("traducido", foreground=pal.spanish, font=("Calibri", 11))
        self.chat_box.tag_config("original", foreground=pal.english, font=("Calibri", 10))
        self.chat_box.tag_config("saliente", foreground=pal.outgoing, font=("Calibri", 11, "bold"))
        self.chat_box.tag_config("error", foreground=pal.error, font=("Calibri", 10, "bold"))
        self.chat_box.tag_config("divisor", foreground=pal.separator, font=("Calibri", 4))

        # --- Entrada de texto ---
        input_frame = tk.Frame(self.root, bg=pal.bg, height=48)
        input_frame.pack_propagate(False)
        input_frame.pack(padx=14, pady=(0, 8), fill=tk.X)

        self.input_box = tk.Entry(input_frame, bg=pal.bg_input, fg=pal.text_main,
                                   insertbackground=pal.text_main, font=("Calibri", 11),
                                   relief=tk.FLAT, highlightthickness=1,
                                   highlightbackground=pal.border, highlightcolor=pal.accent,
                                   selectbackground=pal.selection, selectforeground=pal.text_main)
        self.input_box.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=8, padx=(0, 8))
        self.input_box.bind("<Return>", self.dispatch_to_game)

        self.send_button = tk.Button(input_frame, text="", command=lambda: self.dispatch_to_game(None),
                                      bg=pal.accent, fg=pal.accent_text, activebackground=pal.accent_hover,
                                      relief=tk.FLAT, font=("Calibri", 10, "bold"), bd=0, padx=16,
                                      cursor="hand2")
        self.send_button.pack(side=tk.RIGHT)

        # --- Controles ---
        controls = tk.Frame(self.root, bg=pal.bg)
        controls.pack(padx=14, pady=(0, 8), fill=tk.X)

        self.keep_on_top_cb = ttk.Checkbutton(controls, text="", variable=self.keep_on_top,
                                               command=self.toggle_topmost)
        self.keep_on_top_cb.pack(side=tk.LEFT, padx=(0, 12))
        self.auto_send_cb = ttk.Checkbutton(controls, text="", variable=self.auto_send)
        self.auto_send_cb.pack(side=tk.LEFT, padx=(0, 12))

        self.select_log_button = tk.Button(controls, text="", command=self.select_log, bg=pal.bg_panel,
                                            fg=pal.text_main, relief=tk.FLAT, font=("Calibri", 9), bd=0,
                                            padx=10, pady=4, cursor="hand2")
        self.select_log_button.pack(side=tk.LEFT, padx=(0, 6))
        self.copy_last_button = tk.Button(controls, text="", command=self.copy_last_translation, bg=pal.bg_panel,
                                           fg=pal.text_main, relief=tk.FLAT, font=("Calibri", 9), bd=0,
                                           padx=10, pady=4, cursor="hand2")
        self.copy_last_button.pack(side=tk.LEFT, padx=(0, 6))
        self.clear_chat_button = tk.Button(controls, text="", command=self.clear_chat, bg=pal.bg_panel,
                                            fg=pal.text_main, relief=tk.FLAT, font=("Calibri", 9), bd=0,
                                            padx=10, pady=4, cursor="hand2")
        self.clear_chat_button.pack(side=tk.LEFT, padx=(0, 6))

        self.pause_button = tk.Button(controls, text="",
                                       command=self.toggle_translation_pause,
                                       bg=pal.bg_panel, fg=pal.text_main,
                                       activebackground=pal.border, activeforeground=pal.text_main,
                                       relief=tk.FLAT, font=("Calibri", 9), bd=0, padx=10, pady=4,
                                       cursor="hand2")
        self.pause_button.pack(side=tk.LEFT)

        # --- Config DeepL ---
        self.config_frame = ttk.LabelFrame(self.root, text="")
        self.config_frame.pack(padx=14, pady=(0, 14), fill=tk.X)

        inner = tk.Frame(self.config_frame, bg=pal.bg_panel)
        inner.pack(fill=tk.X, padx=10, pady=10)
        inner.columnconfigure(0, weight=1)

        self.deepl_key_label = tk.Label(inner, text="", bg=pal.bg_panel, fg=pal.text_dim,
                                         font=("Calibri", 9))
        self.deepl_key_label.grid(row=0, column=0, sticky="w")
        self.key_entry = tk.Entry(inner, width=40, bg=pal.bg_input, fg=pal.text_main,
                                   insertbackground=pal.text_main, font=("Calibri", 9), show="*",
                                   relief=tk.FLAT, highlightthickness=1, highlightbackground=pal.border)
        self.key_entry.grid(row=1, column=0, sticky="ew", pady=(4, 0), ipady=4)

        btns = tk.Frame(inner, bg=pal.bg_panel)
        btns.grid(row=1, column=1, padx=(8, 0))
        self.activate_deepl_button = tk.Button(btns, text="", command=self.activate_deepl, bg=pal.accent,
                                                fg=pal.accent_text, relief=tk.FLAT, font=("Calibri", 9, "bold"),
                                                bd=0, padx=10, pady=4, cursor="hand2")
        self.activate_deepl_button.pack(side=tk.LEFT, padx=(0, 6))
        self.use_google_button = tk.Button(btns, text="", command=self.use_google, bg=pal.bg_input,
                                            fg=pal.text_main, relief=tk.FLAT, font=("Calibri", 9), bd=0,
                                            padx=10, pady=4, cursor="hand2")
        self.use_google_button.pack(side=tk.LEFT)

        # Widgets a ocultar en modo invisible
        self._normal_mode_widgets = [header, translate_bar, controls, self.config_frame]
        self._input_frame = input_frame
        self._compact_header_widgets = [self.engine_label, self.status_label, self.game_status_label]

        self.log_status("searching", False)
        self.update_game_status(False, None)
        self._refresh_language_texts()

    # ------------------------------------------------------------------
    # Configuracion (API key via keyring, con fallback ofuscado)
    # ------------------------------------------------------------------

    def restore_saved_settings(self):
        api_key = None
        try:
            if KEYRING_OK:
                api_key = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
        except Exception as e:
            self.append_message(self.t("keyring_read_failed", error=e), "aviso")

        if not api_key and os.path.exists(FALLBACK_KEY_FILE):
            try:
                with open(FALLBACK_KEY_FILE, "rb") as f:
                    api_key = _deobfuscate(f.read().strip())
            except Exception:
                api_key = None

        if api_key:
            self.key_entry.insert(0, api_key)
            threading.Thread(target=self._load_deepl_worker, args=(api_key,), daemon=True).start()

    def _load_deepl_worker(self, api_key):
        try:
            self.engine.set_deepl(api_key)
            self.ui_queue.put(("update_engine_label", None))
            self.ui_queue.put(("system", self.t("deepl_auto_ok")))
        except Exception as e:
            self.ui_queue.put(("system", self.t("deepl_auto_failed", error=e)))

    def save_deepl_key(self, api_key):
        try:
            if KEYRING_OK:
                keyring.set_password(KEYRING_SERVICE, KEYRING_USER, api_key)
                return
        except Exception:
            pass
        # Fallback: guardado local ofuscado (no es cifrado real, pero no queda texto plano)
        try:
            with open(FALLBACK_KEY_FILE, "wb") as f:
                f.write(_obfuscate(api_key))
        except Exception as e:
            self.ui_queue.put(("error", self.t("deepl_save_failed", error=e)))

    def activate_deepl(self):
        api_key = self.key_entry.get().strip()
        if not api_key:
            messagebox.showwarning(APP_NAME, self.t("deepl_key_missing"))
            return
        self.set_controls_enabled(False)
        threading.Thread(target=self._activate_deepl_worker, args=(api_key,), daemon=True).start()

    def _activate_deepl_worker(self, api_key):
        try:
            self.engine.set_deepl(api_key)
            self.save_deepl_key(api_key)
            self.ui_queue.put(("update_engine_label", None))
            self.ui_queue.put(("ui_message", self.t("deepl_activated_ok")))
        except Exception as e:
            self.ui_queue.put(("ui_error", self.t("deepl_activate_failed", error=e)))
        finally:
            self.ui_queue.put(("set_controls_enabled", True))

    def use_google(self):
        try:
            self.engine.set_google()
        except Exception as e:
            messagebox.showerror(APP_NAME, self.t("google_activate_failed", error=e))
            return
        self.update_engine_label()
        self.append_message(self.t("engine_changed_google"), "aviso")

    def update_engine_label(self):
        prefix = self.t("engine_prefix")
        if self.engine.mode == "DeepL":
            self.engine_label.config(text=f"{prefix}: {self.t('engine_deepl')}", fg=self.pal.speaker)
        else:
            self.engine_label.config(text=f"{prefix}: {self.t('engine_google')}", fg=self.pal.accent)

    def toggle_translation_pause(self):
        self.translation_paused = not self.translation_paused
        if self.translation_paused:
            self.pause_button.config(text=self.t("resume_btn"))
            self.append_message(self.t("translation_paused_msg"), "aviso")
        else:
            self.pause_button.config(text=self.t("pause_btn"))
            self.append_message(self.t("translation_resumed_msg"), "aviso")

    def update_game_status(self, is_open, note_key=None):
        self._last_game_status_is_open = is_open
        self._last_game_status_note = note_key
        prefix = self.t("game_prefix")
        if note_key:
            self.game_status_label.config(text=f"{prefix}: {self.t(note_key)}", fg=self.pal.text_dim)
        elif is_open:
            self.game_status_label.config(text=f"{prefix}: {self.t('connected')}", fg=self.pal.accent)
        else:
            self.game_status_label.config(text=f"{prefix}: {self.t('waiting')}", fg=self.pal.warning)

    def set_controls_enabled(self, enabled):
        state = tk.NORMAL if enabled else tk.DISABLED
        try:
            self.send_button.config(state=state)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Lectura del log (con rotacion por inodo + deteccion de encoding)
    # ------------------------------------------------------------------

    def start_log_watcher(self):
        self.log_thread = threading.Thread(target=self.monitor_log_file, name="NWN-Log-Watcher", daemon=True)
        self.log_thread.start()
        self.game_watch_thread = threading.Thread(target=self.watch_game_window,
                                                    name="NWN-Window-Watcher", daemon=True)
        self.game_watch_thread.start()

    def watch_game_window(self):
        """Chequea cada pocos segundos si la ventana de Neverwinter esta
        abierta, para poder mostrar si esta 'conectado' o 'esperando' -
        util para saber de un vistazo si hace falta reabrir el juego."""
        if gw is None:
            self.ui_queue.put(("game_status", (False, "no_pygetwindow")))
            return
        was_open = None
        while self.running:
            try:
                found = self.find_nwn_window()
                is_open = found is not None
            except Exception:
                is_open = False
            if is_open != was_open:
                self.ui_queue.put(("game_status", (is_open, None)))
                was_open = is_open
            time.sleep(2)

    def select_log(self):
        path = filedialog.askopenfilename(
            title=self.t("select_log_dialog_title"),
            filetypes=[("Log", "*.txt"), ("*", "*.*")])
        if path:
            self.log_path = path
            self.log_status("log_selected", True, name=os.path.basename(path))
            self.append_message(self.t("log_selected_msg", path=path), "aviso")

    def log_status(self, key, found, **fmt):
        self._last_log_status_key = key
        self._last_log_status_found = found
        self._last_log_status_kwargs = fmt
        color = self.pal.accent if found else self.pal.warning
        prefix = self.t("log_prefix")
        self.status_label.config(text=f"{prefix}: {self.t(key, **fmt)}", fg=color)

    @staticmethod
    def _decode_line(raw_bytes):
        try:
            return raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return raw_bytes.decode("latin-1", errors="ignore")

    @staticmethod
    def get_file_inode(path):
        try:
            return os.stat(path).st_ino
        except OSError:
            return None

    def monitor_log_file(self):
        while self.running and not self.log_path:
            self.ui_queue.put(("log_status", ("searching", False)))
            self.log_path = find_log_file()
            time.sleep(1)

        if not self.running:
            return

        self.ui_queue.put(("log_status", ("connected", True)))
        self.ui_queue.put(("system", self.t("log_detected_status")))

        self.read_log_file()

    def read_log_file(self):
        last_inode = None
        f = None
        try:
            while self.running:
                if not self.log_path or not os.path.isfile(self.log_path):
                    time.sleep(1)
                    continue

                current_inode = self.get_file_inode(self.log_path)
                if f is None or current_inode != last_inode:
                    if f:
                        f.close()
                    f = open(self.log_path, "rb")
                    f.seek(0, os.SEEK_END)
                    last_inode = current_inode
                    if last_inode is not None:
                        self.ui_queue.put(("system", self.t("log_connected_status")))

                # Si el archivo se hizo mas chico que nuestra posicion actual
                # (mismo inodo, pero el juego lo trunco/reinicio al arrancar
                # una sesion nueva), volvemos al inicio en vez de quedarnos
                # esperando datos que ya no van a llegar en esa posicion.
                try:
                    current_size = os.fstat(f.fileno()).st_size
                except OSError:
                    current_size = None
                if current_size is not None and current_size < f.tell():
                    f.seek(0)
                    self.ui_queue.put((
                        "system",
                        self.t("log_reset_status"),
                    ))

                raw_line = f.readline()
                if not raw_line:
                    time.sleep(LOG_POLL_INTERVAL)
                    # revisa si el log roto (nueva sesion crea archivo nuevo con mismo nombre)
                    new_inode = self.get_file_inode(self.log_path)
                    if new_inode != last_inode:
                        continue  # se reabrira en la siguiente vuelta del while
                    continue

                clean_line = self._decode_line(raw_line).strip()
                if clean_line:
                    self.process_log_line(clean_line)
        except Exception as e:
            self.ui_queue.put(("error", self.t("log_read_error", error=e)))
        finally:
            if f:
                f.close()

    def _message_fingerprint(self, speaker, text):
        return (speaker or "").strip().lower(), " ".join(text.split()).strip().lower()

    def _is_duplicate_message(self, speaker, text):
        fingerprint = self._message_fingerprint(speaker, text)
        with self.seen_lock:
            if fingerprint in self.seen_message_set:
                return True
            if len(self.seen_messages) == self.seen_messages.maxlen:
                old = self.seen_messages.popleft()
                self.seen_message_set.discard(old)
            self.seen_messages.append(fingerprint)
            self.seen_message_set.add(fingerprint)
        return False

    def process_log_line(self, line):
        parsed = self.parser.parse(line)
        if parsed is None:
            return
        speaker, text = parsed
        if not self.parser.should_translate(text):
            return
        if self.translation_paused:
            return
        if self._is_duplicate_message(speaker, text):
            return
        try:
            self.translation_queue.put((speaker, text), timeout=0.5)
        except queue.Full:
            self.ui_queue.put(("error", self.t("queue_full_error")))

    def translation_worker(self):
        while self.running:
            try:
                job = self.translation_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if job is None:
                self.translation_queue.task_done()
                break
            speaker, text = job
            try:
                if self.translation_paused:
                    continue
                translated = self.engine.translate(text, source_lang=self.translate_source_lang, target_lang=self.translate_target_lang)
                self.last_translation = translated
                self.ui_queue.put(("chat", {"speaker": speaker, "english": text, "spanish": translated}))
            except Exception as e:
                self.ui_queue.put(("error", self.t("translate_error", snippet=text[:40], error=e)))
            finally:
                self.translation_queue.task_done()

    # ------------------------------------------------------------------
    # Envio de texto al juego
    # ------------------------------------------------------------------

    def dispatch_to_game(self, event):
        text_own = self.input_box.get().strip()
        if not text_own:
            return
        auto_send = self.auto_send.get()
        self.input_box.delete(0, tk.END)
        threading.Thread(target=self._send_worker, args=(text_own, auto_send), daemon=True).start()

    def _send_worker(self, text_own, auto_send):
        with self.send_lock:
            try:
                # Usa el mismo caché estricto que las traducciones recibidas.
                # La clave incluye texto exacto + idiomas + motor, por lo que
                # Google/DeepL y frases diferentes nunca se mezclan.
                text_target = self.engine.translate(text_own, source_lang=self.translate_target_lang, target_lang=self.translate_source_lang, use_cache=True)
            except Exception as e:
                self.ui_queue.put(("error", self.t("send_prepare_error", error=e)))
                return

            if auto_send:
                try:
                    self.send_text_to_nwn(text_target)
                    self.ui_queue.put(("outgoing", {"text": text_target, "sent": True}))
                except Exception as e:
                    self.ui_queue.put(("error", str(e)))
            else:
                self.ui_queue.put(("outgoing", {"text": text_target, "sent": False}))

    def find_nwn_window(self):
        if gw is None:
            raise RuntimeError(self.t("no_pygetwindow_error"))
        for title in ("Neverwinter Nights: Enhanced Edition", "Neverwinter Nights"):
            windows = gw.getWindowsWithTitle(title)
            windows = [w for w in windows if w.visible]
            if windows:
                return windows[0]
        raise RuntimeError(self.t("window_not_found_error"))

    def send_text_to_nwn(self, text):
        if pyautogui is None:
            raise RuntimeError(self.t("no_pyautogui_error"))
        window = self.find_nwn_window()
        title = (getattr(window, "title", "") or "").lower()
        if "neverwinter nights" not in title:
            raise RuntimeError("La ventana encontrada no parece ser Neverwinter Nights.")
        window.activate()
        time.sleep(0.15)
        pyautogui.press('enter')
        time.sleep(0.05)
        pyautogui.write(text, interval=0.01)
        time.sleep(0.05)
        pyautogui.press('enter')
        self.ui_queue.put(("return_focus", None))

    def return_focus(self):
        try:
            self.root.lift()
            self.input_box.focus_set()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Cola de UI (thread-safe)
    # ------------------------------------------------------------------

    def process_ui_queue(self):
        try:
            while True:
                action, data = self.ui_queue.get_nowait()
                if action == "chat":
                    self.display_chat(data)
                elif action == "outgoing":
                    self.display_outgoing(data)
                elif action == "error":
                    self.display_error(data)
                elif action == "system":
                    self.append_message(f"[{self.t('system_prefix')}]: {data}", "aviso")
                elif action == "update_engine_label":
                    self.update_engine_label()
                elif action == "ui_message":
                    messagebox.showinfo(APP_NAME, data)
                elif action == "ui_error":
                    messagebox.showerror(APP_NAME, data)
                elif action == "set_controls_enabled":
                    self.set_controls_enabled(data)
                elif action == "game_status":
                    self.update_game_status(*data)
                elif action == "log_status":
                    self.log_status(*data)
                elif action == "return_focus":
                    self.return_focus()
                elif action == "toggle_invisible":
                    self._handle_f9_toggle()
        except queue.Empty:
            pass
        finally:
            if self.running:
                self.root.after(50, self.process_ui_queue)

    def _get_speaker_tag(self, speaker, current_message_counter):
        """Devuelve un tag de color estable para cada hablante de la sesion.

        Los colores ya no se liberan ni se reciclan tras cierto numero de
        mensajes: asi un nombre no cambia de color durante una sesion larga.
        """
        if not speaker:
            return "hablante"

        key = re.sub(r"\s+", " ", speaker.strip()).casefold()

        tag_name = self.speaker_tag_map.get(key)
        if tag_name:
            return tag_name

        color_index = len(self.speaker_color_map)
        if color_index < len(self.pal.speaker_colors):
            color = self.pal.speaker_colors[color_index]
        else:
            # Caso extremo: generamos tonos saturados y de luminosidad
            # controlada; nunca usamos blanco como color de respaldo.
            i = self.next_speaker_color
            self.next_speaker_color += 1
            hue = (i * 0.618033988749895) % 1.0
            saturation = 0.68
            lightness = 0.60
            r, g, b = colorsys.hls_to_rgb(hue, lightness, saturation)
            color = "#{:02X}{:02X}{:02X}".format(
                int(r * 255), int(g * 255), int(b * 255)
            )

        tag_name = f"speaker_{len(self.speaker_color_map) + 1}"
        self.speaker_tag_map[key] = tag_name
        self.speaker_color_map[tag_name] = color
        self.speaker_display_map[tag_name] = speaker.strip()

        # Incluso en modo invisible el color identifica al hablante; solo el
        # fondo del overlay desaparece.
        self.chat_box.tag_config(
            tag_name, foreground=color, font=("Georgia", 11, "bold")
        )
        return tag_name

    def _set_overlay_text_colors(self, enabled):
        """Cambia los colores de los tags sin recrear el contenido del chat."""
        if enabled:
            text_color = self.pal.overlay_text
            self.chat_box.tag_config("aviso", foreground=text_color, font=("Calibri", 10, "bold"))
            self.chat_box.tag_config("traducido", foreground=text_color, font=("Calibri", 11, "bold"))
            # En invisible el ingles queda claramente secundario: mas pequeno
            # para que el ojo encuentre primero la traduccion al espanol.
            self.chat_box.tag_config("original", foreground=text_color, font=("Calibri", 8))
            self.chat_box.tag_config("saliente", foreground=text_color, font=("Calibri", 11, "bold"))
            self.chat_box.tag_config("error", foreground=text_color, font=("Calibri", 11, "bold"))
            self.chat_box.tag_config("divisor", foreground=self._transparent_tag_color, font=("Calibri", 4))
            # El overlay vuelve transparente el fondo, pero conserva los
            # colores de los nombres para identificar a cada persona.
            for tag_name, color in self.speaker_color_map.items():
                self.chat_box.tag_config(tag_name, foreground=color, font=("Georgia", 11, "bold"))
        else:
            self.chat_box.tag_config("aviso", foreground=self.pal.system, font=("Calibri", 9, "italic"))
            self.chat_box.tag_config("traducido", foreground=self.pal.spanish, font=("Calibri", 11))
            self.chat_box.tag_config("original", foreground=self.pal.english, font=("Calibri", 10))
            self.chat_box.tag_config("saliente", foreground=self.pal.outgoing, font=("Calibri", 11, "bold"))
            self.chat_box.tag_config("error", foreground=self.pal.error, font=("Calibri", 10, "bold"))
            self.chat_box.tag_config("divisor", foreground=self.pal.separator, font=("Calibri", 4))
            for tag_name, color in self.speaker_color_map.items():
                self.chat_box.tag_config(tag_name, foreground=color, font=("Georgia", 11, "bold"))

    def copy_speaker_from_click(self, event):
        """Copia el nombre del hablante al hacer doble clic sobre él."""
        index = self.chat_box.index(f"@{event.x},{event.y}")
        tags = self.chat_box.tag_names(index)
        speaker_tag = next((tag for tag in tags if tag.startswith("speaker_")), None)
        if not speaker_tag:
            return

        speaker = self.speaker_display_map.get(speaker_tag)
        if not speaker:
            return

        self.root.clipboard_clear()
        self.root.clipboard_append(speaker)
        self.root.update_idletasks()
        self.append_message(self.t("name_copied", speaker=speaker), "aviso")
        return "break"

    @staticmethod
    def _transparent_tag_color():
        # El separador es casi imperceptible en modo invisible.
        # Este color no coincide con el transparentcolor de la ventana.
        return "#1B1B1D"

    def display_chat(self, data):
        self.chat_message_counter += 1
        if data["speaker"]:
            self.append_message(f"{data['speaker']}\n", self._get_speaker_tag(data["speaker"], self.chat_message_counter))
        prefix_mine = LANGUAGE_ABBR.get(self.translate_target_lang, self.translate_target_lang.upper())
        prefix_other = LANGUAGE_ABBR.get(self.translate_source_lang, self.translate_source_lang.upper())
        self.append_message(f"   {prefix_mine}: {data['spanish']}\n", "traducido")
        self.append_message(f"   {prefix_other}: {data['english']}\n", "original")
        self.append_message("\u2500" * 40 + "\n", "divisor")
        self.trim_chat()

    def display_outgoing(self, data):
        prefix = self.t("sent_to_game") if data["sent"] else self.t("auto_send_off")
        self.append_message(f"--> {prefix}: {data['text']}\n", "saliente")
        self.append_message("\u2500" * 40 + "\n", "divisor")
        self.trim_chat()

    def display_error(self, message):
        self.append_message(f"[ERROR] {message}\n", "error")
        self.trim_chat()

    def append_message(self, text, tag=None):
        self.chat_box.config(state='normal')
        fraction = self.chat_box.yview()[1]
        if tag:
            self.chat_box.insert(tk.END, text, tag)
        else:
            self.chat_box.insert(tk.END, text)
        self.chat_box.config(state='disabled')
        if fraction >= 0.9:
            self.chat_box.see(tk.END)

    def trim_chat(self):
        line_count = int(self.chat_box.index('end-1c').split('.')[0])
        if line_count > MAX_CHAT_MESSAGES:
            self.chat_box.config(state='normal')
            self.chat_box.delete("1.0", f"{line_count - MAX_CHAT_MESSAGES}.0")
            self.chat_box.config(state='disabled')

    # ------------------------------------------------------------------
    # Controles varios
    # ------------------------------------------------------------------

    def copy_last_translation(self):
        if not self.last_translation:
            messagebox.showinfo(APP_NAME, self.t("no_translation_yet"))
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self.last_translation)
        self.append_message(self.t("last_translation_copied"), "aviso")

    def clear_chat(self):
        self.chat_box.config(state='normal')
        self.chat_box.delete("1.0", tk.END)
        self.chat_box.config(state='disabled')

    def toggle_topmost(self):
        self.root.attributes("-topmost", self.keep_on_top.get())

    # ------------------------------------------------------------------
    # Atajo global de teclado (funciona con el foco en el juego)
    # ------------------------------------------------------------------

    def setup_global_hotkey(self):
        if GLOBAL_HOTKEYS_OK:
            try:
                global_hotkeys.add_hotkey("f9", self._on_global_hotkey)
                self._native_hotkey_thread = None
                return
            except Exception as e:
                self.append_message(self.t("hotkey_register_failed", error=e), "aviso")

        # Fallback sin dependencia externa: Windows consulta el estado global de F9.
        # Esto evita perder F9 solo porque la libreria 'keyboard' no este instalada.
        if os.name == "nt":
            self._native_hotkey_thread = threading.Thread(
                target=self._native_f9_watcher,
                name="NWN-F9-Watcher",
                daemon=True,
            )
            self._native_hotkey_thread.start()
            self.append_message(self.t("hotkey_registered_ok"), "aviso")
        else:
            self._native_hotkey_thread = None
            self.append_message(self.t("hotkey_unavailable"), "aviso")

    def _native_f9_watcher(self):
        """Detector global de F9 para Windows cuando 'keyboard' no esta disponible."""
        user32 = ctypes.windll.user32
        VK_F9 = 0x78
        was_down = False
        while self.running:
            try:
                is_down = bool(user32.GetAsyncKeyState(VK_F9) & 0x8000)
            except Exception:
                return
            if is_down and not was_down:
                self.ui_queue.put(("toggle_invisible", None))
            was_down = is_down
            time.sleep(0.035)

    def _on_local_f9(self, event=None):
        """Recibe F9 cuando la ventana del traductor tiene el foco."""
        self._request_f9_toggle()
        return "break"

    def _on_global_hotkey(self):
        # El callback global corre fuera del hilo de Tkinter.
        self._request_f9_toggle()

    def _request_f9_toggle(self):
        """Envia la peticion de F9 al hilo propietario de Tkinter."""
        if self.running:
            self.ui_queue.put(("toggle_invisible", None))

    def _handle_f9_toggle(self):
        """Cambia el modo una sola vez por pulsacion F9."""
        if not self.running:
            return
        now = time.monotonic()
        if now - self._last_f9_time < self._f9_debounce_seconds:
            return
        self._last_f9_time = now
        self.toggle_invisible_mode()

    # ------------------------------------------------------------------
    # Modo invisible (overlay translucido, solo Windows)
    # ------------------------------------------------------------------

    def toggle_invisible_mode(self):
        if not self.invisible_mode:
            self.enter_invisible_mode()
        else:
            self.exit_invisible_mode()

    def enter_invisible_mode(self):
        """Activa el overlay usando la misma estructura que la version 4.1.

        Importante: el Entry NO se desacopla, NO usa place() y NO se oculta.
        En Windows, -transparentcolor hace transparente solo los pixeles que
        coinciden con la clave; el Entry conserva un fondo opaco propio y por
        eso sigue siendo visible y clickeable.
        """
        pal = self.pal
        transparent_key = "#010203"

        try:
            self.root.attributes("-transparentcolor", transparent_key)
        except tk.TclError:
            messagebox.showwarning(
                APP_NAME,
                "El modo invisible usa una funcion especifica de Windows "
                "(-transparentcolor) que no esta disponible en este sistema.")
            return

        self.invisible_mode = True
        self._pre_overlay_geometry = self.root.geometry()
        self._return_to_compact_mode = self.compact_mode or self.root.winfo_height() <= 610

        # Ocultar SOLO los paneles secundarios. La barra de escritura
        # (_input_frame) permanece en su pack original.
        for widget in self._normal_mode_widgets:
            widget.pack_forget()
        try:
            self.send_button.pack_forget()
        except Exception:
            pass

        self.root.overrideredirect(True)
        self.root.configure(bg=transparent_key)

        # Chat: totalmente transparente.
        chat_frame = self.chat_box.master
        chat_frame.configure(bg=transparent_key)
        self.chat_box.configure(
            bg=transparent_key,
            highlightthickness=0,
            padx=6,
            pady=6
        )
        self._set_overlay_text_colors(True)

        # ESTE ES EL PUNTO CLAVE:
        # igual que en la v4.1, el contenedor de entrada se mantiene en pack.
        # Solo el frame se vuelve transparente; el Entry conserva su fondo real.
        self._input_frame.configure(bg=transparent_key)
        self.input_box.configure(
            bg=pal.bg_input,
            fg=pal.text_main,
            insertbackground=pal.text_main,
            font=("Calibri", 11),
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=pal.accent,
            highlightcolor=pal.accent_hover
        )

        # Eliminamos el hint del overlay: no aporta nada y no debe competir
        # visualmente con la unica zona de entrada.
        try:
            if hasattr(self, "overlay_hint") and self.overlay_hint.winfo_exists():
                self.overlay_hint.destroy()
        except Exception:
            pass

        # Garantizar que el frame de entrada siga en la jerarquia de pack.
        try:
            self._input_frame.place_forget()
        except Exception:
            pass
        self._input_frame.pack_forget()
        self._input_frame.pack(
            side=tk.BOTTOM,
            padx=8,
            pady=(4, 8),
            fill=tk.X
        )
        self.input_box.pack_forget()
        self.input_box.pack(
            side=tk.LEFT,
            fill=tk.X,
            expand=True,
            ipady=6,
            padx=(0, 0)
        )

        self.input_box.focus_set()
        self._input_frame.lift()

        # En invisible no mostramos el boton Enviar. Enter sigue enviando.
        try:
            self.send_button.pack_forget()
        except Exception:
            pass

        self.root.attributes("-topmost", True)
        self.root.update_idletasks()

    def exit_invisible_mode(self):
        pal = self.pal
        self.invisible_mode = False

        try:
            self.root.attributes("-transparentcolor", "")
        except tk.TclError:
            pass

        self.root.overrideredirect(False)
        self.root.configure(bg=pal.bg)

        try:
            if hasattr(self, "overlay_hint") and self.overlay_hint.winfo_exists():
                self.overlay_hint.destroy()
        except Exception:
            pass

        header, translate_bar, controls, config_frame = self._normal_mode_widgets
        input_frame = self._input_frame
        chat_frame = self.chat_box.master

        # Limpiar tanto pack como place para evitar restos del overlay.
        for widget in (header, translate_bar, controls, config_frame, chat_frame, input_frame):
            try:
                widget.pack_forget()
            except Exception:
                pass
            try:
                widget.place_forget()
            except Exception:
                pass
        for widget in (self.input_box, self.send_button):
            try:
                widget.pack_forget()
            except Exception:
                pass
            try:
                widget.place_forget()
            except Exception:
                pass

        chat_frame.configure(bg=pal.bg)
        self.chat_box.configure(
            bg=pal.bg_panel,
            highlightthickness=1,
            padx=12,
            pady=10
        )
        self._set_overlay_text_colors(False)

        input_frame.configure(bg=pal.bg, height=48)
        input_frame.pack_propagate(False)
        self.input_box.configure(
            bg=pal.bg_input,
            fg=pal.text_main,
            insertbackground=pal.text_main,
            font=("Calibri", 11),
            highlightthickness=1,
            highlightbackground=pal.border,
            highlightcolor=pal.accent,
            relief=tk.FLAT
        )

        # Restaurar exactamente el modo que habia antes de entrar al overlay.
        # Durante esta restauracion bloqueamos el handler de <Configure> para
        # evitar que una reordenacion intermedia vuelva a romper la caja de texto.
        self._layout_restore_in_progress = True
        try:
            restore_compact = getattr(self, "_return_to_compact_mode", False)

            self.root.attributes("-topmost", self.keep_on_top.get())
            if hasattr(self, "_pre_overlay_geometry"):
                self.root.geometry(self._pre_overlay_geometry)
            self.root.update_idletasks()

            self.compact_mode = bool(restore_compact)
            if restore_compact:
                # No pasamos primero por el layout completo: reconstruimos
                # directamente el layout compacto para garantizar que la caja
                # de escritura quede visible al salir de invisible.
                self._apply_compact_layout()
            else:
                self._repack_normal_widgets()

            # Aplicar el icono despues de retirar el overrideredirect.
            self._apply_app_icon()
            self.root.update_idletasks()
            self.input_box.focus_set()
        finally:
            self._layout_restore_in_progress = False

    def _rebuild_normal_layout(self):
        """Restaura el layout normal sin duplicar widgets."""
        if self.invisible_mode:
            self.exit_invisible_mode()
        else:
            self._repack_normal_widgets()

    def _repack_normal_widgets(self):
        """Restaura el layout normal. La barra de escritura queda anclada
        al borde inferior y mantiene una altura minima fija."""
        header, translate_bar, controls, config_frame = self._normal_mode_widgets
        input_frame = self._input_frame
        chat_frame = self.chat_box.master

        for widget in (header, translate_bar, controls, config_frame, chat_frame, input_frame):
            try:
                widget.pack_forget()
            except Exception:
                pass
        for widget in (self.input_box, self.send_button):
            try:
                widget.pack_forget()
            except Exception:
                pass

        input_frame.configure(bg=self.pal.bg, height=48)
        input_frame.pack_propagate(False)
        self.input_box.configure(
            bg=self.pal.bg_input, fg=self.pal.text_main,
            insertbackground=self.pal.text_main,
            highlightthickness=1,
            highlightbackground=self.pal.border,
            highlightcolor=self.pal.accent,
            relief=tk.FLAT
        )

        header.pack(side=tk.TOP, fill=tk.X, padx=14, pady=(12, 6))
        # Los indicadores se ocultan solo en compacto; al volver a normal
        # deben volver a administrarse explícitamente por pack.
        self.engine_label.pack(side=tk.LEFT, padx=(12, 0))
        self.interface_lang_combo.pack(side=tk.RIGHT, padx=(8, 0))
        self.invisible_btn.pack(side=tk.RIGHT)
        self.status_label.pack(side=tk.RIGHT, padx=(0, 14))
        self.game_status_label.pack(side=tk.RIGHT, padx=(0, 14))
        translate_bar.pack(side=tk.TOP, fill=tk.X, padx=14, pady=(0, 6))
        config_frame.pack(side=tk.TOP, padx=14, pady=(0, 14), fill=tk.X)
        controls.pack(side=tk.TOP, padx=14, pady=(0, 8), fill=tk.X)

        # La entrada se reserva primero en el borde inferior.
        input_frame.pack(side=tk.BOTTOM, padx=14, pady=(0, 8), fill=tk.X)
        self.input_box.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=8, padx=(0, 8))
        self.send_button.pack(side=tk.RIGHT)

        # El chat ocupa exclusivamente el espacio restante.
        chat_frame.pack(side=tk.TOP, padx=14, pady=6, fill=tk.BOTH, expand=True)
        self.input_box.focus_set()

    def _start_drag(self, event):
        self._drag_offset = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _do_drag(self, event):
        x = event.x_root - self._drag_offset[0]
        y = event.y_root - self._drag_offset[1]
        self.root.geometry(f"+{x}+{y}")

    # ------------------------------------------------------------------

    def close(self):
        self.running = False
        try:
            self.translation_queue.put_nowait(None)
        except queue.Full:
            pass
        if GLOBAL_HOTKEYS_OK:
            try:
                global_hotkeys.unhook_all()
            except Exception:
                pass
        self.root.destroy()


if __name__ == "__main__":
    # Identidad estable para el icono de la aplicación en la barra de tareas de Windows.
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "NWNEE.Traductor.5.4"
            )
        except Exception:
            pass
    root = tk.Tk()
    app = TranslatorApp(root)
    root.mainloop()
