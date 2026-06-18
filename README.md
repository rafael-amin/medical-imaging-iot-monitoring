# medical-imaging-iot-monitoring
IoT monitoring system for hospital medical imaging devices  CT, MRI, and X-ray with IEC 60601-2-44 thermal management logic and fault classification
# Medical Imaging IoT Monitoring System

A self-initiated technical project building a connected monitoring platform for a simulated hospital imaging department. The system covers CT, MRI, and DR X-ray devices, with IEC 60601-2-44 compliant thermal management logic, fault classification, and a service engineering reference layer documenting subsystem architecture and failure modes.

This project was built to develop and demonstrate working knowledge of medical imaging system behaviour relevant to field service engineering. It does not replace hands-on hardware experience but reflects independent technical study of the systems a medical imaging FSE works with daily.

System design, architecture decisions, and engineering logic are the author's own work. Implementation was completed with AI coding assistance.

---

## Why This Project Exists

Field service engineering for medical imaging requires understanding system behaviour at a subsystem level, not just following a checklist. After 4.5 years commissioning Fujifilm and Shimadzu systems across 50+ hospital sites, this project was built to extend that understanding into CT system monitoring, thermal management, and fault classification logic, the kind of knowledge that separates reactive maintenance from proactive service engineering.

---

## Current Project Status

**What is built and working now:**

- CT scanner thermal monitoring logic with IEC 60601-2-44 compliant thresholds
- Modbus TCP register map for CT scanner parameters mirroring real service interfaces
- Fault classification engine for CT subsystem faults by severity and type
- Medical imaging engineering reference document covering CT, MRI, DR X-ray, UPS, Environmental Monitor, and Smart Power Meter subsystem architecture

**What is planned and in development:**

- MQTT telemetry pipeline connecting device layer to monitoring layer
- MRI and DR X-ray monitoring nodes
- InfluxDB time-series data storage
- Grafana dashboard for real-time visualisation
- CT subsystem fault tree with service action mapping
- IQ/OQ qualification protocol documentation

---

## System Architecture

The platform is structured in five layers:

**Device Layer** — Simulated medical imaging devices. Each device exposes parameters via Modbus TCP register maps mirroring real service interfaces.

**Edge Processing Layer** — Local monitoring logic running IEC 60601-2-44 compliant thermal threshold checks, scan cycle cooling protocol validation, and real-time fault detection.

**Fault Classification Engine** — Classifies faults by subsystem and severity. Fault categories cover thermal warnings, cooling failures, tube protection triggers, and system level errors.

**Data Pipeline** — MQTT-based telemetry transport from device layer to monitoring layer. Planned, in development.

**Reference Documentation Layer** — Technical documentation covering CT subsystem architecture, electromechanical components, service engineering perspective, and failure mode analysis.

---

## CT Scanner — Technical Focus

The CT scanner node is the most detailed component, reflecting the service engineering depth required for CT field service roles.

### Monitored Parameters

| Parameter | Register | Normal Range | Warning Threshold | Critical Threshold |
|---|---|---|---|---|
| Tube Temperature | 40001 | 0 to 45 deg C | 48 deg C | 52 deg C |
| Coolant Temperature | 40002 | 0 to 40 deg C | 44 deg C | 48 deg C |
| Anode Rotation Speed | 40003 | 8000 to 10800 RPM | Below 8000 RPM | Below 7000 RPM |
| kV Setting | 40004 | 80 to 140 kV | Outside range | Outside range |
| mA Setting | 40005 | 50 to 400 mA | Outside range | Outside range |
| Heat Units Accumulated | 40006 | 0 to 3,500,000 HU | 3,200,000 HU | 3,500,000 HU |

### IEC 60601-2-44 Thermal Management Logic

IEC 60601-2-44 is the international standard governing the safety of CT X-ray equipment. The standard defines requirements for X-ray tube thermal protection, cooling system performance, and patient dose management.

This system implements:

- Continuous tube temperature monitoring against IEC 60601-2-44 thermal limits
- Scan cycle cooling protocol enforcing minimum cooling intervals between scans based on accumulated heat units
- Coolant temperature lag detection flagging conditions where coolant temperature lags tube temperature beyond expected differential
- Tube protection trigger logic simulating the system behaviour that protects the tube from thermal damage

### Why 52 Degrees Celsius Matters

At 52 degrees Celsius the X-ray tube approaches the critical thermal limit where anode bearing lubrication degrades and structural damage becomes a risk. A real CT scanner will trigger a tube protection lockout at this threshold. The cost of X-ray tube replacement is typically 300,000 to 500,000 DKK. Proactive thermal monitoring is one of the most important aspects of CT preventive maintenance.

---

## CT Subsystem Architecture — Service Engineering Perspective

### X-Ray Tube Assembly

The most critical and expensive component. Consists of the rotating anode, cathode filament, focusing cup, vacuum envelope, and oil cooling system.

Common failures: anode bearing wear, filament degradation, cooling system leaks, vacuum seal failure.

Service indicator: tube temperature exceeding 48 degrees Celsius warning threshold during normal operation suggests cooling system degradation before critical failure.

### High Voltage Generator

Generates the kV and mA required for X-ray production. Contains high voltage transformer, rectifier stack, filament supply, and kV and mA control electronics.

Common failures: kV regulation drift, mA instability, arc faults during high-power scans, control board failures.

### Gantry and Slip Ring Assembly

The rotating frame carrying the X-ray tube and detector array. Slip rings provide electrical continuity between rotating and stationary sections.

Common failures: slip ring contact wear causing data transmission errors and image artefacts, belt wear, bearing degradation.

### Cooling System

Oil-based cooling circuit removing heat from the X-ray tube. Consists of coolant pump, heat exchanger, PT100 RTD temperature sensors, and flow monitoring.

Common failures: pump degradation, heat exchanger fouling, coolant contamination, sensor drift.

Service indicator: coolant temperature approaching warning threshold during normal scan protocols, or temperature differential between tube and coolant outside expected range.

### Detector Array

Converts X-ray photons to electrical signals. Scintillator crystal arrays coupled to photodiodes processed by the Data Acquisition System.

Common failures: dead detector channels causing ring artefacts, DAS electronics faults, calibration drift.

### Patient Table

Motorised table with position encoder for precise patient positioning. Drive system uses servo motor and ball screw mechanism.

Common failures: position encoder drift, drive belt wear, limit switch failure.

---

## Devices in the Reference Document

| Device | Key Parameters | Relevant Standard |
|---|---|---|
| CT Scanner | Tube temperature, coolant temp, anode speed, kV, mA, heat units | IEC 60601-2-44 |
| MRI Scanner | Magnet temperature, gradient coil temp, RF power, helium level, SAR | IEC 60601-2-33 |
| DR X-Ray | Detector temperature, kV, mA, dose area product | IEC 60601-2-54 |
| UPS | Battery level, charge status, input and output voltage | IEC 62040 |
| Environmental Monitor | Room temperature, humidity, air pressure | ISO 14644 |
| Smart Power Meter | Active power, reactive power, power factor, THD | EN 50160 |

---

## Technology Used

| Component | Technology |
|---|---|
| Device simulation | Python, Modbus TCP |
| Thermal monitoring logic | Python |
| Fault classification | Python rule engine |
| Reference documentation | HTML, Markdown |
| Data pipeline (planned) | MQTT, Mosquitto broker |
| Storage (planned) | InfluxDB |
| Visualisation (planned) | Grafana |

---

## About

Built by Md. Rafael Amin, Electrical Engineer, MSc Aarhus University 2025, with 4.5 years field service experience on Fujifilm and Shimadzu medical imaging systems across 50+ hospital sites in Bangladesh.

LinkedIn: linkedin.com/in/rafael-amin-293443118

Contact: rafaelamin28@gmail.com
