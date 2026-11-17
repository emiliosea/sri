"""Alertas de caída/golpe que llegan por LoRa desde nodos de campo (canal de grupo "SRI").

El firmware v1.18.0-sri2 (o más nuevo) de cada nodo manda, cuando su detector engancha un evento, 3 veces (cada 20 s):

    SRI1 CAIDA dif 7.97g pico 8.79g @25.662300,-100.422100 t1794705000 #3 (1/3)

Desde sri3 también manda su posición cada 4 minutos ("SRI1 POS ...", ver leer_pos).

La base (el nodo conectado a la PC) lo recibe como mensaje de canal "NOMBRE: texto". Aquí se lee ese texto,
se juntan las repeticiones en una sola alerta y se guarda cuál sigue activa (hasta que alguien la borra).
"""

import hashlib
import re
import threading
import time

CANAL = "SRI"
PATRON = re.compile(
    r"^(?P<nombre>.+?): SRI1 (?P<tipo>CAIDA|GOLPE|[A-Z?]+) dif (?P<dif>-?\d+(?:\.\d+)?)g pico (?P<pico>-?\d+(?:\.\d+)?)g"
    r"(?: @(?P<lat>-?\d+(?:\.\d+)?),(?P<lon>-?\d+(?:\.\d+)?))? t(?P<epoch>\d+) #(?P<cuenta>\d+) \((?P<n>\d)/(?P<de>\d)\)"
    r"(?: i(?P<id>[0-9a-fA-F]{8}))?")


# Posición periódica (firmware sri3, cada 4 min):  "NOMBRE: SRI1 POS @25.662300,-100.422100 t1794705000 b3920"
# Desde sri4 agrega " e<seg>" (segundos desde la última posición GPS válida; -1 = nunca) y " a<mín>/<máx>"
# (aceleración en g desde la posición anterior). Sin GPS la posición llega como 0,0 (solo sirve el resumen).
# Desde sri5: " c<°C>" (temperatura del sensor del nodo) e " i<8 hex>" (inicio de la llave pública: identidad fija
# del nodo de campo, para no confundir dos nodos con el mismo nombre). Formato completo: docs/firmware.md.
PATRON_POS = re.compile(
    r"^(?P<nombre>.+?): SRI1 POS @(?P<lat>-?\d+(?:\.\d+)?),(?P<lon>-?\d+(?:\.\d+)?) t(?P<epoch>\d+)"
    r"(?: b(?P<mv>\d+))?(?: e(?P<edad>-?\d+))?(?: a(?P<amin>\d+(?:\.\d+)?)/(?P<amax>\d+(?:\.\d+)?))?"
    r"(?: c(?P<temp>-?\d+(?:\.\d+)?))?(?: i(?P<id>[0-9a-fA-F]{8}))?")


def leer_pos(texto):
    """Texto del mensaje de canal -> {nombre, lat, lon, epoch, mv, edad, amin, amax}, o None si no es posición SRI."""
    m = PATRON_POS.match((texto or "").strip())
    if not m:
        return None
    d = m.groupdict()
    num = lambda k, f=float: f(d[k]) if d[k] is not None else None  # noqa: E731
    return {"nombre": d["nombre"].strip(), "lat": float(d["lat"]), "lon": float(d["lon"]),
            "epoch": int(d["epoch"]), "mv": num("mv", int), "edad": num("edad", int),
            "amin": num("amin"), "amax": num("amax"), "temp": num("temp"),
            "id": d["id"].lower() if d["id"] else None}


def num_campo(nombre, ident=None):
    """Número de un nodo de campo que llega por LoRa: el de su llave (igual que si estuviera conectado o en los
    contactos) cuando el mensaje trae su identidad (sri5); si no, uno sacado del nombre (firmware anterior)."""
    if ident:
        return int(ident[:8], 16)
    return int.from_bytes(nombre.encode()[:4].ljust(4, b"_"), "big")


def clave_canal(frase):
    """Llave del canal privado SRI (16 bytes) a partir de una frase: todos los nodos con la misma frase se entienden."""
    return hashlib.sha256(("SRI:" + frase).encode("utf-8")).digest()[:16]


def leer(texto):
    """Texto del mensaje de canal -> dict de la alerta, o None si no es una alerta SRI."""
    m = PATRON.match((texto or "").strip())
    if not m:
        return None
    d = m.groupdict()
    lat, lon = d.get("lat"), d.get("lon")
    return {"nombre": d["nombre"].strip(), "tipo": "caida" if d["tipo"] == "CAIDA" else "golpe" if d["tipo"] == "GOLPE"
            else d["tipo"].lower(), "dif_g": float(d["dif"]), "pico_g": float(d["pico"]),
            "lat": float(lat) if lat else None, "lon": float(lon) if lon else None,
            "epoch": int(d["epoch"]), "cuenta": int(d["cuenta"]), "repeticion": int(d["n"]),
            "id": d["id"].lower() if d.get("id") else None}


class AlertasRed:
    """Alertas recibidas por la red: una por (nodo, número de evento, hora); activas hasta que se borran."""

    def __init__(self):
        self._lock = threading.Lock()
        self._alertas = {}            # (nombre, cuenta, epoch) -> alerta

    def registrar(self, a):
        """Guarda una alerta leída. Devuelve (es_nueva, alerta)."""
        clave = (a["nombre"], a["cuenta"], a["epoch"])
        with self._lock:
            prev = self._alertas.get(clave)
            if prev:
                prev["repeticiones"] = max(prev["repeticiones"], a.get("repeticion", 1))
                prev["ultima_rx"] = int(time.time())
                return False, dict(prev)
            ahora = int(time.time())
            nueva = dict(a, recibido=ahora, ultima_rx=ahora, activa=True, repeticiones=a.get("repeticion", 1))
            if abs(a["epoch"] - ahora) > 600:              # reloj del nodo mal (se reinició sin GPS): usar la
                nueva["epoch_nodo"] = a["epoch"]           # hora de llegada, menos lo que tardan las repeticiones
                nueva["epoch"] = ahora - 20 * (a.get("repeticion", 1) - 1)
            self._alertas[clave] = nueva
            if len(self._alertas) > 200:                        # no crecer sin límite
                viejas = sorted(self._alertas, key=lambda k: self._alertas[k]["recibido"])[:50]
                for k in viejas:
                    self._alertas.pop(k, None)
            return True, dict(nueva)

    def de(self, nombre):
        """Alerta activa más reciente de un nodo (o None)."""
        with self._lock:
            act = [a for a in self._alertas.values() if a["nombre"] == nombre and a["activa"]]
        return dict(max(act, key=lambda a: a["recibido"])) if act else None

    def activas(self):
        with self._lock:
            return sorted((dict(a) for a in self._alertas.values() if a["activa"]), key=lambda a: -a["recibido"])

    def borrar(self, nombre=None):
        """Borra (desactiva) las alertas de un nodo, o todas si no se da nombre. Devuelve cuántas."""
        n = 0
        with self._lock:
            for a in self._alertas.values():
                if a["activa"] and (nombre is None or a["nombre"] == nombre):
                    a["activa"] = False
                    n += 1
        return n
