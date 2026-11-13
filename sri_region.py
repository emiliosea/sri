"""Paquetes de región para funcionar sin internet.

Un paquete vive en <datos>/region/<id>/ (se arma con region/construir_region.py) y tiene:
  region.json      nombre, recuadro [sur, oeste, norte, este] y zooms
  mapa.mbtiles     mosaicos del mapa en blanco y negro (PNG 256 px)
  relieve.mbtiles  mosaicos de elevación terrarium (AWS Terrain Tiles)
  agua.json        cuerpos de agua de OpenStreetMap (mismo formato que /api/terreno/agua)
"""

import io
import json
import os
import socket
import sqlite3
import threading
import time

import sri_config as cfg


class Region:
    def __init__(self, carpeta):
        with open(os.path.join(carpeta, "region.json"), encoding="utf-8") as f:
            m = json.load(f)
        self.id, self.nombre, self.caja = m["id"], m["nombre"], m["caja"]
        self.zoom_mapa, self.zoom_relieve = m.get("zoom_mapa", 16), m.get("zoom_relieve", 14)
        self.carpeta = carpeta
        self._db, self._lock = {}, threading.Lock()
        self._agua = None
        for nombre in ("mapa", "relieve"):
            ruta = os.path.join(carpeta, nombre + ".mbtiles")
            if os.path.isfile(ruta):
                self._db[nombre] = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True, check_same_thread=False)

    def info(self):
        return {"id": self.id, "nombre": self.nombre, "caja": self.caja, "mapa": "mapa" in self._db,
                "relieve": "relieve" in self._db, "agua": os.path.isfile(os.path.join(self.carpeta, "agua.json"))}

    def _tile(self, capa, z, x, y):
        db = self._db.get(capa)
        if db is None:
            return None
        with self._lock:
            r = db.execute("SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                           (z, x, (2 ** z - 1) - y)).fetchone()
        return r[0] if r else None

    def tile_mapa(self, z, x, y):
        """PNG del mosaico; más allá del zoom del paquete se amplía el mosaico padre."""
        if z <= self.zoom_mapa:
            return self._tile("mapa", z, x, y)
        d = z - self.zoom_mapa
        padre = self._tile("mapa", self.zoom_mapa, x >> d, y >> d)
        if padre is None:
            return None
        from PIL import Image
        n = 2 ** d
        lado = 256 // n
        ox, oy = (x % n) * lado, (y % n) * lado
        img = Image.open(io.BytesIO(padre)).crop((ox, oy, ox + lado, oy + lado)).resize((256, 256), Image.BILINEAR)
        b = io.BytesIO()
        img.save(b, "PNG")
        return b.getvalue()

    def tile_relieve(self, z, x, y):
        return self._tile("relieve", z, x, y)

    def agua(self):
        if self._agua is None:
            try:
                with open(os.path.join(self.carpeta, "agua.json"), encoding="utf-8") as f:
                    self._agua = json.load(f).get("agua", [])
            except (OSError, ValueError):
                self._agua = []
        return self._agua

    def cubre(self, s, w, n, e):
        S, W, N, E = self.caja
        return s >= S and w >= W and n <= N and e <= E

    def toca(self, s, w, n, e):
        S, W, N, E = self.caja
        return not (n < S or s > N or e < W or w > E)

    def agua_en(self, s, w, n, e):
        """Cuerpos de agua del paquete que tocan el recuadro."""
        out = []
        for f in self.agua():
            c = f["coords"]
            if any(s <= p[0] <= n and w <= p[1] <= e for p in c):
                out.append(f)
        return out


_regiones = None


def regiones():
    global _regiones
    if _regiones is None:
        _regiones = []
        base = cfg.ruta_datos("region")
        if os.path.isdir(base):
            for d in sorted(os.listdir(base)):
                if os.path.isfile(os.path.join(base, d, "region.json")):
                    try:
                        _regiones.append(Region(os.path.join(base, d)))
                    except (OSError, ValueError, KeyError) as e:
                        print(f"[region] No se pudo abrir {d}: {e}", flush=True)
        if _regiones:
            print("[region] Paquetes: " + ", ".join(r.nombre for r in _regiones), flush=True)
    return _regiones


def region_de_tile(z, x, y):
    """Primera región cuyo recuadro toca el mosaico."""
    import math
    n = 2 ** z
    w, e = x / n * 360 - 180, (x + 1) / n * 360 - 180
    lat = lambda t: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * t / n))))
    nn, s = lat(y), lat(y + 1)
    return next((r for r in regiones() if r.toca(s, w, nn, e)), None)


# --------------------------------------------------------------------------- ¿hay internet?
_red = {"t": 0.0, "ok": True}


def hay_internet():
    """Prueba barata (conexión TCP a un DNS público), recordada 30 s."""
    if os.environ.get("SRI_SIN_INTERNET") == "1":      # para probar el modo sin conexión
        return False
    if time.time() - _red["t"] < 30:
        return _red["ok"]
    ok = False
    for host in ("1.1.1.1", "8.8.8.8"):
        try:
            with socket.create_connection((host, 443), timeout=1.5):
                ok = True
                break
        except OSError:
            pass
    _red.update(t=time.time(), ok=ok)
    return ok


def marcar_sin_internet():
    """Lo llama el servidor cuando una consulta externa falla: evita esperar timeouts repetidos."""
    _red.update(t=time.time(), ok=False)
