"""Rutas, configuración y guardado seguro para el servidor SRI.

Funciona igual al correr desde el código (`python server.py`) y como programa empaquetado (PyInstaller):

- Recursos (interfaz web): junto al código, o dentro del paquete (`sys._MEIPASS`).
- Datos (eventos, posiciones, calibración, cachés):
    1. variable de entorno SRI_DATOS
    2. `datos = "..."` en la configuración
    3. desde el código: ./data (como hasta ahora)
       empaquetado: /var/lib/sri si se puede escribir, si no ~/.local/share/sri
- Configuración (TOML, opcional): SRI_CONFIG, /etc/sri/config.toml o ~/.config/sri/config.toml.
"""

import json
import os
import sys

EMPAQUETADO = getattr(sys, "frozen", False)
BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(BASE, "static")
VERSION = "0.2.1"


def _leer_config():
    import tomllib
    rutas = [os.environ.get("SRI_CONFIG"), "/etc/sri/config.toml",
             os.path.expanduser("~/.config/sri/config.toml")]
    for r in rutas:
        if r and os.path.isfile(r):
            try:
                with open(r, "rb") as f:
                    return tomllib.load(f), r
            except (OSError, tomllib.TOMLDecodeError) as e:
                print(f"[config] No se pudo leer {r}: {e}", flush=True)
    return {}, None


CONFIG, CONFIG_RUTA = _leer_config()


def _escribible(d):
    try:
        os.makedirs(d, exist_ok=True)
        prueba = os.path.join(d, ".escritura")
        with open(prueba, "w") as f:
            f.write("ok")
        os.remove(prueba)
        return True
    except OSError:
        return False


def _dir_datos():
    d = os.environ.get("SRI_DATOS") or CONFIG.get("datos")
    if d:
        return os.path.expanduser(d)
    if not EMPAQUETADO:
        return os.path.join(BASE, "data")
    return "/var/lib/sri" if _escribible("/var/lib/sri") else os.path.expanduser("~/.local/share/sri")


DATOS = _dir_datos()


def ruta_datos(*partes):
    return os.path.join(DATOS, *partes)


def conf(seccion, clave, defecto=None):
    """Valor de la configuración, ej. conf("servidor", "puerto", 5000)."""
    return (CONFIG.get(seccion) or {}).get(clave, defecto)


def _fsync_dir(d):
    try:
        fd = os.open(d, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def guardar_json(ruta, obj, **kw):
    """Escritura segura ante cortes de luz: archivo temporal, fsync y renombrar (atómico)."""
    d = os.path.dirname(ruta)
    os.makedirs(d, exist_ok=True)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, **kw)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, ruta)
    _fsync_dir(d)


def agregar_linea(ruta, texto):
    """Agrega una línea a un registro (.jsonl) y la fuerza a disco."""
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "a", encoding="utf-8") as f:
        f.write(texto.rstrip("\n") + "\n")
        f.flush()
        os.fsync(f.fileno())
