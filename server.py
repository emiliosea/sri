"""Rastreador de nodos Meshtastic.

Uso:
    python server.py                 # detecta el nodo por USB automáticamente
    python server.py --port /dev/ttyUSB0
    python server.py --demo          # datos simulados, sin hardware

Luego abre http://localhost:5000
"""

import argparse
import math
import os
import random
import threading
import time

from flask import Flask, jsonify, send_from_directory

app = Flask(__name__, static_folder="static")

# Estado compartido entre la conexión y la web
state = {"mode": None, "connected": False, "error": None, "my_node": None}
source = None  # objeto que entrega los nodos (real o demo)


def normalize(raw):
    """Convierte un nodo del formato de la librería meshtastic a algo simple para la web."""
    user = raw.get("user", {})
    pos = raw.get("position", {})
    metrics = raw.get("deviceMetrics", {})
    lat = pos.get("latitude")
    lon = pos.get("longitude")
    # Algunos firmwares solo mandan latitudeI/longitudeI (enteros * 1e7)
    if lat is None and "latitudeI" in pos:
        lat = pos["latitudeI"] / 1e7
    if lon is None and "longitudeI" in pos:
        lon = pos["longitudeI"] / 1e7
    if lat == 0 and lon == 0:
        lat = lon = None  # 0,0 significa "sin GPS"
    return {
        "num": raw.get("num"),
        "id": user.get("id"),
        "long_name": user.get("longName") or user.get("id") or str(raw.get("num")),
        "short_name": user.get("shortName", "?"),
        "hw_model": user.get("hwModel"),
        "lat": lat,
        "lon": lon,
        "altitude": pos.get("altitude"),
        "position_time": pos.get("time"),
        "battery": metrics.get("batteryLevel"),
        "voltage": metrics.get("voltage"),
        "channel_util": metrics.get("channelUtilization"),
        "air_util_tx": metrics.get("airUtilTx"),
        "uptime": metrics.get("uptimeSeconds"),
        "snr": raw.get("snr"),
        "hops_away": raw.get("hopsAway"),
        "last_heard": raw.get("lastHeard"),
    }


def mac_text(mac):
    """La librería entrega la MAC en base64 ('/6ydWJXB'); la pasamos a 'ff:ac:9d:58:95:c1'."""
    if not mac or ":" in mac:
        return mac
    import base64
    try:
        return ":".join(f"{b:02x}" for b in base64.b64decode(mac))
    except ValueError:
        return mac


class LastSeen:
    """Guarda en disco la última posición GPS conocida de cada nodo.

    Así no se pierde aunque el GPS se quede sin señal, el nodo se reinicie
    o se reinicie este servidor. Archivo: data/last_seen.json
    """

    def __init__(self, path):
        import json
        import os
        self._json, self._os = json, os
        self.path = path
        self._lock = threading.Lock()
        try:
            with open(path) as f:
                self._data = {int(k): v for k, v in json.load(f).items()}
        except (FileNotFoundError, ValueError):
            self._data = {}

    def _save(self):
        self._os.makedirs(self._os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            self._json.dump(self._data, f, indent=2)
        self._os.replace(tmp, self.path)  # escritura atómica: no se corrompe si se corta

    def update(self, nodes):
        """Guarda las posiciones nuevas y agrega 'last_pos' a cada nodo."""
        now = int(time.time())
        changed = False
        with self._lock:
            for n in nodes:
                prev = self._data.get(n["num"])
                if n.get("lat") is not None and n.get("lon") is not None:
                    pos_time = n.get("position_rx") or n.get("position_time") or now
                    if (prev is None or prev["lat"] != n["lat"] or prev["lon"] != n["lon"]
                            or prev.get("position_time") != pos_time):
                        prev = {
                            "lat": n["lat"], "lon": n["lon"], "altitude": n.get("altitude"),
                            "position_time": pos_time, "saved_at": now,
                            "long_name": n.get("long_name"), "short_name": n.get("short_name"),
                        }
                        self._data[n["num"]] = prev
                        changed = True
                n["last_pos"] = prev
            if changed:
                self._save()
        return nodes

    def missing(self, nodes):
        """Nodos guardados que no están en la lista actual (p. ej. el nodo está desconectado).

        Se devuelven sin datos en vivo, solo con su última posición conocida.
        """
        present = {n["num"] for n in nodes}
        with self._lock:
            return [{
                "num": num, "id": f"!{num:08x}",
                "long_name": p.get("long_name") or f"!{num:08x}",
                "short_name": p.get("short_name") or "?",
                "lat": None, "lon": None, "last_pos": p, "offline": True,
                "last_heard": p.get("saved_at"),
            } for num, p in self._data.items() if num not in present]


last_seen = None  # se crea en main() según el modo


_uptime_seen = {}  # num -> (uptime, momento en que vimos ese valor)


_pos_rx = {}  # num -> momento (epoch) en que recibimos su última posición


def track_positions(nodes):
    """Agrega 'position_rx': cuándo llegó de verdad la última posición de cada nodo.

    El campo 'time' que manda el nodo no es confiable (puede quedarse en una hora vieja),
    así que se usa la hora en que este servidor recibió el paquete de posición.
    """
    for n in nodes:
        n["position_rx"] = _pos_rx.get(n["num"])
    return nodes


def track_uptime(nodes):
    """Agrega 'uptime_at': cuándo se recibió el uptime actual.

    El nodo solo reporta su uptime cada cierto tiempo. Con esta marca el navegador
    puede seguir contando en vivo: uptime + (ahora - uptime_at).
    """
    now = int(time.time())
    for n in nodes:
        up = n.get("uptime")
        if up is None:
            continue
        prev = _uptime_seen.get(n["num"])
        if prev is None or prev[0] != up:
            prev = (up, now)
            _uptime_seen[n["num"]] = prev
        n["uptime_at"] = prev[1]
    return nodes


class MeshSource:
    """Conexión real al nodo, por USB o por Bluetooth.

    La librería mantiene iface.nodes actualizado; aquí solo lo leemos.
    """

    def __init__(self, dev_path=None, ble=None):
        self.dev_path = dev_path
        self.ble = ble  # dirección o nombre Bluetooth; si es None se usa USB
        self.label = f"Bluetooth {ble}" if ble else (dev_path or "USB (autodetectado)")
        self.iface = None
        self._lost = threading.Event()
        self._stop = threading.Event()  # se activa al cambiar de conexión desde la interfaz
        threading.Thread(target=self._connect_loop, daemon=True).start()

    @property
    def mode(self):
        return "ble" if self.ble else "serial"

    @property
    def target(self):
        return self.ble or self.dev_path

    def stop(self):
        """Detiene esta conexión para siempre (al cambiar a otra desde la interfaz)."""
        self._stop.set()
        self._close()

    def _connect_loop(self):
        from pubsub import pub

        def on_lost(interface, topic=pub.AUTO_TOPIC):
            if self._stop.is_set() or interface is not self.iface:
                return  # aviso de una conexión vieja; no afecta a la actual
            state["connected"] = False
            state["error"] = "Se perdió la conexión con el nodo"
            self._lost.set()

        pub.subscribe(on_lost, "meshtastic.connection.lost")

        def on_position(packet, interface):
            if self._stop.is_set():
                return
            pos = packet.get("decoded", {}).get("position", {})
            if packet.get("from") is not None and ("latitudeI" in pos or "latitude" in pos):
                _pos_rx[packet["from"]] = int(time.time())
                lat = pos.get("latitude", pos.get("latitudeI", 0) / 1e7)
                lon = pos.get("longitude", pos.get("longitudeI", 0) / 1e7)
                print(f"Posición recibida de !{packet['from']:08x}: {lat:.6f}, {lon:.6f}", flush=True)

        self._on_position, self._on_lost = on_position, on_lost  # pubsub guarda referencias débiles
        pub.subscribe(on_position, "meshtastic.receive.position")

        last_check = time.monotonic()
        while not self._stop.is_set():
            if self._lost.is_set():
                self._close()
                self._lost.clear()
            if self.iface is None:
                iface = None
                try:
                    iface = self._open()
                    if self._stop.is_set():  # cambiaron de conexión mientras conectábamos
                        self.iface = iface
                        self._close()
                        break
                    info = iface.getMyNodeInfo() or {}
                    self.iface = iface
                    state["my_node"] = info.get("num")
                    state["connected"] = True
                    state["connected_since"] = int(time.time())
                    state["error"] = None
                    print("Conectado al nodo", info.get("user", {}).get("longName"), flush=True)
                except Exception as e:  # noqa: BLE001
                    state["connected"] = False
                    if isinstance(e, FileNotFoundError) or "No such file" in str(e):
                        state["error"] = ("No hay ningún nodo conectado por USB"
                                          + (f" ({self.dev_path} no existe)" if self.dev_path else "")
                                          + ". Conecta el cable; se conecta solo.")
                    else:
                        state["error"] = f"No se pudo conectar: {e}"
                    print(state["error"], flush=True)
                    # Cerrar el intento fallido; si no, sigue ocupando el puerto
                    if iface is not None:
                        try:
                            iface.close()
                        except Exception:  # noqa: BLE001
                            pass
            elif self.ble and time.monotonic() - last_check > 60:
                # Por Bluetooth el enlace puede morir sin aviso (p. ej. fuera de alcance).
                # Un ping cada minuto lo detecta; ping() fuerza la reconexión si falla.
                last_check = time.monotonic()
                threading.Thread(target=self.ping, daemon=True).start()
            self._stop.wait(5)

    def _ble_cleanup(self):
        """Cierra a nivel sistema (BlueZ) un enlace Bluetooth que quedó medio abierto.

        Si un intento falla, el enlace puede quedar abierto; mientras tanto el nodo
        deja de anunciarse y los reintentos no lo encuentran.
        """
        import re
        import subprocess
        if self.ble and re.fullmatch(r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", self.ble):
            try:
                subprocess.run(["bluetoothctl", "disconnect", self.ble],
                               capture_output=True, timeout=8)
                time.sleep(1)
            except Exception:  # noqa: BLE001
                pass

    def _open(self):
        if self.ble:
            from meshtastic.ble_interface import BLEInterface
            self._ble_cleanup()
            try:
                return BLEInterface(self.ble)
            except Exception:
                self._ble_cleanup()
                raise
        from meshtastic.serial_interface import SerialInterface
        if not self.dev_path:
            import glob
            if not (glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")):
                raise FileNotFoundError("ningún puerto USB")
        return SerialInterface(devPath=self.dev_path)

    def _close(self):
        """Cierra la conexión actual para liberar el puerto antes de reconectar.

        Con Bluetooth, close() puede quedarse colgado si el enlace ya murió;
        por eso se hace en otro hilo y no se espera más de 5 s.
        """
        iface, self.iface = self.iface, None
        if iface is not None:
            def close():
                try:
                    iface.close()
                except Exception:  # noqa: BLE001
                    pass
            t = threading.Thread(target=close, daemon=True)
            t.start()
            t.join(5)
        self._ble_cleanup()

    def mark_dead(self, reason):
        """El enlace dejó de responder aunque la librería no se dio cuenta: forzar reconexión."""
        print("Conexión muerta:", reason, flush=True)
        state["connected"] = False
        state["error"] = reason
        self._lost.set()

    def nodes(self):
        if not self.iface or not self.iface.nodes:
            return []
        return last_seen.update(track_positions(track_uptime([normalize(n) for n in list(self.iface.nodes.values())])))

    def info(self):
        """Datos fijos del dispositivo conectado: identificadores, firmware, radio."""
        from meshtastic.protobuf import config_pb2, mesh_pb2

        iface = self.iface
        if iface is None or iface.myInfo is None:
            return {"ok": False, "error": "No hay conexión con el nodo"}
        my, meta = iface.myInfo, iface.metadata
        me = (iface.nodesByNum or {}).get(my.my_node_num, {})
        user = me.get("user", {})
        lora = iface.localNode.localConfig.lora
        LoRa = config_pb2.Config.LoRaConfig
        role = config_pb2.Config.DeviceConfig.Role
        channels = iface.localNode.channels or []
        primary = next((c for c in channels if c.role == 1), None)  # 1 = PRIMARY
        return {
            "ok": True,
            "port": self.label,
            "node_id": user.get("id"),
            "node_num": my.my_node_num,
            "long_name": user.get("longName"),
            "short_name": user.get("shortName"),
            "hw_model": user.get("hwModel"),
            # ID único del chip, grabado de fábrica: lo más parecido a un número de serie
            "device_id": my.device_id.hex().upper() if my.device_id else None,
            "mac": mac_text(user.get("macaddr")),
            "public_key": user.get("publicKey"),
            "firmware": meta.firmware_version if meta else None,
            "firmware_edition": mesh_pb2.FirmwareEdition.Name(my.firmware_edition)
            if hasattr(mesh_pb2, "FirmwareEdition") else None,
            "pio_env": my.pio_env,
            "reboot_count": my.reboot_count,
            "role": role.Name(meta.role) if meta else None,
            "has_bluetooth": meta.hasBluetooth if meta else None,
            "has_wifi": meta.hasWifi if meta else None,
            "region": LoRa.RegionCode.Name(lora.region),
            "modem_preset": LoRa.ModemPreset.Name(lora.modem_preset) if lora.use_preset else "PERSONALIZADO",
            "hop_limit": lora.hop_limit,
            "tx_power": lora.tx_power,
            "tx_enabled": lora.tx_enabled,
            "channel": (primary.settings.name or "(predeterminado)") if primary else None,
            "nodedb_count": my.nodedb_count,
            "gps_mode": config_pb2.Config.PositionConfig.GpsMode.Name(
                iface.localNode.localConfig.position.gps_mode),
            "gps_update_interval": iface.localNode.localConfig.position.gps_update_interval,
            "position_broadcast_secs": iface.localNode.localConfig.position.position_broadcast_secs,
            "bluetooth_mode": config_pb2.Config.BluetoothConfig.PairingMode.Name(
                iface.localNode.localConfig.bluetooth.mode),
        }

    _ping_lock = threading.Lock()

    def ping(self, timeout=10):
        """Pide al nodo sus metadatos y mide cuánto tarda en responder.

        Comprueba todo el camino: cable USB, puerto serial y firmware del nodo.
        """
        from meshtastic.protobuf import admin_pb2

        iface = self.iface
        if iface is None:
            return {"ok": False, "error": "No hay conexión con el nodo"}
        if not self._ping_lock.acquire(blocking=False):
            return {"ok": False, "error": "Ya hay un ping en curso"}
        try:
            done = threading.Event()
            result = {}

            def on_response(packet):
                decoded = packet.get("decoded", {})
                if "admin" in decoded:
                    meta = decoded["admin"]["raw"].get_device_metadata_response
                    result["firmware"] = meta.firmware_version
                    result["hw_model"] = meta.hw_model
                    result["from"] = packet.get("from")
                    result["request_id"] = decoded.get("requestId")
                    done.set()
                elif decoded.get("routing", {}).get("errorReason", "NONE") != "NONE":
                    result["error"] = decoded["routing"]["errorReason"]
                    done.set()
                # Un ACK de routing sin error no es la respuesta; seguir esperando

            msg = admin_pb2.AdminMessage()
            msg.get_device_metadata_request = True
            start = time.monotonic()
            # Enviar en otro hilo: si el enlace Bluetooth murió, el envío se queda
            # colgado para siempre y bloquearía todos los pings siguientes.
            sent_box = {}

            def send():
                try:
                    sent_box["pkt"] = iface.localNode._sendAdmin(msg, wantResponse=True, onResponse=on_response)
                except Exception as e:  # noqa: BLE001
                    sent_box["error"] = e

            t = threading.Thread(target=send, daemon=True)
            t.start()
            t.join(5)
            if t.is_alive():
                self.mark_dead("El enlace con el nodo dejó de responder; reconectando...")
                return {"ok": False, "error": "No se pudo enviar: el enlace con el nodo está caído. Reconectando..."}
            if "error" in sent_box:
                raise sent_box["error"]
            sent_id = getattr(sent_box.get("pkt"), "id", None)
            if not done.wait(timeout):
                if state["mode"] == "ble":
                    self.mark_dead("El nodo dejó de responder por Bluetooth; reconectando...")
                return {"ok": False, "error": f"El nodo no respondió en {timeout} s", "sent_id": sent_id}
            ms = round((time.monotonic() - start) * 1000)
            if "error" in result:
                return {"ok": False, "error": f"El nodo respondió con error: {result['error']}", "ms": ms}
            # Pruebas de que la respuesta es real:
            #  - request_id de la respuesta == id del paquete que mandamos
            #  - from == número de nuestro nodo
            return {
                "ok": True, "ms": ms,
                "firmware": result.get("firmware"),
                "sent_id": sent_id,
                "request_id": result.get("request_id"),
                "id_match": sent_id is not None and sent_id == result.get("request_id"),
                "from": f"!{result['from']:08x}" if result.get("from") is not None else None,
                "from_match": result.get("from") == state["my_node"],
            }
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"Error al enviar el ping: {e}"}
        finally:
            self._ping_lock.release()


class DemoSource:
    """Nodos simulados que se mueven alrededor de San Pedro Garza García."""

    mode, target = "demo", None

    def stop(self):
        pass

    CENTER = (25.6600, -100.4200)

    def __init__(self, count=5):
        self._lock = threading.Lock()
        now = int(time.time())
        self._nodes = []
        for i in range(count):
            self._nodes.append({
                "num": 0x1000 + i,
                "user": {"id": f"!demo{i:04x}", "longName": f"Nodo Demo {i + 1}",
                         "shortName": f"D{i + 1}", "hwModel": random.choice(["TBEAM", "HELTEC_V3", "RAK4631"])},
                "position": {"latitude": self.CENTER[0] + random.uniform(-0.03, 0.03),
                             "longitude": self.CENTER[1] + random.uniform(-0.03, 0.03),
                             "altitude": random.randint(500, 800), "time": now},
                "deviceMetrics": {"batteryLevel": random.randint(40, 100), "voltage": 4.0,
                                  "channelUtilization": random.uniform(1, 15),
                                  "airUtilTx": random.uniform(0.1, 3), "uptimeSeconds": random.randint(100, 90000)},
                "snr": random.uniform(-10, 10), "hopsAway": 0 if i == 0 else random.randint(1, 3),
                "lastHeard": now,
                "_heading": random.uniform(0, 2 * math.pi),
            })
        # Un nodo sin GPS para ver cómo se muestra
        self._nodes[-1]["position"] = {}
        state["my_node"] = self._nodes[0]["num"]
        state["connected"] = True
        state["connected_since"] = int(time.time())
        threading.Thread(target=self._simulate, daemon=True).start()

    def _simulate(self):
        while True:
            time.sleep(3)
            now = int(time.time())
            with self._lock:
                for n in self._nodes:
                    if random.random() < 0.3:
                        continue  # no todos reportan cada vez
                    pos = n["position"]
                    if "latitude" in pos:
                        n["_heading"] += random.uniform(-0.5, 0.5)
                        pos["latitude"] += 0.0004 * math.cos(n["_heading"])
                        pos["longitude"] += 0.0004 * math.sin(n["_heading"])
                        pos["time"] = now
                        _pos_rx[n["num"]] = now       # "llegó una posición nueva"
                    m = n["deviceMetrics"]
                    m["batteryLevel"] = max(0, m["batteryLevel"] - random.choice([0, 0, 1]))
                    m["voltage"] = round(3.3 + 0.9 * m["batteryLevel"] / 100, 2)
                    m["uptimeSeconds"] += 3
                    n["snr"] = round(random.uniform(-10, 10), 1)
                    n["lastHeard"] = now

    def nodes(self):
        with self._lock:
            nodes = last_seen.update(track_positions(track_uptime([normalize(n) for n in self._nodes])))
        nodes[0]["impact"] = self._demo_impact()
        return nodes

    # Detector de caídas simulado: un evento cada ~45 s (para probar la interfaz)
    _imp = {"available": True, "sensor_ok": True, "active": False, "type": None, "peak_g": None,
            "time": None, "count": 0, "threshold_g": 7.0, "accel_g": 1.0}
    _imp_next = 0

    def _demo_impact(self):
        now = time.time()
        if not DemoSource._imp_next:
            DemoSource._imp_next = now + 15
        if now >= DemoSource._imp_next:
            DemoSource._imp_next = now + 45
            caida = random.random() < 0.5
            pico, reposo = round(random.uniform(4, 12), 2), round(random.uniform(0.98, 1.06), 2)
            dif = round(pico - reposo, 2)
            DemoSource._imp["last_move"] = {"peak_g": pico, "rest_g": reposo, "diff_g": dif, "time": int(now)}
            if dif >= DemoSource._imp["threshold_g"]:      # igual que el firmware: solo alerta sobre el umbral
                DemoSource._imp.update({"active": True, "type": "caida" if caida else "golpe",
                                        "peak_g": pico, "rest_g": reposo, "diff_g": dif,
                                        "time": int(now), "count": DemoSource._imp["count"] + 1})
                log_impact(dict(DemoSource._imp))
        DemoSource._imp["accel_g"] = round(random.uniform(0.97, 1.03), 2)
        return dict(DemoSource._imp)

    _acc_hist = []
    _moves = []
    _acc_thread = None

    def _acc_sim(self):
        """Aceleración simulada: ~1 g con golpes de vez en cuando (solo modo demo)."""
        next_hit = time.time() + 8
        while True:
            now = time.time()
            cur = round(random.uniform(0.98, 1.04), 2)
            amin, amax = cur - 0.02, cur + 0.03
            if now >= next_hit:
                amax = round(random.uniform(2.5, 11), 2)
                amin = round(random.uniform(0.1, 0.4), 2) if random.random() < 0.5 else 0.9
                rest = round(random.uniform(0.98, 1.05), 2)
                thr = DemoSource._imp["threshold_g"]
                t_eval = now + 2
                DemoSource._moves.append({"peak_g": amax, "rest_g": rest, "diff_g": round(amax - rest, 2),
                                          "time": int(t_eval), "alerted": amax - rest >= thr})
                next_hit = now + random.uniform(12, 25)
            DemoSource._acc_hist.append([round(now, 1), cur, round(amin, 2), round(amax, 2)])
            DemoSource._acc_hist = DemoSource._acc_hist[-900:]
            time.sleep(1)

    def accel_history(self, seconds):
        if DemoSource._acc_thread is None:
            DemoSource._acc_thread = threading.Thread(target=self._acc_sim, daemon=True)
            DemoSource._acc_thread.start()
        since = time.time() - seconds
        return {"samples": [x for x in DemoSource._acc_hist if x[0] >= since],
                "moves": [m for m in DemoSource._moves if m["time"] >= since and m["time"] <= time.time()],
                "threshold_g": DemoSource._imp["threshold_g"], "available": True}

    def impact_cmd(self, name, value):
        if name == "impacto" and value == "0":
            DemoSource._imp["active"] = False
        elif name == "umbral_g":
            DemoSource._imp["threshold_g"] = float(value)
        return {"ok": True, "impact": dict(DemoSource._imp)}

    def info(self):
        n = self._nodes[0]
        return {
            "ok": True, "port": "(demo)", "node_id": n["user"]["id"], "node_num": n["num"],
            "long_name": n["user"]["longName"], "short_name": n["user"]["shortName"],
            "hw_model": n["user"]["hwModel"], "device_id": "DEMO0000DEMO0000DEMO0000DEMO0000",
            "mac": "00:00:00:00:10:00", "public_key": None, "firmware": "demo",
            "firmware_edition": "VANILLA", "pio_env": "demo", "reboot_count": 0, "role": "CLIENT",
            "has_bluetooth": True, "has_wifi": False, "region": "US", "modem_preset": "LONG_FAST",
            "hop_limit": 3, "tx_power": 0, "tx_enabled": True, "channel": "(predeterminado)",
            "nodedb_count": len(self._nodes),
        }

    def ping(self, timeout=10):
        ms = random.randint(15, 80)
        time.sleep(ms / 1000)
        pid = random.randint(1, 2**32 - 1)
        return {"ok": True, "ms": ms, "firmware": "demo", "sent_id": pid, "request_id": pid,
                "id_match": True, "from": f"!{state['my_node']:08x}", "from_match": True}


@app.route("/")
def index():
    resp = send_from_directory("static", "index.html")
    resp.headers["Cache-Control"] = "no-cache"  # que el navegador siempre cargue la versión nueva
    return resp


@app.route("/api/nodes")
def api_nodes():
    nodes = source.nodes()
    nodes += last_seen.missing(nodes)  # aunque no haya conexión, mostrar la última posición guardada
    return jsonify({"status": state, "server_time": int(time.time()), "nodes": nodes})


@app.route("/api/info")
def api_info():
    return jsonify(source.info())


@app.route("/api/ping", methods=["POST"])
def api_ping():
    return jsonify(source.ping())


# ---------------------------------------------------------------------------
# Conexión: ver, buscar dispositivos y cambiar entre USB y Bluetooth
# ---------------------------------------------------------------------------
CONN_FILE = None          # data/connection.json: última conexión elegida
_switch_lock = threading.Lock()
MESHTASTIC_BLE_SERVICE = "6ba1b218-15a8-461f-9fa8-5dcae273eafd"
MESHCORE_BLE_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"   # Nordic UART, usado por MeshCore
FIRMWARE = "meshcore"     # "meshcore" (por defecto) o "meshtastic" (con --meshtastic)


def make_source(mode, target):
    """Crea la conexión al nodo según el firmware que tenga."""
    if FIRMWARE == "meshcore":
        from meshcore_source import MeshCoreSource
        track = lambda ns: last_seen.update(track_uptime(ns))  # noqa: E731
        src = MeshCoreSource(state, track, ble=target) if mode == "ble" else \
            MeshCoreSource(state, track, dev_path=target)
        src.on_impact = log_impact
        cal = load_calibration()
        if cal:
            src.calibration = cal_string(cal)
        return src
    return MeshSource(ble=target) if mode == "ble" else MeshSource(dev_path=target)


def save_connection(mode, target):
    import json
    import os
    os.makedirs(os.path.dirname(CONN_FILE), exist_ok=True)
    with open(CONN_FILE, "w") as f:
        json.dump({"mode": mode, "target": target}, f)


def load_connection():
    import json
    try:
        with open(CONN_FILE) as f:
            c = json.load(f)
        return c if c.get("mode") in ("ble", "serial") else None
    except (FileNotFoundError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Detector de caídas y golpes (acelerómetro, firmware MeshCore v1.18.0-rabanito)
# ---------------------------------------------------------------------------
def impact_log_path():
    import os
    name = "impactos_demo.jsonl" if state.get("mode") == "demo" else "impactos.jsonl"
    return os.path.join(os.path.dirname(CONN_FILE), name)


def log_impact(imp):
    """Guarda cada caída/golpe en data/impactos.jsonl, con la posición conocida del nodo."""
    import json
    import os
    pos = None
    me = state.get("my_node")
    if me is not None:
        nodes = [n for n in source.nodes() if n["num"] == me] if source else []
        p = nodes[0].get("last_pos") if nodes else None
        if p:
            pos = {"lat": p["lat"], "lon": p["lon"]}
    rec = {"recibido": int(time.time()), "tipo": imp.get("type"), "pico_g": imp.get("peak_g"),
           "reposo_g": imp.get("rest_g"), "dif_g": imp.get("diff_g"),
           "hora_nodo": imp.get("time"), "cuenta": imp.get("count"), "posicion": pos}
    with open(impact_log_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"*** {str(imp.get('type')).upper()} detectado: pico {imp.get('peak_g')} g, "
          f"diferencia {imp.get('diff_g')} g ***", flush=True)


@app.route("/api/impacto/reset", methods=["POST"])
def api_impact_reset():
    if not hasattr(source, "impact_cmd"):
        return jsonify({"ok": False, "error": "Solo disponible con MeshCore"}), 400
    return jsonify(source.impact_cmd("impacto", "0"))


@app.route("/api/impacto/umbral", methods=["POST"])
def api_impact_threshold():
    from flask import request
    if not hasattr(source, "impact_cmd"):
        return jsonify({"ok": False, "error": "Solo disponible con MeshCore"}), 400
    try:
        g = float((request.get_json(silent=True) or {}).get("g"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Umbral no válido"}), 400
    if not 1.0 <= g <= 55:
        return jsonify({"ok": False, "error": "La diferencia mínima debe estar entre 1 y 55 g"}), 400
    return jsonify(source.impact_cmd("umbral_g", f"{g:.2f}"))


@app.route("/api/acel")
def api_accel():
    """Historial de aceleración para la gráfica. ?segundos=60 (máx 900)."""
    from flask import request
    try:
        secs = max(10, min(900, int(request.args.get("segundos", 60))))
    except ValueError:
        secs = 60
    if not hasattr(source, "accel_history"):
        return jsonify({"samples": [], "moves": [], "threshold_g": None, "available": False})
    return jsonify(source.accel_history(secs))


# ---------------------------------------------------------------------------
# Calibración del acelerómetro (método de las 6 caras)
#   Para cada eje: offset = (lectura cara arriba + cara abajo) / 2
#                  ganancia = (lectura cara arriba - cara abajo) / 2   (debería ser 1 g)
#   El nodo corrige: a_cal = (a_crudo - offset) / ganancia
# ---------------------------------------------------------------------------
CARAS = ["x+", "x-", "y+", "y-", "z+", "z-"]
_cal_caras = {}   # medición (sin calibrar) de cada cara: "z+" -> [x, y, z]


def cal_path():
    import os
    return os.path.join(os.path.dirname(CONN_FILE), "calibracion.json")


def load_calibration():
    import json
    try:
        with open(cal_path(), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return None


def cal_string(cal):
    vals = [round(v * 1000) for v in cal["offset"]] + [round(v * 1000) for v in cal["ganancia"]]
    return "|".join(str(v) for v in vals)


@app.route("/api/calibracion")
def api_cal_status():
    return jsonify({"actual": load_calibration(), "caras": _cal_caras, "faltan": [c for c in CARAS if c not in _cal_caras]})


@app.route("/api/calibracion/medir", methods=["POST"])
def api_cal_measure():
    if not hasattr(source, "read_raw_axes") or not state.get("connected"):
        return jsonify({"ok": False, "error": "Conecta el nodo (MeshCore) para calibrar"}), 400
    v = source.read_raw_axes()
    if not v or None in v:
        return jsonify({"ok": False, "error": "El nodo no envió los ejes (¿firmware sin calibración?)"}), 400
    i = max(range(3), key=lambda k: abs(v[k]))          # el eje que apunta hacia arriba/abajo
    if abs(v[i]) < 0.5 or sum(abs(v[k]) for k in range(3) if k != i) > 0.6:
        return jsonify({"ok": False, "error": "El nodo no está apoyado en una cara (inclinado o moviéndose). "
                                              f"Ejes: x={v[0]:.2f} y={v[1]:.2f} z={v[2]:.2f}"}), 400
    cara = "xyz"[i] + ("+" if v[i] > 0 else "-")
    _cal_caras[cara] = [round(x, 4) for x in v]
    return jsonify({"ok": True, "cara": cara, "ejes": _cal_caras[cara], "caras": _cal_caras,
                    "faltan": [c for c in CARAS if c not in _cal_caras]})


@app.route("/api/calibracion/aplicar", methods=["POST"])
def api_cal_apply():
    import json
    faltan = [c for c in CARAS if c not in _cal_caras]
    if faltan:
        return jsonify({"ok": False, "error": "Faltan caras: " + ", ".join(faltan)}), 400
    off, gan = [], []
    for k, eje in enumerate("xyz"):
        up, down = _cal_caras[eje + "+"][k], _cal_caras[eje + "-"][k]
        off.append(round((up + down) / 2, 4))
        gan.append(round((up - down) / 2, 4))
    if any(not 0.5 <= g <= 2.0 for g in gan) or any(abs(o) > 5 for o in off):
        return jsonify({"ok": False, "error": f"Resultado fuera de rango (offset {off}, ganancia {gan}); repite las caras"}), 400
    cal = {"offset": off, "ganancia": gan, "fecha": int(time.time()), "caras": dict(_cal_caras)}
    with open(cal_path(), "w", encoding="utf-8") as f:
        json.dump(cal, f, indent=2)
    source.calibration = cal_string(cal)
    r = source.impact_cmd("acc_cal", source.calibration)
    if not r.get("ok"):
        return jsonify({"ok": False, "error": "Se guardó, pero el nodo no la aceptó: " + r.get("error", "")}), 400
    return jsonify({"ok": True, "calibracion": cal})


@app.route("/api/calibracion/borrar", methods=["POST"])
def api_cal_reset():
    import os
    _cal_caras.clear()
    if os.path.exists(cal_path()):
        os.remove(cal_path())
    if hasattr(source, "impact_cmd") and state.get("connected"):
        source.calibration = None
        source.impact_cmd("acc_cal", "0|0|0|1000|1000|1000")
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Ruta desde esta computadora hasta el nodo
#   Calles: OSRM de routing.openstreetmap.de (servicio gratuito de OpenStreetMap).
#   Si no responde, o con modo "recta": línea recta con la distancia geodésica.
# ---------------------------------------------------------------------------
def haversine_m(lat1, lon1, lat2, lon2):
    import math
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


@app.route("/api/ruta")
def api_route():
    import json
    import urllib.request
    from flask import request
    try:
        lat1, lon1 = (float(x) for x in request.args["desde"].split(","))
        lat2, lon2 = (float(x) for x in request.args["hasta"].split(","))
    except (KeyError, ValueError):
        return jsonify({"ok": False, "error": "Faltan coordenadas (desde=lat,lon&hasta=lat,lon)"}), 400
    if not (-90 <= lat1 <= 90 and -90 <= lat2 <= 90 and -180 <= lon1 <= 180 and -180 <= lon2 <= 180):
        return jsonify({"ok": False, "error": "Coordenadas fuera de rango"}), 400
    modo = request.args.get("modo", "pie")
    recta = {"ok": True, "modo": "recta", "coords": [[lat1, lon1], [lat2, lon2]],
             "distancia_m": round(haversine_m(lat1, lon1, lat2, lon2)), "duracion_s": None}
    if modo == "recta":
        return jsonify(recta)
    perfil = "routed-car" if modo == "auto" else "routed-foot"
    url = (f"https://routing.openstreetmap.de/{perfil}/route/v1/driving/"
           f"{lon1:.6f},{lat1:.6f};{lon2:.6f},{lat2:.6f}?overview=full&geometries=geojson")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "rastreador-meshcore/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)
        rt = data["routes"][0]
        coords = [[c[1], c[0]] for c in rt["geometry"]["coordinates"]]
        return jsonify({"ok": True, "modo": modo, "coords": coords,
                        "distancia_m": round(rt["distance"]), "duracion_s": round(rt["duration"])})
    except Exception as e:  # noqa: BLE001
        recta["aviso"] = f"No se pudo calcular la ruta por calles ({type(e).__name__}); se muestra línea recta."
        return jsonify(recta)


# ---------------------------------------------------------------------------
# Ubicación de ESTA computadora: "recordar lugares" por Wi-Fi (todo local)
#   La computadora no tiene GPS. Cuando se fija la ubicación con un clic en el mapa,
#   se guarda junto con la "huella" de las redes Wi-Fi que se ven en ese lugar
#   (BSSID -> intensidad). Después se compara la huella actual con las guardadas.
# ---------------------------------------------------------------------------
_wifi_cache = {"t": 0, "redes": {}}


def wifi_scan(max_age=20):
    """Redes Wi-Fi visibles: {bssid: señal 0-100}. Usa nmcli (NetworkManager), sin sudo."""
    import subprocess
    if time.time() - _wifi_cache["t"] < max_age:
        return _wifi_cache["redes"]
    try:
        out = subprocess.run(["nmcli", "-t", "-f", "BSSID,SIGNAL", "dev", "wifi", "list", "--rescan", "auto"],
                             capture_output=True, text=True, timeout=20).stdout
    except Exception:  # noqa: BLE001
        return {}
    redes = {}
    for line in out.splitlines():
        line = line.replace("\\:", "\x00")          # nmcli escapa los ':' de la MAC
        if ":" not in line:
            continue
        bssid, sig = line.rsplit(":", 1)
        try:
            redes[bssid.replace("\x00", ":").lower()] = int(sig)
        except ValueError:
            pass
    _wifi_cache.update(t=time.time(), redes=redes)
    return redes


def similitud_wifi(a, b):
    """Jaccard ponderado por intensidad: 1 = misma huella, 0 = ninguna red en común."""
    claves = set(a) | set(b)
    if not claves:
        return 0.0, 0
    num = sum(min(a.get(k, 0), b.get(k, 0)) for k in claves)
    den = sum(max(a.get(k, 0), b.get(k, 0)) for k in claves)
    return (num / den if den else 0.0), len(set(a) & set(b))


def lugares_path():
    import os
    name = "lugares_wifi_demo.json" if state.get("mode") == "demo" else "lugares_wifi.json"
    return os.path.join(os.path.dirname(CONN_FILE), name)


def load_lugares():
    import json
    try:
        with open(lugares_path(), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return []


def save_lugares(lugares):
    import json
    with open(lugares_path(), "w", encoding="utf-8") as f:
        json.dump(lugares, f, indent=1)


SIMILITUD_MIN = 0.25    # coincidencia mínima para reconocer un lugar
COMUNES_MIN = 3         # y al menos 3 redes en común


@app.route("/api/mi_ubicacion")
def api_my_location():
    redes = wifi_scan()
    lugares = load_lugares()
    if not redes:
        return jsonify({"ok": False, "motivo": "sin_wifi", "redes": 0, "lugares": len(lugares)})
    mejor, mejor_s, mejor_c = None, 0.0, 0
    for i, lg in enumerate(lugares):
        sim, comunes = similitud_wifi(redes, lg["huella"])
        if sim > mejor_s:
            mejor, mejor_s, mejor_c = i, sim, comunes
    if mejor is not None and mejor_s >= SIMILITUD_MIN and mejor_c >= COMUNES_MIN:
        lg = lugares[mejor]
        return jsonify({"ok": True, "lat": lg["lat"], "lon": lg["lon"], "lugar": mejor + 1,
                        "similitud": round(mejor_s, 2), "comunes": mejor_c, "redes": len(redes),
                        "lugares": len(lugares)})
    return jsonify({"ok": False, "motivo": "lugar_desconocido" if lugares else "sin_lugares",
                    "redes": len(redes), "lugares": len(lugares), "similitud": round(mejor_s, 2)})


@app.route("/api/mi_ubicacion/fijar", methods=["POST"])
def api_my_location_set():
    """Guarda (o actualiza) un lugar: la posición dada + la huella Wi-Fi actual."""
    from flask import request
    body = request.get_json(silent=True) or {}
    try:
        lat, lon = float(body["lat"]), float(body["lon"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"ok": False, "error": "Faltan lat/lon"}), 400
    redes = wifi_scan(max_age=0)
    if not redes:
        return jsonify({"ok": False, "error": "No se ven redes Wi-Fi; no se puede recordar el lugar"}), 400
    lugares = load_lugares()
    # Si ya hay un lugar a menos de 100 m, o con la misma huella, se actualiza en vez de duplicarlo
    for lg in lugares:
        if haversine_m(lat, lon, lg["lat"], lg["lon"]) < 100 or similitud_wifi(redes, lg["huella"])[0] >= 0.5:
            lg.update(lat=lat, lon=lon, huella=redes, guardado=int(time.time()))
            save_lugares(lugares)
            return jsonify({"ok": True, "lugar": lugares.index(lg) + 1, "nuevo": False, "redes": len(redes)})
    lugares.append({"lat": lat, "lon": lon, "huella": redes, "guardado": int(time.time())})
    save_lugares(lugares)
    return jsonify({"ok": True, "lugar": len(lugares), "nuevo": True, "redes": len(redes)})


@app.route("/api/mi_ubicacion/olvidar", methods=["POST"])
def api_my_location_forget():
    import os
    if os.path.exists(lugares_path()):
        os.remove(lugares_path())
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Elevación del terreno (hoja "Terreno")
#   Mosaicos abiertos AWS Terrain Tiles (formato "terrarium", sin clave):
#     altura (m) = R * 256 + G + B / 256 - 32768
#   Zoom 14: ~8.6 m por píxel en Monterrey. Los mosaicos se guardan en memoria.
# ---------------------------------------------------------------------------
TERRAIN_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
TERRAIN_Z = 14
_tiles = {}                     # (z, x, y) -> imagen RGB de Pillow
_tiles_lock = threading.Lock()


def _terrain_tile(x, y, z=TERRAIN_Z):
    import io
    import urllib.request
    from PIL import Image
    with _tiles_lock:
        if (z, x, y) in _tiles:
            return _tiles[(z, x, y)]
    req = urllib.request.Request(TERRAIN_URL.format(z=z, x=x, y=y),
                                 headers={"User-Agent": "rastreador-meshcore/1.0"})
    for intento in range(3):           # S3 a veces tarda; reintentar
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                img = Image.open(io.BytesIO(r.read())).convert("RGB")
            break
        except OSError:
            if intento == 2:
                raise
    img.load()
    with _tiles_lock:
        if len(_tiles) > 200:          # límite de memoria (~50 MB)
            _tiles.pop(next(iter(_tiles)))
        _tiles[(z, x, y)] = img
    return img


def _px_elev(px, py, z=TERRAIN_Z):
    """Altura en el píxel global (px, py) del zoom z."""
    tx, ty = int(px // 256), int(py // 256)
    r, g, b = _terrain_tile(tx, ty, z).getpixel((int(px) % 256, int(py) % 256))
    return r * 256 + g + b / 256 - 32768


def _merc_px(lat, lon, z):
    import math
    n = 2 ** z * 256
    lr = math.radians(lat)
    return ((lon + 180) / 360 * n - 0.5,
            (1 - math.log(math.tan(lr) + 1 / math.cos(lr)) / math.pi) / 2 * n - 0.5)


def elevation_at(lat, lon, z=TERRAIN_Z):
    """Altura sobre el nivel del mar (m) con interpolación bilineal entre 4 píxeles."""
    import math
    fx, fy = _merc_px(lat, lon, z)
    x0, y0 = math.floor(fx), math.floor(fy)
    dx, dy = fx - x0, fy - y0
    e00, e10 = _px_elev(x0, y0, z), _px_elev(x0 + 1, y0, z)
    e01, e11 = _px_elev(x0, y0 + 1, z), _px_elev(x0 + 1, y0 + 1, z)
    return (e00 * (1 - dx) * (1 - dy) + e10 * dx * (1 - dy) + e01 * (1 - dx) * dy + e11 * dx * dy)


@app.route("/api/terreno/malla")
def api_terrain_mesh():
    """Malla de alturas n x n para la vista de alambre.
    ?caja=lat1,lon1,lat2,lon2&n=80. Elige el zoom más alto con <= 16 mosaicos."""
    from concurrent.futures import ThreadPoolExecutor
    from flask import request
    try:
        la1, lo1, la2, lo2 = (float(v) for v in request.args.get("caja", "").split(","))
        n = max(10, min(int(request.args.get("n", 80)), 150))
    except ValueError:
        return jsonify({"ok": False, "error": "caja=lat1,lon1,lat2,lon2"}), 400
    s, w, nn, e = min(la1, la2), min(lo1, lo2), max(la1, la2), max(lo1, lo2)
    z = TERRAIN_Z
    while z > 6:
        x1, y1 = _merc_px(nn, w, z)
        x2, y2 = _merc_px(s, e, z)
        tiles = [(tx, ty) for tx in range(int(x1 // 256), int(x2 // 256) + 2)
                 for ty in range(int(y1 // 256), int(y2 // 256) + 2)]
        if len(tiles) <= 16:
            break
        z -= 1
    try:
        with ThreadPoolExecutor(8) as ex:          # bajar los mosaicos en paralelo
            list(ex.map(lambda t: _terrain_tile(t[0], t[1], z), tiles))
        alt = [round(elevation_at(s + (nn - s) * i / (n - 1), w + (e - w) * j / (n - 1), z), 1)
               for i in range(n) for j in range(n)]
    except Exception as ex_:  # noqa: BLE001
        return jsonify({"ok": False, "error": f"No se pudo leer el terreno ({type(ex_).__name__}); ¿hay internet?"}), 502
    return jsonify({"ok": True, "n": n, "caja": [s, w, nn, e], "zoom": z, "alturas": alt})


# ---------------------------------------------------------------------------
# Cuerpos de agua (OpenStreetMap vía Overpass): ríos, arroyos, canales, lagos, presas.
#   Se envía a overpass-api.de solo el recuadro del terreno (no la posición exacta).
# ---------------------------------------------------------------------------
OVERPASS_URLS = ["https://overpass-api.de/api/interpreter",          # principal y espejos públicos
                 "https://overpass.kumi.systems/api/interpreter",
                 "https://overpass.private.coffee/api/interpreter"]
_agua_cache = {}
AGUA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "agua")   # caché en disco
_CLASE_AGUA = {"river": "río", "stream": "arroyo", "canal": "canal", "drain": "dren", "ditch": "zanja",
               "lake": "lago", "reservoir": "presa", "pond": "estanque", "lagoon": "laguna", "oxbow": "laguna",
               "basin": "estanque", "wastewater": "laguna de tratamiento"}


def _clase_agua(tags):
    if tags.get("waterway"):
        return _CLASE_AGUA.get(tags["waterway"], "arroyo")
    if tags.get("landuse") == "reservoir":
        return "presa"
    return _CLASE_AGUA.get(tags.get("water", ""), "cuerpo de agua")


def _cerrado(g):
    return len(g) > 3 and g[0] == g[-1]


@app.route("/api/terreno/agua")
def api_terrain_water():
    """?caja=lat1,lon1,lat2,lon2 -> {"ok", "agua": [{tipo: area|linea, clase, nombre, coords: [[lat, lon], ...]}]}"""
    import json
    import urllib.parse
    import urllib.request
    from flask import request
    try:
        la1, lo1, la2, lo2 = (float(v) for v in request.args.get("caja", "").split(","))
    except ValueError:
        return jsonify({"ok": False, "error": "caja=lat1,lon1,lat2,lon2"}), 400
    s, w, n, e = min(la1, la2), min(lo1, lo2), max(la1, la2), max(lo1, lo2)
    if (n - s) * (e - w) > 1.0:
        return jsonify({"ok": False, "error": "Área demasiado grande"}), 400
    clave = tuple(round(v, 3) for v in (s, w, n, e))
    if clave in _agua_cache:
        return jsonify(_agua_cache[clave])
    archivo = os.path.join(AGUA_DIR, "_".join(f"{v:.3f}" for v in clave) + ".json")
    try:
        with open(archivo, encoding="utf-8") as f:
            _agua_cache[clave] = json.load(f)
        return jsonify(_agua_cache[clave])
    except (OSError, ValueError):
        pass
    bb = f"{s},{w},{n},{e}"
    q = (f'[out:json][timeout:25];('
         f'way["natural"="water"]({bb});relation["natural"="water"]({bb});'
         f'way["waterway"~"^(river|stream|canal|drain|ditch)$"]({bb});'
         f'way["landuse"="reservoir"]({bb});relation["landuse"="reservoir"]({bb}););out tags geom;')
    datos, error = None, None
    for url in OVERPASS_URLS:              # si uno está saturado, probar el siguiente
        try:
            req = urllib.request.Request(url, data=urllib.parse.urlencode({"data": q}).encode(),
                                         headers={"User-Agent": "rastreador-meshcore/1.0"})
            with urllib.request.urlopen(req, timeout=45) as r:
                datos = json.load(r)
            break
        except Exception as ex:  # noqa: BLE001
            error = type(ex).__name__
    if datos is None:
        return jsonify({"ok": False, "error": f"No se pudo consultar OpenStreetMap ({error}); se reintentará"}), 502
    agua = []
    for el in datos.get("elements", []):
        tags = el.get("tags", {})
        clase, nombre = _clase_agua(tags), tags.get("name")
        if el["type"] == "way":
            g = [[round(p["lat"], 6), round(p["lon"], 6)] for p in el.get("geometry", [])]
            if len(g) < 2:
                continue
            area = not tags.get("waterway") and _cerrado(g)
            agua.append({"tipo": "area" if area else "linea", "clase": clase, "nombre": nombre, "coords": g})
        else:   # relación (multipolígono): cada miembro "outer" como área, o como línea si no cierra
            for m in el.get("members", []):
                if m.get("role") not in ("outer", "") or not m.get("geometry"):
                    continue
                g = [[round(p["lat"], 6), round(p["lon"], 6)] for p in m["geometry"]]
                agua.append({"tipo": "area" if _cerrado(g) else "linea", "clase": clase, "nombre": nombre, "coords": g})
    res = {"ok": True, "agua": agua, "fuente": "© OpenStreetMap (Overpass)"}
    if len(_agua_cache) > 50:
        _agua_cache.pop(next(iter(_agua_cache)))
    _agua_cache[clave] = res
    try:
        os.makedirs(AGUA_DIR, exist_ok=True)
        with open(archivo, "w", encoding="utf-8") as f:
            json.dump(res, f)
    except OSError:
        pass
    return jsonify(res)


@app.route("/api/elevacion", methods=["POST"])
def api_elevation():
    """Body: {"puntos": [[lat, lon], ...]} (máx. 500). Devuelve la altura de cada punto en metros."""
    from flask import request
    pts = (request.get_json(silent=True) or {}).get("puntos") or []
    if not isinstance(pts, list) or not pts or len(pts) > 500:
        return jsonify({"ok": False, "error": "Envía entre 1 y 500 puntos [lat, lon]"}), 400
    try:
        elev = [round(elevation_at(float(p[0]), float(p[1])), 1) for p in pts]
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "error": f"No se pudo leer el terreno ({type(e).__name__}); ¿hay internet?"}), 502
    return jsonify({"ok": True, "elevaciones": elev,
                    "fuente": f"AWS Terrain Tiles (terrarium), zoom {TERRAIN_Z}"})


@app.route("/api/impacto/historial")
def api_impact_history():
    import json
    import os
    try:
        with open(impact_log_path(), encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
    except FileNotFoundError:
        rows = []
    return jsonify({"eventos": rows[-50:][::-1]})


@app.route("/api/connection")
def api_connection():
    return jsonify({"mode": getattr(source, "mode", state["mode"]),
                    "target": getattr(source, "target", None),
                    "switching": _switch_lock.locked()})


@app.route("/api/ports")
def api_ports():
    """Puertos USB/serial que parecen ser un nodo."""
    import glob
    ports = sorted(set(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")))
    result = []
    for p in ports:
        desc = ""
        try:
            from serial.tools import list_ports
            for lp in list_ports.comports():
                if lp.device == p:
                    desc = lp.product or lp.description or ""
        except Exception:  # noqa: BLE001
            pass
        result.append({"port": p, "description": desc})
    return jsonify({"ports": result})


@app.route("/api/ble/scan")
def api_ble_scan():
    """Busca nodos Meshtastic por Bluetooth (~8 s)."""
    import asyncio
    from bleak import BleakScanner

    async def scan():
        service = MESHCORE_BLE_SERVICE if FIRMWARE == "meshcore" else MESHTASTIC_BLE_SERVICE
        found = await BleakScanner.discover(timeout=8, return_adv=True, service_uuids=[service])
        return [{"address": d.address, "name": a.local_name or d.name or "?", "rssi": a.rssi}
                for d, a in found.values()]

    try:
        devices = sorted(asyncio.run(scan()), key=lambda d: -(d["rssi"] or -999))
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "error": f"No se pudo buscar por Bluetooth: {e}"})
    # El nodo conectado ahora por Bluetooth no se anuncia; agregarlo para que se vea
    if getattr(source, "mode", None) == "ble" and state["connected"] and \
            not any(d["address"] == source.target for d in devices):
        devices.insert(0, {"address": source.target, "name": "(conectado ahora)", "rssi": None})
    return jsonify({"ok": True, "devices": devices})


@app.route("/api/connect", methods=["POST"])
def api_connect():
    """Cambia la conexión sin reiniciar el servidor. Body: {"mode": "ble"|"serial", "target": "..."}"""
    import re
    from flask import request
    global source
    body = request.get_json(silent=True) or {}
    mode, target = body.get("mode"), (body.get("target") or "").strip() or None
    if mode == "ble":
        if not target or not re.fullmatch(r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}|[\w\-]{1,40}", target):
            return jsonify({"ok": False, "error": "Dirección Bluetooth no válida"}), 400
    elif mode == "serial":
        if target and not re.fullmatch(r"/dev/tty[\w]+", target):
            return jsonify({"ok": False, "error": "Puerto no válido"}), 400
    else:
        return jsonify({"ok": False, "error": "Modo no válido (usa 'ble' o 'serial')"}), 400
    if getattr(source, "mode", None) == "demo":
        return jsonify({"ok": False, "error": "En modo demo no se puede cambiar la conexión"}), 400
    if not _switch_lock.acquire(blocking=False):
        return jsonify({"ok": False, "error": "Ya se está cambiando la conexión"}), 409
    try:
        old = source
        state.update({"connected": False, "error": "Cambiando de conexión...", "mode": mode})
        old.stop()  # libera el puerto USB o el enlace Bluetooth
        time.sleep(1)
        source = make_source(mode, target)
        save_connection(mode, target)
        print(f"Conexión cambiada a {mode} {target or '(auto)'}", flush=True)
        return jsonify({"ok": True, "mode": mode, "target": target})
    finally:
        _switch_lock.release()


def main():
    global source
    parser = argparse.ArgumentParser(description="Rastreador de nodos Meshtastic")
    parser.add_argument("--port", help="Puerto serial, ej. /dev/ttyUSB0 (por defecto: autodetectar)")
    parser.add_argument("--ble", metavar="DIRECCION",
                        help="Conectar por Bluetooth, ej. AA:BB:CC:DD:EE:FF o el nombre MeshCore-NOMBRE")
    parser.add_argument("--demo", action="store_true", help="Usar nodos simulados")
    parser.add_argument("--meshtastic", action="store_true",
                        help="El nodo tiene firmware Meshtastic (por defecto: MeshCore)")
    parser.add_argument("--http-port", type=int, default=5000)
    args = parser.parse_args()

    global last_seen
    import os
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    last_seen = LastSeen(os.path.join(data_dir, "last_seen_demo.json" if args.demo else "last_seen.json"))

    global CONN_FILE
    CONN_FILE = os.path.join(data_dir, "connection.json")
    # Sin --port/--ble/--demo: usar la última conexión elegida en la interfaz
    if not (args.demo or args.ble or args.port):
        saved = load_connection()
        if saved:
            print(f"Usando la última conexión guardada: {saved['mode']} {saved.get('target') or ''}", flush=True)
            if saved["mode"] == "ble":
                args.ble = saved["target"]
            else:
                args.port = saved.get("target")

    if args.demo:
        state["mode"] = "demo"
        source = DemoSource()
    else:
        global FIRMWARE
        FIRMWARE = "meshtastic" if args.meshtastic else "meshcore"
        state["firmware"] = FIRMWARE
        state["mode"] = "ble" if args.ble else "serial"
        source = make_source(state["mode"], args.ble or args.port)
        print(f"Firmware: {FIRMWARE}", flush=True)

    print(f"Abre http://localhost:{args.http_port}")
    app.run(host="127.0.0.1", port=args.http_port, debug=False)


if __name__ == "__main__":
    main()
