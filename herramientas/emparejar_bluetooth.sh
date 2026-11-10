#!/usr/bin/env bash
# (Etapa Meshtastic) Empareja la PC con el nodo por Bluetooth. Con MeshCore + BLE_NO_PIN ya no hace falta.
# Cuando aparezca "Enter passkey", escribe el PIN del nodo (por defecto 123456) y Enter.
ADDR="${1:-AA:BB:CC:DD:EE:FF}"

echo "== Quitando emparejamiento anterior (si existe)"
bluetoothctl disconnect "$ADDR" > /dev/null 2>&1
bluetoothctl remove "$ADDR" > /dev/null 2>&1

echo "== Buscando el nodo $ADDR (15 s)..."
bluetoothctl --timeout 15 scan le | grep -i "$ADDR" | head -1

echo
echo "== Emparejando. Cuando diga 'Enter passkey', escribe 123456 y presiona Enter."
# KeyboardOnly obliga a pedir el PIN (emparejamiento autenticado)
bluetoothctl --agent KeyboardOnly --timeout 60 pair "$ADDR"

echo
echo "== Confiando y desconectando (para que la interfaz pueda conectarse)"
bluetoothctl trust "$ADDR" | tail -1
bluetoothctl disconnect "$ADDR" | tail -1

echo
bluetoothctl info "$ADDR" | grep -E "Name|Paired|Bonded|Trusted|Connected"
