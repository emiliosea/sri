# Instalación en la estación (programa nativo)

Fase 1 del [plan de la estación](plan-estacion.md): SRI como programa instalable en Linux, sin Python ni
dependencias aparte. Probado en Debian 13 x86_64 con RABANITO por Bluetooth.

## Construir el paquete

En una computadora con la misma arquitectura que la estación (x86_64 o ARM64):

```bash
empaquetar/construir.sh
```

Crea:
- `empaquetar/dist/sri/` - el programa (Python y dependencias incluidos, ~60 MB).
- `empaquetar/dist/sri_0.1.0_amd64.deb` - el paquete para instalar (~21 MB).

## Instalar

```bash
sudo apt install ./sri_0.1.0_amd64.deb
```

El paquete:
- instala el programa en `/opt/sri/` (comandos `sri` y `sri-kiosco`);
- crea el usuario de sistema `sri` (grupos `dialout` para USB y `bluetooth`);
- instala y arranca el servicio **`sri`** (systemd): arranca con la computadora y se reinicia solo si falla;
- guarda los datos en **`/var/lib/sri/`** y la configuración en **`/etc/sri/config.toml`**;
- abre la **ventana de pantalla completa** al iniciar sesión en el escritorio (`/etc/xdg/autostart`).

Necesita `bluez` y `curl`; para la ventana, Chromium (o Firefox).

## Configurar

`/etc/sri/config.toml`:

```toml
[nodo]
conexion = "ble"                  # ble | usb | demo
direccion = "MeshCore-RABANITO"   # o la dirección AA:BB:CC:DD:EE:FF
puerto = "/dev/ttyACM0"           # si conexion = "usb"

[servidor]
puerto = 5000
escuchar = "127.0.0.1"            # solo esta computadora (fase 2: red local con contraseña)
```

Después: `sudo systemctl restart sri`. La conexión elegida en la interfaz (cinta Conexión) tiene prioridad y
se recuerda en `/var/lib/sri/connection.json`.

Para pasar los datos de pruebas (calibración, eventos, lugares Wi-Fi) a la estación:

```bash
sudo cp data/*.json data/*.jsonl /var/lib/sri/ && sudo chown -R sri:sri /var/lib/sri
```

## Uso diario

| Acción | Comando |
|---|---|
| Ver estado del servicio | `systemctl status sri` |
| Ver registro (últimas líneas, en vivo) | `journalctl -u sri -f` |
| Reiniciar / detener | `sudo systemctl restart sri` / `sudo systemctl stop sri` |
| Abrir la interfaz en una ventana normal | `sri-kiosco --ventana` |
| Cerrar la pantalla completa para mantenimiento | `sri-kiosco --pausar` (volver: `sri-kiosco --reanudar`) |
| Desinstalar (conserva los datos) | `sudo apt remove sri` |
| Desinstalar y borrar datos | `sudo apt purge sri` |

En una computadora de desarrollo, instalar el paquete también abre la pantalla completa al iniciar sesión:
usar `sri-kiosco --pausar` para desactivarla.

## Seguridad del servicio

Corre como usuario sin privilegios `sri`, sin acceso a `/home`, con el sistema en solo lectura salvo
`/var/lib/sri`, y escucha solo en `127.0.0.1`. Los archivos de datos se escriben de forma atómica (archivo
temporal, `fsync` y renombrar) para no corromperse si se corta la luz.

## Pendiente (siguientes fases)

- Fase 2: acceso desde la red local con contraseña y página de estado de salud.
- Fase 3: funcionamiento sin internet (paquete de región con mapa, relieve y agua).
- Fase 4: rutas sin internet. Fase 5: Raspberry Pi (ARM64).
