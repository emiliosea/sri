# Firmware del nodo (MeshCore modificado)

RABANITO usa **MeshCore v1.18.0** (commit `81dbae5`) con cambios propios, versión **`v1.18.0-sri7`** (FARO, la base, usa `sri5`)
(antes `v1.18.0-rabanito`; la sri2 agrega las **alertas por LoRa** la sri3 la **posición cada 4 minutos** la sri4 el **resumen de aceleración** la sri5 la **identidad fija y la temperatura** del nodo de campo la sri6 el **reporte cada 10 s** y la sri7 el **reporte adaptativo y compacto**).
Los cambios están en [`firmware/rabanito-acelerometro.patch`](../firmware/rabanito-acelerometro.patch).

## Qué cambia respecto al MeshCore oficial

| Archivo | Cambio |
|---|---|
| `variants/t1000-e/target.h` | Estado del acelerómetro, banco de 5 s, alarma y calibración |
| `variants/t1000-e/target.cpp` | Lectura del QMA6100P (±32 g), detector de caídas, calibración, nuevas custom vars, ejes en la telemetría (canal 2) |
| `src/helpers/nrf52/SerialBLEInterface.cpp` | Opción `BLE_NO_PIN`: canal de datos Bluetooth sin PIN (la actualización DFU por Bluetooth sigue con PIN) |
| `src/helpers/esp32/SerialBLEInterface.cpp` | La misma opción `BLE_NO_PIN` para placas ESP32 (FARO, Heltec V4) |
| `variants/heltec_v4/platformio.ini` | Objetivos `heltec_v4_companion_radio_usb_sri` (FARO, base por USB, `v1.18.0-sri5`) y `heltec_v4_companion_radio_ble_sri` (por Bluetooth, `v1.18.0-sri5-ble`, con `BLE_NO_PIN`) |
| `variants/t1000-e/platformio.ini` | Versión `v1.18.0-sri7` (USB) y `v1.18.0-sri7-ble` (Bluetooth, con `BLE_NO_PIN`) |
| `examples/companion_radio/MyMesh.cpp/.h` | `alertaSRI()`: manda la caída/golpe por el canal de grupo "SRI" (ver abajo) |

El algoritmo se explica en [detector-de-caidas.md](detector-de-caidas.md).

## Archivos listos para flashear

| Archivo | Uso |
|---|---|
| `firmware/RABANITO-meshcore-v1.18.0-sri7-ble.uf2` | **Bluetooth** (el de RABANITO y los nodos de campo). El USB solo carga. |
| `firmware/RABANITO-meshcore-v1.18.0-sri7.uf2` | **USB** (datos por cable, sin Bluetooth) |
| `firmware/FARO-heltec-v4-meshcore-v1.18.0-sri5-usb.bin` | **FARO** (Heltec V4, ESP32-S3), la base: imagen completa por **USB**, se carga en la dirección 0x0 |

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
    .pio/build/t1000e_companion_radio_ble/firmware.hex -o ../RABANITO-meshcore-v1.18.0-sri7-ble.uf2
```

Notas:
- La conversión a `.uf2` se hace a mano porque el objetivo `-t create_uf2` de MeshCore falla con rutas que
  tienen espacios (como "SRI TESIS").
- No correr dos compilaciones al mismo tiempo en la misma carpeta.

## Arquitectura: nodos de campo, base FARO y SRI

```
 nodos de campo (los lleva la persona)        base fija                    PC
 RABANITO (T1000-E) ─┐                     ┌──────────┐  cable USB   ┌──────────────┐
 nodo SRI propio  ───┼── LoRa, canal "SRI" │   FARO   │ ───────────▶ │ SRI: mapa,   │
 otros nodos ...  ───┘   (privado, frase)  │ Heltec V4│              │ gráfica,     │
                                           └──────────┘              │ alertas      │
                                                                     └──────────────┘
```

- **Nodos de campo:** miden y mandan solos (sin app ni PC) por el canal privado **"SRI"**: alertas de caída/golpe
  al momento y un **reporte adaptativo** (cada 3 s en movimiento, 30 s quieto; posición GPS, batería, temperatura, aceleración mín/máx). Cada mensaje
  lleva la **identidad fija** del nodo (`i` + inicio de su llave pública), así dos nodos con el mismo nombre no se
  confunden y SRI lo reconoce aunque cambie de nombre.
- **FARO (base):** queda fijo, conectado a la PC por **cable USB** (SRI lo encuentra solo entre los puertos USB); solo escucha el canal y pasa los mensajes. No
  necesita GPS ni acelerómetro.
- **SRI:** junta los reportes de todos los nodos de campo: los pone en el mapa, la hoja Dispositivo y la ficha de
  cada nodo; la Gráfica muestra la aceleración del nodo de campo seleccionado; las alertas suenan y trazan la ruta.

### Protocolo para un nodo de campo propio

Cualquier placa con MeshCore (u otro firmware que hable MeshCore) sirve como nodo de campo si manda estos
**mensajes de texto al canal de grupo "SRI"** (misma frase que la base; la llave es
`sha256("SRI:" + frase)[:16]`). MeshCore antepone el nombre del nodo (`NOMBRE: `). Campos separados por espacio;
los que no tenga la placa se omiten (salvo los marcados como obligatorios).

**Reporte en texto** (lleva el nombre; en sri7 sale cada 60 s, los demás van en binario):

```
SRI1 POS @<lat>,<lon> t<hora> [b<mV>] [e<seg>] [a<mín>/<máx>] [c<°C>] [i<id>]
SRI1 POS @25.661943,-100.422518 t1794953624 b4018 e3 a0.92/1.85 c23.7 id9a3737d
```

| Campo | Qué es |
|---|---|
| `@lat,lon` | **Obligatorio.** Posición en grados (6 decimales). Sin GPS: `@0.000000,0.000000` (SRI solo usa la telemetría) |
| `t` | **Obligatorio.** Hora del nodo (segundos Unix) |
| `b` | Batería en mV |
| `e` | Segundos desde la última posición GPS válida (-1 = nunca); si es grande el GPS perdió la señal |
| `a` | Aceleración mínima/máxima en g desde el reporte anterior |
| `c` | Temperatura del sensor del nodo en °C (no la del chip) |
| `i` | Identidad: 8 caracteres hex, inicio de la llave pública del nodo. Muy recomendado |

**Reporte binario compacto** (sri7): datagrama de canal (`sendGroupData`, en la app `CHANNEL_DATA_RECV`) con
`data_type` **`0xFF53`** (rango de pruebas de MeshCore, sin registro) y 25 bytes, little endian. Ocupa ~0.3 s de
aire en vez de ~0.65 s del texto. No lleva nombre: SRI lo toma del último reporte en texto con la misma identidad.

| Bytes | Campo |
|---|---|
| 0 | Versión del formato = 1 |
| 1-4 | Identidad: 4 primeros bytes de la llave pública |
| 5-8 / 9-12 | Latitud / longitud × 10⁶ (int32; 0 = sin GPS) |
| 13-14 | Batería en mV |
| 15-16 | Segundos desde la última posición GPS válida (0xFFFF = nunca) |
| 17-18 / 19-20 | Aceleración mínima / máxima desde el reporte anterior, en centésimas de g (0xFFFF = sin dato) |
| 21-22 | Temperatura en décimas de °C (int16; 0x8000 = sin dato) |
| 23 | Banderas: bit 0 = en movimiento |
| 24 | Número de reporte (0-255, vuelve a 0; SRI lo usa para no contar repetidos) |

**Alerta** (al detectar; se repite 3 veces cada 20 s porque los mensajes de canal no tienen acuse):

```
SRI1 <CAIDA|GOLPE> dif <g>g pico <g>g [@<lat>,<lon>] t<hora> #<n.º de evento> (<rep>/3) [i<id>]
SRI1 CAIDA dif 7.97g pico 8.79g @25.662300,-100.422100 t1794705000 #3 (1/3) id9a3737d
```

El orden de los campos importa (SRI los lee en ese orden). En el firmware de este proyecto lo hacen
`MyMesh::alertaSRI()` y `MyMesh::posicionSRI()` (`examples/companion_radio/MyMesh.cpp`), que toman los datos del
`SensorManager` de la placa (variables `alerta` y `resumen`; ver `variants/t1000-e/target.cpp`). Un nodo propio
puede reusar esas dos funciones implementando esas dos variables en su `SensorManager`.

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

## Reporte periódico (sri3: cada 4 min; sri6: cada 10 s; sri7: adaptativo)

Además de las alertas, cada **10 s** (sri3 a sri5: cada 4 minutos) el nodo manda su posición GPS por el mismo canal privado **"SRI"** (no por
el anuncio, que es público), para que la base vea por dónde va el senderista:

```
SRI1 POS @25.662300,-100.422100 t1794705000 b3920
```

(posición, hora del nodo, batería en mV). La primera sale 1 minuto después de encender. Solo se manda si hay canal
"SRI", el GPS está encendido y ya tiene posición (sin señal GPS no manda nada); mientras sale una alerta se espera,
porque la alerta ya lleva la posición. Los nodos sin GPS (como FARO) nunca la mandan. El intervalo se cambia al
compilar con `-D SRI_POS_INTERVALO_MS=...`.

**sri7 - adaptativo:** cada **3 s** mientras el nodo se mueve y hasta 20 s después del último movimiento (lo decide
el mismo criterio de reposo del detector), cada **30 s** quieto; si empieza a moverse adelanta el reporte. Variables
`rapido_s` (2-60 s) y `reporte_s` (5-600 s), se cambian desde SRI con el nodo conectado directo y vuelven a 3 s / 30 s
al reiniciar. La mayoría van en binario (ver arriba); uno en texto cada 60 s.

**Por qué no cada segundo (sri6):** cada reporte (~100 bytes) ocupa **~0.65 s de aire** con SF8 / BW 62.5 kHz.
Cada segundo el radio estaría transmitiendo el 65 % del tiempo y los reportes chocarían entre sí y con las
alertas. Cada 10 s es ~6.5 % del canal por nodo, deja lugar a las alertas y a varios nodos de campo. El intervalo
se cambia sin recompilar con la variable `reporte_s` (5 a 600 s; vuelve a 10 s al reiniciar), desde SRI con el
nodo de campo conectado directo (cinta **Detector**, "Reporte por LoRa"), o al compilar con `-D SRI_POS_INTERVALO_MS`.
SRI usa la **hora de llegada** de cada reporte (el reloj del nodo se atrasa al reiniciarlo).

**Desde sri4** el mensaje lleva también la antigüedad de la posición y un resumen del acelerómetro:

```
SRI1 POS @25.662300,-100.422100 t1794705000 b3920 e300 a0.40/3.85
```

`e` = segundos desde la última posición GPS válida (-1 = nunca; si es grande, el GPS perdió la señal y la
posición es la última conocida) y `a` = aceleración mínima/máxima en g desde la posición anterior. Con
acelerómetro se manda aunque no haya GPS (posición 0,0, que SRI ignora). El nodo lleva ese mín/máx en la
variable `resumen` (`mín*100|máx*100|edad`), que se reinicia al mandar la posición. En SRI la posición se pone en ese nodo del mapa (con su batería y
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
de prueba de fábrica ("IO Output test") y el 17 nov 2026 se le cargó MeshCore `v1.18.0-sri2-ble`. Desde `sri5` es la **base** y usa la variante **USB**.

| Ajuste | Valor |
|---|---|
| Nombre | FARO |
| Papel | **Base fija**: companion por **USB** (cable a la PC), escucha el canal "SRI" y pasa todo a SRI |
| Firmware | `v1.18.0-sri5` (objetivo `heltec_v4_companion_radio_usb_sri`). Con la variante Bluetooth (`..._ble_sri`) el cable solo da corriente y los datos van por Bluetooth (8C:FD:49:B6:90:D1) |
| Modelo que reporta | Heltec V4.3 OLED |
| Radio | 915.0 MHz, BW 62.5 kHz, SF 8, CR 4/5 (igual que RABANITO) |
| Potencia | 10 (valor del SX1262; con el amplificador de la placa sale ~22 dBm según MeshCore). SRI muestra la salida en la antena y marca la temperatura como "del chip" |
| Sensores | No tiene acelerómetro ni GPS: no detecta caídas por sí solo. La "temperatura" que reporta es la del chip (~47 °C), no la del ambiente |

**Flashear** (por USB, sin botones):

```bash
cd firmware/MeshCore
../.venv-pio/bin/pio run -e heltec_v4_companion_radio_usb_sri -t upload --upload-port /dev/ttyACM1
```

o con la imagen ya hecha: `esptool.py --chip esp32s3 write_flash 0x0 firmware/FARO-heltec-v4-meshcore-v1.18.0-sri5-usb.bin`.
Usar `/dev/ttyACMn` (no la ruta `/dev/serial/by-id/...`: lleva `:` y esptool no la entiende).
La primera compilación para ESP32 descarga las herramientas (~37 min). Después se configura nombre y radio desde
SRI o con la librería `meshcore` (`set_name`, `set_radio`).

