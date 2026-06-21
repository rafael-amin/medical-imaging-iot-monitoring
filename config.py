# config.py
# Medical Equipment Remote Monitoring Platform
# Hospital Imaging Infrastructure — Connected Service Architecture
#
# Standards implemented:
#   IEC 60601-1    — Medical electrical equipment safety
#   IEC 60601-2-44 — Particular requirements for CT scanners
#   ISO 13485      — Quality management for medical devices
#   DICOM          — Equipment status parameters (operational only)
#
# Real data sources:
#   DMI API        — Danish Meteorological Institute
#                    Real Danish outdoor temp/humidity
#                    Drives room environment simulation
#
# Author: Md Rafael Amin
# Self-initiated technical development project — 2025

# ── BROKER ────────────────────────────────────────────────────────────────────
BROKER_HOST      = 'localhost'
BROKER_PORT      = 1883
PUBLISH_INTERVAL = 2

# ── DMI API — Real Danish Weather ─────────────────────────────────────────────
# Free open data — dmi.dk/friedata/guides/general-guidelines/
# Register free at dmi.dk to get API key
# Used to drive realistic room environment simulation
# Hospital HVAC load is higher in summer — real pattern
DMI_API_KEY  = 'YOUR_FREE_DMI_API_KEY'
DMI_STATION  = '06074'    # Aarhus Airport weather station
DMI_URL      = (
    'https://dmigw.govcloud.dk/v2/metObs/collections/'
    'observation/items?api-key={key}'
    '&stationId={station}&limit=1'
    '&parameterId=temp_dry,humidity'
    '&datetime=2024-01-01T00:00:00Z/..'
)

# Fallback — used when DMI API unavailable
# Based on real Aarhus annual averages
DEFAULT_OUTDOOR_TEMP     = 8.5
DEFAULT_OUTDOOR_HUMIDITY = 78.0

# ── IEC 60601-1 ENVIRONMENT THRESHOLDS ───────────────────────────────────────
# IEC 60601-1 Table 1 — Normal operating conditions
# Every certified medical device must operate within these

ROOM_TEMP_MIN      = 18.0   # °C — IEC 60601-1 minimum
ROOM_TEMP_MAX      = 24.0   # °C — recommended maximum
ROOM_TEMP_ALARM    = 27.0   # °C — equipment at risk
ROOM_TEMP_CRITICAL = 30.0   # °C — IEC 60601-1 absolute maximum

ROOM_HUMIDITY_MIN      = 20.0   # %RH — IEC 60601-1 minimum
ROOM_HUMIDITY_MAX      = 60.0   # %RH — recommended maximum
ROOM_HUMIDITY_CRITICAL = 75.0   # %RH — IEC 60601-1 absolute maximum

# ── IEC 60601-2-44 CT SCANNER THRESHOLDS ─────────────────────────────────────
# Particular requirements for CT X-ray equipment
# Values based on Siemens SOMATOM service specifications
# X-ray tube replacement cost: DKK 400,000+
# Thermal protection prevents catastrophic tube failure

TUBE_TEMP_IDLE     = 35.0   # °C — normal idle
TUBE_TEMP_SCAN     = 45.0   # °C — normal during scan
TUBE_TEMP_WARN     = 42.0   # °C — elevated — monitor
TUBE_TEMP_ALARM    = 48.0   # °C — thermal protection may engage
TUBE_TEMP_CRITICAL = 52.0   # °C — shutdown — tube damage risk

COOLANT_TEMP_NORMAL = 28.0  # °C — normal coolant
COOLANT_TEMP_WARN   = 35.0  # °C — cooling degrading
COOLANT_TEMP_ALARM  = 40.0  # °C — cooling fault

# ── DR X-RAY THRESHOLDS ───────────────────────────────────────────────────────
# Fujifilm FDR D-EVO flat panel detector specifications
# Based on real Fujifilm service manual parameters
# Your direct field experience with these systems

DETECTOR_TEMP_LOW  = 15.0   # °C — condensation risk
DETECTOR_TEMP_HIGH = 35.0   # °C — dark current increases

# Calibration intervals — ISO 13485 traceable
# Non-compliance = regulatory finding in Danish accreditation
DR_FLAT_FIELD_INTERVAL = 720    # hours — 30 days
DR_GAIN_CAL_INTERVAL   = 4380   # hours — 6 months
DR_FULL_PM_INTERVAL    = 8760   # hours — 12 months

# Daily workload thresholds
DR_DAILY_WARN  = 200   # exposures/day — high workload
DR_DAILY_ALARM = 300   # exposures/day — very high — detector wear

# ── UPS THRESHOLDS ────────────────────────────────────────────────────────────
# Hospital UPS — Eaton 9PX specifications
# Power failure during CT scan = patient safety incident
# Biomedical engineering teams monitor these values daily

UPS_BATTERY_GOOD     = 80.0   # % — healthy
UPS_BATTERY_WARN     = 60.0   # % — schedule replacement
UPS_BATTERY_ALARM    = 40.0   # % — replace urgently
UPS_BATTERY_CRITICAL = 20.0   # % — imminent failure

UPS_RUNTIME_GOOD     = 30.0   # minutes — adequate
UPS_RUNTIME_WARN     = 15.0   # minutes — marginal
UPS_RUNTIME_CRITICAL = 5.0    # minutes — critical

# EN 50160 power quality — same standard as wind project
# Hospital receives grid power subject to same limits
UPS_INPUT_VOLT_LOW  = 207.0   # V
UPS_INPUT_VOLT_HIGH = 253.0   # V

# ── MRI SCANNER THRESHOLDS ───────────────────────────────────────────────────
# Siemens MAGNETOM Altea 1.5T / Prisma 3T specifications
# Most critical asset in imaging department
# Replacement cost: DKK 8,000,000–25,000,000
#
# CRYOGENIC SYSTEM — superconducting magnet at 4 Kelvin (-269°C)
# Liquid helium bathes superconducting coil windings
# Quench = sudden boil-off of all liquid helium → magnetic field collapse
# Quench causes: scan failure, potential patient harm, DKK 500,000+ damage
# Helium refill cost: DKK 50,000–100,000 per event
#
# Sources:
#   mriquestions.com — liquid helium and quench documentation
#   UCSF Radiology — magnet quench safety protocol
#   Medical Imaging Source — helium level monitoring procedures
#   IEC 60601-2-33 — MR equipment safety requirements

# Helium level — % of cryostat capacity
# Source: Medical Imaging Source — "Maintain levels above 60%"
MRI_HELIUM_GOOD       = 80.0   # % — healthy level
MRI_HELIUM_WARN       = 60.0   # % — service engineer contact required
MRI_HELIUM_ALARM      = 40.0   # % — refill urgently — quench risk elevated
MRI_HELIUM_CRITICAL   = 20.0   # % — imminent quench risk

# Cryostat pressure — helium vapour pressure in vessel
# Normal operating: slight positive pressure 0.0–0.5 bar gauge
# Pressure rise = cooling system fault or helium boil-off
MRI_CRYO_PRESS_NORMAL = 0.3    # bar gauge — normal
MRI_CRYO_PRESS_WARN   = 0.8    # bar gauge — elevated
MRI_CRYO_PRESS_ALARM  = 1.2    # bar gauge — fault condition
MRI_CRYO_PRESS_CRIT   = 2.0    # bar gauge — burst disk risk

# Cold head temperature — two-stage cryocooler
# Stage 1: ~50K  Stage 2: ~4.2K (liquid helium temperature)
# Zero Boil-Off (ZBO) systems — standard since 2010s
# Cold head compressor requires annual maintenance
MRI_COLDHEAD_TEMP_GOOD = 4.5   # K — normal operating (4.2K = liquid He)
MRI_COLDHEAD_TEMP_WARN = 6.0   # K — elevated — cryocooler check
MRI_COLDHEAD_TEMP_ALARM= 8.0   # K — fault — helium boiling off faster

# Gradient coil temperature — water-cooled system
# Gradient coils generate intense heat during scanning sequences
# Particularly EPI (Echo Planar Imaging) and DWI protocols
# Source: Patent US8564292 — gradient coil cooling control
MRI_GRADIENT_TEMP_NORM = 35.0  # °C — normal operating
MRI_GRADIENT_TEMP_WARN = 42.0  # °C — elevated — cooling check
MRI_GRADIENT_TEMP_ALARM= 48.0  # °C — duty cycle reduction required
MRI_GRADIENT_TEMP_CRIT = 55.0  # °C — thermal protection — scan stop

# RF amplifier temperature
# Transmit RF chain generates heat proportional to duty cycle
MRI_RF_TEMP_NORM  = 38.0   # °C — normal
MRI_RF_TEMP_WARN  = 45.0   # °C — elevated
MRI_RF_TEMP_ALARM = 52.0   # °C — fault

# Magnetic field strength — Tesla
# Should be stable to ±0.0001T under normal conditions
# Sudden field change = quench indicator
MRI_FIELD_NOMINAL = 1.5    # T — for 1.5T scanner (MAGNETOM Altea)
MRI_FIELD_WARN    = 0.01   # T deviation — elevated
MRI_FIELD_ALARM   = 0.1    # T deviation — significant drift

# Chiller water temperature — gradient and RF cooling loop
# Chilled water inlet to gradient coil assembly
MRI_CHILLER_INLET_NORM = 18.0  # °C — normal chilled water supply
MRI_CHILLER_INLET_WARN = 22.0  # °C — chiller efficiency degrading
MRI_CHILLER_INLET_ALARM= 26.0  # °C — cooling fault

# Oxygen level in MRI room — safety critical
# Helium quench displaces oxygen — ASPHYXIATION RISK
# Source: pureairemonitoring.com — MRI helium safety
# IEC 60601-2-33 requires O2 monitoring in MRI rooms
O2_LEVEL_SAFE     = 20.9   # % — normal atmospheric oxygen
O2_LEVEL_WARN     = 19.5   # % — slight depletion — investigate
O2_LEVEL_ALARM    = 18.0   # % — dangerous — evacuate room
O2_LEVEL_CRITICAL = 16.0   # % — immediately life-threatening

# ── MAINTENANCE INTERVALS ─────────────────────────────────────────────────────
# ISO 13485 — documented maintenance schedule required
# Based on real manufacturer PM specifications
# These are intervals you as a field engineer would schedule

MAINTENANCE_INTERVALS = {
    'ct_scanner':   4380,    # hours — 6 months
    'dr_xray':      8760,    # hours — 12 months annual PM
    'ups':          2190,    # hours — 3 months battery check
    'environment':  8760,    # hours — 12 months sensor cal
    'mri_scanner':  4380,    # hours — 6 months
                             # cold head compressor service
                             # gradient coil inspection
                             # RF calibration
                             # helium level check and top-up assessment
                             # shim adjustment verification
}

# ── DEVICE NODES ──────────────────────────────────────────────────────────────
# Five devices — one hospital imaging department
# Topic structure mirrors DICOM hierarchical naming:
#   HOSPITAL / DEPARTMENT / DEVICE / DATA_TYPE

NODES = [
    {
        'id':              'HOSP01.IMG01.CT01',
        'name':            'CT Scanner — Imaging Room 1',
        'type':            'ct_scanner',
        'manufacturer':    'Siemens Healthineers',
        'model':           'SOMATOM go.Up',
        'port':            5020,
        'topic_telemetry': 'HOSP01/IMG01/CT01/TELEMETRY',
        'topic_state':     'HOSP01/IMG01/CT01/STATE',
        'topic_alarm':     'HOSP01/IMG01/CT01/ALARM',
        'topic_heartbeat': 'HOSP01/IMG01/CT01/HEARTBEAT',
    },
    {
        'id':              'HOSP01.IMG01.DR01',
        'name':            'DR X-Ray System — Imaging Room 2',
        'type':            'dr_xray',
        'manufacturer':    'Fujifilm',
        'model':           'FDR D-EVO II',
        'port':            5021,
        'topic_telemetry': 'HOSP01/IMG01/DR01/TELEMETRY',
        'topic_state':     'HOSP01/IMG01/DR01/STATE',
        'topic_alarm':     'HOSP01/IMG01/DR01/ALARM',
        'topic_heartbeat': 'HOSP01/IMG01/DR01/HEARTBEAT',
    },
    {
        'id':              'HOSP01.IMG01.MRI01',
        'name':            'MRI Scanner — Imaging Room 3',
        'type':            'mri_scanner',
        'manufacturer':    'Siemens Healthineers',
        'model':           'MAGNETOM Altea 1.5T',
        'port':            5025,
        # DICOM modality code: MR
        # IEC standard: IEC 60601-2-33
        # Most critical asset — cryogenic superconducting magnet
        # Replacement cost: DKK 15,000,000–25,000,000
        'topic_telemetry': 'HOSP01/IMG01/MRI01/TELEMETRY',
        'topic_state':     'HOSP01/IMG01/MRI01/STATE',
        'topic_alarm':     'HOSP01/IMG01/MRI01/ALARM',
        'topic_heartbeat': 'HOSP01/IMG01/MRI01/HEARTBEAT',
        'topic_cryo':      'HOSP01/IMG01/MRI01/CRYOGENICS',
    },
    {
        'id':              'HOSP01.POWER01.UPS01',
        'name':            'UPS Power Backup — Imaging Wing',
        'type':            'ups',
        'manufacturer':    'Eaton',
        'model':           '9PX 11000i',
        'port':            5022,
        'topic_telemetry': 'HOSP01/POWER01/UPS01/TELEMETRY',
        'topic_state':     'HOSP01/POWER01/UPS01/STATE',
        'topic_alarm':     'HOSP01/POWER01/UPS01/ALARM',
        'topic_heartbeat': 'HOSP01/POWER01/UPS01/HEARTBEAT',
    },
    {
        'id':              'HOSP01.ENV01.ROOM01',
        'name':            'Environment Monitor — Imaging Suite',
        'type':            'environment',
        'manufacturer':    'Vaisala',
        'model':           'HMT120',
        'port':            5023,
        'topic_telemetry': 'HOSP01/ENV01/ROOM01/TELEMETRY',
        'topic_state':     'HOSP01/ENV01/ROOM01/STATE',
        'topic_alarm':     'HOSP01/ENV01/ROOM01/ALARM',
        'topic_heartbeat': 'HOSP01/ENV01/ROOM01/HEARTBEAT',
    },
]

# ISO 50001 power meter extension. Keeping this here makes gateway.py and
# edge_processor.py treat the meter as a first-class Layer 1-3 device.
try:
    from energy_config import ENERGY_NODES
    NODES.extend(ENERGY_NODES)
except ImportError:
    pass

AUTHORISED_DEVICES = {node['id'] for node in NODES}

# ── DICOM STATUS MAPPING ──────────────────────────────────────────────────────
# DICOM PS3.3 Modality Performed Procedure Step status values
# Real DICOM codes that equipment broadcasts to PACS

DICOM_STATUS_MAP = {
    'READY':       'IN PROGRESS',
    'SCANNING':    'IN PROGRESS',
    'WARMING_UP':  'SCHEDULED',
    'ERROR':       'DISCONTINUED',
    'OFFLINE':     'DISCONTINUED',
    'MAINTENANCE': 'DISCONTINUED',
}

# ── OPERATIONAL STATES ────────────────────────────────────────────────────────
OP_STATES = [
    'READY',
    'SCANNING',
    'WARMING_UP',
    'ERROR',
    'OFFLINE',
    'MAINTENANCE',
]

FAULT_PROBABILITY = 0.05
