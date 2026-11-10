# Firmware del nodo (MeshCore modificado)

RABANITO usa **MeshCore v1.18.0** (commit `81dbae5`) con cambios propios, versión **`v1.18.0-rabanito`**.
Los cambios están en [`firmware/rabanito-acelerometro.patch`](../firmware/rabanito-acelerometro.patch).

## Qué cambia respecto al MeshCore oficial

| Archivo | Cambio |
|---|---|
| `variants/t1000-e/target.h` | Estado del acelerómetro, banco de 5 s, alarma y calibración |
| `variants/t1000-e/target.cpp` | Lectura del QMA6100P (±32 g), detector de caídas, calibración, nuevas custom vars, ejes en la telemetría (canal 2) |
| `src/helpers/nrf52/SerialBLEInterface.cpp` | Opción `BLE_NO_PIN`: canal de datos Bluetooth sin PIN (la actualización DFU por Bluetooth sigue con PIN) |
| `variants/t1000-e/platformio.ini` | Versión `v1.18.0-rabanito` (USB) y `v1.18.0-rabanito-ble` (Bluetooth, con `BLE_NO_PIN`) |

El algoritmo se explica en [detector-de-caidas.md](detector-de-caidas.md).

## Archivos listos para flashear

| Archivo | Uso |
|---|---|
| `firmware/RABANITO-meshcore-v1.18.0-rabanito-ble.uf2` | **Bluetooth** (firmware actual de RABANITO). El USB solo carga. |
| `firmware/RABANITO-meshcore-v1.18.0-rabanito.uf2` | **USB** (datos por cable, sin Bluetooth) |

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
    .pio/build/t1000e_companion_radio_ble/firmware.hex -o ../RABANITO-meshcore-v1.18.0-rabanito-ble.uf2
```

Notas:
- La conversión a `.uf2` se hace a mano porque el objetivo `-t create_uf2` de MeshCore falla con rutas que
  tienen espacios (como "SRI TESIS").
- No correr dos compilaciones al mismo tiempo en la misma carpeta.

## Configuración del nodo

| Ajuste | Valor |
|---|---|
| Nombre | RABANITO |
| Radio | 915.0 MHz, BW 62.5 kHz, SF 8, CR 4/5, 22 dBm |
| GPS | encendido (`gps = 1`) |
| Compartir ubicación en anuncios | sí (`adv_loc_policy = 1`) |
| Hora | se sincroniza con la PC en cada conexión |
