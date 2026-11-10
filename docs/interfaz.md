# Interfaz

Interfaz web organizada **al estilo Excel**. Las capturas son del modo demo (nodos simulados).

![Hoja Mapa](img/interfaz-mapa.png)

## Partes de la pantalla

| Parte | Qué contiene |
|---|---|
| **Barra de título** | Nombre del nodo, sonido sí/no, tema claro/oscuro |
| **Cinta de opciones** | Todos los botones, en pestañas: **Inicio** (ping, hojas, ruta), **Detector** (borrar alarma, dif. mínima, calibrar, eventos, CSV), **Ruta** (modo, Google Maps, quitar, ubicación de la PC), **Conexión** (USB / Bluetooth) |
| **Cuadro de nombre + barra de fórmulas** | Nodo y resumen de su estado en una línea |
| **Panel lateral** | Solo información: Estado, Detector de caídas, Ubicación, Ruta, Nodos |
| **Hojas (abajo)** | Mapa, Gráfica, Eventos, Dispositivo. Se pueden abrir directo con `?hoja=grafica`, etc. |
| **Barra de estado** | Listo / ALARMA, conexión, batería, aceleración, dif. mínima, hora de actualización |

Colores: blanco y negro, **azul** para lo resaltado (este nodo, en vivo, OK) y **rojo** para alertas. Todas las
horas en CST (Monterrey).

## Hojas

**Gráfica** - aceleración en vivo (1 lectura por segundo). La banda gris es el mínimo-máximo que midió el nodo
entre lecturas (ahí se ven los golpes); la línea roja punteada es el nivel de alerta (reposo + dif. mínima);
los marcadores son los movimientos evaluados (triángulo rojo = alertó, círculo azul = no).

![Hoja Gráfica](img/interfaz-grafica.png)

**Eventos** - tabla de caídas y golpes que alertaron, con **Exportar CSV** (UTF-8, se abre bien en Excel).

![Hoja Eventos](img/interfaz-eventos.png)

**Dispositivo** - identidad, firmware, GPS, sensores y radio del nodo.

## Ubicación y ruta

- **Visto por última vez**: si el GPS pierde señal, el mapa muestra la última posición guardada (marcador rojo
  punteado) con la hora.
- **Ruta automática** desde esta computadora hasta la última ubicación del nodo, con distancia y tiempo (a pie,
  en coche o línea recta). Con una alarma, la ruta se destaca y la interfaz cambia a la hoja Mapa.
- Rutas por calles con OSRM (routing.openstreetmap.de): se envían las coordenadas de la PC y del nodo. Sin
  respuesta, se dibuja línea recta.
- **Ubicación de la PC** (no tiene GPS): la primera vez en un lugar se fija con un clic en el mapa y se guarda la
  huella de las redes Wi-Fi; después el lugar se reconoce solo. Todo queda en la computadora
  (`data/lugares_wifi.json`).

## Calibración del acelerómetro

Cinta **Detector -> Calibrar acelerómetro**: poner el nodo quieto sobre cada una de sus 6 caras, "Medir cara" y
luego "Aplicar". Se guarda en `data/calibracion.json` y se reenvía al nodo en cada conexión.

## Datos locales (`data/`, no se sube al repositorio)

| Archivo | Contenido |
|---|---|
| `connection.json` | Última conexión (USB/Bluetooth) |
| `last_seen.json` | Última posición GPS de cada nodo |
| `impactos.jsonl` | Eventos del detector con su posición |
| `calibracion.json` | Calibración del acelerómetro |
| `lugares_wifi.json` | Lugares de la PC y sus huellas Wi-Fi |

## API del servidor

| Ruta | Uso |
|---|---|
| `GET /api/nodes` | Estado y nodos (posición, batería, detector) |
| `GET /api/info` | Información del dispositivo |
| `POST /api/ping` | Ping al nodo |
| `GET /api/acel?segundos=60` | Historial de aceleración (gráfica) |
| `GET /api/impacto/historial` | Eventos guardados |
| `POST /api/impacto/reset`, `/api/impacto/umbral` | Borrar alarma / cambiar dif. mínima |
| `GET/POST /api/calibracion/...` | Calibración de 6 caras |
| `GET /api/ruta?desde=lat,lon&hasta=lat,lon&modo=pie` | Ruta |
| `GET /api/mi_ubicacion`, `POST /api/mi_ubicacion/fijar` | Ubicación de la PC por Wi-Fi |
| `GET /api/connection`, `POST /api/connect`, `GET /api/ble/scan`, `GET /api/ports` | Conexión |
