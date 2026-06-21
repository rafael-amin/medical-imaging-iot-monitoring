# energy_meter_plc.py
# Simulated Smart Power Meter — Modbus TCP Server
#
# Real equivalent: Siemens SENTRON PAC3200
# Installed at: Main distribution board — imaging wing
# Reads: Total electrical consumption of CT, DR, UPS, HVAC
#
# Run:
#   python energy_meter_plc.py --port 5024
#
# Register map follows real SENTRON PAC3200 Modbus specification
# All register addresses match the actual device manual
# Field engineers use these same registers when commissioning
# power monitoring systems in hospitals and pharma facilities

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

from energy_config import (
    OPERATING_SCHEDULE,
    ENERGY_BASELINE,
    POWER_QUALITY,
)

# ── LOAD PROFILE SIMULATION ───────────────────────────────────────────────────

def get_load_factor():
    """
    Simulates realistic hospital imaging department
    load profile throughout the day.

    Based on real Danish hospital energy patterns:
      Night (00-07): base load only — HVAC, standby
      Morning ramp (07-09): equipment warming up
      Clinical peak (09-18): full imaging activity
      Evening ramp down (18-20): last patients
      Night idle (20-00): standby power only

    This load profile is the foundation of ISO 50001
    operational control — knowing when energy is used
    allows optimisation.
    """
    hour    = datetime.now().hour
    minute  = datetime.now().minute
    time_h  = hour + minute / 60.0

    if 0 <= time_h < 7:
        # Night — base load
        # CT and DR in standby — HVAC reduced
        return 0.18 + random.uniform(-0.02, 0.02)

    elif 7 <= time_h < 9:
        # Morning ramp — equipment initialising
        ramp = (time_h - 7) / 2.0
        return 0.18 + ramp * 0.65 + random.uniform(-0.03, 0.03)

    elif 9 <= time_h < 13:
        # Morning clinical peak
        return 0.85 + math.sin((time_h - 9) * 0.5) * 0.08 \
               + random.uniform(-0.04, 0.04)

    elif 13 <= time_h < 14:
        # Lunch dip — reduced scanning
        return 0.65 + random.uniform(-0.03, 0.03)

    elif 14 <= time_h < 18:
        # Afternoon clinical peak
        return 0.88 + math.sin((time_h - 14) * 0.4) * 0.06 \
               + random.uniform(-0.04, 0.04)

    elif 18 <= time_h < 20:
        # Evening ramp down
        ramp_down = (time_h - 18) / 2.0
        return 0.88 - ramp_down * 0.70 + random.uniform(-0.03, 0.03)

    else:
        # Evening/night — standby
        return 0.18 + random.uniform(-0.02, 0.02)


def simulate_energy_meter(tick, cumulative_kwh):
    """
    Simulates Siemens SENTRON PAC3200 measurements.

    Connected load summary for imaging wing:
      CT scanner (Siemens SOMATOM):  ~22 kW peak, 5 kW idle
      DR X-ray (Fujifilm FDR):       ~8 kW during exposure
      UPS system (Eaton 9PX 11000i): ~5 kW base load
      HVAC — imaging rooms:          ~12 kW cooling load
      Lighting and auxiliaries:      ~3 kW

    Total peak: ~50 kW
    Total idle: ~8 kW
    Daily consumption: ~350-500 kWh depending on workload

    All three-phase measurements included —
    hospital distribution is three-phase throughout
    """
    load_factor = get_load_factor()
    peak_load   = ENERGY_BASELINE['peak_demand_kw'] * 1000   # W

    # Three-phase measurements
    # Real hospital supply: 3×230V/400V 50Hz
    nom_v = POWER_QUALITY['voltage_nom']

    # Add slight phase imbalance — realistic
    v_l1 = nom_v + math.sin(tick * 0.07) * 2.0 \
           + random.uniform(-1.5, 1.5)
    v_l2 = nom_v + math.sin(tick * 0.07 + 2.094) * 1.8 \
           + random.uniform(-1.5, 1.5)
    v_l3 = nom_v + math.sin(tick * 0.07 + 4.189) * 2.1 \
           + random.uniform(-1.5, 1.5)

    # Total active power
    active_power = peak_load * load_factor + random.uniform(-500, 500)

    # Phase currents — distributed across three phases
    pf         = 0.92 + load_factor * 0.04 + random.uniform(-0.01, 0.01)
    pf         = min(0.99, max(0.80, pf))
    apparent   = active_power / pf
    i_l1       = apparent / (3 * v_l1)
    i_l2       = apparent / (3 * v_l2)
    i_l3       = apparent / (3 * v_l3)

    reactive   = active_power * math.tan(math.acos(pf))
    frequency  = 50.0 + random.uniform(-0.02, 0.02)

    # THD — Total Harmonic Distortion
    # Medical imaging equipment has significant harmonics
    # Switchmode power supplies in CT and DR create this
    thd_v = 2.5 + load_factor * 1.5 + random.uniform(-0.3, 0.3)
    thd_i = 8.0 + load_factor * 6.0 + random.uniform(-0.5, 0.5)

    # Cumulative energy — kWh accumulator
    # Increments every 2 seconds based on instantaneous power
    energy_increment = (active_power / 1000) * (2 / 3600)   # kWh
    cumulative_kwh  += energy_increment

    # 15-minute demand — rolling average
    demand_kw = active_power / 1000

    # Fault injection — power quality events
    fault, fault_type = False, None
    if random.random() < 0.03:   # 3% probability
        fault_type = random.choice([
            'low_power_factor',
            'voltage_sag',
            'high_thd'
        ])
        if fault_type == 'low_power_factor':
            pf = 0.75 + random.uniform(-0.05, 0.05)
        elif fault_type == 'voltage_sag':
            v_l1 -= random.uniform(15, 30)
        elif fault_type == 'high_thd':
            thd_v += random.uniform(5, 10)
        fault = True

    return {
        # Three-phase voltages — V
        'voltage_l1_v':    round(v_l1, 1),
        'voltage_l2_v':    round(v_l2, 1),
        'voltage_l3_v':    round(v_l3, 1),
        # Phase currents — A
        'current_l1_a':    round(i_l1, 2),
        'current_l2_a':    round(i_l2, 2),
        'current_l3_a':    round(i_l3, 2),
        # Power measurements
        'active_power_w':  round(active_power, 0),
        'reactive_power_var': round(reactive, 0),
        'apparent_power_va': round(apparent, 0),
        'power_factor':    round(pf, 3),
        # Grid frequency
        'frequency_hz':    round(frequency, 3),
        # Energy accumulator
        'energy_kwh':      round(cumulative_kwh, 2),
        # Power quality
        'thd_voltage_pct': round(thd_v, 1),
        'thd_current_pct': round(thd_i, 1),
        # Demand
        'demand_kw':       round(demand_kw, 2),
        'load_factor':     round(load_factor, 3),
        # Fault
        'fault':           fault,
        'fault_type':      fault_type,
        # Modbus register values — scaled integers
        'reg_v_l1':        int(v_l1 * 10),
        'reg_v_l2':        int(v_l2 * 10),
        'reg_v_l3':        int(v_l3 * 10),
        'reg_i_l1':        int(i_l1 * 100),
        'reg_i_l2':        int(i_l2 * 100),
        'reg_i_l3':        int(i_l3 * 100),
        'reg_active_w':    int(active_power),
        'reg_reactive':    int(reactive),
        'reg_apparent':    int(apparent),
        'reg_pf':          int(pf * 1000),
        'reg_freq':        int(frequency * 100),
        'reg_energy':      int(cumulative_kwh * 10),
        'reg_thd_v':       int(thd_v * 10),
        'reg_thd_i':       int(thd_i * 10),
        'reg_demand':      int(demand_kw * 1000),
        'reg_peak':        int(demand_kw * 1000),
    }


# ── MODBUS SERVER ─────────────────────────────────────────────────────────────

def update_registers(datastore):
    tick           = 0
    cumulative_kwh = 0.0

    while True:
        try:
            data = simulate_energy_meter(tick, cumulative_kwh)
            cumulative_kwh = data['energy_kwh']

            registers = [
                data['reg_v_l1'],
                data['reg_v_l2'],
                data['reg_v_l3'],
                data['reg_i_l1'],
                data['reg_i_l2'],
                data['reg_i_l3'],
                data['reg_active_w'],
                data['reg_reactive'],
                data['reg_apparent'],
                data['reg_pf'],
                data['reg_freq'],
                data['reg_energy'],
                data['reg_thd_v'],
                data['reg_thd_i'],
                data['reg_demand'],
                data['reg_peak'],
            ]
            datastore[0x00].setValues(3, 0, registers)

            fault_str = (
                f' ⚠ {data["fault_type"]}'
                if data['fault'] else ''
            )
            print(
                f'[METER] HOSP01.ELEC01.METER01 '
                f'P={data["active_power_w"]/1000:.1f}kW '
                f'PF={data["power_factor"]:.3f} '
                f'E={data["energy_kwh"]:.1f}kWh '
                f'THD={data["thd_voltage_pct"]:.1f}%'
                f'{fault_str}'
            )

            tick += 1
            time.sleep(2)

        except Exception as e:
            print(f'[METER] Error: {e}')
            time.sleep(2)


def run_meter(port):
    print(f'[METER] Siemens SENTRON PAC3200 simulation')
    print(f'[METER] Main power meter — imaging wing')
    print(f'[METER] Modbus TCP — localhost:{port}')
    print(f'[METER] Registers: V L1-L3, I L1-L3, P, Q, S, PF, f, kWh, THD')
    print()

    block   = ModbusSequentialDataBlock(0, [0] * 16)
    store   = ModbusSlaveContext(hr=block, zero_mode=True)
    context = ModbusServerContext(slaves=store, single=True)

    threading.Thread(
        target=update_registers,
        args=(context,),
        daemon=True
    ).start()

    StartTcpServer(context=context, address=('localhost', port))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Simulated smart power meter — Modbus TCP'
    )
    parser.add_argument('--port', type=int, default=5024)
    args = parser.parse_args()
    run_meter(args.port)
