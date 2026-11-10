# Avance del proyecto

Bitácora por etapas del desarrollo del Sistema de Respuesta Inmediata (SRI) con el nodo **RABANITO**
(Seeed SenseCAP T1000-E). Fechas en hora de Monterrey (CST).

| Etapa | Fecha | Resultado |
|---|---|---|
| 1. Interfaz base con Meshtastic (USB) | 5 nov 2026 | Mapa, telemetría y ping funcionando |
| 2. Bluetooth y "visto por última vez" | 5-6 nov 2026 | Conexión inalámbrica estable; última posición guardada |
| 3. Migración a MeshCore | 9 nov 2026 | Nodo con MeshCore v1.18.0; radio en 915 MHz |
| 4. Detector de caídas (v1) | 9 nov 2026 | Firmware propio que usa el acelerómetro |
| 5. Detector v2, gráfica y calibración | 9-10 nov 2026 | Algoritmo pico - reposo, ±32 g, calibración de 6 caras |
| 6. Ruta, interfaz tipo Excel y GitHub | 10 nov 2026 | Ruta automática, eventos en CSV, repositorio público |
| 7. Terreno y elevación (MapLibre) | 10 nov 2026 | Mapa 3D con relieve, alturas y perfil de la ruta |

---

## Etapa 1 - Interfaz base con Meshtastic por USB (5 nov)

- Servidor en Python (Flask) con la librería oficial `meshtastic`; página web con mapa Leaflet.
- Modo **demo** con nodos simulados para trabajar sin hardware.
- Coordenadas en decimal y grados/minutos/segundos, con botones Copiar y Google Maps.
- **Ping** al nodo con prueba de que la respuesta es real: el ID del paquete de respuesta coincide con el enviado.
- Uptime en vivo e información del dispositivo (ID único del chip, MAC, firmware, radio).
- GPS del nodo activado (venía apagado de fábrica).

## Etapa 2 - Bluetooth y "visto por última vez" (5-6 nov)

- Conexión por **Bluetooth** desde Linux. Problemas encontrados y resueltos (detalle en [conexion.md](conexion.md)):
  - `bleak` 3.x se colgaba: se fijó `bleak` 1.x.
  - El Bluetooth del nodo con PIN no respondía desde Linux: se usó modo sin PIN.
  - Enlaces Bluetooth "medio abiertos" que impedían reconectar: el servidor los cierra antes de conectar.
- **Visto por última vez**: la última posición GPS se guarda en disco y se muestra aunque el GPS pierda señal.
- Horas en **CST**, tema **claro/oscuro**, fuente monoespaciada, paleta blanco/negro con azul y rojo.
- Panel para **cambiar entre USB y Bluetooth** sin reiniciar el servidor.
- Nombre del nodo: **RABANITO (RABA)**.
- Incidencia: el nodo entró dos veces en un ciclo de reinicios cada 101 s; se resolvió apagándolo por completo.

## Etapa 3 - Migración a MeshCore (9 nov)

- El nodo se flasheó con **MeshCore v1.18.0** (companion). La interfaz se adaptó con la librería `meshcore`.
- MeshCore entrega además **temperatura** y **luz** (lux).
- La radio venía en **869.6 MHz** (banda europea); se cambió a **915 MHz**, dentro de la banda permitida en México
  (902-928 MHz).
- Se sincroniza la hora del nodo con la PC en cada conexión.

## Etapa 4 - Detector de caídas, primera versión (9 nov)

- El MeshCore oficial **no usa el acelerómetro** del T1000-E (QMA6100P): se escribió un **firmware modificado**
  (`v1.18.0-rabanito`) que lo lee 50 veces por segundo.
- Primera versión: alerta cuando la aceleración pasa un umbral; distingue caída (con caída libre antes) y golpe.
- La alarma queda **enganchada** en el nodo hasta que la interfaz la borra.
- En la interfaz: **foco rojo** junto a "este nodo", alarma sonora y registro de eventos en disco.
- Versión **Bluetooth** del firmware sin PIN en el canal de datos (la actualización por Bluetooth sigue con PIN).

## Etapa 5 - Detector v2, gráfica en vivo y calibración (9-10 nov)

- **Algoritmo v2** (propuesto en este proyecto): banco de 5 s; cuando el nodo queda en reposo se compara el último
  pico con el valor en reposo y se alerta si `pico - reposo >= dif. mínima`. Así, sacudir el nodo mientras se
  carga no dispara la alarma. Ver [detector-de-caidas.md](detector-de-caidas.md).
- Pestaña **Gráfica**: aceleración en vivo; el firmware reporta el mínimo y máximo entre lecturas para que se
  vean los golpes de milisegundos.
- Rango del acelerómetro ampliado a **±32 g** (antes ±16 g, que se saturaba en golpes fuertes).
- **Calibración de 6 caras**: el eje Z tenía un offset de **0.274 g**; tras calibrar, en reposo marca **1.00 g**
  en cualquier posición.

## Etapa 6 - Ruta, interfaz tipo Excel y GitHub (10 nov)

- **Ruta automática** desde esta computadora hasta la última ubicación del nodo (a pie, en coche o línea recta),
  con distancia y tiempo; se dibuja sola y se destaca al detectar una caída.
- La PC no tiene GPS: se ubica **reconociendo lugares por sus redes Wi-Fi** (todo local).
- Interfaz reorganizada **al estilo Excel**: cinta de opciones, barra de fórmulas, hojas abajo
  (Mapa, Gráfica, Eventos, Dispositivo) y barra de estado. Ver [interfaz.md](interfaz.md).
- Hoja **Eventos** con exportación a **CSV** para análisis en Excel.
- Código publicado en GitHub.

## Etapa 7 - Terreno y elevación con MapLibre (10 nov)

- Hoja **Terreno** con **MapLibre GL 5.24** (guardado en el proyecto): mapa en 3D, sombreado de relieve,
  ruta y marcadores.
- Elevación con **AWS Terrain Tiles** (gratis, sin clave). El servidor calcula la altura de cualquier punto
  con interpolación bilineal.
- Altura del nodo y de la PC, y **perfil de elevación de la ruta** con subida/bajada acumulada y pendiente.
- Ejemplo real: nodo a 654 m (GPS: 700 m), PC a 386 m; ruta de 38 km a pie que sube 558 m y baja 290 m.

---

## Resultados de las pruebas (hasta el 10 nov)

Pruebas manuales (dejar caer y golpear el nodo sobre la mesa y superficies blandas), registradas por el detector:

| Tipo | Eventos | Pico promedio | Pico mínimo | Pico máximo |
|---|---|---|---|---|
| Caída | 14 | 12.08 g | 5.37 g | 23.96 g |
| Golpe | 21 | 16.12 g | 2.59 g | 37.78 g |
| **Total** | **35** | | | |

- Diferencia pico - reposo (eventos del algoritmo v2): promedio **14.93 g**, máxima **36.78 g**.
- Los primeros eventos son del algoritmo v1 y del rango ±16 g; los posteriores usan ±32 g y la calibración.
- Son pruebas con el nodo solo, no con una persona: sirven para calibrar, no como validación clínica.

## Pendientes y siguientes pasos

- Ajustar la clasificación caída/golpe para **caídas de personas** (en el cuerpo la caída libre no llega a ~0 g;
  probar límite de 0.5-0.6 g y exigir que termine poco antes del pico).
- Guardar la dif. mínima y la calibración **en la memoria del nodo** (hoy se pierden al reiniciarlo; la interfaz
  reenvía la calibración al conectar).
- **Enviar la alerta por la malla LoRa** a otros nodos MeshCore, no solo a la PC conectada.
- Probar el GPS en exteriores y medir el tiempo hasta la primera posición.
- Volver a usar el **PIN de Bluetooth** si se encuentra cómo emparejar con PIN desde Linux (BlueZ).
- Pruebas con portador humano y definición de la dif. mínima definitiva.
