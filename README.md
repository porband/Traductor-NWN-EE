# Traductor NWN:EE

🇪🇸 [Español](#español) | 🇬🇧 [English](#english)

---

## Español

Traductor de chat en tiempo real para el roleplay de **Neverwinter Nights: Enhanced Edition**. Lee el log del cliente mientras jugás y muestra cada mensaje traducido al instante, sin que tengas que copiar y pegar nada.

### Qué hace

- Detecta automáticamente el log de chat de NWN:EE y traduce cada línea a medida que aparece.
- Separa quién habla del mensaje, e ignora lo que no hace falta traducir (OOC, links, líneas de sistema del log).
- **Modo invisible**: una ventana transparente y superpuesta al juego, que muestra solo el texto traducido, sin fondo ni bordes — para leer sin salir de la partida. Se activa con **F9**.
- Envío de texto directo al juego desde la caja de escritura de la app.
- **Interfaz bilingüe**: elegís el idioma de los botones y menús (español o inglés) desde un desplegable, independiente de lo que estés traduciendo.
- **Traductor de dos vías, tipo Google Translate**: dos selectores (de qué idioma → a qué idioma) con un botón **⇄** para invertir la dirección al instante, incluso a mitad de una conversación.

### Instalación

No hace falta instalar Python ni nada. Bajá el `.exe` de la sección [Releases](../../releases), abrilo y listo.

> Si Windows muestra la advertencia "Windows protegió su PC", hacé clic en **Más información → Ejecutar de todas formas**. Pasa porque el ejecutable no tiene firma digital, no porque haya algo mal.

### Configuración

**No se necesita configurar nada para empezar a traducir.** Al abrir la app por primera vez:

1. Te pregunta en qué idioma querés la interfaz (español o inglés). Queda guardado para la próxima vez, pero lo podés cambiar cuando quieras desde el desplegable de arriba.
2. Busca sola el log de NWN:EE en tu carpeta de Documentos.
3. Usa **Google Translate** como motor por defecto — funciona sin cuenta ni API key.
4. El traductor arranca traduciendo de inglés a español (o al revés, según el idioma que elegiste para la interfaz) — lo podés cambiar en cualquier momento con los selectores y el botón ⇄.

#### DeepL (opcional)

Si preferís usar DeepL en vez de Google (suele dar traducciones más naturales):

1. Conseguí una API key gratuita en [deepl.com](https://www.deepl.com/pro-api).
2. Pegala en el campo **"DeepL API Key"** dentro de la app y hacé clic en **"Activar DeepL"**.
3. La key queda guardada de forma segura en el almacén de credenciales de Windows — no hay que volver a escribirla la próxima vez que abras el programa.

Podés volver a Google en cualquier momento con el botón **"Usar Google"**.

### Controles

| Acción | Cómo se hace |
|---|---|
| Activar/desactivar modo invisible | Botón en la app, o tecla **F9** en cualquier momento (incluso con el juego en foco) |
| Cambiar el idioma de la interfaz | Desplegable arriba a la derecha |
| Cambiar de/hacia qué idioma traduce | Los dos selectores de la barra superior, o el botón **⇄** para invertir |
| Enviar un mensaje al juego | Escribir en la caja de abajo y Enter, o botón **Enviar** |
| Seleccionar el log manualmente | Botón **"Seleccionar LOG"**, por si la detección automática no lo encuentra |
| Copiar la última traducción | Botón **"Copiar último"** |
| Copiar el nombre de un personaje | Doble clic sobre su nombre en el chat |

### Requisitos

- Windows (el modo invisible usa una función específica de Windows y no está disponible en otros sistemas).
- Conexión a internet (los motores de traducción son servicios en línea).

### Para desarrolladores

```bash
pip install -r requirements.txt
python "Traductor NWNEE v5.4.py"
```

Para generar el ejecutable:

```bash
pyinstaller "Traductor NWNEE v5.4.spec"
```

---

## English

Real-time chat translator for **Neverwinter Nights: Enhanced Edition** roleplay. It reads the game client's log while you play and shows every message translated instantly, no copy-pasting needed.

### Features

- Automatically detects the NWN:EE chat log and translates each line as it appears.
- Separates who's speaking from the message, and ignores anything that doesn't need translating (OOC, links, system log lines).
- **Invisible mode**: a transparent window overlaid on the game, showing only the translated text with no background or borders — so you can read without leaving the game. Toggled with **F9**.
- Send text straight to the game from the app's input box.
- **Bilingual interface**: choose the language for buttons and menus (Spanish or English) from a dropdown, independent of what's being translated.
- **Two-way translator, Google Translate style**: two selectors (from which language → to which language) with a **⇄** button to flip the direction instantly, even mid-conversation.

### Installation

No need to install Python or anything else. Download the `.exe` from the [Releases](../../releases) section, open it, and you're set.

> If Windows shows the "Windows protected your PC" warning, click **More info → Run anyway**. That happens because the executable isn't digitally signed, not because something's wrong.

### Configuration

**Nothing needs to be configured to start translating.** The first time you open the app:

1. It asks which language you want for the interface (Spanish or English). It's saved for next time, but you can change it anytime from the dropdown at the top.
2. It finds the NWN:EE log in your Documents folder on its own.
3. It uses **Google Translate** as the default engine — no account or API key needed.
4. The translator starts translating from English to Spanish (or the other way around, depending on the interface language you picked) — you can change it anytime with the selectors and the ⇄ button.

#### DeepL (optional)

If you'd rather use DeepL instead of Google (it tends to give more natural translations):

1. Get a free API key at [deepl.com](https://www.deepl.com/pro-api).
2. Paste it into the **"DeepL API Key"** field in the app and click **"Activate DeepL"**.
3. The key is stored securely in Windows' credential manager — you won't need to type it again next time you open the program.

You can switch back to Google anytime with the **"Use Google"** button.

### Controls

| Action | How |
|---|---|
| Toggle invisible mode | Button in the app, or press **F9** anytime (even with the game focused) |
| Change interface language | Dropdown at the top right |
| Change which language it translates from/to | The two selectors in the top bar, or the **⇄** button to flip them |
| Send a message to the game | Type in the box below and press Enter, or the **Send** button |
| Manually select the log | **"Select LOG"** button, in case auto-detection doesn't find it |
| Copy the last translation | **"Copy last"** button |
| Copy a character's name | Double-click their name in the chat |

### Requirements

- Windows (invisible mode uses a Windows-specific feature and isn't available on other systems).
- Internet connection (the translation engines are online services).

### For developers

```bash
pip install -r requirements.txt
python "Traductor NWNEE v5.4.py"
```

To build the executable:

```bash
pyinstaller "Traductor NWNEE v5.4.spec"
```