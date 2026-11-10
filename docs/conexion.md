# Conexión con el nodo (USB y Bluetooth en Linux)

Probado en Debian 13 (BlueZ 5.82) con un Seeed SenseCAP T1000-E.

## Arrancar

```bash
.venv/bin/python server.py --ble AA:BB:CC:DD:EE:FF   # Bluetooth (firmware ...-rabanito-ble)
.venv/bin/python server.py --port /dev/ttyACM0       # USB (firmware ...-rabanito)
.venv/bin/python server.py                            # la última conexión elegida en la interfaz
.venv/bin/python server.py --demo                     # nodos simulados, sin hardware
.venv/bin/python server.py --meshtastic --port ...    # nodo con firmware Meshtastic (etapa anterior)
```

Abrir http://localhost:5000. Desde la interfaz se puede cambiar de USB a Bluetooth sin reiniciar
(cinta **Conexión**). La última conexión se guarda en `data/connection.json`.

## USB

- El T1000-E aparece como `/dev/ttyACM0`. El usuario debe estar en el grupo `dialout`:
  `sudo usermod -aG dialout $USER` y volver a iniciar sesión.
- Solo un programa puede usar el puerto a la vez.
- Si la conexión se corta justo al conectar el nodo, puede ser ModemManager probándolo como módem:
  ```bash
  echo 'ATTRS{idVendor}=="239a", ENV{ID_MM_DEVICE_IGNORE}="1"' | sudo tee /etc/udev/rules.d/99-meshtastic-mm.rules
  sudo udevadm control --reload-rules
  ```

## Bluetooth

- El nodo aparece como **`MeshCore-RABANITO`**. Buscarlo desde la cinta **Conexión -> Bluetooth -> Buscar nodos**.
- **USB o Bluetooth, no los dos**: con el firmware Bluetooth el USB solo carga; con el firmware USB no hay Bluetooth.
- El nodo acepta **una sola conexión** Bluetooth: cerrar la app MeshCore del celular antes.
- No hace falta emparejar en la PC. Si quedó un emparejamiento viejo: `bluetoothctl remove AA:BB:CC:DD:EE:FF`.

### Problemas encontrados y cómo se resolvieron

| Síntoma | Causa | Solución |
|---|---|---|
| La conexión se quedaba "colgada" | `bleak` 3.x con meshtastic en Linux | Fijar `bleak>=1.0,<2` (en `requirements.txt`) |
| Se conecta pero no responde a ninguna lectura | El nodo exige emparejar **con PIN** y BlueZ empareja sin pedirlo | Firmware con `BLE_NO_PIN` (canal de datos sin PIN) |
| No se puede reconectar tras cerrar el servidor | BlueZ deja el enlace "medio abierto" y el nodo deja de anunciarse | El servidor corre `bluetoothctl disconnect` antes y después de conectar |
| Lecturas "In Progress" o timeouts | Lectura pendiente atascada en BlueZ | `sudo systemctl restart bluetooth` y reiniciar el nodo |
| (pruebas) | EATT en BlueZ 5.82 | En `/etc/bluetooth/main.conf`, `[GATT] Channels = 1` (se dejó así; puede no ser indispensable) |

**Seguridad:** sin PIN, cualquiera a ~10 m con la app MeshCore puede conectarse al nodo y ver sus datos.
La actualización de firmware por Bluetooth sí sigue protegida con PIN (123456).

## Incidencia: reinicios en bucle

Dos veces el nodo quedó reiniciándose cada ~101 s (con firmware Meshtastic), incluso sin nada conectado.
Se resolvió **apagándolo por completo**: desconectar el USB, mantener el botón ~10 s hasta que se apague,
encenderlo y volver a conectar.
