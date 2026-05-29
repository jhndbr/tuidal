# Tidal TUI — Terminal Music Player

Un reproductor de música de terminal para **Tidal**, con interfaz interactiva, navegación de playlists y controles de reproducción.

```
┌──────────────────────────────────────────────┐
│ Tidal TUI        ♫ Music Player              │
├────────────┬─────────────────────────────────┤
│ Playlists  │ Track List (DataTable)          │
│ (sidebar)  │                                 │
├────────────┴─────────────────────────────────┤
│ Now Playing (progress + controls)             │
├──────────────────────────────────────────────┤
│ space: Play/Pause  n: Next  p: Prev  +/-: Vol
└──────────────────────────────────────────────┘
```

## Inicio Rápido

### Ejecutar la aplicación

```bash
uv run tidal-tui
```

O alternativamente:

```bash
uv run python -m tidal_tui
```

### Opciones

```bash
# Especificar calidad de audio
uv run tidal-tui --quality high        # AAC 320 kbps (default)
uv run tidal-tui --quality lossless    # FLAC
uv run tidal-tui --quality max         # MQA (si disponible)

# Cerrar sesión y re-autenticar
uv run tidal-tui --logout
```

## Requisitos del Sistema

### 1. **Python 3.10+**

```bash
python --version
```

### 2. **libmpv** (para reproducción de audio)

**Linux (Arch/Manjaro):**
```bash
sudo pacman -S mpv
```

**Linux (Debian/Ubuntu):**
```bash
sudo apt-get install libmpv1 libmpv-dev
```

**macOS:**
```bash
brew install mpv
```

### 3. **uv** (gestor de Python, recomendado)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Dependencias

Las dependencias Python se definen en `pyproject.toml` y se instalan automáticamente con `uv`.

**Principales:**
- **textual** — Framework para UI en terminal
- **tidalapi** — API client para Tidal
- **python-mpv** — Bindings para libmpv (reproducción de audio)

## Instalación en el Sistema

### Opción 1: Instalación Local con uv (Recomendado)

```bash
# 1. Clonar el repositorio
git clone https://github.com/jhndbr/tuidal.git
cd tuidal

# 2. Instalar dependencias
uv sync

# 3. Ejecutar
uv run tidal-tui
```

### Opción 2: Instalar como Comando Global

```bash
# 1. Navegar al directorio del proyecto
cd /ruta/a/tuidal

# 2. Compilar/instalar en el sistema
uv pip install -e .

# 3. Ahora puedes ejecutar desde cualquier lugar
tidal-tui
```

### Opción 3: Crear un Alias

```bash
# Agregar al ~/.bashrc o ~/.zshrc
alias tidal='cd /ruta/a/tuidal && uv run tidal-tui'

# Recargar shell
source ~/.bashrc
```

## Controles de Teclado

| Tecla | Acción |
|-------|--------|
| `Space` | Play/Pause |
| `N` | Siguiente canción |
| `P` | Canción anterior |
| `+` | Aumentar volumen |
| `-` | Disminuir volumen |
| `Q` | Salir |

## Autenticación

La primera vez que ejecutes la aplicación, se te pedirá que inicies sesión en Tidal.

- Los tokens se guardan en `~/.config/tidal-tui/session.json`
- Para cerrar sesión: `uv run tidal-tui --logout`

## Estructura del Proyecto

```
tuidal/
├── app.py                 # Aplicación principal (TUI)
├── __main__.py            # Punto de entrada
├── config.py              # Configuración y persistencia
├── models.py              # Modelos de datos
├── services/
│   ├── tidal_service.py   # Cliente Tidal
│   └── player_backend.py  # Backend de reproducción
├── widgets/
│   ├── track_list.py      # Lista de canciones
│   ├── playlist_browser.py# Navegador de playlists
│   └── now_playing.py     # Panel de reproducción actual
└── styles/
    └── player.tcss        # Estilos de la UI
```

## Desarrollo

```bash
# Instalar en modo desarrollo
uv sync

# Ejecutar en desarrollo
uv run tidal-tui

# Ver logs
uv run tidal-tui 2>&1 | tee app.log
```

## Licencia

Este proyecto está bajo licencia [Especificar aquí].

## Reporte de Errores

Abre un issue en [GitHub](https://github.com/jhndbr/tuidal/issues).
