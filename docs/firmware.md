# Firmware del nodo (MeshCore modificado)

RABANITO usa **MeshCore v1.18.0** (commit `81dbae5`) con cambios propios, versión **`v1.18.0-sri3`**
(antes `v1.18.0-rabanito`; la sri2 agrega las **alertas por LoRa** y la sri3 la **posición cada 4 minutos**).
Los cambios están en [`firmware/rabanito-acelerometro.patch`](../firmware/rabanito-acelerometro.patch).

## Qué cambia respecto al MeshCore oficial

| Archivo | Cambio |
|---|---|
| `variants/t1000-e/target.h` | Estado del acelerómetro, banco de 5 s, alarma y calibración |
| `variants/t1000-e/target.cpp` | Lectura del QMA6100P (±32 g), detector de caídas, calibración, nuevas custom vars, ejes en la telemetría (canal 2) |
| `src/helpers/nrf52/SerialBLEInterface.cpp` | Opción `BLE_NO_PIN`: canal de datos Bluetooth sin PIN (la actualización DFU por Bluetooth sigue con PIN) |
| `src/helpers/esp32/SerialBLEInterface.cpp` | La misma opción `BLE_NO_PIN` para placas ESP32 (FARO, Heltec V4) |
| `variants/heltec_v4/platformio.ini` | Objetivo `heltec_v4_companion_radio_ble_sri` (versión `v1.18.0-sri3-ble`, con `BLE_NO_PIN`) |
| `variants/t1000-e/platformio.ini` | Versión `v1.18.0-sri3` (USB) y `v1.18.0-sri3-ble` (Bluetooth, con `BLE_NO_PIN`) |
| `examples/companion_radio/MyMesh.cpp/.h` | `alertaSRI()`: manda la caída/golpe por el canal de grupo "SRI" (ver abajo) |

El algoritmo se explica en [detector-de-caidas.md](detector-de-caidas.md).

## Archivos listos para flashear

| Archivo | Uso |
|---|---|
| `firmware/RABANITO-meshcore-v1.18.0-sri3-ble.uf2` | **Bluetooth** (el de RABANITO y los nodos de campo). El USB solo carga. |
| `firmware/RABANITO-meshcore-v1.18.0-sri3.uf2` | **USB** (datos por cable, sin Bluetooth) |
| `firmware/FARO-heltec-v4-meshcore-v1.18.0-sri3-ble.bin` | **FARO** (Heltec V4, ESP32-S3): imagen completa por Bluetooth, se carga en la dirección 0x0 |

## Flashear

**Opción A - copiando el .uf2**

1. Cerrar la interfaz.
2. Mantener presionado el botón del T1000-E mientras se conecta el cable USB (LED verde fijo).
   Aparece una unidad "T1000-E".
3. Copiar el `.uf2` a esa unidad. El nodo se reinicia solo.

**Opción B - desde la terminal (no hace falta el botón)**

```bash
cd firmware/MeshCore
../.venv-pio/bin/pio run -e t1000e_companion_radio_ble -t upload --upload-port /dev/ttyACM0
```

PlatformIO hace el "toque de 1200 baud" para entrar al bootloader y sube el firmware con `nrfutil`.
Usar `t1000e_companion_radio_usb` para la versión USB.

Al flashear la misma versión de MeshCore se conservan el nombre, la radio y la identidad del nodo.

## Compilar desde el código

`firmware/MeshCore/` no está en el repositorio (es otro proyecto, ~370 MB con dependencias). Para recrearlo:

```bash
cd firmware
git clone https://github.com/meshcore-dev/MeshCore.git
cd MeshCore
git checkout 81dbae5
git apply ../rabanito-acelerometro.patch
cd .. && uv venv -q .venv-pio && uv pip install -q -p .venv-pio platformio
cd MeshCore
../.venv-pio/bin/pio run -e t1000e_companion_radio_ble
../.venv-pio/bin/python bin/uf2conv/uf2conv.py -f 0xADA52840 -c \
    .pio/build/t1000e_companion_radio_ble/firmware.hex -o ../RABANITO-meshcore-v1.18.0-sri3-ble.uf2
```

Notas:
- La conversión a `.uf2` se hace a mano porque el objetivo `-t create_uf2` de MeshCore falla con rutas que
  tienen espacios (como "SRI TESIS").
- No correr dos compilaciones al mismo tiempo en la misma carpeta.

## Alertas por LoRa (v1.18.0-sri2)

Cuando el detector engancha una caída o golpe, el nodo manda **solo** (sin app ni PC) un mensaje al canal de
grupo privado **"SRI"**, 3 veces cada 20 s porque los mensajes de canal no tienen acuse de recibo:

```
SRI1 CAIDA dif 7.97g pico 8.79g @25.662300,-100.422100 t1794705000 #3 (1/3)
```

(tipo, diferencia pico - reposo, pico, posición GPS si la hay, hora del nodo, número de evento, repetición). Se
lee también en la app MeshCore. La base (el nodo conectado a la PC) lo recibe y SRI lo muestra como alerta de ese
nodo. Si el nodo no tiene el canal "SRI", no manda nada (la alarma sigue en el nodo y en la PC conectada).

**Configurar el canal:** conectar cada nodo a SRI una vez y, en la hoja **Red LoRa**, "Configurar canal SRI en este
nodo" con la **misma frase** en todos (la llave del canal sale de la frase). Valor `alerta` en las custom vars:
`tipo|pico*100|dif*100|epoch|cuenta` mientras falta mandarla.

## Posición cada 4 minutos (v1.18.0-sri3)

Además de las alertas, cada **4 minutos** el nodo manda su posición GPS por el mismo canal privado **"SRI"** (no por
el anuncio, que es público), para que la base vea por dónde va el senderista:

```
SRI1 POS @25.662300,-100.422100 t1794705000 b3920
```

(posición, hora del nodo, batería en mV). La primera sale 1 minuto después de encender. Solo se manda si hay canal
"SRI", el GPS está encendido y ya tiene posición (sin señal GPS no manda nada); mientras sale una alerta se espera,
porque la alerta ya lleva la posición. Los nodos sin GPS (como FARO) nunca la mandan. El intervalo se cambia al
compilar con `-D SRI_POS_INTERVALO_MS=...`. En SRI la posición se pone en ese nodo del mapa (con su batería y
"Posición llega: por LoRa") y se guarda como su última posición conocida.

## Configuración del nodo

| Ajuste | Valor |
|---|---|
| Nombre | RABANITO |
| Radio | 915.0 MHz, BW 62.5 kHz, SF 8, CR 4/5, 22 dBm |
| GPS | encendido (`gps = 1`) |
| Compartir ubicación en anuncios | sí (`adv_loc_policy = 1`) |
| Hora | se sincroniza con la PC en cada conexión |

## FARO: Heltec WiFi LoRa 32 V4 (ESP32-S3)

Segundo nodo del proyecto y el primero con ESP32, la placa elegida para el dispositivo SRI. Llegó con el firmware
de prueba de fábrica ("IO Output test") y el 17 nov 2026 se le cargó MeshCore `v1.18.0-sri2-ble` (después `sri3-ble`).

| Ajuste | Valor |
|---|---|
| Nombre | FARO (en Bluetooth: `MeshCore-FARO`, dirección 8C:FD:49:B6:90:D1) |
| Papel | Nodo de campo por Bluetooth (companion) |
| Modelo que reporta | Heltec V4.3 OLED |
| Radio | 915.0 MHz, BW 62.5 kHz, SF 8, CR 4/5 (igual que RABANITO) |
| Potencia | 10 (valor del SX1262; con el amplificador de la placa sale ~22 dBm según MeshCore). SRI muestra la salida en la antena y marca la temperatura como "del chip" |
| Sensores | No tiene acelerómetro ni GPS: no detecta caídas por sí solo. La "temperatura" que reporta es la del chip (~47 °C), no la del ambiente |

**Flashear** (por USB, sin botones):

```bash
cd firmware/MeshCore
../.venv-pio/bin/pio run -e heltec_v4_companion_radio_ble_sri -t upload --upload-port /dev/ttyACM0
```

o con la imagen ya hecha: `esptool.py --chip esp32s3 write_flash 0x0 firmware/FARO-heltec-v4-meshcore-v1.18.0-sri3-ble.bin`.
La primera compilación para ESP32 descarga las herramientas (~37 min). Después se configura nombre y radio desde
SRI o con la librería `meshcore` (`set_name`, `set_radio`).

