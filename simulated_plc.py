# simulated_plc.py
# Simulated Medical Equipment — Modbus TCP Server
#
# Represents the embedded controller inside hospital imaging equipment
# In real life this is the equipment's own service communication module
# Siemens SOMATOM CT, Fujifilm FDR DR, Eaton UPS, Vaisala sensors
# all expose operational data via service protocols
#
# This simulation is based on:
#   Real Fujifilm FDR service parameters (field experience)
#   IEC 60601-2-44 CT operational parameters
#   Eaton 9PX UPS specifications
#   Vaisala HMT120 sensor specifications
#
# Run four instances — one per device:
#   python simulated_plc.py --node ct       --port 5020
#   python simulated_plc.py --node dr       --port 5021
#   python simulated_plc.py --node ups      --port 5022
#   python simulated_plc.py --node env      --port 5023

import argparse
import math
import random
import threading
import time
from datetime import datetime

from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusServerContext,
    ModbusSlaveContext,
)
from pymodbus.server import StartTcpServer

from config import (
    TUBE_TEMP_IDLE, TUBE_TEMP_SCAN, TUBE_TEMP_WARN,
    TUBE_TEMP_ALARM, TUBE_TEMP_CRITICAL,
    COOLANT_TEMP_NORMAL,
    DETECTOR_TEMP_LOW, DETECTOR_TEMP_HIGH,
    DR_FLAT_FIELD_INTERVAL, DR_GAIN_CAL_INTERVAL,
    UPS_BATTERY_GOOD, UPS_BATTERY_WARN,
    ROOM_TEMP_MIN, ROOM_TEMP_MAX,
    ROOM_HUMIDITY_MIN, ROOM_HUMIDITY_MAX,
    FAULT_PROBABILITY,
)

# ── REGISTER MAP ──────────────────────────────────────────────────────────────
# Modbus holding registers — same concept as real equipment service registers
# Gateway reads these via FC=03 (Read Holding Registers)
# Edge processor writes REG_CONTROL via FC=06 (Write Single Register)
#
# Register  Address  Parameter          Scale   Unit
# 40001     0        primary_value      ×0.1    °C or % or V
# 40002     1        secondary_value    ×0.1    °C or %
# 40003     2        tertiary_value     ×0.1    various
# 40004     3        status_code        ×1      0-5 state enum
# 40005     4        fault_flag         ×1      0=ok 1=fault
# 40006     5        fault_type_code    ×1      fault enum
# 40007     6        uptime_hours_int   ×1      integer hours
# 40008     7        daily_count        ×1      count today
# 40009     8        hours_since_cal    ×0.1    hours
# 40010     9        secondary_health   ×0.1    % or °C
# 40011     10       CONTROL OUTPUT     ×1      0=none 1=reset 2=maintenance

REG_PRIMARY    = 0   # main monitoring parameter
REG_SECONDARY  = 1   # secondary parameter
REG_TERTIARY   = 2   # third parameter
REG_STATUS     = 3   # operational state code
REG_FAULT_FLAG = 4   # 0=normal 1=fault
REG_FAULT_TYPE = 5   # fault type code
REG_UPTIME     = 6   # runtime hours
REG_DAILY      = 7   # daily count/events
REG_CAL_HOURS  = 8   # hours since calibration
REG_HEALTH     = 9   # battery % or coolant temp
REG_CONTROL    = 10  # edge processor writes here

# Status codes — operational state enum
STATUS_CODE = {
    'READY':       0,
    'SCANNING':    1,
    'WARMING_UP':  2,
    'ERROR':       3,
    'OFFLINE':     4,
    'MAINTENANCE': 5,
}

# Fault type codes per device
CT_FAULT_CODES = {
    None:             0,
    'tube_overheat':  1,
    'coolant_fault':  2,
    'power_fault':    3,
    'communication':  4,
}

DR_FAULT_CODES = {
    None:              0,
    'detector_fault':  1,
    'cal_overdue':     2,
    'exposure_error':  3,
    'communication':   4,
}

UPS_FAULT_CODES = {
    None:           0,
    'on_battery':   1,
    'battery_low':  2,
    'overload':     3,
    'comm_fault':   4,
}

ENV_FAULT_CODES = {
    None:          0,
    'temp_high':   1,
    'temp_low':    2,
    'humidity_high': 3,
    'sensor_fault':  4,
}

# Device configuration
DEVICE_CONFIG = {
    'ct': {
        'id':   'HOSP01.IMG01.CT01',
        'name': 'CT Scanner — Imaging Room 1',
        'desc': 'Siemens SOMATOM go.Up — X-ray tube thermal monitoring',
    },
    'dr': {
        'id':   'HOSP01.IMG01.DR01',
        'name': 'DR X-Ray System — Imaging Room 2',
        'desc': 'Fujifilm FDR D-EVO II — flat panel detector monitoring',
    },
    'ups': {
        'id':   'HOSP01.POWER01.UPS01',
        'name': 'UPS Power Backup — Imaging Wing',
        'desc': 'Eaton 9PX 11000i — hospital power backup',
    },
    'env': {
        'id':   'HOSP01.ENV01.ROOM01',
        'name': 'Environment Monitor — Imaging Suite',
        'desc': 'Vaisala HMT120 — IEC 60601 environment compliance',
    },
}


# ── PHYSICS SIMULATION ────────────────────────────────────────────────────────

def simulate_ct(tick):
    """
    CT Scanner thermal simulation.
    IEC 60601-2-44 — CT X-ray equipment requirements.

    Tube temperature follows real thermal profile:
      - Idle: 30-35°C — cooling system maintaining baseline
      - Warm up: temp rises 2-3°C as system initialises
      - Scanning: temp rises sharply — X-ray tube generating heat
      - Rest: temp falls gradually — cooling system active
      - Consecutive scans: progressive heat buildup

    Coolant temperature follows tube with thermal lag.
    KV and mA parameters from real DICOM tags.
    """
    # Scan cycle — 45 seconds scanning, 75 seconds rest
    # Realistic for busy imaging department
    cycle_pos = (tick * 2) % 120   # 120 second cycle
    scanning  = cycle_pos < 45

    # Tube temperature thermal model
    if scanning:
        # Rising temperature during scan
        scan_progress = cycle_pos / 45
        tube_temp = TUBE_TEMP_IDLE + (
            (TUBE_TEMP_SCAN - TUBE_TEMP_IDLE) * scan_progress
        ) + random.uniform(-0.5, 0.5)
    else:
        # Cooling — exponential decay back to idle
        rest_progress = (cycle_pos - 45) / 75
        tube_temp = TUBE_TEMP_SCAN - (
            (TUBE_TEMP_SCAN - TUBE_TEMP_IDLE) *
            (1 - math.exp(-rest_progress * 2))
        ) + random.uniform(-0.3, 0.3)

    # Coolant temperature — thermal lag behind tube
    coolant_temp = COOLANT_TEMP_NORMAL + (tube_temp - TUBE_TEMP_IDLE) * 0.15 \
                   + random.uniform(-0.2, 0.2)

    # DICOM parameters — KVP and tube current
    # Real values from CT scan protocols
    kv  = 120 if scanning else 0    # kV — standard CT protocol
    ma  = 250 if scanning else 0    # mA — standard CT protocol
    uptime = round(tick * 2 / 3600, 1)

    # Fault injection
    fault, fault_type = False, None
    if random.random() < FAULT_PROBABILITY:
        fault      = True
        fault_type = random.choice(['tube_overheat', 'coolant_fault'])
        if fault_type == 'tube_overheat':
            tube_temp   += random.uniform(8, 15)
            coolant_temp+= random.uniform(5, 10)

    status = 'SCANNING' if (scanning and not fault) else \
             'ERROR' if fault else 'READY'

    return {
        'tube_temp_c':    round(tube_temp, 1),
        'coolant_temp_c': round(coolant_temp, 1),
        'kv_output':      kv,
        'ma_output':      ma,
        'scanning':       scanning,
        'uptime_hours':   uptime,
        'status':         status,
        'fault':          fault,
        'fault_type':     fault_type,
        # Modbus register values
        'reg_primary':    int(tube_temp * 10),
        'reg_secondary':  int(coolant_temp * 10),
        'reg_tertiary':   kv,
        'reg_status':     STATUS_CODE.get(status, 0),
        'reg_fault_flag': int(fault),
        'reg_fault_type': CT_FAULT_CODES.get(fault_type, 0),
        'reg_uptime':     int(uptime),
        'reg_daily':      int(tick * 0.05),
        'reg_cal_hours':  0,
        'reg_health':     int(coolant_temp * 10),
    }


def simulate_dr(tick):
    """
    DR Digital X-Ray simulation.
    Based on Fujifilm FDR D-EVO II service parameters.
    Your direct field experience — Fujifilm CR/DR systems.

    Key monitored parameters:
      Detector temperature — affects dark current and image quality
      Calibration status — regulatory compliance requirement
      Daily exposure count — equipment wear tracking
      System ready status — availability KPI
    """
    # Detector temperature — stable with small drift
    detector_temp = 22.0 + math.sin(tick * 0.05) * 2.0 \
                    + random.uniform(-0.3, 0.3)

    # Exposure count — builds through the day
    # NHS data: medium hospital ~120 X-ray exposures/day
    hour    = datetime.now().hour
    day_pct = max(0, (hour - 7) / 11) if 7 <= hour <= 18 else 0
    exposures_today = int(120 * day_pct + random.uniform(-5, 5))

    # Hours since last calibration
    # Gain calibration due every 4380 hours (6 months)
    hours_since_cal    = (tick * 2 / 3600) % DR_GAIN_CAL_INTERVAL
    flat_field_due     = hours_since_cal > (DR_FLAT_FIELD_INTERVAL * 0.95)
    gain_cal_due       = hours_since_cal > (DR_GAIN_CAL_INTERVAL   * 0.95)

    uptime = round(tick * 2 / 3600, 1)
    ready  = detector_temp > DETECTOR_TEMP_LOW and \
             detector_temp < DETECTOR_TEMP_HIGH

    # Fault injection
    fault, fault_type = False, None
    if random.random() < FAULT_PROBABILITY:
        fault      = True
        fault_type = random.choice(['detector_fault', 'exposure_error'])

    status = 'ERROR' if fault else \
             'READY' if ready else 'WARMING_UP'

    return {
        'detector_temp_c':   round(detector_temp, 1),
        'exposures_today':   exposures_today,
        'hours_since_cal':   round(hours_since_cal, 1),
        'flat_field_due':    flat_field_due,
        'gain_cal_due':      gain_cal_due,
        'uptime_hours':      uptime,
        'ready':             ready,
        'status':            status,
        'fault':             fault,
        'fault_type':        fault_type,
        # Modbus register values
        'reg_primary':    int(detector_temp * 10),
        'reg_secondary':  exposures_today,
        'reg_tertiary':   int(hours_since_cal * 10),
        'reg_status':     STATUS_CODE.get(status, 0),
        'reg_fault_flag': int(fault),
        'reg_fault_type': DR_FAULT_CODES.get(fault_type, 0),
        'reg_uptime':     int(uptime),
        'reg_daily':      exposures_today,
        'reg_cal_hours':  int(hours_since_cal * 10),
        'reg_health':     int(detector_temp * 10),
    }


def simulate_ups(tick):
    """
    Hospital UPS simulation.
    Eaton 9PX 11000i specifications.

    Critical parameter — power failure during CT scan
    is a patient safety incident in Danish hospitals.
    Radiographers and biomedical engineers monitor this daily.

    Battery aging model:
      New battery degrades ~1% per month under normal use
      High temperature accelerates aging
      Real replacement threshold: 80% capacity
    """
    # Battery capacity — degrades slowly over time
    # Simulates real battery aging
    age_factor = min(1.0, tick * 2 / (3600 * 24 * 365))  # 0 to 1 over a year
    battery_pct = 95.0 - (age_factor * 20) + random.uniform(-1, 1)
    battery_pct = max(15.0, min(100.0, battery_pct))

    # Input voltage from grid — EN 50160 range
    input_voltage = 230.0 + math.sin(tick * 0.1) * 3.0 \
                    + random.uniform(-2.0, 2.0)

    # Load percentage — imaging wing consumption
    # CT and DR equipment draw significant power
    hour        = datetime.now().hour
    base_load   = 65.0 if 8 <= hour <= 18 else 35.0
    load_pct    = base_load + random.uniform(-5, 10)

    # Runtime remaining — based on battery and load
    runtime_min = battery_pct * 0.55 * (100 / max(50, load_pct))

    # On battery — grid power failure event (2% probability)
    on_battery = random.random() < 0.02

    # Fault injection
    fault, fault_type = False, None
    if random.random() < FAULT_PROBABILITY:
        fault      = True
        fault_type = random.choice(['battery_low', 'overload'])
        if fault_type == 'battery_low':
            battery_pct -= random.uniform(20, 35)
        elif fault_type == 'overload':
            load_pct    += random.uniform(20, 35)

    status = 'ON_BATTERY' if on_battery else \
             'ERROR' if fault else 'NORMAL'

    return {
        'battery_pct':       round(battery_pct, 1),
        'input_voltage_v':   round(input_voltage, 1),
        'load_pct':          round(load_pct, 1),
        'runtime_min':       round(runtime_min, 1),
        'on_battery':        on_battery,
        'status':            status,
        'fault':             fault,
        'fault_type':        fault_type,
        # Modbus register values
        'reg_primary':    int(battery_pct * 10),
        'reg_secondary':  int(input_voltage * 10),
        'reg_tertiary':   int(load_pct * 10),
        'reg_status':     STATUS_CODE.get(status, STATUS_CODE['READY']),
        'reg_fault_flag': int(fault or on_battery),
        'reg_fault_type': UPS_FAULT_CODES.get(fault_type, 0),
        'reg_uptime':     int(tick * 2 / 3600),
        'reg_daily':      0,
        'reg_cal_hours':  0,
        'reg_health':     int(runtime_min * 10),
    }


def simulate_env(tick, outdoor_temp=8.5, outdoor_humidity=78.0):
    """
    Room environment simulation.
    IEC 60601-1 operating environment compliance.

    Hospital HVAC maintains imaging room within IEC 60601-1 limits.
    Real Vaisala HMT120 sensor — used in Danish hospitals.

    Outdoor weather (real DMI data) influences room conditions:
      Summer — outdoor heat increases HVAC load
      Winter — dry outdoor air affects indoor humidity
    """
    hour = datetime.now().hour

    # HVAC effectiveness varies with outdoor conditions
    # Harder to maintain 18-24°C when outdoor is >25°C or <-5°C
    hvac_load     = max(0, (outdoor_temp - 18) / 20)
    room_base     = 21.0 + hvac_load * 2.5
    room_temp     = room_base + math.sin(tick * 0.02) * 0.5 \
                    + random.uniform(-0.3, 0.3)

    # Humidity — inversely related to temperature
    # Outdoor humidity influences indoor through HVAC
    outdoor_influence = (outdoor_humidity - 78) * 0.1
    room_humidity = 45.0 + outdoor_influence \
                    + math.sin(tick * 0.015) * 3.0 \
                    + random.uniform(-1.0, 1.0)
    room_humidity = max(15.0, min(80.0, room_humidity))

    # IEC 60601-1 compliance
    temp_ok     = ROOM_TEMP_MIN <= room_temp <= ROOM_TEMP_MAX
    humidity_ok = ROOM_HUMIDITY_MIN <= room_humidity <= ROOM_HUMIDITY_MAX

    # Fault injection — HVAC failure
    fault, fault_type = False, None
    if random.random() < FAULT_PROBABILITY:
        fault      = True
        fault_type = random.choice(['temp_high', 'humidity_high'])
        if fault_type == 'temp_high':
            room_temp    += random.uniform(4, 8)
        elif fault_type == 'humidity_high':
            room_humidity+= random.uniform(15, 25)

    status = 'NORMAL' if (temp_ok and humidity_ok and not fault) \
             else 'WARNING'

    return {
        'room_temp_c':        round(room_temp, 1),
        'room_humidity_pct':  round(room_humidity, 1),
        'outdoor_temp_c':     round(outdoor_temp, 1),
        'outdoor_humidity_pct': round(outdoor_humidity, 1),
        'iec60601_temp_ok':   temp_ok,
        'iec60601_humid_ok':  humidity_ok,
        'iec60601_compliant': temp_ok and humidity_ok,
        'status':             status,
        'fault':              fault,
        'fault_type':         fault_type,
        # Modbus register values
        'reg_primary':    int(room_temp * 10),
        'reg_secondary':  int(room_humidity * 10),
        'reg_tertiary':   int(outdoor_temp * 10),
        'reg_status':     STATUS_CODE.get(status, 0),
        'reg_fault_flag': int(fault),
        'reg_fault_type': ENV_FAULT_CODES.get(fault_type, 0),
        'reg_uptime':     int(tick * 2 / 3600),
        'reg_daily':      0,
        'reg_cal_hours':  0,
        'reg_health':     int(room_humidity * 10),
    }


# ── REGISTER UPDATE LOOP ──────────────────────────────────────────────────────

def update_registers(node_type, datastore, config):
    """
    Updates Modbus holding registers every 2 seconds.
    Reads control register — implements command response loop.
    """
    tick    = 0
    node_id = config['id']

    # Import outdoor data for environment node
    if node_type == 'env':
        from data_client import get_outdoor_data, start_background_refresh
        start_background_refresh()

    while True:
        try:
            # Read control register — edge processor may have written here
            try:
                control_val = datastore[0x00].getValues(
                    3, REG_CONTROL, count=1
                )[0]
            except (IndexError, Exception):
                control_val = 0
            # Generate readings based on device type
            if node_type == 'ct':
                data = simulate_ct(tick)
            elif node_type == 'dr':
                data = simulate_dr(tick)
            elif node_type == 'ups':
                data = simulate_ups(tick)
            else:  # env
                outdoor = get_outdoor_data() if node_type == 'env' \
                          else {'temp_c': 8.5, 'humidity_pct': 78.0}
                data = simulate_env(
                    tick,
                    outdoor.get('temp_c', 8.5),
                    outdoor.get('humidity_pct', 78.0)
                )

            # Handle control command
            if control_val == 1:
                data['status']     = 'READY'
                data['fault']      = False
                data['fault_type'] = None
            elif control_val == 2:
                data['status'] = 'MAINTENANCE'

            # Write to Modbus registers
            registers = [
                data['reg_primary'],
                data['reg_secondary'],
                data['reg_tertiary'],
                data['reg_status'],
                data['reg_fault_flag'],
                data['reg_fault_type'],
                data['reg_uptime'],
                data['reg_daily'],
                data['reg_cal_hours'],
                data['reg_health'],
            ]
            datastore[0x00].setValues(3, 0, registers)

            # Terminal output
            fault_str = (
                f' ⚠ {data["fault_type"]}' if data.get('fault') else ''
            )
            ctrl_str = (
                f' [CTRL:{control_val}]' if control_val != 0 else ''
            )

            if node_type == 'ct':
                print(
                    f'[PLC:{node_id}] '
                    f'Tube={data["tube_temp_c"]}°C '
                    f'Coolant={data["coolant_temp_c"]}°C '
                    f'[{data["status"]}]'
                    f'{fault_str}{ctrl_str}'
                )
            elif node_type == 'dr':
                print(
                    f'[PLC:{node_id}] '
                    f'Detector={data["detector_temp_c"]}°C '
                    f'Exp={data["exposures_today"]} '
                    f'[{data["status"]}]'
                    f'{fault_str}{ctrl_str}'
                )
            elif node_type == 'ups':
                print(
                    f'[PLC:{node_id}] '
                    f'Bat={data["battery_pct"]}% '
                    f'Input={data["input_voltage_v"]}V '
                    f'[{data["status"]}]'
                    f'{fault_str}{ctrl_str}'
                )
            else:
                print(
                    f'[PLC:{node_id}] '
                    f'Temp={data["room_temp_c"]}°C '
                    f'RH={data["room_humidity_pct"]}% '
                    f'[{data["status"]}]'
                    f'{"✓IEC60601" if data["iec60601_compliant"] else "⚠NON-COMPLIANT"}'
                    f'{fault_str}{ctrl_str}'
                )

            tick += 1
            time.sleep(2)

        except Exception as e:
            print(f'[PLC:{node_id}] Error: {e}')
            time.sleep(2)


# ── MODBUS TCP SERVER ─────────────────────────────────────────────────────────

def run_plc(node_type, port):
    config = DEVICE_CONFIG[node_type]
    print(f'[PLC] Starting — {config["id"]}')
    print(f'[PLC] {config["desc"]}')
    print(f'[PLC] Modbus TCP — localhost:{port}')
    print(f'[PLC] Register map: 40001=primary 40002=secondary '
          f'40003=tertiary 40004=status 40005=fault')
    print(f'[PLC] 40011=CONTROL (edge processor writes here)')
    print()

    block   = ModbusSequentialDataBlock(0, [0] * 11)
    store   = ModbusSlaveContext(hr=block, zero_mode=True)
    context = ModbusServerContext(slaves=store, single=True)

    threading.Thread(
        target=update_registers,
        args=(node_type, context, config),
        daemon=True
    ).start()

    print(f'[PLC] Listening on port {port}')
    StartTcpServer(context=context, address=('localhost', port))


# ── ENTRY POINT ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Simulated medical equipment — Modbus TCP server'
    )
    parser.add_argument(
        '--node',
        choices=['ct', 'dr', 'ups', 'env'],
        required=True,
        help='Device type: ct=CT scanner, dr=DR X-ray, '
             'ups=UPS power, env=environment'
    )
    parser.add_argument(
        '--port',
        type=int,
        required=True,
        help='Modbus TCP port (5020, 5021, 5022, 5023)'
    )
    args = parser.parse_args()
    run_plc(args.node, args.port)
