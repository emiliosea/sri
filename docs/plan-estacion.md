# Plan: pasar a programa nativo para la estación al aire libre

Estado: **fases 1 y 3 listas** (13 nov 2026), ver [instalacion.md](instalacion.md). Zona del paquete: Parque La
Huasteca (Santa Catarina, N.L.) y la zona metropolitana. Hoy la interfaz corre como servidor Flask + página web; sirve para pruebas,
pero la estación va a quedar instalada al aire libre, sin nadie atendiéndola.

## Condiciones de la estación

| Condición | Decisión |
|---|---|
| Computadora | **Mini PC x86_64** (lo más probable); que también compile para **Raspberry Pi (ARM64)** |
| Pantalla | **Las dos**: ventana a pantalla completa (kiosco) cuando hay pantalla, y acceso por la red local |
| Internet | **Sin internet o intermitente**: lo esencial debe funcionar sin conexión |

## Arquitectura propuesta

Se conserva el código actual (Python + la interfaz HTML) y se separa en dos piezas:

```
 servicio "sri" (systemd, arranca con la computadora, se reinicia solo si falla)
   - conexión con el nodo (Bluetooth / USB), detector, registro de eventos
   - API + interfaz web en el puerto 5000 (red local, con contraseña)
   - datos sin conexión: mapas, relieve, agua (paquetes descargados antes)
        ^
        |  http://localhost:5000
 ventana "sri-kiosco" (pywebview / WebKitGTK, pantalla completa, sin navegador)
   - solo muestra la interfaz; si se cierra o falla, el seguimiento sigue
```

- **Empaquetado**: PyInstaller (carpeta con Python y dependencias incluidos) dentro de un paquete **.deb**
  (instala el servicio, crea el usuario y los permisos) y un **AppImage** para probar sin instalar.
- **Dos arquitecturas**: el .deb se compila en cada una (x86_64 aquí; ARM64 en la Pi o en GitHub Actions).
- **Datos** fuera del programa: `/var/lib/sri/` (eventos, últimas posiciones, calibración, caché) y
  configuración en `/etc/sri/config.toml` (nodo, puerto, contraseña, región sin conexión, ubicación fija de la
  estación).

## Qué depende hoy de internet y qué se hará

| Función | Servicio actual | Sin conexión |
|---|---|---|
| Mapa base (hojas Mapa y Terreno) | tile.openstreetmap.org | **Paquete de mapa de la región** (PMTiles de Protomaps/OpenStreetMap, un solo archivo) dibujado en blanco y negro. No se permite descargar en masa los mosaicos de tile.openstreetmap.org |
| Relieve y alturas | AWS Terrain Tiles | **Paquete de relieve** de la región (los mismos mosaicos, descargados antes; uso permitido) |
| Cuerpos de agua | Overpass | **Paquete de agua** de la región, sacado de un extracto de OpenStreetMap (Geofabrik) |
| Ruta por calles | routing.openstreetmap.de (OSRM) | Fase 1: línea recta (ya existe). Fase 2: **OSRM local** con el extracto de la región |
| Clima | Open-Meteo | Se guarda el último pronóstico y se muestra su antigüedad; sin conexión queda el sensor del nodo |
| Ubicación de la PC | Wi-Fi (nmcli) | Ya funciona sin internet; en la estación fija se usa la **ubicación fija** de la configuración |
| Google Maps (botones) | google.com | Se ocultan sin conexión |

Todo lo descargado vive en un **"paquete de región"** (por ejemplo `huasteca-2026-11.sri`) que se prepara con
internet y se copia a la estación.

## Lo que pide estar al aire libre

- **Arranque solo y reinicio**: servicio systemd con `Restart=always`; la ventana se vuelve a abrir si se cierra.
- **Cortes de luz**: escrituras atómicas (archivo temporal + renombrar) para no corromper datos; registros con
  tamaño máximo.
- **Hora**: la estación pone la hora al nodo. La mini PC tiene reloj con pila; una Raspberry Pi no, así que sin
  internet habría que tomar la hora del GPS del nodo.
- **Bluetooth**: permisos del usuario del servicio para BlueZ (sin sudo), reconexión automática (ya existe).
- **Acceso por red**: contraseña, y opción de solo lectura para quien solo consulta.
- **Estado de salud**: página con conexión al nodo, batería, espacio en disco, temperatura de la PC y si hay
  internet.

## Fases

1. **Programa instalable (x86_64)**: datos y configuración fuera del código, servicio systemd, ventana kiosco,
   paquete .deb y AppImage. Funciona igual que hoy (con internet).
2. **Red local**: escuchar en la red con contraseña, modo solo lectura, página de estado de salud.
3. **Sin conexión**: paquete de región (mapa, relieve, agua), caché del clima, todo con respaldo sin internet.
4. **Ruta sin conexión**: OSRM local para la región.
5. **Raspberry Pi**: compilación ARM64 y pruebas de rendimiento (la hoja Terreno ya se optimizó).

Cada fase deja la estación funcionando; la fase 1 no cambia nada de lo que ya hace la interfaz.
