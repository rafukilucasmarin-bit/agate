# Agate Loader

Un cargador de mods para Geometry Dash que **funciona igual que Geode** y añade **un único cambio**:

> Si detecta un mod hecho para una versión de Geometry Dash anterior a la última, **lo actualiza a la última versión**.

Se instala en Windows con un `.exe` (asistente tipo *setup*) y en macOS con un `.pkg` que te pide la app de
Geometry Dash y deja **todo dentro del juego**.

## Estado real del proyecto (léelo antes de usarlo)

| Pieza | Estado |
|---|---|
| `autoport/` (el cambio: auto-actualizar mods) | Escrito y **probado**: 27 tests contra un Geode Index simulado en local |
| `installer/macos/tool/uninstall.sh` | Probado en un árbol de app falso |
| `src/main.cpp` (mod que lanza el actualizador) | **No compilado** (no había Geode SDK ni GD en el entorno) |
| `installer/windows/agate.nsi` | **No compilado** (no había `makensis`) |
| `installer/macos/` (`postinstall`, `build-pkg.sh`) | Solo comprobada la sintaxis bash; necesita macOS para probarse |
| `.github/workflows/release.yml` | YAML válido, **no ejecutado** |
| Binarios `.exe` / `.pkg` | **No existen todavía**: los genera el workflow (ver abajo) |

Dos cosas que no pude verificar contra la fuente y que el CI comprueba por ti:

1. **Campos del JSON del Geode Index** (`payload`, `download_link`, `hash`, `gd`…) y el comportamiento exacto de
   `/mods/{id}/versions/latest?gd=…`. Están aislados en `index.py` (`_parse_*`). Además, el actualizador **no se fía
   del servidor**: verifica el SHA-256 y vuelve a leer el `mod.json` del paquete descargado.
2. **Contenido del zip oficial de macOS.** El `postinstall` asume (según la documentación del instalador de Geode)
   `Geode.dylib`, `GeodeBootstrapper.dylib` y un `libfmod.dylib` sustituto. Si el zip oficial no coincide,
   `tools/fetch_geode.py` **falla a propósito** en vez de empaquetar algo roto. En ese caso compara con
   `installer/mac/Scripts/postinstall` del repositorio oficial de Geode y ajusta `REQUIRED` y el `postinstall`.

## Cómo funciona

**El loader no se reescribe**: Geode es años de trabajo (hooks, bindings por versión de GD…). Agate instala los
binarios **oficiales** de Geode, sin modificar, y usa su mismo índice de mods. Lo único nuevo:

```
Abres GD → Geode carga Agate AutoPort (mod con "gd": "*", sin hooks → nunca queda obsoleto)
        → lanza en segundo plano  agate-autoport run --installed-gd <tu versión> ...
        → agate-autoport:
            1. pide al Geode Index la última versión de GD y del loader
            2. lee el mod.json de cada geode/mods/*.geode; "outdated" = su `gd` < la última
            3. para cada mod desactualizado, prueba en orden:
               a) ÍNDICE: ¿hay versión del mod para la última GD? → descarga + SHA-256 + revisión de mod.json
               b) RETARGET: solo si el mod NO tiene binarios (.dll/.dylib): cambia `gd` en mod.json
               c) COMPILAR (opt-in): clona el repo del Index y compila con la CLI de Geode
            4. si nada funciona, el mod no se toca (Geode lo mostrará como incompatible)
```

### Por qué no se "cambia el número de versión" sin más

Un mod con código nativo está compilado contra las direcciones de memoria de **una** versión de GD. Editar su
`mod.json` para decir que es de la última versión haría que cargara código con offsets equivocados y **cerraría el
juego**. Por eso el retarget solo se aplica a mods sin binarios; para los demás hace falta una versión real
(del Index) o recompilar contra el SDK actual.

### Salvaguardas

- **Solo portar si tu GD es la última.** El mod pasa tu versión real (`--installed-gd`). Si tu juego es anterior, portar
  rompería tus mods en tu versión → no se hace (salvo `--force`). Si tu juego es más nuevo que lo que el Index conoce,
  no hay nada a lo que portar todavía.
- **HTTPS + SHA-256 obligatorios**; sin hash, no se instala. Se rechazan zips con rutas `..` o absolutas.
- **No hay downgrades** ni se acepta un paquete de otro `id`.
- **Copia de seguridad** de cada mod sustituido en `geode/agate/backups/<id>/`; reversión con
  `agate-autoport rollback <id>`.
- Si el archivo está bloqueado (juego abierto en Windows) se deja en `geode/agate/pending/` y se aplica en el siguiente arranque.
- **Compilar desde código está desactivado por defecto** (ejecuta código de terceros): actívalo en los ajustes del mod
  o con `--allow-build`. Solo se clonan repos de `github.com`, `gitlab.com` y `codeberg.org`.
- Registro de lo hecho: `geode/agate/ported.json` y `last-run.json`.
- Durante la instalación **no** se portan mods (el instalador no sabe qué versión de GD tienes); ocurre al abrir el juego.

Dependencias: si un mod actualizado necesita otro mod que no tienes, se intenta instalar desde el Index.

## Obtener los instaladores

1. Sube este repositorio a GitHub.
2. *Actions → Build installers → Run workflow* (o crea una etiqueta `v1.0.0` para publicar una release).
3. Descarga `Agate-Setup-<ver>.exe` y `Agate-Loader-<ver>.pkg` de los artefactos.

Para firmar el `.pkg`, define el secreto `MACOS_INSTALLER_IDENTITY` (certificado *Developer ID Installer*) y
notariza. Sin firmar, macOS pedirá *clic derecho → Abrir*.

## Instalar

**Windows:** ejecuta `Agate-Setup-<ver>.exe`. Detecta la carpeta de Steam; si no, elígela (la que contiene
`GeometryDash.exe`). Copia el loader, `agate\agate-autoport.exe` y `geode\mods\agate.autoport.geode` dentro del juego.
Desinstalar: *Aplicaciones* de Windows → Agate Loader (no borra tus mods).

**macOS:** abre `Agate-Loader-<ver>.pkg`; al final se abre un selector: elige **Geometry Dash.app**
(Steam: `~/Library/Application Support/Steam/steamapps/common/Geometry Dash`). Se instala en
`Contents/Frameworks`, `Contents/geode` y `Contents/Resources/agate`. Se guarda el `libfmod.dylib` original como
`restore_fmod.dylib`. Desinstalar: `Contents/Resources/agate/uninstall.sh`. Log: `/var/log/agate-install.log`.

## Desarrollo

```bash
python -m unittest discover -s autoport/tests -v          # tests del actualizador (solo stdlib)
python -m agate_autoport --geode-dir <ruta/geode> --dry-run  # (desde autoport/) simulacro sobre tus mods
```

Uso manual: `agate-autoport [run|status|rollback <id>] [--dry-run] [--allow-build] [--force] [--json]`.

## Seguridad: descarga solo de fuentes oficiales

Al investigar aparecieron repositorios que se hacen pasar por Geode ("Geode-GD-Mod-Loader", "Geode-Geometry-Dash",
"geode-2.209"…) con versiones inventadas. Las fuentes oficiales son `github.com/geode-sdk` y `geode-sdk.org`.
`tools/fetch_geode.py` solo descarga de `github.com/geode-sdk/geode`.
