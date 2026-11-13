"""Construye el "paquete de región" para usar SRI sin internet.

    .venv/bin/python region/construir_region.py huasteca            # todo
    .venv/bin/python region/construir_region.py huasteca --paso vector

Pasos (cada uno se puede repetir; lo ya descargado se reusa):
  vector   datos del mapa (Protomaps, de OpenStreetMap) solo del recuadro, en vector.mbtiles
  mapa     dibuja los mosaicos del mapa en blanco y negro (MapLibre en Chromium sin ventana) -> mapa.mbtiles
  relieve  mosaicos de elevación (AWS Terrain Tiles, terrarium) -> relieve.mbtiles
  agua     cuerpos de agua (OpenStreetMap vía Overpass) -> agua.json
Resultado en region/paquetes/<nombre>/ (copiar esa carpeta a <datos>/region/<nombre>/ de la estación).
"""

import argparse
import json
import math
import os
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

AQUI = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "SRI-region/1.0 (github.com/emiliosea/sri)"}

REGIONES = {
    # Parque La Huasteca (Santa Catarina, N.L.) y la zona metropolitana cercana
    "huasteca": {"nombre": "La Huasteca, Santa Catarina NL", "caja": [25.50, -100.60, 25.80, -100.15],
                 "zoom_vector": 15, "zoom_mapa": 16, "zoom_relieve": 14},
}
PROTOMAPS = "https://build.protomaps.com/{fecha}.pmtiles"
TERRARIUM = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"


# --------------------------------------------------------------------------- utilidades
def tiles_en_caja(caja, z):
    s, w, n, e = caja
    N = 2 ** z
    x = lambda lon: int((lon + 180) / 360 * N)
    y = lambda lat: int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * N)
    for tx in range(x(w), x(e) + 1):
        for ty in range(y(n), y(s) + 1):
            yield z, tx, ty


def abrir_mbtiles(ruta, meta):
    db = sqlite3.connect(ruta, check_same_thread=False)
    db.execute("CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS tiles (zoom_level INT, tile_column INT, tile_row INT, tile_data BLOB, "
               "PRIMARY KEY (zoom_level, tile_column, tile_row))")
    for k, v in meta.items():
        db.execute("INSERT OR REPLACE INTO metadata VALUES (?, ?)", (k, str(v)))
    db.commit()
    return db


def guardar_tile(db, z, x, y, datos):
    # MBTiles usa filas TMS (y invertida)
    db.execute("INSERT OR REPLACE INTO tiles VALUES (?, ?, ?, ?)", (z, x, (2 ** z - 1) - y, datos))


def tiene_tile(db, z, x, y):
    return db.execute("SELECT 1 FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                      (z, x, (2 ** z - 1) - y)).fetchone() is not None


def descargar(url, headers=None, intentos=4):
    for i in range(intentos):
        try:
            req = urllib.request.Request(url, headers={**UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if i == intentos - 1:
                raise
        except OSError:
            if i == intentos - 1:
                raise
        time.sleep(2 * (i + 1))


# --------------------------------------------------------------------------- paso: vector
def build_reciente():
    """Fecha del build diario más reciente de Protomaps que exista."""
    for d in range(0, 20):
        f = time.strftime("%Y%m%d", time.gmtime(time.time() - d * 86400))
        try:
            req = urllib.request.Request(PROTOMAPS.format(fecha=f), method="HEAD", headers=UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                if r.status == 200:
                    return f
        except OSError:
            pass
    raise SystemExit("No se encontró un build reciente de Protomaps")


def paso_vector(reg, dest):
    from pmtiles.reader import Reader
    fecha = build_reciente()
    url = PROTOMAPS.format(fecha=fecha)
    cache = {}

    def get_bytes(offset, length):            # lecturas por rango HTTP; los directorios se reusan
        k = (offset, length)
        if k not in cache:
            cache[k] = descargar(url, {"Range": f"bytes={offset}-{offset + length - 1}"})
        return cache[k]

    rd = Reader(get_bytes)
    hdr = rd.header()
    meta = rd.metadata()
    db = abrir_mbtiles(os.path.join(dest, "vector.mbtiles"),
                       {"name": "Protomaps " + fecha, "format": "pbf", "compression": "gzip",
                        "json": json.dumps({"vector_layers": meta.get("vector_layers", [])}),
                        "attribution": "© OpenStreetMap contributors, Protomaps", "fuente": url})
    todos = [t for z in range(0, reg["zoom_vector"] + 1) for t in tiles_en_caja(reg["caja"], z)]
    faltan = [t for t in todos if not tiene_tile(db, *t)]
    print(f"[vector] build {fecha}; {len(todos)} mosaicos ({len(faltan)} por descargar)", flush=True)
    # los directorios se leen primero en un solo hilo; luego los mosaicos en paralelo
    for z in range(0, reg["zoom_vector"] + 1):
        rd.get(*next(tiles_en_caja(reg["caja"], z)))
    hechos, total_b = 0, 0
    with ThreadPoolExecutor(8) as ex:
        for (z, x, y), datos in zip(faltan, ex.map(lambda t: rd.get(*t), faltan)):
            if datos:
                guardar_tile(db, z, x, y, datos)
                total_b += len(datos)
            hechos += 1
            if hechos % 200 == 0:
                db.commit()
                print(f"[vector] {hechos}/{len(faltan)} ({total_b / 1e6:.1f} MB)", flush=True)
    db.commit()
    db.close()
    print(f"[vector] listo: {total_b / 1e6:.1f} MB nuevos", flush=True)
    return {"fecha_protomaps": fecha, "compresion": str(hdr.get("tile_compression"))}


# --------------------------------------------------------------------------- paso: mapa
def paso_mapa(reg, dest, zmin=8):
    """Dibuja los mosaicos del mapa con MapLibre en Chromium sin ventana, a partir de vector.mbtiles."""
    import base64
    import io
    import subprocess
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from PIL import Image

    herr = os.path.join(AQUI, "herramientas")
    vec = sqlite3.connect(os.path.join(dest, "vector.mbtiles"), check_same_thread=False)
    out = abrir_mbtiles(os.path.join(dest, "mapa.mbtiles"),
                        {"name": "SRI " + reg["nombre"], "format": "png", "minzoom": zmin, "maxzoom": reg["zoom_mapa"],
                         "bounds": ",".join(str(v) for v in (reg["caja"][1], reg["caja"][0], reg["caja"][3], reg["caja"][2])),
                         "attribution": "© OpenStreetMap contributors, Protomaps"})
    out_lock, vec_lock = threading.Lock(), threading.Lock()
    dentro = {(z, x, y) for z in range(zmin, reg["zoom_mapa"] + 1) for (z, x, y) in tiles_en_caja(reg["caja"], z)}
    trabajos = []
    for z in range(zmin, reg["zoom_mapa"] + 1):
        ts = [t for t in dentro if t[0] == z]
        xs, ys = [t[1] for t in ts], [t[2] for t in ts]
        for x0 in range(min(xs), max(xs) + 1, 4):
            for y0 in range(min(ys), max(ys) + 1, 4):
                if any(not tiene_tile(out, z, x0 + i, y0 + j) for i in range(4) for j in range(4) if (z, x0 + i, y0 + j) in dentro):
                    trabajos.append({"z": z, "x0": x0, "y0": y0})
    print(f"[mapa] {len(dentro)} mosaicos en {len(trabajos)} bloques por dibujar", flush=True)
    estado = {"hechos": 0, "fin": threading.Event(), "error": None}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _envia(self, datos, tipo, extra=None):
            self.send_response(200 if datos is not None else 404)
            self.send_header("Content-Type", tipo)
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(datos or b"")))
            self.end_headers()
            self.wfile.write(datos or b"")

        def do_GET(self):
            p = urllib.parse.unquote(self.path.split("?")[0])
            if p == "/":
                return self._envia(open(os.path.join(herr, "dibujar.html"), "rb").read(), "text/html")
            if p == "/estilo.json":
                return self._envia(open(os.path.join(herr, "estilo.json"), "rb").read(), "application/json")
            if p == "/trabajos":
                return self._envia(json.dumps(trabajos).encode(), "application/json")
            if p.startswith("/maplibre/") or p.startswith("/fonts/"):
                f = os.path.join(herr, p.lstrip("/"))
                if not os.path.isfile(f):                       # rango de letras que no se descargó
                    return self._envia(None, "application/octet-stream")
                return self._envia(open(f, "rb").read(), "application/javascript" if f.endswith(".js")
                                   else "text/css" if f.endswith(".css") else "application/x-protobuf")
            if p.startswith("/v/"):
                z, x, y = (int(v) for v in p[3:-4].split("/"))
                with vec_lock:
                    r = vec.execute("SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                                    (z, x, (2 ** z - 1) - y)).fetchone()
                if not r:
                    return self._envia(None, "application/x-protobuf")
                return self._envia(r[0], "application/x-protobuf", {"Content-Encoding": "gzip"})
            self._envia(None, "text/plain")

        def do_POST(self):
            d = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/log":
                print("[mapa:navegador]", d.get("m"), flush=True)
                return self._envia(b"ok", "text/plain")
            if self.path == "/fin":
                estado["error"] = d.get("error")
                estado["fin"].set()
                return self._envia(b"ok", "text/plain")
            img = Image.open(io.BytesIO(base64.b64decode(d["png"].split(",", 1)[1]))).convert("L")
            z, pad = d["z"], d["pad"]
            with out_lock:
                for i in range(4):
                    for j in range(4):
                        t = (z, d["x0"] + i, d["y0"] + j)
                        if t not in dentro:
                            continue
                        x, y = (pad + i) * 256, (pad + j) * 256
                        b = io.BytesIO()
                        img.crop((x, y, x + 256, y + 256)).save(b, "PNG", optimize=True)
                        guardar_tile(out, *t, b.getvalue())
                out.commit()
                estado["hechos"] += 1
                if estado["hechos"] % 25 == 0:
                    print(f"[mapa] {estado['hechos']}/{len(trabajos)} bloques", flush=True)
            self._envia(b"ok", "text/plain")

    if not trabajos:
        return {"mosaicos": len(dentro)}
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    perfil = os.path.join(dest, ".chromium")
    nav = subprocess.Popen(["chromium", "--headless=new", "--no-sandbox", "--hide-scrollbars", "--window-size=1600,1600",
                            "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--force-device-scale-factor=1",
                            f"--user-data-dir={perfil}", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        while not estado["fin"].wait(30):
            if nav.poll() is not None:
                raise SystemExit("Chromium se cerró antes de terminar")
    finally:
        nav.terminate()
        srv.shutdown()
    if estado["error"]:
        raise SystemExit("Error al dibujar: " + estado["error"])
    n, tam = out.execute("SELECT count(*), sum(length(tile_data)) FROM tiles").fetchone()
    print(f"[mapa] listo: {n} mosaicos, {tam / 1e6:.1f} MB", flush=True)
    return {"mosaicos": n, "mb": round(tam / 1e6, 1)}


# --------------------------------------------------------------------------- paso: relieve
def paso_relieve(reg, dest, zmin=6):
    """Mosaicos de elevación (terrarium) del recuadro, con un margen para que la interpolación no se corte."""
    s, w, n, e = reg["caja"]
    caja = [s - 0.03, w - 0.03, n + 0.03, e + 0.03]
    db = abrir_mbtiles(os.path.join(dest, "relieve.mbtiles"),
                       {"name": "Relieve " + reg["nombre"], "format": "png", "encoding": "terrarium",
                        "attribution": "AWS Terrain Tiles (Mapzen, USGS, SRTM y otros)"})
    todos = [t for z in range(zmin, reg["zoom_relieve"] + 1) for t in tiles_en_caja(caja, z)]
    faltan = [t for t in todos if not tiene_tile(db, *t)]
    print(f"[relieve] {len(todos)} mosaicos ({len(faltan)} por descargar)", flush=True)
    total, hechos = 0, 0
    with ThreadPoolExecutor(8) as ex:
        for (z, x, y), datos in zip(faltan, ex.map(lambda t: descargar(TERRARIUM.format(z=t[0], x=t[1], y=t[2])), faltan)):
            if datos:
                guardar_tile(db, z, x, y, datos)
                total += len(datos)
            hechos += 1
            if hechos % 100 == 0:
                db.commit()
                print(f"[relieve] {hechos}/{len(faltan)} ({total / 1e6:.1f} MB)", flush=True)
    db.commit()
    n_, tam = db.execute("SELECT count(*), sum(length(tile_data)) FROM tiles").fetchone()
    db.close()
    print(f"[relieve] listo: {n_} mosaicos, {tam / 1e6:.1f} MB", flush=True)
    return {"mosaicos": n_, "mb": round(tam / 1e6, 1)}


# --------------------------------------------------------------------------- paso: agua
def paso_agua(reg, dest):
    """Cuerpos de agua de OpenStreetMap (la misma consulta que usa el servidor)."""
    sys.path.insert(0, os.path.dirname(AQUI))
    from server import consultar_agua
    s, w, n, e = reg["caja"]
    # en 3 x 3 partes para que Overpass no se tarde demasiado; los que cruzan partes se quitan repetidos
    k = 3
    agua, vistos = [], set()
    for i in range(k):
        for j in range(k):
            ss, nn = s + (n - s) * i / k, s + (n - s) * (i + 1) / k
            ww, ee = w + (e - w) * j / k, w + (e - w) * (j + 1) / k
            for intento in range(4):
                try:
                    parte = consultar_agua(ss, ww, nn, ee)
                    break
                except OSError as ex:
                    print(f"[agua] parte {i * k + j + 1}/{k * k}: {ex}, reintentando...", flush=True)
                    time.sleep(10 * (intento + 1))
            else:
                raise SystemExit("Overpass no respondió; vuelve a correr el paso agua más tarde")
            for f in parte:
                clave = (f["nombre"], f["clase"], f["tipo"], tuple(f["coords"][0]), tuple(f["coords"][-1]), len(f["coords"]))
                if clave not in vistos:
                    vistos.add(clave)
                    agua.append(f)
            print(f"[agua] parte {i * k + j + 1}/{k * k}: {len(parte)} (total {len(agua)})", flush=True)
    with open(os.path.join(dest, "agua.json"), "w", encoding="utf-8") as f:
        json.dump({"ok": True, "agua": agua, "fuente": "© OpenStreetMap (Overpass)",
                   "fecha": time.strftime("%Y-%m-%d")}, f, ensure_ascii=False)
    nombres = len({x["nombre"] for x in agua if x["nombre"]})
    print(f"[agua] listo: {len(agua)} cuerpos de agua ({nombres} con nombre)", flush=True)
    return {"cuerpos": len(agua)}


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("region", choices=REGIONES)
    ap.add_argument("--paso", choices=["vector", "mapa", "relieve", "agua"], action="append")
    a = ap.parse_args()
    reg = REGIONES[a.region]
    dest = os.path.join(AQUI, "paquetes", a.region)
    os.makedirs(dest, exist_ok=True)
    pasos = a.paso or ["vector", "mapa", "relieve", "agua"]
    manifest_ruta = os.path.join(dest, "region.json")
    try:
        with open(manifest_ruta) as f:
            manifest = json.load(f)
    except (OSError, ValueError):
        manifest = {}
    manifest.update({"id": a.region, "nombre": reg["nombre"], "caja": reg["caja"],
                     "zoom_mapa": reg["zoom_mapa"], "zoom_relieve": reg["zoom_relieve"]})
    for p in pasos:
        r = globals()["paso_" + p](reg, dest)
        manifest.setdefault("pasos", {})[p] = {"fecha": time.strftime("%Y-%m-%d %H:%M"), **(r or {})}
        with open(manifest_ruta, "w") as f:
            json.dump(manifest, f, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    sys.exit(main())
