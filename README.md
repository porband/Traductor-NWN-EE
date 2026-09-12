# Traductor NWN:EE

Traductor de chat en tiempo real para el roleplay de **Neverwinter Nights: Enhanced Edition**. Lee el log del cliente mientras jugás y muestra cada mensaje traducido al instante, sin que tengas que copiar y pegar nada.

## Qué hace

- Detecta automáticamente el log de chat de NWN:EE y traduce cada línea a medida que aparece.
- Separa quién habla del mensaje, e ignora lo que no hace falta traducir (OOC, links, líneas de sistema del log).
- **Modo invisible**: una ventana transparente y superpuesta al juego, que muestra solo el texto traducido, sin fondo ni bordes — para leer sin salir de la partida. Se activa con **F9**.
- Envío de texto directo al juego desde la caja de escritura de la app.

## Instalación

No hace falta instalar Python ni nada. Bajá el `.exe` de la sección [Releases](../../releases), abrilo y listo.

> Si Windows muestra la advertencia "Windows protegió su PC", hacé clic en **Más información → Ejecutar de todas formas**. Pasa porque el ejecutable no tiene firma digital, no porque haya algo mal.

## Configuración

**No se necesita configurar nada para empezar a traducir.** Al abrir la app:

1. Busca sola el log de NWN:EE en tu carpeta de Documentos.
2. Usa **Google Translate** como motor por defecto — funciona sin cuenta ni API key.

### DeepL (opcional)

Si preferís usar DeepL en vez de Google (suele dar traducciones más naturales):

1. Conseguí una API key gratuita en [deepl.com](https://www.deepl.com/pro-api).
2. Pegala en el campo **"DeepL API Key"** dentro de la app y hacé clic en **"Activar DeepL"**.
3. La key queda guardada de forma segura en el almacén de credenciales de Windows — no hay que volver a escribirla la próxima vez que abras el programa.

Podés volver a Google en cualquier momento con el botón **"Usar Google"**.

## Controles

| Acción | Cómo se hace |
|---|---|
| Activar/desactivar modo invisible | Botón en la app, o tecla **F9** en cualquier momento (incluso con el juego en foco) |
| Enviar un mensaje al juego | Escribir en la caja de abajo y Enter, o botón **Enviar** |
| Seleccionar el log manualmente | Botón **"Seleccionar LOG"**, por si la detección automática no lo encuentra |
| Copiar la última traducción | Botón **"Copiar último"** |
| Copiar el nombre de un personaje | Doble clic sobre su nombre en el chat |

## Requisitos

- Windows (el modo invisible usa una función específica de Windows y no está disponible en otros sistemas).
- Conexión a internet (los motores de traducción son servicios en línea).

## Para desarrolladores

Si querés correr el código fuente en vez del `.exe`:

```bash
pip install -r requirements.txt
python "Traductor NWNEE v5.4.py"
```

Para generar el ejecutable:

```bash
pyinstaller "Traductor NWNEE v5.4.spec"
```
