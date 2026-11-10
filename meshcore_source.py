"""Conexión a un nodo con firmware MeshCore (companion) por USB o Bluetooth.

La librería `meshcore` es asíncrona: aquí corre en su propio hilo con su propio
event loop. Cada pocos segundos se le piden al nodo sus datos (telemetría, batería,
contactos) y se guardan en caché; la web lee esa caché.

Ofrece lo mismo que la conexión Meshtastic del servidor:
    nodes(), info(), ping(), stop(), mode, target
"""

import asyncio
import collections
import glob
import threading
import time

POLL_SECS = 10          # cada cuánto se piden datos al nodo
IMPACT_SECS = 1         # cada cuánto se revisa el acelerómetro (alarma y gráfica)
HIST_SECS = 15 * 60     # cuánto historial de aceleración se guarda para la gráfica
CMD_TIMEOUT = 6         # segundos máximos por comando
MAX_FAILS = 3           # fallos seguidos antes de reconectar


def battery_pct(mv):
    """Porcentaje aproximado de una batería de litio a partir del voltaje (mV)."""
    if not mv:
        return None
    return max(0, min(100, round((mv - 3300) / (4150 - 3300) * 100)))


def num_from_key(pubkey_hex):
    """Número de nodo a partir de los primeros 4 bytes de la llave pública."""
    return int(pubkey_hex[:8], 16)


def valid(lat, lon):
    return lat is not None and lon is not None and not (abs(lat) < 1e-6 and abs(lon) < 1e-6)


class MeshCoreSource:
    """Conexión real a un nodo MeshCore (companion USB o BLE)."""

    def __init__(self, state, track, dev_path=None, ble=None):
        self.state = state          # dict compartido con el servidor (conectado, error, ...)
        self.track = track          # función del servidor que agrega uptime_at / last_pos
        self.dev_path = dev_path
        self.ble = ble
        self.mc = None
        self.loop = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._cache = {"self": None, "contacts": [], "device": {}, "custom": {}}
        self._pos_rx = None         # cuándo llegó la última posición GPS válida
        self._impact = None         # estado del detector de caídas (firmware v1.18.0-rabanito)
        self.on_impact = None       # función del servidor que se llama con cada evento nuevo
        self.acc_hist = collections.deque(maxlen=HIST_SECS // IMPACT_SECS)  # [t, actual, mín, máx]
        self.moves = collections.deque(maxlen=300)   # movimientos evaluados al quedar en reposo
        self.calibration = None     # "ox|oy|oz|gx|gy|gz" (milésimas); se envía al nodo al conectar
        threading.Thread(target=self._thread, daemon=True).start()

    # ---------------- datos de conexión ----------------
    @property
    def mode(self):
        return "ble" if self.ble else "serial"

    @property
    def target(self):
        return self.ble or self.dev_path

    def stop(self):
        self._stop.set()
        if self.loop and self.mc:
            fut = asyncio.run_coroutine_threadsafe(self._disconnect(), self.loop)
            try:
                fut.result(5)
            except Exception:  # noqa: BLE001
                pass

    # ---------------- hilo con su event loop ----------------
    def _thread(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._main())

    async def _disconnect(self):
        mc, self.mc = self.mc, None
        if mc:
            try:
                await asyncio.wait_for(mc.disconnect(), 5)
            except Exception:  # noqa: BLE001
                pass
        await self._ble_cleanup()

    async def _ble_cleanup(self):
        """Cierra a nivel sistema (BlueZ) un enlace Bluetooth que quedó medio abierto.

        Si el servidor se detuvo sin desconectarse, BlueZ deja el enlace abierto; mientras
        tanto el nodo no se anuncia y no se le puede volver a conectar.
        """
        import re
        if self.ble and re.fullmatch(r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", self.ble):
            try:
                p = await asyncio.create_subprocess_exec(
                    "bluetoothctl", "disconnect", self.ble,
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                await asyncio.wait_for(p.wait(), 8)
                await asyncio.sleep(1)
            except Exception:  # noqa: BLE001
                pass

    async def _connect(self):
        from meshcore import MeshCore
        if self.ble:
            await self._ble_cleanup()
            mc = await MeshCore.create_ble(self.ble, default_timeout=CMD_TIMEOUT)
        else:
            port = self.dev_path
            if not port:
                ports = sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))
                if not ports:
                    raise FileNotFoundError("ningún puerto USB")
                port = ports[0]
            mc = await MeshCore.create_serial(port, 115200, default_timeout=CMD_TIMEOUT)
        if mc is None or not mc.is_connected:
            raise ConnectionError("el nodo no respondió al protocolo MeshCore")
        return mc

    async def _cmd(self, coro):
        """Ejecuta un comando y devuelve el payload, o None si falla."""
        from meshcore import EventType
        try:
            r = await asyncio.wait_for(coro, CMD_TIMEOUT)
        except Exception:  # noqa: BLE001
            return None
        return None if r is None or r.type == EventType.ERROR else r.payload

    async def _main(self):
        fails = 0
        while not self._stop.is_set():
            if self.mc is None:
                try:
                    self.mc = await asyncio.wait_for(self._connect(), 30)
                    c = self.mc.commands
                    # Al conectar: poner la hora de la PC en el nodo y leer datos fijos
                    await self._cmd(c.set_time(int(time.time())))
                    dev = await self._cmd(c.send_device_query()) or {}
                    custom = await self._cmd(c.get_custom_vars()) or {}
                    with self._lock:
                        self._cache["device"], self._cache["custom"] = dev, custom
                    if self.calibration:   # la calibración vive en la RAM del nodo: reenviarla
                        await self._cmd(c.set_custom_var("acc_cal", self.calibration))
                    await self._poll()
                    await self._poll_impact()
                    self.state.update({"connected": True, "error": None,
                                       "connected_since": int(time.time()),
                                       "my_node": num_from_key(self.mc.self_info["public_key"])})
                    print("Conectado al nodo MeshCore", self.mc.self_info.get("name"), flush=True)
                    fails = 0
                except Exception as e:  # noqa: BLE001
                    await self._disconnect()
                    self.state["connected"] = False
                    if isinstance(e, FileNotFoundError) or "No such file" in str(e):
                        self.state["error"] = ("No hay ningún nodo conectado por USB"
                                               + (f" ({self.dev_path} no existe)" if self.dev_path else "")
                                               + ". Conecta el cable; se conecta solo.")
                    else:
                        self.state["error"] = f"No se pudo conectar: {e or type(e).__name__}"
                    print(self.state["error"], flush=True)
                    await self._sleep(5)
                    continue
            for _ in range(POLL_SECS // IMPACT_SECS):
                await self._sleep(IMPACT_SECS)
                if self.mc is None or self._stop.is_set():
                    break
                await self._poll_impact()
            if self.mc is None or self._stop.is_set():
                continue
            ok = await self._poll()
            fails = 0 if ok else fails + 1
            if fails >= MAX_FAILS or not self.mc.is_connected:
                self.state.update({"connected": False, "error": "El nodo dejó de responder; reconectando..."})
                print(self.state["error"], flush=True)
                await self._disconnect()
                fails = 0
        await self._disconnect()

    async def _sleep(self, secs):
        end = time.monotonic() + secs
        while time.monotonic() < end and not self._stop.is_set():
            await asyncio.sleep(0.5)

    async def _poll_impact(self):
        """Lee las variables del detector de caídas (solo existen en el firmware modificado)."""
        v = await self._cmd(self.mc.commands.get_custom_vars())
        if v is None:
            return
        with self._lock:
            self._cache["custom"] = v
        if "impacto" not in v:
            self._impact = {"available": False}
            return
        info = v.get("impacto_info", "")
        cur = amin = amax = None
        acel = v.get("acel", "-")
        if "|" in acel:                      # actual|mín|máx (centésimas de g)
            cur, amin, amax = (int(x) / 100 for x in acel.split("|")[:3])
        elif acel not in ("-", ""):
            cur = amin = amax = float(acel)
        if cur is not None:
            self.acc_hist.append([round(time.time(), 1), cur, amin, amax])
        imp = {"available": True, "sensor_ok": info != "sin_sensor", "active": v.get("impacto") == "1",
               "accel_g": cur,
               "threshold_g": float(v.get("umbral_g") or 0) or None,
               "type": None, "peak_g": None, "time": None, "count": 0}
        parts = info.split("|")
        if len(parts) >= 4:      # tipo|pico|epoch|cuenta[|dif|reposo]
            tipo, pico, epoch, cuenta = parts[:4]
            imp.update({"type": tipo if tipo != "-" else None, "peak_g": int(pico) / 100,
                        "time": int(epoch) or None, "count": int(cuenta)})
            if len(parts) >= 6:
                imp.update({"diff_g": int(parts[4]) / 100, "rest_g": int(parts[5]) / 100})
        # Último movimiento evaluado al quedar en reposo (alerte o no): pico|reposo|dif|epoch
        ult = v.get("ultimo", "-").split("|")
        if len(ult) == 4:
            imp["last_move"] = {"peak_g": int(ult[0]) / 100, "rest_g": int(ult[1]) / 100,
                                "diff_g": int(ult[2]) / 100, "time": int(ult[3]) or None}
            lm = imp["last_move"]
            if lm["time"] and (not self.moves or self.moves[-1]["time"] != lm["time"]):
                self.moves.append(dict(lm, alerted=bool(imp["threshold_g"]) and lm["diff_g"] >= imp["threshold_g"]))
        prev = self._impact or {}
        if imp["active"] and imp["count"] != prev.get("count") and self.on_impact:
            self.on_impact(dict(imp))
        self._impact = imp

    def read_raw_axes(self, secs=2.0, timeout=15):
        """Promedio de cada eje SIN calibrar durante `secs` segundos (para la calibración)."""
        if self.mc is None or self.loop is None:
            return None

        async def do():
            c = self.mc.commands
            await self._cmd(c.get_self_telemetry())      # reinicia el promedio en el nodo
            await asyncio.sleep(secs)
            tel = await self._cmd(c.get_self_telemetry())
            for item in (tel or {}).get("lpp", []):
                if item.get("type") == "accelerometer" and item.get("channel") == 2:
                    v = item.get("value")
                    if isinstance(v, dict):
                        return [v.get("acc_x"), v.get("acc_y"), v.get("acc_z")]
                    if isinstance(v, (list, tuple)) and len(v) == 3:
                        return list(v)
            return None

        try:
            return asyncio.run_coroutine_threadsafe(do(), self.loop).result(timeout)
        except Exception:  # noqa: BLE001
            return None

    def accel_history(self, seconds):
        """Aceleración y movimientos de los últimos `seconds` segundos (para la gráfica)."""
        since = time.time() - seconds
        imp = self._impact or {}
        return {"samples": [x for x in list(self.acc_hist) if x[0] >= since],
                "moves": [m for m in list(self.moves) if (m["time"] or 0) >= since],
                "threshold_g": imp.get("threshold_g"),
                "available": bool(imp.get("available")) and bool(imp.get("sensor_ok"))}

    def impact_cmd(self, name, value, timeout=8):
        """Cambia una variable del detector (borrar alarma, umbral)."""
        if self.mc is None or self.loop is None:
            return {"ok": False, "error": "No hay conexión con el nodo"}

        async def do():
            r = await self._cmd(self.mc.commands.set_custom_var(name, str(value)))
            await self._poll_impact()
            return r

        try:
            r = asyncio.run_coroutine_threadsafe(do(), self.loop).result(timeout)
        except Exception:  # noqa: BLE001
            return {"ok": False, "error": "El nodo no respondió"}
        if r is None:
            return {"ok": False, "error": "El nodo rechazó el cambio (¿firmware sin detector?)"}
        return {"ok": True, "impact": self._impact}

    async def _poll(self):
        """Pide al nodo telemetría, estadísticas y contactos. True si respondió."""
        c = self.mc.commands
        tel = await self._cmd(c.get_self_telemetry())
        stats = await self._cmd(c.get_stats_core())
        contacts = await self._cmd(c.get_contacts())
        if tel is None and stats is None:
            return False
        await self._cmd(c.send_appstart())  # refresca self_info (nombre, coordenadas del anuncio)
        me = dict(self.mc.self_info or {})
        lat = lon = alt = None
        temps, lux, volt = [], None, None
        for item in (tel or {}).get("lpp", []):
            t, v = item.get("type"), item.get("value")
            if t == "gps" and isinstance(v, dict):
                lat, lon, alt = v.get("latitude"), v.get("longitude"), v.get("altitude")
            elif t == "temperature":
                temps.append(v)
            elif t == "illuminance":
                lux = v
            elif t == "voltage":
                volt = v
        if not valid(lat, lon) and valid(me.get("adv_lat"), me.get("adv_lon")):
            lat, lon = me["adv_lat"], me["adv_lon"]
        if valid(lat, lon):
            self._pos_rx = int(time.time())
        else:
            lat = lon = alt = None
        with self._lock:
            self._cache["self"] = {
                "info": me, "lat": lat, "lon": lon, "alt": alt, "temps": temps, "lux": lux,
                "volt": volt, "battery_mv": (stats or {}).get("battery_mv"),
                "uptime": (stats or {}).get("uptime_secs"), "seen": int(time.time()),
            }
            if contacts is not None:
                self._cache["contacts"] = list(contacts.values())
        return True

    # ---------------- lo que pide la web ----------------
    def nodes(self):
        with self._lock:
            s, contacts, dev = self._cache["self"], list(self._cache["contacts"]), self._cache["device"]
        if not s or not self.state.get("connected"):
            return []
        me = s["info"]
        mv = s["battery_mv"] or (s["volt"] * 1000 if s["volt"] else None)
        name = me.get("name") or "?"
        out = [{
            "num": num_from_key(me["public_key"]), "id": me["public_key"][:12],
            "long_name": name, "short_name": name[:4].upper(), "hw_model": dev.get("model"),
            "lat": s["lat"], "lon": s["lon"], "altitude": s["alt"],
            "position_time": self._pos_rx, "position_rx": self._pos_rx,
            "battery": battery_pct(mv), "voltage": round(mv / 1000, 2) if mv else None,
            "channel_util": None, "air_util_tx": None, "uptime": s["uptime"],
            "snr": None, "hops_away": 0, "last_heard": s["seen"],
            "temperature": s["temps"][0] if s["temps"] else None, "lux": s["lux"],
            "impact": self._impact,
        }]
        for ct in contacts:
            key = ct.get("public_key", "")
            if len(key) < 8:
                continue
            lat, lon = ct.get("adv_lat"), ct.get("adv_lon")
            ok = valid(lat, lon)
            nm = ct.get("adv_name") or key[:8]
            out.append({
                "num": num_from_key(key), "id": key[:12], "long_name": nm, "short_name": nm[:4].upper(),
                "hw_model": {1: "Companion", 2: "Repetidor", 3: "Sala", 4: "Sensor"}.get(ct.get("type"), "?"),
                "lat": lat if ok else None, "lon": lon if ok else None, "altitude": None,
                "position_time": ct.get("last_advert") if ok else None,
                "position_rx": ct.get("last_advert") if ok else None,
                "battery": None, "voltage": None, "channel_util": None, "air_util_tx": None,
                "uptime": None, "snr": None,
                "hops_away": ct.get("out_path_len") if (ct.get("out_path_len") or -1) >= 0 else None,
                "last_heard": ct.get("last_advert"),
            })
        return self.track(out)

    def info(self):
        with self._lock:
            s, dev, custom = self._cache["self"], dict(self._cache["device"]), dict(self._cache["custom"])
        if not s or not self.state.get("connected"):
            return {"ok": False, "error": "No hay conexión con el nodo"}
        me = s["info"]
        key = me.get("public_key", "")
        gps = custom.get("gps")
        return {"ok": True, "groups": [
            ["Identificación", [
                ["Nombre", me.get("name")],
                ["ID (inicio de la llave)", key[:12]],
                ["Llave pública (identidad única)", key, True],
                ["Hardware", dev.get("model")],
            ]],
            ["Firmware", [
                ["Firmware", "MeshCore (companion)"],
                ["Versión", dev.get("ver")], ["Compilado", dev.get("fw_build")],
                ["Máx. contactos", dev.get("max_contacts")], ["Máx. canales", dev.get("max_channels")],
            ]],
            ["GPS y sensores", [
                ["GPS", "Encendido" if gps == "1" else "Apagado" if gps == "0" else gps],
                ["Compartir ubicación en anuncios", "Sí" if me.get("adv_loc_policy") else "No"],
                ["Temperatura", " / ".join(f"{t:.1f} °C" for t in s["temps"]) or None],
                ["Luz", f"{s['lux']:.0f} lux" if s["lux"] is not None else None],
                ["Batería", f"{s['battery_mv']} mV" if s["battery_mv"] else None],
            ]],
            ["Radio LoRa", [
                ["Frecuencia", f"{me.get('radio_freq')} MHz"],
                ["Ancho de banda", f"{me.get('radio_bw')} kHz"],
                ["Spreading factor", me.get("radio_sf")], ["Coding rate", f"4/{me.get('radio_cr')}"],
                ["Potencia TX", f"{me.get('tx_power')} dBm (máx {me.get('max_tx_power')})"],
            ]],
            ["Conexión", [
                ["Puerto", f"Bluetooth {self.ble}" if self.ble else (self.dev_path or "USB (autodetectado)")],
                ["Contactos", len(self._cache["contacts"])],
            ]],
        ]}

    def ping(self, timeout=8):
        """Pide al nodo su información de dispositivo y mide cuánto tarda en responder."""
        if self.mc is None or self.loop is None or not self.state.get("connected"):
            return {"ok": False, "error": "No hay conexión con el nodo"}

        async def do():
            t0 = time.monotonic()
            p = await self._cmd(self.mc.commands.send_device_query())
            return p, round((time.monotonic() - t0) * 1000)

        try:
            p, ms = asyncio.run_coroutine_threadsafe(do(), self.loop).result(timeout)
        except Exception:  # noqa: BLE001
            return {"ok": False, "error": f"El nodo no respondió en {timeout} s"}
        if p is None:
            return {"ok": False, "error": "El nodo no respondió"}
        me = (self.mc.self_info or {}) if self.mc else {}
        return {"ok": True, "ms": ms, "firmware": p.get("ver"), "model": p.get("model"),
                "from": f"{me.get('name')} ({(me.get('public_key') or '')[:12]})", "from_match": True}
