# gateway.py
# IoT Gateway — Medical Equipment Monitoring
#
# Real-world equivalent:
#   Siemens teamplay Fleet edge gateway
#   Philips HealthSuite local connector
#   Hospital biomedical engineering server
#
# What this does:
#   Polls all four devices via Modbus TCP every 2 seconds
#   Converts raw register integers to engineering values
#   Enriches with real DMI outdoor data
#   Adds DICOM status context
#   Publishes complete JSON via MQTT to Mosquitto
#   Sends heartbeat per device every 20 seconds
#   Publishes state change messages on transitions
#
# Run: python gateway.py

import json
import threading
import time
from datetime import datetime

import paho.mqtt.client as mqtt
from pymodbus.client import ModbusTcpClient

from config import (
    BROKER_HOST, BROKER_PORT, PUBLISH_INTERVAL,
    NODES, DICOM_STATUS_MAP,
    TUBE_TEMP_WARN, TUBE_TEMP_ALARM, TUBE_TEMP_CRITICAL,
    UPS_BATTERY_WARN, UPS_BATTERY_ALARM, UPS_BATTERY_CRITICAL,
    ROOM_TEMP_MIN, ROOM_TEMP_MAX,
    ROOM_HUMIDITY_MIN, ROOM_HUMIDITY_MAX,
)
from data_client import get_outdoor_data, start_background_refresh

HEARTBEAT_EVERY = 10   # ticks — every 20 seconds

# Register addresses — must match simulated_plc.py
REG_PRIMARY    = 0
REG_SECONDARY  = 1
REG_TERTIARY   = 2
REG_STATUS     = 3
REG_FAULT_FLAG = 4
REG_FAULT_TYPE = 5
REG_UPTIME     = 6
REG_DAILY      = 7
REG_CAL_HOURS  = 8
REG_HEALTH     = 9
REG_CONTROL    = 10

STATUS_DECODE = {
    0: 'READY',
    1: 'SCANNING',
    2: 'WARMING_UP',
    3: 'ERROR',
    4: 'OFFLINE',
    5: 'MAINTENANCE',
}

CT_FAULT_DECODE  = {0: None, 1: 'tube_overheat', 2: 'coolant_fault',
                    3: 'power_fault', 4: 'communication'}
DR_FAULT_DECODE  = {0: None, 1: 'detector_fault', 2: 'cal_overdue',
                    3: 'exposure_error', 4: 'communication'}
UPS_FAULT_DECODE = {0: None, 1: 'on_battery', 2: 'battery_low',
                    3: 'overload', 4: 'comm_fault'}
ENV_FAULT_DECODE = {0: None, 1: 'temp_high', 2: 'temp_low',
                    3: 'humidity_high', 4: 'sensor_fault'}


# ── MODBUS READING ────────────────────────────────────────────────────────────

def read_device_registers(port):
    """Read all 10 sensor registers from device via Modbus TCP."""
    return read_registers(port, count=10)


def read_registers(port, count):
    """Read holding registers from a device via Modbus TCP."""
    try:
        client = ModbusTcpClient('localhost', port=port, timeout=3)
        if not client.connect():
            return None
        result = client.read_holding_registers(
            address=0, count=count, slave=1
        )
        client.close()
        if result.isError():
            return None
        return result.registers
    except Exception:
        return None


def send_control_command(port, command, device_id):
    """
    Write control command to device register 40011.
    command: 1=reset/clear fault  2=set maintenance mode
    Closed control loop — gateway commands the device.
    """
    try:
        client = ModbusTcpClient('localhost', port=port, timeout=3)
        if not client.connect():
            return False
        result = client.write_register(
            address=REG_CONTROL, value=command, slave=1
        )
        client.close()
        if not result.isError():
            action = {1: 'RESET', 2: 'MAINTENANCE'}.get(command, 'UNKNOWN')
            print(f'[GW] MODBUS WRITE → {device_id}:'
                  f'{port} reg40011={command} ({action})')
            return True
        return False
    except Exception as e:
        print(f'[GW] Control write error: {e}')
        return False


def decode_ct_registers(registers, node, outdoor):
    """Decode CT scanner register values to engineering units."""
    tube_temp    = registers[REG_PRIMARY]   / 10.0
    coolant_temp = registers[REG_SECONDARY] / 10.0
    kv_output    = registers[REG_TERTIARY]
    status       = STATUS_DECODE.get(registers[REG_STATUS], 'UNKNOWN')
    fault_active = bool(registers[REG_FAULT_FLAG])
    fault_type   = CT_FAULT_DECODE.get(registers[REG_FAULT_TYPE])
    uptime_hours = registers[REG_UPTIME]
    scans_today  = registers[REG_DAILY]

    # DICOM status context
    dicom_status = DICOM_STATUS_MAP.get(status, 'DISCONTINUED')

    return {
        'device_id':       node['id'],
        'device_name':     node['name'],
        'device_type':     node['type'],
        'manufacturer':    node['manufacturer'],
        'model':           node['model'],
        'timestamp':       datetime.now().isoformat(),
        'status':          status,
        'dicom_status':    dicom_status,
        # IEC 60601-2-44 parameters
        'tube_temp_c':     round(tube_temp, 1),
        'coolant_temp_c':  round(coolant_temp, 1),
        'kv_output':       kv_output,
        'scanning':        status == 'SCANNING',
        'scans_today':     scans_today,
        'uptime_hours':    uptime_hours,
        # Fault state
        'fault_active':    fault_active,
        'fault_type':      fault_type,
        # Environment context
        'outdoor_temp_c':  outdoor.get('temp_c', 8.5),
    }


def decode_dr_registers(registers, node, outdoor):
    """Decode DR X-ray register values — Fujifilm FDR parameters."""
    detector_temp   = registers[REG_PRIMARY]   / 10.0
    exposures_today = registers[REG_SECONDARY]
    hours_since_cal = registers[REG_CAL_HOURS] / 10.0
    status          = STATUS_DECODE.get(registers[REG_STATUS], 'UNKNOWN')
    fault_active    = bool(registers[REG_FAULT_FLAG])
    fault_type      = DR_FAULT_DECODE.get(registers[REG_FAULT_TYPE])
    uptime_hours    = registers[REG_UPTIME]

    # Calibration status — ISO 13485 compliance
    flat_field_due = hours_since_cal > (720  * 0.95)
    gain_cal_due   = hours_since_cal > (4380 * 0.95)
    dicom_status   = DICOM_STATUS_MAP.get(status, 'DISCONTINUED')

    return {
        'device_id':          node['id'],
        'device_name':        node['name'],
        'device_type':        node['type'],
        'manufacturer':       node['manufacturer'],
        'model':              node['model'],
        'timestamp':          datetime.now().isoformat(),
        'status':             status,
        'dicom_status':       dicom_status,
        # Fujifilm FDR parameters
        'detector_temp_c':    round(detector_temp, 1),
        'exposures_today':    exposures_today,
        'hours_since_cal':    round(hours_since_cal, 1),
        'flat_field_cal_due': flat_field_due,
        'gain_cal_due':       gain_cal_due,
        'uptime_hours':       uptime_hours,
        # ISO 13485 compliance
        'calibration_compliant': not (flat_field_due or gain_cal_due),
        # Fault state
        'fault_active':       fault_active,
        'fault_type':         fault_type,
    }


def decode_ups_registers(registers, node, outdoor):
    """Decode UPS register values — Eaton 9PX parameters."""
    battery_pct   = registers[REG_PRIMARY]   / 10.0
    input_voltage = registers[REG_SECONDARY] / 10.0
    load_pct      = registers[REG_TERTIARY]  / 10.0
    status        = STATUS_DECODE.get(registers[REG_STATUS], 'UNKNOWN')
    fault_active  = bool(registers[REG_FAULT_FLAG])
    fault_type    = UPS_FAULT_DECODE.get(registers[REG_FAULT_TYPE])
    runtime_min   = registers[REG_HEALTH] / 10.0
    on_battery    = status == 'ON_BATTERY'

    return {
        'device_id':       node['id'],
        'device_name':     node['name'],
        'device_type':     node['type'],
        'manufacturer':    node['manufacturer'],
        'model':           node['model'],
        'timestamp':       datetime.now().isoformat(),
        'status':          status,
        # Eaton 9PX parameters
        'battery_pct':     round(battery_pct, 1),
        'input_voltage_v': round(input_voltage, 1),
        'load_pct':        round(load_pct, 1),
        'runtime_min':     round(runtime_min, 1),
        'on_battery':      on_battery,
        # EN 50160 grid power quality
        'input_volt_ok':   207.0 <= input_voltage <= 253.0,
        # Fault state
        'fault_active':    fault_active or on_battery,
        'fault_type':      'on_battery' if on_battery else fault_type,
    }


def decode_env_registers(registers, node, outdoor):
    """Decode environment register values — IEC 60601-1 compliance."""
    room_temp     = registers[REG_PRIMARY]   / 10.0
    room_humidity = registers[REG_SECONDARY] / 10.0
    outdoor_temp  = registers[REG_TERTIARY]  / 10.0
    status        = STATUS_DECODE.get(registers[REG_STATUS], 'UNKNOWN')
    fault_active  = bool(registers[REG_FAULT_FLAG])
    fault_type    = ENV_FAULT_DECODE.get(registers[REG_FAULT_TYPE])

    temp_ok     = ROOM_TEMP_MIN <= room_temp <= ROOM_TEMP_MAX
    humidity_ok = ROOM_HUMIDITY_MIN <= room_humidity <= ROOM_HUMIDITY_MAX

    return {
        'device_id':              node['id'],
        'device_name':            node['name'],
        'device_type':            node['type'],
        'manufacturer':           node['manufacturer'],
        'model':                  node['model'],
        'timestamp':              datetime.now().isoformat(),
        'status':                 status,
        # Vaisala HMT120 measurements
        'room_temp_c':            round(room_temp, 1),
        'room_humidity_pct':      round(room_humidity, 1),
        'outdoor_temp_c':         outdoor.get('temp_c', outdoor_temp),
        'outdoor_humidity_pct':   outdoor.get('humidity_pct', 78.0),
        # IEC 60601-1 compliance
        'iec60601_temp_ok':       temp_ok,
        'iec60601_humidity_ok':   humidity_ok,
        'iec60601_compliant':     temp_ok and humidity_ok,
        # Fault state
        'fault_active':           fault_active,
        'fault_type':             fault_type,
    }


def decode_mri_registers(registers, node, outdoor):
    """
    Decode MRI scanner register values.
    Siemens MAGNETOM Altea 1.5T — cryogenic and thermal monitoring.

    Register layout:
      0  helium_level    × 0.1   %
      1  cryo_pressure   × 0.01  bar gauge
      2  coldhead_temp   × 0.01  Kelvin
      3  gradient_temp   × 0.1   °C
      4  rf_amp_temp     × 0.1   °C
      5  chiller_inlet   × 0.1   °C
      6  field_deviation × 0.001 milliTesla
      7  o2_level        × 0.1   %
      8  status_code     × 1
      9  fault_flag      × 1

    IEC 60601-2-33 — MR equipment safety
    """
    helium_pct    = registers[0] / 10.0
    cryo_pressure = registers[1] / 100.0
    coldhead_k    = registers[2] / 100.0
    gradient_temp = registers[3] / 10.0
    rf_temp       = registers[4] / 10.0
    chiller_temp  = registers[5] / 10.0
    field_dev_mt  = registers[6] / 1000.0
    o2_level      = registers[7] / 10.0
    fault_active  = bool(registers[9])

    # Status decode — MRI has extended states
    mri_status_decode = {
        0: 'READY',
        1: 'SCANNING',
        2: 'RAMPING_UP',
        3: 'QUENCH_RISK',
        4: 'QUENCH',
        5: 'MAINTENANCE',
        6: 'OFFLINE',
    }
    status = mri_status_decode.get(registers[8], 'UNKNOWN')

    # Helium health classification
    if helium_pct >= 80:
        helium_status = 'GOOD'
    elif helium_pct >= 60:
        helium_status = 'MONITOR'
    elif helium_pct >= 40:
        helium_status = 'LOW'
    else:
        helium_status = 'CRITICAL'

    return {
        'device_id':              node['id'],
        'device_name':            node['name'],
        'device_type':            node['type'],
        'manufacturer':           node['manufacturer'],
        'model':                  node['model'],
        'timestamp':              datetime.now().isoformat(),
        'status':                 status,
        # ── CRYOGENIC ──────────────────────────────────────────
        'helium_level_pct':       round(helium_pct, 1),
        'helium_status':          helium_status,
        'cryo_pressure_bar':      round(cryo_pressure, 3),
        'coldhead_temp_k':        round(coldhead_k, 2),
        # ── GRADIENT SYSTEM ────────────────────────────────────
        'gradient_temp_c':        round(gradient_temp, 1),
        'chiller_inlet_temp_c':   round(chiller_temp, 1),
        # ── RF SYSTEM ──────────────────────────────────────────
        'rf_amp_temp_c':          round(rf_temp, 1),
        # ── MAGNETIC FIELD ─────────────────────────────────────
        'field_nominal_t':        1.5,
        'field_deviation_mt':     round(field_dev_mt, 4),
        # ── ROOM SAFETY — IEC 60601-2-33 ───────────────────────
        'o2_level_pct':           round(o2_level, 1),
        'o2_safe':                o2_level >= 19.5,
        # ── FAULT ──────────────────────────────────────────────
        'fault_active':           fault_active,
        'fault_type':             None,   # decoded in edge processor
    }


def decode_energy_registers(registers, node, outdoor):
    """
    Decode Siemens SENTRON PAC3200 power meter register values.

    Register layout:
      0-2  voltage L1/L2/L3      x 0.1 V
      3-5  current L1/L2/L3      x 0.01 A
      6    active power          W
      7    reactive power        VAr
      8    apparent power        VA
      9    power factor          x 0.001
      10   frequency             x 0.01 Hz
      11   cumulative energy     x 0.1 kWh
      12   voltage THD           x 0.1 %
      13   current THD           x 0.1 %
      14   demand                W
      15   peak demand           W
    """
    voltage_l1 = registers[0] / 10.0
    voltage_l2 = registers[1] / 10.0
    voltage_l3 = registers[2] / 10.0
    current_l1 = registers[3] / 100.0
    current_l2 = registers[4] / 100.0
    current_l3 = registers[5] / 100.0
    active_w   = registers[6]
    reactive   = registers[7]
    apparent   = registers[8]
    pf         = registers[9] / 1000.0
    frequency  = registers[10] / 100.0
    energy_kwh = registers[11] / 10.0
    thd_v      = registers[12] / 10.0
    thd_i      = registers[13] / 10.0
    demand_kw  = registers[14] / 1000.0
    peak_kw    = registers[15] / 1000.0

    voltage_ok = all(207.0 <= v <= 253.0
                     for v in (voltage_l1, voltage_l2, voltage_l3))
    frequency_ok = 49.5 <= frequency <= 50.5
    power_quality_ok = voltage_ok and frequency_ok and pf >= 0.90 \
        and thd_v <= 8.0

    return {
        'device_id':           node['id'],
        'device_name':         node['name'],
        'device_type':         node['type'],
        'manufacturer':        node['manufacturer'],
        'model':               node['model'],
        'timestamp':           datetime.now().isoformat(),
        'status':              'NORMAL' if power_quality_ok else 'WARNING',
        'voltage_l1_v':        round(voltage_l1, 1),
        'voltage_l2_v':        round(voltage_l2, 1),
        'voltage_l3_v':        round(voltage_l3, 1),
        'current_l1_a':        round(current_l1, 2),
        'current_l2_a':        round(current_l2, 2),
        'current_l3_a':        round(current_l3, 2),
        'active_power_w':      active_w,
        'reactive_power_var':  reactive,
        'apparent_power_va':   apparent,
        'power_factor':        round(pf, 3),
        'frequency_hz':        round(frequency, 2),
        'energy_kwh':          round(energy_kwh, 1),
        'thd_voltage_pct':     round(thd_v, 1),
        'thd_current_pct':     round(thd_i, 1),
        'demand_kw':           round(demand_kw, 2),
        'peak_demand_kw':      round(peak_kw, 2),
        'voltage_ok':          voltage_ok,
        'frequency_ok':        frequency_ok,
        'power_quality_ok':    power_quality_ok,
        'fault_active':        not power_quality_ok,
        'fault_type':          None if power_quality_ok else 'power_quality',
    }


DECODE_FUNCTIONS = {
    'ct_scanner':  decode_ct_registers,
    'dr_xray':     decode_dr_registers,
    'ups':         decode_ups_registers,
    'environment': decode_env_registers,
    'mri_scanner': decode_mri_registers,
    'energy_meter': decode_energy_registers,
}


# ── MQTT ──────────────────────────────────────────────────────────────────────

def build_mqtt_client():
    client = mqtt.Client(client_id='medical_gateway_v1')

    def on_connect(c, userdata, flags, rc):
        if rc == 0:
            print(
                f'[GW] Connected to Mosquitto '
                f'{BROKER_HOST}:{BROKER_PORT}'
            )
        else:
            print(f'[GW] MQTT connection failed — code {rc}')

    client.on_connect = on_connect
    try:
        client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
    except ConnectionRefusedError:
        print('[GW] ERROR: Cannot connect to Mosquitto')
        print('[GW] Run: mosquitto -v')
        raise
    return client


def publish_heartbeat(client, node, tick):
    if tick % HEARTBEAT_EVERY != 0:
        return
    hb = {
        'device_id':  node['id'],
        'timestamp':  datetime.now().isoformat(),
        'status':     'ALIVE',
        'tick':       tick,
    }
    client.publish(node['topic_heartbeat'], json.dumps(hb), qos=0)


def publish_state_change(client, node, current, previous):
    msg = {
        'device_id': node['id'],
        'timestamp': datetime.now().isoformat(),
        'state':     current,
        'previous':  previous,
    }
    client.publish(node['topic_state'], json.dumps(msg), qos=1)
    print(f'[GW] STATE → {node["id"]}: {previous} → {current}')


# ── MAIN LOOP ─────────────────────────────────────────────────────────────────

def run():
    print('=' * 60)
    print('Medical Equipment Remote Monitoring Gateway')
    print('Hospital Imaging Infrastructure — HOSP01')
    print('Md Rafael Amin — MSc Electrical Engineering 2025')
    print('Standards: IEC 60601-1, IEC 60601-2-44, ISO 13485')
    print('Real data: DMI Denmark — outdoor conditions')
    print('=' * 60)
    print()

    # Start DMI data refresh
    print('[GW] Starting DMI outdoor data refresh...')
    start_background_refresh()

    # Connect MQTT
    client = build_mqtt_client()
    client.loop_start()
    time.sleep(1)

    prev_states = {node['id']: 'UNKNOWN' for node in NODES}
    tick = 0

    print()
    print('[GW] Gateway running. Ctrl+C to stop.')
    print()

    while True:
        try:
            outdoor = get_outdoor_data()

            for node in NODES:
                register_count = 16 if node['type'] == 'energy_meter' else 10
                registers = read_registers(node['port'], register_count)

                if registers is None:
                    print(
                        f'[GW] ⚫ {node["id"]:<35} '
                        f'port {node["port"]} — no response'
                    )
                    continue

                # Decode registers
                decode_fn = DECODE_FUNCTIONS.get(node['type'])
                if not decode_fn:
                    continue
                reading = decode_fn(registers, node, outdoor)

                # Publish telemetry
                client.publish(
                    node['topic_telemetry'],
                    json.dumps(reading),
                    qos=1
                )

                # State change detection
                curr_status = reading.get('status', 'UNKNOWN')
                if prev_states[node['id']] != curr_status:
                    publish_state_change(
                        client, node,
                        curr_status,
                        prev_states[node['id']]
                    )
                    prev_states[node['id']] = curr_status

                # Heartbeat
                publish_heartbeat(client, node, tick)

                # Terminal output
                fault_str = (
                    f' ⚠ {reading.get("fault_type")}'
                    if reading.get('fault_active') else ''
                )

                if node['type'] == 'ct_scanner':
                    print(
                        f'[GW] {node["id"]:<35} '
                        f'Tube={reading["tube_temp_c"]}°C '
                        f'[{curr_status}]{fault_str}'
                    )
                elif node['type'] == 'dr_xray':
                    cal = ' [CAL DUE]' if reading.get('gain_cal_due') else ''
                    print(
                        f'[GW] {node["id"]:<35} '
                        f'Det={reading["detector_temp_c"]}°C '
                        f'Exp={reading["exposures_today"]} '
                        f'[{curr_status}]{cal}{fault_str}'
                    )
                elif node['type'] == 'ups':
                    print(
                        f'[GW] {node["id"]:<35} '
                        f'Bat={reading["battery_pct"]}% '
                        f'Input={reading["input_voltage_v"]}V '
                        f'[{curr_status}]{fault_str}'
                    )
                elif node['type'] == 'mri_scanner':
                    he  = reading.get('helium_level_pct', 0)
                    he_icon = ('🟢' if he >= 80
                               else '🟡' if he >= 60 else '🔴')
                    o2  = reading.get('o2_level_pct', 20.9)
                    o2_str = '' if o2 >= 19.5 else f' ⚠O2={o2}%'
                    print(
                        f'[GW] {node["id"]:<35} '
                        f'{he_icon}He={he:.1f}% '
                        f'Grad={reading.get("gradient_temp_c",0):.1f}°C '
                        f'[{curr_status}]{o2_str}{fault_str}'
                    )
                elif node['type'] == 'energy_meter':
                    print(
                        f'[GW] {node["id"]:<35} '
                        f'P={reading["active_power_w"]/1000:.1f}kW '
                        f'PF={reading["power_factor"]:.3f} '
                        f'E={reading["energy_kwh"]:.1f}kWh '
                        f'[{curr_status}]{fault_str}'
                    )
                else:  # environment
                    comp = '✓IEC60601' if reading['iec60601_compliant'] \
                           else '⚠NON-COMPLIANT'
                    print(
                        f'[GW] {node["id"]:<35} '
                        f'{reading["room_temp_c"]}°C '
                        f'{reading["room_humidity_pct"]}%RH '
                        f'[{comp}]{fault_str}'
                    )

            tick += 1
            print()
            time.sleep(PUBLISH_INTERVAL)

        except KeyboardInterrupt:
            print('\n[GW] Stopping...')
            client.loop_stop()
            client.disconnect()
            break

        except Exception as e:
            print(f'[GW] Error: {e}')
            time.sleep(PUBLISH_INTERVAL)


if __name__ == '__main__':
    run()
