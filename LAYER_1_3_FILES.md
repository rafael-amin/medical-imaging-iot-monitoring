# Layer 1-3 Runtime Files

These are the exact Python files needed to run Layers 1-3 completely.

## Layer 1 - Device Simulators

- `simulated_plc.py` - CT, DR X-ray, UPS, and environment Modbus simulators.
- `mri_plc.py` - MRI Modbus simulator.
- `energy_meter_plc.py` - Siemens SENTRON-style power meter simulator.

## Layer 2 - Gateway

- `gateway.py` - polls all six Modbus devices and publishes MQTT telemetry.

## Layer 3 - Edge Processor

- `edge_processor.py` - subscribes to MQTT, classifies readings, watches heartbeats,
  tracks states, schedules maintenance, and writes SQLite records.

## Shared Runtime Dependencies

- `config.py` - core device nodes, ports, MQTT topics, and medical thresholds.
- `energy_config.py` - power meter node and ISO 50001 / EN 50160 thresholds.
- `data_client.py` - DMI weather enrichment with seasonal fallback.

## Not Required To Run Layers 1-3

- `analytics.py` - offline report after data exists.
- `energy_analytics.py` - offline ISO 50001 report after energy data exists.
- `cloud_client.py` - Layer 4 Azure IoT Hub.
- `influx_writer.py` - Layer 5 InfluxDB writer.

## External Services Needed

- Mosquitto MQTT broker on `localhost:1883`.
- Python packages from `requirements.txt`: for Layers 1-3 the required packages are
  `pymodbus`, `paho-mqtt`, and `requests`.
