# edge_processor.py
# Edge Intelligence — Medical Equipment Monitoring
#
# Real-world equivalent:
#   Siemens teamplay Fleet Edge Intelligence Unit
#   Hospital biomedical engineering server
#   On-premise service logic before cloud
#
# Four OT functions implemented:
#   1. IEC 60601 Classification — threshold-based severity
#   2. Asset State Machine — tracks device state transitions
#   3. Heartbeat Watchdog — detects silent device failures
#   4. Maintenance Scheduler — ISO 13485 PM tracking
#
# Standards:
#   IEC 60601-1    — medical equipment safety thresholds
#   IEC 60601-2-44 — CT scanner specific limits
#   ISO 13485      — maintenance schedule traceability
#   EN 50160       — power quality for UPS input monitoring

import json
import sqlite3
import threading
import time
from collections import deque
from datetime import datetime

import paho.mqtt.client as mqtt

from config import (
    BROKER_HOST, BROKER_PORT, NODES,
    AUTHORISED_DEVICES, MAINTENANCE_INTERVALS,
    TUBE_TEMP_WARN, TUBE_TEMP_ALARM, TUBE_TEMP_CRITICAL,
    COOLANT_TEMP_WARN, COOLANT_TEMP_ALARM,
    DR_DAILY_WARN, DR_DAILY_ALARM,
    UPS_BATTERY_WARN, UPS_BATTERY_ALARM, UPS_BATTERY_CRITICAL,
    UPS_RUNTIME_WARN, UPS_RUNTIME_CRITICAL,
    UPS_INPUT_VOLT_LOW, UPS_INPUT_VOLT_HIGH,
    ROOM_TEMP_MIN, ROOM_TEMP_MAX, ROOM_TEMP_ALARM, ROOM_TEMP_CRITICAL,
    ROOM_HUMIDITY_MIN, ROOM_HUMIDITY_MAX, ROOM_HUMIDITY_CRITICAL,
)
from energy_config import ENERGY_BASELINE, POWER_QUALITY

# ── ASSET STATE MACHINE ───────────────────────────────────────────────────────
ASSET_STATES   = {}   # {device_id: current state}
NORMAL_COUNT   = {}   # {device_id: consecutive normal readings}
AVAILABILITY   = {}   # {device_id: {running: int, total: int}}
CLEAR_AFTER    = 3    # consecutive READY readings to clear ERROR

def update_asset_state(device_id, incoming_status, severity):
    """
    Manages state transitions per device.
    Tracks availability — primary KPI for medical equipment.
    Target: 99% availability for imaging equipment.
    """
    if device_id not in AVAILABILITY:
        AVAILABILITY[device_id] = {'running': 0, 'total': 0}
    AVAILABILITY[device_id]['total'] += 1

    current = ASSET_STATES.get(device_id, 'READY')

    if incoming_status in ('ERROR', 'OFFLINE') and \
       current not in ('ERROR', 'OFFLINE'):
        ASSET_STATES[device_id] = incoming_status
        NORMAL_COUNT[device_id] = 0
        print(
            f'   → STATE CHANGE: {device_id} '
            f'{current} → {incoming_status}'
        )

    elif incoming_status == 'READY' and \
         current in ('ERROR', 'OFFLINE'):
        count = NORMAL_COUNT.get(device_id, 0) + 1
        NORMAL_COUNT[device_id] = count
        if count >= CLEAR_AFTER:
            ASSET_STATES[device_id] = 'READY'
            NORMAL_COUNT[device_id] = 0
            print(
                f'   → STATE CLEARED: {device_id} '
                f'returned to READY'
            )
    else:
        ASSET_STATES[device_id] = incoming_status

    if ASSET_STATES.get(device_id) in ('READY', 'SCANNING'):
        AVAILABILITY[device_id]['running'] += 1

    avail = AVAILABILITY[device_id]
    return round(
        avail['running'] / avail['total'] * 100, 1
    ) if avail['total'] > 0 else 100.0


# ── HEARTBEAT WATCHDOG ────────────────────────────────────────────────────────
LAST_SEEN         = {}
HEARTBEAT_TIMEOUT = 15   # seconds

def heartbeat_watchdog():
    """
    Background thread — detects silent device failures.
    Critical in hospital environments:
      Equipment offline = clinical workflow disruption
      Field engineer dispatch required
    """
    while True:
        time.sleep(5)
        now = time.time()
        for node in NODES:
            did = node['id']
            if did in LAST_SEEN:
                gap = now - LAST_SEEN[did]
                if gap > HEARTBEAT_TIMEOUT:
                    print(
                        f'⚫ DEVICE_OFFLINE │ {did} │ '
                        f'No data for {gap:.0f}s — '
                        f'check device and network'
                    )
                    ASSET_STATES[did] = 'OFFLINE'


# ── MAINTENANCE SCHEDULER ─────────────────────────────────────────────────────
RUNTIME_HOURS = {}

def check_maintenance(device_id, device_type, uptime_hours):
    """
    Flags when device is due for scheduled PM.
    ISO 13485 — documented maintenance schedule required.
    Generates work order for biomedical engineering team.
    """
    RUNTIME_HOURS[device_id] = uptime_hours
    interval = MAINTENANCE_INTERVALS.get(device_type, 8760)
    if uptime_hours > 0 and (uptime_hours % interval) < 0.1:
        print(
            f'🔧 MAINTENANCE_DUE │ {device_id} │ '
            f'{uptime_hours:.0f}h runtime │ '
            f'Schedule PM visit — ISO 13485'
        )
        return True
    return False


# ── IEC 60601 CLASSIFICATION ──────────────────────────────────────────────────
COLOURS = {
    'CRITICAL': '🔴',
    'ALARM':    '🟠',
    'WARNING':  '🟡',
    'NORMAL':   '🟢',
}

def classify(reading):
    """
    Classifies medical equipment readings against standards.

    IEC 60601-2-44 — CT X-ray tube temperature limits
    IEC 60601-1    — Operating environment limits
    ISO 13485      — Calibration compliance
    EN 50160       — Power quality for UPS input

    Returns: (severity, reason, recommended_action)
    """
    device_type = reading.get('device_type', '')

    # Route MRI to dedicated classifier
    if device_type == 'mri_scanner':
        return classify_mri(reading)

    # Route energy meter to ISO 50001 / EN 50160 classifier
    if device_type == 'energy_meter':
        return classify_energy(reading)

    # ── CT SCANNER ────────────────────────────────────────────
    if device_type == 'ct_scanner':
        tube    = reading.get('tube_temp_c', 35.0)
        coolant = reading.get('coolant_temp_c', 28.0)

        if tube >= TUBE_TEMP_CRITICAL:
            return (
                'CRITICAL',
                f'Tube overtemperature {tube}°C — '
                f'IEC 60601-2-44 limit exceeded',
                'Stop scanning immediately — '
                'check cooling system — '
                'contact Siemens Healthineers service'
            )
        if coolant >= COOLANT_TEMP_ALARM:
            return (
                'CRITICAL',
                f'Coolant temp {coolant}°C — '
                f'cooling system fault',
                'Stop scanning — inspect coolant circuit — '
                'dispatch field engineer'
            )
        if tube >= TUBE_TEMP_ALARM:
            return (
                'ALARM',
                f'Tube temperature elevated {tube}°C — '
                f'thermal protection may engage',
                'Reduce scan frequency — '
                'monitor coolant temperature'
            )
        if tube >= TUBE_TEMP_WARN or coolant >= COOLANT_TEMP_WARN:
            return (
                'WARNING',
                f'Tube={tube}°C Coolant={coolant}°C — '
                f'elevated temperatures',
                'Monitor closely — review scan protocol'
            )
        if reading.get('fault_active'):
            return (
                'ALARM',
                f'CT fault: {reading.get("fault_type")}',
                'Check error log — contact service'
            )
        return (
            'NORMAL',
            f'CT operating normally — '
            f'Tube={tube}°C within IEC 60601-2-44 limits',
            'Continue normal operation'
        )

    # ── DR X-RAY ──────────────────────────────────────────────
    elif device_type == 'dr_xray':
        det     = reading.get('detector_temp_c', 22.0)
        exp     = reading.get('exposures_today', 0)
        gain_due= reading.get('gain_cal_due', False)
        ff_due  = reading.get('flat_field_cal_due', False)

        if reading.get('fault_active'):
            return (
                'CRITICAL',
                f'DR detector fault: {reading.get("fault_type")}',
                'Take system offline — '
                'contact Fujifilm service — '
                'do not perform examinations'
            )
        if gain_due:
            return (
                'ALARM',
                'Gain calibration overdue — '
                'ISO 13485 non-compliance risk',
                'Schedule calibration immediately — '
                'image quality may be affected — '
                'contact biomedical engineering'
            )
        if exp >= DR_DAILY_ALARM:
            return (
                'ALARM',
                f'Very high daily workload: '
                f'{exp} exposures — detector wear risk',
                'Review workload — '
                'consider deferring non-urgent cases'
            )
        if ff_due:
            return (
                'WARNING',
                'Flat field calibration due',
                'Schedule flat field calibration — '
                'routine maintenance required'
            )
        if exp >= DR_DAILY_WARN:
            return (
                'WARNING',
                f'High daily workload: {exp} exposures',
                'Monitor detector temperature'
            )
        return (
            'NORMAL',
            f'DR system ready — '
            f'Detector={det}°C calibration current',
            'Continue normal operation'
        )

    # ── UPS ───────────────────────────────────────────────────
    elif device_type == 'ups':
        bat      = reading.get('battery_pct', 95.0)
        runtime  = reading.get('runtime_min', 45.0)
        on_bat   = reading.get('on_battery', False)
        inp_volt = reading.get('input_voltage_v', 230.0)

        if on_bat and bat <= UPS_BATTERY_CRITICAL:
            return (
                'CRITICAL',
                f'UPS on battery — {bat}% — '
                f'{runtime:.0f} min remaining — '
                f'imminent shutdown risk',
                'IMMEDIATE ACTION: Check mains supply — '
                'prepare for controlled shutdown if '
                'power not restored within 5 minutes — '
                'patient safety priority'
            )
        if on_bat:
            return (
                'ALARM',
                f'UPS on battery power — {bat}% — '
                f'{runtime:.0f} min remaining',
                'Investigate mains power failure — '
                'notify facilities management — '
                'prepare contingency'
            )
        if bat <= UPS_BATTERY_ALARM:
            return (
                'ALARM',
                f'UPS battery critically low: {bat}% — '
                f'replace urgently',
                'Schedule battery replacement immediately — '
                'contact Eaton service'
            )
        if not (UPS_INPUT_VOLT_LOW <= inp_volt <= UPS_INPUT_VOLT_HIGH):
            return (
                'ALARM',
                f'Input voltage {inp_volt}V outside '
                f'EN 50160 limits (207-253V)',
                'Notify facilities — check distribution board'
            )
        if bat <= UPS_BATTERY_WARN:
            return (
                'WARNING',
                f'UPS battery at {bat}% — '
                f'schedule replacement',
                'Plan battery replacement at next maintenance'
            )
        if runtime <= UPS_RUNTIME_WARN:
            return (
                'WARNING',
                f'Runtime only {runtime:.0f} min — '
                f'battery aging',
                'Assess battery replacement schedule'
            )
        return (
            'NORMAL',
            f'UPS on mains — battery {bat}% — '
            f'{runtime:.0f} min backup available',
            'Continue monitoring'
        )

    # ── ENVIRONMENT ───────────────────────────────────────────
    elif device_type == 'environment':
        temp     = reading.get('room_temp_c', 21.0)
        humidity = reading.get('room_humidity_pct', 45.0)

        if temp >= ROOM_TEMP_CRITICAL:
            return (
                'CRITICAL',
                f'Room temperature {temp}°C — '
                f'IEC 60601-1 absolute maximum exceeded',
                'IMMEDIATE: Take equipment offline — '
                'notify facilities management — '
                'check HVAC system — '
                'equipment warranty may be voided'
            )
        if humidity >= ROOM_HUMIDITY_CRITICAL:
            return (
                'CRITICAL',
                f'Humidity {humidity}% — '
                f'condensation risk on equipment',
                'Take equipment offline — '
                'notify facilities — '
                'check HVAC dehumidifier'
            )
        if temp >= ROOM_TEMP_ALARM:
            return (
                'ALARM',
                f'Room temperature {temp}°C — '
                f'above IEC 60601-1 recommended range',
                'Check HVAC — reduce room heat load — '
                'contact facilities management'
            )
        if not (ROOM_TEMP_MIN <= temp <= ROOM_TEMP_MAX):
            return (
                'ALARM',
                f'Room temperature {temp}°C outside '
                f'IEC 60601-1 range {ROOM_TEMP_MIN}-{ROOM_TEMP_MAX}°C',
                'Adjust HVAC settings — '
                'notify biomedical engineering'
            )
        if not (ROOM_HUMIDITY_MIN <= humidity <= ROOM_HUMIDITY_MAX):
            return (
                'WARNING',
                f'Humidity {humidity}% outside '
                f'IEC 60601-1 range {ROOM_HUMIDITY_MIN}-{ROOM_HUMIDITY_MAX}%',
                'Check HVAC humidity control'
            )
        return (
            'NORMAL',
            f'Environment compliant — '
            f'{temp}°C {humidity}%RH within IEC 60601-1',
            'Continue monitoring'
        )

    return ('NORMAL', 'Status OK', 'Continue monitoring')


def classify_mri(reading):
    """
    MRI scanner classification.
    IEC 60601-2-33 — MR equipment safety requirements.
    Siemens MAGNETOM service specifications.

    Priority order:
      1. Oxygen level — immediate patient/staff safety
      2. Helium level — quench risk — most expensive failure
      3. Cold head temperature — cryocooler health
      4. Gradient temperature — scanning capability
      5. RF amplifier temperature — secondary
    """
    helium    = reading.get('helium_level_pct', 87.0)
    cryo_p    = reading.get('cryo_pressure_bar', 0.3)
    coldhead  = reading.get('coldhead_temp_k', 4.5)
    gradient  = reading.get('gradient_temp_c', 35.0)
    rf_temp   = reading.get('rf_amp_temp_c', 38.0)
    o2        = reading.get('o2_level_pct', 20.9)
    status    = reading.get('status', 'READY')

    # ── OXYGEN — HIGHEST PRIORITY ──────────────────────────────
    # IEC 60601-2-33 — O2 monitoring mandatory
    # Helium quench displaces O2 — asphyxiation risk
    if o2 <= 16.0:
        return (
            'CRITICAL',
            f'OXYGEN DEPLETION {o2:.1f}% — '
            f'immediately life-threatening',
            'EVACUATE MRI ROOM IMMEDIATELY — '
            'activate emergency ventilation — '
            'do not re-enter without O2 monitor — '
            'possible magnet quench — call emergency services'
        )
    if o2 <= 18.0:
        return (
            'CRITICAL',
            f'O2 level {o2:.1f}% — dangerous — '
            f'possible helium leak or quench',
            'EVACUATE MRI ROOM — '
            'activate quench vent system — '
            'contact Siemens Healthineers emergency line'
        )
    if o2 <= 19.5:
        return (
            'ALARM',
            f'O2 level {o2:.1f}% — slight depletion — investigate',
            'Check helium vent system — '
            'do not perform scans — '
            'ventilate room — contact service engineer'
        )

    # ── QUENCH RISK STATUS ──────────────────────────────────────
    if status == 'QUENCH_RISK':
        return (
            'CRITICAL',
            f'QUENCH RISK — helium {helium:.1f}% or cryocooler fault',
            'STOP ALL SCANNING IMMEDIATELY — '
            'contact Siemens Healthineers cryogenics team — '
            'prepare quench vent — '
            'DKK 500,000+ repair cost if quench occurs'
        )

    # ── HELIUM LEVEL ────────────────────────────────────────────
    # Source: Medical Imaging Source — "maintain above 60%"
    if helium <= 20.0:
        return (
            'CRITICAL',
            f'Helium critically low: {helium:.1f}% — '
            f'quench imminent',
            'STOP SCANNING — emergency helium order — '
            'Siemens Healthineers cryogenics: immediate dispatch — '
            'DKK 50,000–100,000 refill cost'
        )
    if helium <= 40.0:
        return (
            'ALARM',
            f'Helium low: {helium:.1f}% — '
            f'schedule refill urgently',
            'Contact Siemens Healthineers service — '
            'order liquid helium — '
            'check cold head compressor performance'
        )
    if helium <= 60.0:
        return (
            'WARNING',
            f'Helium below recommended minimum: {helium:.1f}%',
            'Schedule helium level check — '
            'verify cryocooler ZBO system performance — '
            'plan refill within 2 weeks'
        )

    # ── COLD HEAD TEMPERATURE ───────────────────────────────────
    # Healthy: ~4.2-4.5K. Rising temp = ZBO failing
    if coldhead >= 8.0:
        return (
            'ALARM',
            f'Cold head temperature {coldhead:.2f}K — '
            f'cryocooler fault — helium boiling off',
            'Contact cryocooler service — '
            'monitor helium level closely — '
            'schedule cold head maintenance'
        )
    if coldhead >= 6.0:
        return (
            'WARNING',
            f'Cold head temperature elevated {coldhead:.2f}K',
            'Check cold head compressor — '
            'verify adsorber filters — '
            'plan maintenance'
        )

    # ── CRYOSTAT PRESSURE ───────────────────────────────────────
    if cryo_p >= 1.2:
        return (
            'ALARM',
            f'Cryostat pressure {cryo_p:.2f} bar — fault condition',
            'Check quench vent pathway — '
            'verify pressure relief — '
            'contact Siemens Healthineers'
        )

    # ── GRADIENT TEMPERATURE ────────────────────────────────────
    if gradient >= 55.0:
        return (
            'CRITICAL',
            f'Gradient coil overtemperature {gradient:.1f}°C — '
            f'thermal protection active',
            'Scanning stopped by thermal protection — '
            'check chilled water supply — '
            'reduce scan duty cycle'
        )
    if gradient >= 48.0:
        return (
            'ALARM',
            f'Gradient temperature {gradient:.1f}°C — '
            f'reduce scan duty cycle',
            'Limit high-gradient sequences (EPI, DWI) — '
            'check chiller inlet temperature — '
            'contact facilities if chiller fault'
        )
    if gradient >= 42.0:
        return (
            'WARNING',
            f'Gradient temperature elevated {gradient:.1f}°C',
            'Monitor — check chiller performance'
        )

    # ── RF AMPLIFIER ────────────────────────────────────────────
    if rf_temp >= 52.0:
        return (
            'ALARM',
            f'RF amplifier overtemperature {rf_temp:.1f}°C',
            'Check RF cooling — reduce SAR — contact service'
        )
    if rf_temp >= 45.0:
        return (
            'WARNING',
            f'RF amplifier temperature elevated {rf_temp:.1f}°C',
            'Monitor RF duty cycle'
        )

    return (
        'NORMAL',
        f'MRI operating normally — '
        f'He={helium:.1f}% '
        f'Grad={gradient:.1f}°C '
        f'O2={o2:.1f}%',
        'Continue normal operation'
    )


# ── DECISION LOGIC ────────────────────────────────────────────────────────────
def classify_energy(reading):
    """
    Power meter classification.
    ISO 50001:2018 energy performance monitoring and EN 50160 power quality.
    """
    active_kw = reading.get('active_power_w', 0) / 1000.0
    pf        = reading.get('power_factor', 1.0)
    freq      = reading.get('frequency_hz', 50.0)
    thd_v     = reading.get('thd_voltage_pct', 0.0)
    thd_i     = reading.get('thd_current_pct', 0.0)
    voltages  = [
        reading.get('voltage_l1_v', 230.0),
        reading.get('voltage_l2_v', 230.0),
        reading.get('voltage_l3_v', 230.0),
    ]

    if any(v < POWER_QUALITY['voltage_low'] or
           v > POWER_QUALITY['voltage_high'] for v in voltages):
        return (
            'ALARM',
            f'Voltage outside EN 50160 limits: '
            f'L1={voltages[0]:.1f}V L2={voltages[1]:.1f}V '
            f'L3={voltages[2]:.1f}V',
            'Notify facilities - inspect imaging wing distribution board'
        )
    if not (POWER_QUALITY['frequency_low'] <= freq <=
            POWER_QUALITY['frequency_high']):
        return (
            'ALARM',
            f'Grid frequency {freq:.2f}Hz outside EN 50160 limits',
            'Notify facilities - verify mains supply quality'
        )
    if thd_v > POWER_QUALITY['thd_voltage_max']:
        return (
            'ALARM',
            f'Voltage THD {thd_v:.1f}% exceeds EN 50160 limit',
            'Investigate harmonic sources - check CT/DR power electronics'
        )
    if thd_i > POWER_QUALITY['thd_current_max']:
        return (
            'WARNING',
            f'Current THD {thd_i:.1f}% elevated',
            'Monitor harmonic distortion - consider power quality analysis'
        )
    if pf < POWER_QUALITY['pf_warning']:
        return (
            'WARNING',
            f'Power factor {pf:.3f} below ISO 50001 target',
            'Review reactive load - consider power factor correction'
        )
    if active_kw > ENERGY_BASELINE['peak_demand_kw'] * 1.10:
        return (
            'WARNING',
            f'Peak demand {active_kw:.1f}kW above energy baseline',
            'Review simultaneous equipment operation - stagger high loads'
        )

    return (
        'NORMAL',
        f'Energy meter normal - P={active_kw:.1f}kW '
        f'PF={pf:.3f} THDv={thd_v:.1f}%',
        'Continue ISO 50001 monitoring'
    )


warning_batch = deque()
normal_batch  = deque()

def apply_decision_logic(reading, severity, reason, action, avail_pct):
    """
    Routes messages based on severity.
    CRITICAL — immediate local action + immediate cloud
    ALARM    — immediate cloud notification
    WARNING  — batch to cloud every 30 seconds
    NORMAL   — batch to cloud every 5 minutes
    """
    did = reading['device_id']
    col = COLOURS.get(severity, '⚪')
    sta = reading.get('status', 'UNKNOWN')

    if severity == 'CRITICAL':
        print(f'{col} CRITICAL │ {did} │ {reason}')
        print(f'   → ACTION: {action}')
        print(f'   → LOCAL RESPONSE <100ms │ '
              f'BIOMEDICAL ENGINEER: Dispatch')
        return 'LOCAL_IMMEDIATE'

    elif severity == 'ALARM':
        print(f'{col} ALARM    │ {did} │ {reason}')
        print(f'   → ACTION: {action}')
        return 'CLOUD_IMMEDIATE'

    elif severity == 'WARNING':
        print(f'{col} WARNING  │ {did} │ {reason}')
        warning_batch.append({**reading, 'severity': severity})
        return 'CLOUD_BATCH_30S'

    else:
        print(
            f'{col} NORMAL   │ {did} │ '
            f'[{sta}] │ avail={avail_pct}%'
        )
        normal_batch.append({**reading, 'severity': severity})
        return 'CLOUD_BATCH_5MIN'


# ── DATABASE ──────────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect('medical_monitor.db')
    c = conn.cursor()

    # Main readings table — all device telemetry
    c.execute('''CREATE TABLE IF NOT EXISTS readings (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp       TEXT,
        device_id       TEXT,
        device_type     TEXT,
        manufacturer    TEXT,
        model           TEXT,
        status          TEXT,
        severity        TEXT,
        action_taken    TEXT,
        availability_pct REAL,
        fault_active    INTEGER,
        fault_type      TEXT,
        primary_value   REAL,
        secondary_value REAL,
        notes           TEXT
    )''')

    # Alarms table — ISO 13485 traceability
    c.execute('''CREATE TABLE IF NOT EXISTS alarms (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp    TEXT,
        device_id    TEXT,
        severity     TEXT,
        reason       TEXT,
        action       TEXT,
        state        TEXT DEFAULT 'ACTIVE',
        resolved_at  TEXT
    )''')

    # Maintenance log — ISO 13485 compliance record
    c.execute('''CREATE TABLE IF NOT EXISTS maintenance_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp   TEXT,
        device_id   TEXT,
        device_type TEXT,
        event_type  TEXT,
        description TEXT,
        engineer    TEXT DEFAULT 'SYSTEM'
    )''')

    # Security events table
    c.execute('''CREATE TABLE IF NOT EXISTS security_events (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        event     TEXT
    )''')

    conn.commit()
    conn.close()
    print('[EDGE] Database ready — medical_monitor.db')
    print('[EDGE] Tables: readings, alarms, maintenance_log, '
          'security_events')


def save_reading(reading, severity, action, avail_pct):
    """Save reading with relevant primary/secondary values per device type."""
    device_type = reading.get('device_type', '')

    # Extract primary and secondary values per device type
    if device_type == 'ct_scanner':
        primary   = reading.get('tube_temp_c', 0)
        secondary = reading.get('coolant_temp_c', 0)
        notes     = f'KV={reading.get("kv_output",0)}'
    elif device_type == 'dr_xray':
        primary   = reading.get('detector_temp_c', 0)
        secondary = reading.get('exposures_today', 0)
        notes     = (f'cal_hours={reading.get("hours_since_cal",0)}'
                     f' gain_due={reading.get("gain_cal_due",False)}')
    elif device_type == 'ups':
        primary   = reading.get('battery_pct', 0)
        secondary = reading.get('input_voltage_v', 0)
        notes     = (f'runtime={reading.get("runtime_min",0)}min'
                     f' on_bat={reading.get("on_battery",False)}')
    elif device_type == 'environment':
        primary   = reading.get('room_temp_c', 0)
        secondary = reading.get('room_humidity_pct', 0)
        notes     = (f'iec60601={reading.get("iec60601_compliant",True)}'
                     f' outdoor={reading.get("outdoor_temp_c",0)}°C')

    elif device_type == 'mri_scanner':
        primary   = reading.get('helium_level_pct', 0)
        secondary = reading.get('gradient_temp_c', 0)
        notes     = (f'coldhead={reading.get("coldhead_temp_k",0)}K'
                     f' o2={reading.get("o2_level_pct",0)}%'
                     f' cryo_p={reading.get("cryo_pressure_bar",0)}bar')
    elif device_type == 'energy_meter':
        primary   = reading.get('active_power_w', 0)
        secondary = reading.get('power_factor', 0) * 1000
        notes     = (f'energy={reading.get("energy_kwh",0)}kWh'
                     f' freq={reading.get("frequency_hz",0)}Hz'
                     f' thd_v={reading.get("thd_voltage_pct",0)}%')
    else:
        primary   = 0
        secondary = 0
        notes     = 'unknown device type'

    try:
        conn = sqlite3.connect('medical_monitor.db')
        conn.cursor().execute(
            '''INSERT INTO readings VALUES
               (NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (reading.get('timestamp'),
             reading.get('device_id'),
             device_type,
             reading.get('manufacturer', ''),
             reading.get('model', ''),
             reading.get('status', ''),
             severity, action, avail_pct,
             int(reading.get('fault_active', False)),
             reading.get('fault_type'),
             primary, secondary, notes)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f'[EDGE] DB error: {e}')


# ── SECURITY MONITORING ───────────────────────────────────────────────────────
SECURITY_EVENTS = []

def check_security(device_id, topic, payload_size):
    """
    Basic OT security baseline monitoring.
    In hospital networks — unauthorised devices are a
    cybersecurity and regulatory compliance risk.
    GDPR + NIS2 Directive applicable to healthcare.
    """
    ok = True
    if device_id not in AUTHORISED_DEVICES:
        msg = (f'UNKNOWN_DEVICE: {device_id} — '
               f'not in authorised device baseline')
        print(f'🔒 SECURITY │ {msg}')
        SECURITY_EVENTS.append({
            'time': datetime.now().isoformat(),
            'event': msg
        })
        ok = False

    parts = topic.split('/')
    if len(parts) < 4:
        msg = f'INVALID_TOPIC: {topic}'
        print(f'🔒 SECURITY │ {msg}')
        ok = False

    if payload_size > 4096:
        msg = f'LARGE_PAYLOAD: {payload_size}B from {device_id}'
        print(f'🔒 SECURITY │ {msg}')
        ok = False

    return ok


# ── MQTT CALLBACKS ────────────────────────────────────────────────────────────

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        for node in NODES:
            client.subscribe('HOSP01/#')
        print('[EDGE] Connected — subscribed to HOSP01/#')
        print('[EDGE] Medical equipment edge controller active')
    else:
        print(f'[EDGE] Connection failed: {rc}')


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode('utf-8'))
    except Exception:
        print(f'[EDGE] Bad payload: {msg.topic}')
        return

    topic      = msg.topic
    device_id  = payload.get('device_id', 'UNKNOWN')
    topic_type = topic.split('/')[-1] if '/' in topic else 'UNKNOWN'

    # Security check
    check_security(device_id, topic, len(msg.payload))

    # Update heartbeat timestamp
    LAST_SEEN[device_id] = time.time()

    # Route by topic type
    if topic_type == 'HEARTBEAT':
        return

    if topic_type == 'STATE':
        print(
            f'[EDGE] STATE │ {device_id} │ '
            f'{payload.get("previous")} → {payload.get("state")}'
        )
        return

    if topic_type == 'TELEMETRY':
        # Classify against IEC 60601 thresholds
        severity, reason, action = classify(payload)

        # Update state machine
        avail_pct = update_asset_state(
            device_id,
            payload.get('status', 'READY'),
            severity
        )

        # Route message
        action_taken = apply_decision_logic(
            payload, severity, reason, action, avail_pct
        )

        # Check maintenance schedule
        uptime = payload.get('uptime_hours', 0)
        if uptime:
            check_maintenance(
                device_id,
                payload.get('device_type', ''),
                uptime
            )

        # Save to database
        save_reading(payload, severity, action_taken, avail_pct)


def run():
    init_db()

    # Start heartbeat watchdog
    threading.Thread(
        target=heartbeat_watchdog,
        daemon=True
    ).start()
    print('[EDGE] Heartbeat watchdog started — '
          f'timeout: {HEARTBEAT_TIMEOUT}s')

    client = mqtt.Client(client_id='medical_edge_processor')
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
    except ConnectionRefusedError:
        print('[EDGE] Run mosquitto -v first')
        return

    print('[EDGE] Medical equipment edge controller running. '
          'Ctrl+C to stop.')
    client.loop_forever()


if __name__ == '__main__':
    run()
