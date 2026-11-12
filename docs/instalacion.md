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
- `empaquetar/dist/sri_0.1.2_amd64.deb` - el paquete para instalar (~21 MB).

## Instalar

```bash
sudo apt install ./sri_0.1.2_amd64.deb
```

Queda como **un programa más**: aparece **SRI** (con su ícono) en el menú de aplicaciones. Al abrirlo arranca el
seguimiento del nodo con el usuario que lo abre (datos en `~/.local/share/sri/`) y se ve en su propia ventana; al
cerrarla, se detiene. Si ya está abierto, volver a abrirlo solo trae la ventana al frente. Mientras la ventana
está abierta, el lanzador revisa cada 5 s que el seguimiento siga vivo y lo vuelve a arrancar si falló.

### Modo estación (la computadora al aire libre)

```bash
sudo sri-estacion activar      # servicio siempre activo + pantalla completa al iniciar sesión
sudo sri-estacion desactivar   # volver a programa normal
sri-estacion estado
```

En modo estación el servicio **`sri`** (systemd) arranca con la computadora y se reinicia solo si falla, corre como
el usuario de sistema `sri` (grupos `dialout` y `bluetooth`) y guarda los datos en **`/var/lib/sri/`**. La ventana
de pantalla completa (`sri-kiosco`) se abre al iniciar sesión y se reabre si se cierra. Abrir SRI desde el menú
con el servicio activo solo muestra la ventana.

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

La configuración también puede ir en `~/.config/sri/config.toml` para el programa de escritorio.

Para pasar los datos de pruebas (calibración, eventos, lugares Wi-Fi) al programa:

```bash
cp -rn data/. ~/.local/share/sri/                                              # programa de escritorio
sudo cp data/*.json data/*.jsonl /var/lib/sri/ && sudo chown -R sri:sri /var/lib/sri   # modo estación
```

## Uso diario

| Acción | Comando |
|---|---|
| Abrir SRI | menú de aplicaciones, o `sri-app` |
| Registro del programa de escritorio | `~/.local/share/sri/sri.log` |
| Ver estado del servicio (modo estación) | `systemctl status sri` |
| Ver registro (últimas líneas, en vivo) | `journalctl -u sri -f` |
| Reiniciar / detener | `sudo systemctl restart sri` / `sudo systemctl stop sri` |
| Abrir la interfaz en una ventana normal | `sri-kiosco --ventana` |
| Cerrar la pantalla completa para mantenimiento | `sri-kiosco --pausar` (volver: `sri-kiosco --reanudar`) |
| Desinstalar (conserva los datos) | `sudo apt remove sri` |
| Desinstalar y borrar datos | `sudo apt purge sri` |

## Seguridad del servicio

Corre como usuario sin privilegios `sri`, sin acceso a `/home`, con el sistema en solo lectura salvo
`/var/lib/sri`, y escucha solo en `127.0.0.1`. Los archivos de datos se escriben de forma atómica (archivo
temporal, `fsync` y renombrar) para no corromperse si se corta la luz.

## Pendiente (siguientes fases)

- Fase 2: acceso desde la red local con contraseña y página de estado de salud.
- Fase 3: funcionamiento sin internet (paquete de región de la Huasteca con mapa, relieve y agua).
- Fase 4: rutas sin internet. Fase 5: Raspberry Pi (ARM64).
