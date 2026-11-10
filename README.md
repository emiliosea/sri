# sri
Interfaz, Sistema de Respuesta Inmediata, Huasteca, usando tecnologìa meshcore y LoRa

Interfaz web para rastrear y vigilar un nodo LoRa (**RABANITO**, Seeed SenseCAP T1000-E) con firmware
**MeshCore**: mapa con la última ubicación GPS, detector de caídas y golpes con el acelerómetro, gráfica en vivo,
ruta desde esta computadora hasta el nodo y conexión por USB o Bluetooth.

## Inicio rápido

    uv venv .venv && uv pip install -p .venv -r requirements.txt
    .venv/bin/python server.py --ble AA:BB:CC:DD:EE:FF     # o: --port /dev/ttyACM0 (USB)

Abrir http://localhost:5000. Sin opciones, `server.py` usa la última conexión elegida en la interfaz.
El firmware del nodo (MeshCore + detector de caídas) está en `firmware/` (ver más abajo).

---

## Bitácora del proyecto


Interfaz web que muestra los nodos de la malla en un mapa, con su telemetría.

## Instalar
    uv venv .venv && uv pip install -p .venv -r requirements.txt

## Correr
    .venv/bin/python server.py            # nodo conectado por USB (autodetecta)
    .venv/bin/python server.py --port /dev/ttyACM0
    .venv/bin/python server.py --demo     # nodos simulados, sin hardware

Abrir http://localhost:5000

En Linux, si no detecta el puerto: `sudo usermod -aG dialout $USER` y volver a iniciar sesión.

Versiones exactas probadas: `requirements.lock` (`uv pip install -p .venv -r requirements.lock`).
Leaflet está descargado en `static/vendor/`, así que la página no depende de un CDN.
Lo único que necesita internet son los mosaicos del mapa (OpenStreetMap).

## Checklist para conectar el nodo
1. Haber cerrado sesión y vuelto a entrar después de `usermod -aG dialout` (comprobar con `groups`: debe salir `dialout`).
2. Conectar el nodo con un cable USB **de datos**.
3. `ls /dev/ttyUSB* /dev/ttyACM*` debe mostrar un puerto. Si no: `sudo dmesg | tail` para ver qué pasó.
4. Probar la conexión: `.venv/bin/meshtastic --info`
5. Correr la interfaz: `.venv/bin/python server.py`

## Notas del T1000-E (SenseCAP)
- Aparece como `/dev/ttyACM0`. GPS activado con `meshtastic --set position.gps_mode ENABLED`.
- El primer fix de GPS puede tardar varios minutos y necesita cielo abierto (cerca de una ventana o afuera).
- Si aún no reinicias sesión tras agregar `dialout`: `sg dialout -c ".venv/bin/python server.py --port /dev/ttyACM0"`
- Solo un programa puede usar el puerto a la vez: cierra el servidor antes de usar el comando `meshtastic`.
- Si la conexión se corta justo al conectar el nodo, puede ser ModemManager probándolo como módem. Para que lo ignore:
  `echo 'ATTRS{idVendor}=="239a", ENV{ID_MM_DEVICE_IGNORE}="1"' | sudo tee /etc/udev/rules.d/99-meshtastic-mm.rules && sudo udevadm control --reload-rules`

## Conexión por Bluetooth (sin cable)
    .venv/bin/python server.py --ble AA:BB:CC:DD:EE:FF

Lo que hizo falta para que funcione en Linux (Debian 13, BlueZ 5.82):
1. **Bluetooth del nodo en modo sin PIN**: `meshtastic --set bluetooth.mode NO_PIN` (por USB).
   Con PIN fijo el nodo se empareja sin pedir el PIN y luego no responde a ninguna lectura.
   Para volver al PIN: `meshtastic --set bluetooth.mode FIXED_PIN`.
   Ojo: sin PIN, cualquiera a ~10 m puede conectarse por Bluetooth al nodo.
2. **bleak 1.x** (ya fijado en requirements.txt). bleak 3.x se cuelga al conectar.
3. En `/etc/bluetooth/main.conf`, sección `[GATT]`: `Channels = 1` (desactiva EATT). Puede que no sea
   indispensable, pero se dejó así durante las pruebas.
4. No hace falta emparejar en modo NO_PIN. Si hubiera un emparejamiento viejo: `bluetoothctl remove AA:BB:CC:DD:EE:FF`.

Notas:
- USB **o** Bluetooth, no los dos a la vez: mientras un programa usa el puerto USB, el nodo deja de anunciarse por Bluetooth.
- El nodo acepta una sola conexión Bluetooth: cierra la app Meshtastic del celular antes.
- Si se queda en "Conectando…" o da timeouts, reinicia el Bluetooth de la PC (`sudo systemctl restart bluetooth`)
  y luego el nodo: BlueZ puede quedarse con una lectura "pendiente" que bloquea las siguientes.
- La primera conexión tarda ~30 s.

## Última posición conocida ("visto por última vez")
- El servidor guarda la última posición GPS de cada nodo en `data/last_seen.json` (en modo demo: `data/last_seen_demo.json`).
- Si el GPS pierde señal, el nodo se reinicia o se reinicia el servidor, el mapa muestra esa última posición
  con un marcador gris punteado y "Visto por última vez hace X (fecha y hora)".
- Cuando el GPS vuelve a tener señal, el marcador vuelve a su color normal y el archivo se actualiza.
- Para borrar el historial: borrar `data/last_seen.json`.

## Cambiar entre USB y Bluetooth desde la interfaz
- Panel **"Conexión"** (debajo del título): pestañas **USB** y **Bluetooth**.
  - USB: "Buscar puertos" -> elegir puerto (o Autodetectar) -> "Conectar por USB".
  - Bluetooth: "Buscar nodos Bluetooth" (~8 s) -> clic en el nodo -> "Conectar por Bluetooth".
- El cambio se hace sin reiniciar el servidor. La última conexión se guarda en `data/connection.json`
  y se usa al arrancar sin argumentos:

      .venv/bin/python server.py

- `--port`, `--ble` o `--demo` en la línea de comandos tienen prioridad sobre la conexión guardada.

## MeshCore (firmware actual del nodo)
Desde el 9 nov 2026 RABANITO tiene **MeshCore v1.18.0 (companion USB)** en lugar de Meshtastic.
- El servidor usa MeshCore por defecto (librería `meshcore`). Para un nodo con Meshtastic: `server.py --meshtastic`.
- Datos que da MeshCore: GPS (custom var `gps`), voltaje/batería, temperatura, luz (lux), uptime y contactos.
- Al conectar, el servidor pone la hora de la PC en el nodo (MeshCore la necesita para los mensajes).
- Ajustes aplicados: `gps=1`, nombre RABANITO, compartir ubicación en anuncios (`adv_loc_policy=1`).
- La identidad del nodo cambió (llave pública `xxxxxxxx...`). La última posición guardada de la etapa
  Meshtastic se pasó a la nueva identidad; copia original en `data/last_seen.meshtastic-backup.json`.
- Radio: 915.0 MHz, BW 62.5 kHz, SF 8, CR 4/5 (cambiado de 869.618 MHz europeo el 9 nov 2026).
- Probar el protocolo a mano: `.venv/bin/meshcli -s /dev/ttyACM0 infos`

## Detector de caídas y golpes (acelerómetro)
El MeshCore oficial no usa el acelerómetro del T1000-E (QMA6100P). Por eso hay un firmware modificado:
**MeshCore v1.18.0-rabanito** (código en `firmware/MeshCore`, cambios en `firmware/rabanito-acelerometro.patch`).

En el nodo (50 lecturas por segundo, rango ±32 g desde el 10 nov 2026; antes ±16 g):
- **Golpe**: la aceleración supera el umbral (2.5 g por defecto, se cambia desde la interfaz).
- **Caída**: caída libre (< 0.35 g por >= 60 ms) seguida de un golpe en menos de 1 s.
- La alarma queda "enganchada" hasta que la interfaz la borra, así no se pierde aunque dure milisegundos.
- Variables MeshCore nuevas: `impacto` (1/0), `impacto_info` (tipo|pico_g*100|epoch|cuenta),
  `umbral_g`, `acel` (aceleración actual; ~1.00 g en reposo).

En la interfaz: foco rojo junto a "este nodo" y sección "Detector de caídas" (botón Borrar alarma,
umbral y aceleración en vivo). Cada evento se guarda en `data/impactos.jsonl` con la posición del nodo.

### Compilar el firmware
    cd firmware/MeshCore
    ../.venv-pio/bin/pio run -e t1000e_companion_radio_usb
    ../.venv-pio/bin/python bin/uf2conv/uf2conv.py -f 0xADA52840 -c \
        .pio/build/t1000e_companion_radio_usb/firmware.hex -o ../RABANITO-meshcore-v1.18.0-rabanito.uf2

(El objetivo `-t create_uf2` de MeshCore falla porque la carpeta "SRI TESIS" tiene un espacio;
por eso la conversión a .uf2 se hace a mano.) No correr dos compilaciones a la vez.

Resultado: `firmware/RABANITO-meshcore-v1.18.0-rabanito.uf2`

### Flashear
1. Cierra la interfaz (libera el puerto USB).
2. Modo de actualización: mantén presionado el botón del T1000-E mientras conectas el cable USB
   (LED verde fijo). Aparece una unidad de disco "T1000-E".
3. Copia `RABANITO-meshcore-v1.18.0-rabanito.uf2` a esa unidad. El nodo se reinicia solo.
4. Abre la interfaz: "Información del dispositivo" debe decir versión `v1.18.0-rabanito` y la sección
   "Detector de caídas" debe mostrar la aceleración (~1.00 g en reposo).

### Versión Bluetooth (firmware actual de RABANITO, 9 nov 2026)
`firmware/RABANITO-meshcore-v1.18.0-rabanito-ble.uf2` = MeshCore companion **BLE** + detector de caídas.
- Compilar: `../.venv-pio/bin/pio run -e t1000e_companion_radio_ble` (desde `firmware/MeshCore`).
- Flashear con el nodo por USB: `../.venv-pio/bin/pio run -e t1000e_companion_radio_ble -t upload --upload-port /dev/ttyACM0`
  (hace solo el "toque de 1200 baud" para entrar al bootloader; igual para la versión USB con `t1000e_companion_radio_usb`).
- **Sin PIN** (`-D BLE_NO_PIN`): MeshCore exige emparejar con PIN y BlueZ en Linux empareja sin pedirlo,
  así que el canal de datos quedó abierto. Cualquiera a ~10 m con la app MeshCore puede conectarse.
  La actualización de firmware por Bluetooth (DFU) sigue protegida con PIN 123456.
- No emparejar en la PC. Si hubo un emparejamiento viejo: `bluetoothctl remove AA:BB:CC:DD:EE:FF`.
- Con este firmware el USB solo carga la batería; los datos van por Bluetooth (o reflashear la versión USB).
- En la interfaz: panel "Conexión" -> Bluetooth -> buscar -> `MeshCore-RABANITO` -> Conectar.

## Pestaña "Gráfica" (aceleración en vivo)
- Arriba del mapa: pestañas **Mapa / Gráfica**. Ventanas de 1, 5 y 15 min; botón [ Tabla ] con los movimientos.
- Línea azul: aceleración |a| leída 1 vez por segundo. Banda gris: mínimo-máximo que midió el nodo entre
  lecturas (el firmware los guarda y los reinicia en cada lectura de `acel`), así se ven los golpes de milisegundos.
- Línea roja punteada: nivel de alerta = reposo del último movimiento + dif. mínima.
- Marcadores: cada movimiento evaluado al quedar en reposo (triángulo rojo = alertó, círculo azul = no), con su diferencia.
- Datos: `GET /api/acel?segundos=60` (el servidor guarda los últimos 15 min en memoria).

### Rango ±32 g (10 nov 2026)
- Registro 0x0F del QMA6100P = 0x0F (±32 g); escala 256 LSB/g (14 bits / 64 g), resolución ~3.9 mg.
- En reposo marca ~1.36 g (con ±16 g marcaba ~1.22 g en la misma posición): es el offset del sensor,
  que pesa más con este rango. La detección no se afecta porque usa pico - reposo medido.
- Con ±32 g por eje, la magnitud máxima medible es sqrt(3)*32 ~ 55 g.

## Ruta hasta el nodo al detectar una caída
- Cuando el detector alerta (caída o golpe), la interfaz cambia a la pestaña Mapa y traza la ruta desde
  esta computadora hasta la última ubicación GPS del nodo, con distancia y tiempo estimado.
- La ruta también se traza sola en cuanto el nodo tiene posición GPS, y se rehace (sin mover el mapa) si el nodo
  se mueve más de ~10 m (como máximo cada 30 s). "Quitar ruta" la apaga hasta la próxima alerta o hasta usar
  "Ver ruta desde esta PC".
- Modos: a pie (por defecto), en coche, línea recta. "Abrir en Google Maps" abre la misma ruta.
- Rutas por calles: OSRM de routing.openstreetmap.de (servicio gratuito de OpenStreetMap). Se le envían las
  coordenadas de la PC y del nodo. Si no responde, se dibuja línea recta con la distancia.
- Ubicación de la PC ("recordar lugares" por Wi-Fi, 10 nov 2026): la PC no tiene GPS y GeoClue/BeaconDB no
  conocen las redes de la zona. La primera vez en un lugar se fija con un clic en el mapa y el servidor guarda la
  huella de las redes Wi-Fi visibles (`nmcli`, sin sudo) en `data/lugares_wifi.json`. Después reconoce el lugar
  solo (coincidencia >= 25 % y >= 3 redes en común) y lo revisa cada minuto. Nada sale de la computadora.
  Cinta "Ruta": "Cambiar mi ubicación" (fija/actualiza el lugar actual) y "Olvidar lugares".

## Calibración: botón abajo
La calibración del acelerómetro se abre con el botón "Calibrar acelerómetro" al final del panel lateral
(muestra "(calibrado)" o "(sin calibrar)" junto al botón).

## Organización de la interfaz (estilo Excel, 10 nov 2026)
- **Barra de título**: nombre del nodo, Sonido y tema claro/oscuro.
- **Cinta de opciones** (todos los botones):
  - Inicio: Ping, ir a una hoja, ver ruta.
  - Detector: Borrar alarma, dif. mínima, Calibrar acelerómetro, Ver eventos, Exportar CSV.
  - Ruta: modo (a pie / en coche / línea recta), Google Maps, Quitar ruta, Cambiar mi ubicación.
  - Conexión: USB / Bluetooth, buscar y conectar.
- **Cuadro de nombre + barra de fórmulas**: nodo y resumen de su estado en una línea.
- **Panel lateral** (solo información): Estado, Detector de caídas, Ubicación, Ruta, Nodos.
- **Hojas abajo**: Mapa, Gráfica, Eventos (tabla de caídas/golpes), Dispositivo.
- **Barra de estado**: Listo/ALARMA, conexión, batería, aceleración, dif. mínima, hora de actualización.
- "Exportar CSV" descarga `eventos_rabanito_AAAA-MM-DD.csv` (UTF-8 con BOM, se abre bien en Excel).
- Copia del diseño anterior: no se guardó en el proyecto (solo en la carpeta temporal de la sesión).

## Reconstruir el firmware desde este repositorio
`firmware/MeshCore/` no se sube (es otro proyecto). Para recrearlo con los cambios de RABANITO:

    cd firmware
    git clone https://github.com/meshcore-dev/MeshCore.git
    cd MeshCore
    git checkout 81dbae5                      # versión usada (MeshCore v1.18.0)
    git apply ../rabanito-acelerometro.patch  # acelerómetro, detector, calibración, BLE sin PIN
    cd .. && uv venv -q .venv-pio && uv pip install -q -p .venv-pio platformio

Luego compilar/flashear como se explica arriba. `data/` tampoco se sube: guarda ubicaciones,
huellas Wi-Fi y la identidad del nodo; la interfaz lo crea sola al usarla.
