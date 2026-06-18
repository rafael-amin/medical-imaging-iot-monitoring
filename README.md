# Medical IoT Monitoring Platform

Remote monitoring platform for a simulated hospital imaging department, built in Python to demonstrate device telemetry, gateway communication, edge intelligence, medical equipment fault classification, and energy monitoring.

This is a self-initiated engineering portfolio project by Md Rafael Amin, combining medical imaging field service experience with IoT, edge processing, and healthcare infrastructure monitoring.

## Current Status

Layers 1 to 3 are completed and running locally on Windows.

| Layer | Status | Description |
|---|---|---|
| Layer 1 - Device Simulators | Complete | Six simulated hospital devices generate live Modbus TCP data |
| Layer 2 - IoT Gateway | Complete | Gateway reads all devices and publishes telemetry to MQTT |
| Layer 3 - Edge Processor | Complete | Edge logic classifies readings, tracks states, monitors heartbeat, and logs to SQLite |
| Layer 4 - Azure IoT Hub | Planned | Future cloud integration |
| Layer 5 - InfluxDB + Grafana | Planned | Future dashboard and time-series visualisation |

## Working Local System

The system simulates six devices in a hospital imaging department:

| Device | Script | Port | Main Parameters |
|---|---|---:|---|
| CT Scanner | `simulated_plc.py --node ct` | 5020 | Tube temperature, coolant temperature, scan state |
| DR X-ray | `simulated_plc.py --node dr` | 5021 | Detector temperature, exposure count, calibration status |
| UPS | `simulated_plc.py --node ups` | 5022 | Battery level, input voltage, runtime |
| Environmental Monitor | `simulated_plc.py --node env` | 5023 | Room temperature, humidity, IEC 60601 compliance |
| Smart Power Meter | `energy_meter_plc.py` | 5024 | Active power, power factor, kWh, THD |
| MRI Scanner | `mri_plc.py` | 5025 | Helium level, cryo pressure, gradient temperature, O2 safety |

## Architecture

```text
Layer 1: Device Simulators
  Python Modbus TCP servers
  CT, DR, UPS, environment, MRI, and smart power meter

Layer 2: IoT Gateway
  gateway.py
  Reads Modbus registers from all devices
  Publishes JSON telemetry to MQTT

Layer 3: Edge Intelligence
  edge_processor.py
  Classifies readings against safety and operational thresholds
  Tracks device state
  Runs heartbeat watchdog
  Logs readings to SQLite
