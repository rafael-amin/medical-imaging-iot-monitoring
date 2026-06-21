# mri_plc.py
# Simulated MRI Scanner — Modbus TCP Server
# Siemens MAGNETOM Altea 1.5T
#
# Run:
#   python mri_plc.py --port 5025
#
# ── REAL PARAMETERS MODELLED ──────────────────────────────────────────────────
#
# This simulation is based on:
#
#   IEC 60601-2-33:2022
#     Particular requirements for the safety of MR equipment
#     Defines operating limits, quench protection, safety systems
#
#   Siemens MAGNETOM technical documentation
#     Helium level monitoring — magnet monitor unit
#     Cold head two-stage cryocooler system (4.2K stage)
#     Gradient coil water cooling — GPA + GC water-cooled
#     Zero Boil-Off (ZBO) refrigeration — standard since 2010s
#
#   mriquestions.com — Q&A in MRI (clinical reference)
#     Liquid helium use, quench physics, ZBO systems
#
#   Medical Imaging Source (March 2024)
#     "Maintain helium levels above 60%"
#     "Contact service engineer if below threshold"
#
#   UCSF Radiology — Magnet Quench Protocol
#     Quench causes, manual quench procedure
#     "Severe and irreparable damage to superconducting coils"
#
#   pureairemonitoring.com — MRI Helium Safety
#     Oxygen displacement risk during helium quench
#     IEC 60601-2-33 requires O2 monitoring in MRI rooms
#
#   Patent US8564292 — Gradient coil cooling control
#     Gradient temperature feedback control model
#     Chiller setpoint adjustment during scanning
#
# ── REGISTER MAP ──────────────────────────────────────────────────────────────
#
# Address  Register   Parameter                Scale   Unit
# 0        40001      helium_level             ×0.1    % of cryostat
# 1        40002      cryo_pressure            ×0.01   bar gauge
# 2        40003      coldhead_temp_k          ×0.01   Kelvin
# 3        40004      gradient_temp_c          ×0.1    °C
# 4        40005      rf_amp_temp_c            ×0.1    °C
# 5        40006      chiller_inlet_temp_c     ×0.1    °C
# 6        40007      field_strength_mt        ×0.001  Tesla (deviation)
# 7        40008      o2_level_pct             ×0.1    % oxygen
# 8        40009      status_code              ×1      state enum
# 9        40010      fault_flag               ×1      0=ok 1=fault
# 10       40011      CONTROL OUTPUT           ×1      edge writes here

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
    MRI_HELIUM_GOOD, MRI_HELIUM_WARN,
    MRI_HELIUM_ALARM, MRI_HELIUM_CRITICAL,
    MRI_CRYO_PRESS_NORMAL, MRI_CRYO_PRESS_WARN,
    MRI_COLDHEAD_TEMP_GOOD, MRI_COLDHEAD_TEMP_WARN,
    MRI_GRADIENT_TEMP_NORM, MRI_GRADIENT_TEMP_WARN,
    MRI_GRADIENT_TEMP_ALARM,
    MRI_RF_TEMP_NORM, MRI_RF_TEMP_WARN,
    MRI_CHILLER_INLET_NORM, MRI_CHILLER_INLET_WARN,
    MRI_FIELD_NOMINAL,
    O2_LEVEL_SAFE, O2_LEVEL_WARN, O2_LEVEL_ALARM,
    FAULT_PROBABILITY,
)

# Operational state codes
MRI_STATUS_CODE = {
    'READY':          0,
    'SCANNING':       1,
    'RAMPING_UP':     2,   # magnet field ramping to full strength
    'QUENCH_RISK':    3,   # helium critically low — stop scanning
    'QUENCH':         4,   # magnet quench event — emergency
    'MAINTENANCE':    5,
    'OFFLINE':        6,
}

# Fault type codes
MRI_FAULT_CODE = {
    None:                0,
    'helium_low':        1,
    'cryo_pressure':     2,
    'coldhead_fault':    3,
    'gradient_overheat': 4,
    'rf_overheat':       5,
    'chiller_fault':     6,
    'field_drift':       7,
    'o2_depletion':      8,   # SAFETY CRITICAL — room evacuation
}

DEVICE_ID   = 'HOSP01.IMG01.MRI01'
DEVICE_NAME = 'MRI Scanner — Imaging Room 3'
DEVICE_DESC = (
    'Siemens MAGNETOM Altea 1.5T — '
    'Superconducting cryogenic magnet monitoring. '
    'IEC 60601-2-33. Helium, gradient, RF, O2 monitoring.'
)


def simulate_mri(tick, helium_pct):
    """
    Simulates Siemens MAGNETOM Altea 1.5T operational telemetry.

    ── CRYOGENIC SYSTEM ─────────────────────────────────────────
    The superconducting magnet operates at 4.2 Kelvin (-268.95°C).
    Liquid helium fills the cryostat — approximately 1,500 litres
    for a 1.5T system.

    Zero Boil-Off (ZBO) system:
      A two-stage Gifford-McMahon cryocooler recondenses helium
      gas back to liquid. This eliminates routine helium loss
      under normal operation. Helium loss occurs only during:
        - Service events (cold head maintenance)
        - Unexpected faults (cryocooler failure)
        - Quench events

    Helium level decline rate simulated:
      Normal: ~0.1% per week under ZBO
      Cold head fault: ~1% per day
      Pre-quench: rapid decline

    ── GRADIENT COIL SYSTEM ─────────────────────────────────────
    The gradient coil (X, Y, Z axes) generates the magnetic
    field gradients needed for spatial encoding of MRI signals.
    During scanning — especially EPI and DWI sequences —
    gradient coils switch rapidly and generate significant heat.
    Water cooling removes this heat.

    A Gradient Power Amplifier (GPA) drives the gradient coils.
    Both GPA and gradient coil are water-cooled via chilled
    water circuit — inlet temperature ~18°C from hospital chiller.

    Temperature rises during:
      - fMRI (functional MRI) — continuous EPI
      - DWI (diffusion-weighted imaging) — high gradient duty cycle
      - Cardiac MRI — fast switching sequences

    ── RF SYSTEM ────────────────────────────────────────────────
    The RF transmit chain (RF amplifier → body coil) generates
    the radiofrequency pulses that excite hydrogen nuclei.
    RF amplifier heat load proportional to SAR (Specific
    Absorption Rate) and scan duration.

    ── OXYGEN MONITORING ────────────────────────────────────────
    IEC 60601-2-33 requires continuous O2 monitoring in MRI room.
    During a magnet quench — 1,500 litres of liquid helium
    converts to ~750,000 litres of gaseous helium — instantly
    displacing oxygen from the room.
    O2 below 19.5% → evacuate immediately.
    O2 below 16% → immediately life-threatening.
    """

    # ── SCAN CYCLE ──────────────────────────────────────────────
    # MRI scan cycle: 8 min exam, 2 min patient change
    # Different from CT — longer scans, lower repeat rate
    cycle_sec   = (tick * 2) % 600   # 10-minute cycle
    scanning    = cycle_sec < 480    # 8 minutes scanning

    # ── HELIUM LEVEL MODEL ───────────────────────────────────────
    # ZBO system — negligible normal decline
    # Slow drift over lifetime — represents months of operation
    # Add small random walk to simulate sensor noise
    helium_drift = -0.0001 + random.uniform(-0.001, 0.001)
    helium_pct   = max(0.0, min(100.0, helium_pct + helium_drift))

    # ── CRYOSTAT PRESSURE ────────────────────────────────────────
    # Normal: slight positive pressure 0.2-0.4 bar gauge
    # Rises slightly when cryocooler is working harder
    # (e.g., room temperature higher, or after service)
    cryo_pressure = (MRI_CRYO_PRESS_NORMAL
                     + math.sin(tick * 0.01) * 0.05
                     + random.uniform(-0.02, 0.02))

    # ── COLD HEAD TEMPERATURE ────────────────────────────────────
    # Two-stage Gifford-McMahon cryocooler
    # Stage 1: ~50K, Stage 2: ~4.2K
    # We monitor Stage 2 (helium temperature)
    # Should be very close to 4.2K for healthy system
    coldhead_k = (MRI_COLDHEAD_TEMP_GOOD
                  + math.sin(tick * 0.008) * 0.1
                  + random.uniform(-0.05, 0.05))

    # ── GRADIENT COIL TEMPERATURE ────────────────────────────────
    # Rises during scanning, falls during patient change
    # EPI sequences (fMRI) cause highest thermal load
    if scanning:
        scan_phase   = (cycle_sec % 120) / 120.0
        grad_temp    = (MRI_GRADIENT_TEMP_NORM
                       + math.sin(scan_phase * math.pi) * 8.0
                       + random.uniform(-0.5, 0.5))
    else:
        # Cooling during patient change
        cool_phase   = (cycle_sec - 480) / 120.0
        grad_temp    = (MRI_GRADIENT_TEMP_NORM + 6.0
                       - cool_phase * 6.0
                       + random.uniform(-0.3, 0.3))

    # ── RF AMPLIFIER TEMPERATURE ─────────────────────────────────
    # Proportional to scan duty cycle
    rf_temp = (MRI_RF_TEMP_NORM
               + (8.0 if scanning else 0.0)
               + random.uniform(-0.5, 0.5))

    # ── CHILLER INLET TEMPERATURE ────────────────────────────────
    # Hospital chilled water supply to gradient coil cooling loop
    # Varies with building load — warmer in summer
    hour = datetime.now().hour
    seasonal_offset = 2.0 if datetime.now().month in [6, 7, 8] else 0.0
    chiller_temp = (MRI_CHILLER_INLET_NORM
                    + seasonal_offset
                    + math.sin(tick * 0.005) * 0.5
                    + random.uniform(-0.2, 0.2))

    # ── MAGNETIC FIELD DEVIATION ─────────────────────────────────
    # Field is extremely stable under normal operation
    # Small drift from external interference or temperature change
    # Measured as deviation from nominal (1.5T)
    field_dev_mt = random.uniform(-0.0001, 0.0001)   # milliTesla

    # ── OXYGEN LEVEL ─────────────────────────────────────────────
    # Normal atmospheric oxygen: 20.9%
    # MRI room O2 stable under normal conditions
    # Any deviation = investigate immediately
    o2_level = O2_LEVEL_SAFE + random.uniform(-0.1, 0.1)

    # ── FAULT INJECTION ──────────────────────────────────────────
    fault, fault_type = False, None
    if random.random() < FAULT_PROBABILITY:
        fault_type = random.choice([
            'helium_low',
            'gradient_overheat',
            'coldhead_fault',
            'chiller_fault',
        ])
        fault = True

        if fault_type == 'helium_low':
            helium_pct  -= random.uniform(5, 15)
            cryo_pressure += random.uniform(0.3, 0.8)

        elif fault_type == 'gradient_overheat':
            grad_temp   += random.uniform(8, 18)

        elif fault_type == 'coldhead_fault':
            coldhead_k  += random.uniform(1.5, 4.0)
            cryo_pressure += random.uniform(0.2, 0.5)

        elif fault_type == 'chiller_fault':
            chiller_temp += random.uniform(5, 10)
            grad_temp   += random.uniform(3, 8)

    # ── OPERATIONAL STATUS ───────────────────────────────────────
    if helium_pct <= MRI_HELIUM_CRITICAL:
        status = 'QUENCH_RISK'
    elif fault_type in ('coldhead_fault', 'helium_low'):
        status = 'QUENCH_RISK'
    elif fault:
        status = 'SCANNING' if scanning else 'READY'
    elif scanning:
        status = 'SCANNING'
    else:
        status = 'READY'

    return {
        # Identity
        'device_id':              DEVICE_ID,
        'device_name':            DEVICE_NAME,
        'device_type':            'mri_scanner',
        'manufacturer':           'Siemens Healthineers',
        'model':                  'MAGNETOM Altea 1.5T',
        'timestamp':              datetime.now().isoformat(),
        'status':                 status,

        # ── CRYOGENIC SYSTEM ─────────────────────────────────────
        # Most important parameters for MRI service engineering
        'helium_level_pct':       round(helium_pct, 1),
        'cryo_pressure_bar':      round(cryo_pressure, 3),
        'coldhead_temp_k':        round(coldhead_k, 2),

        # ── GRADIENT SYSTEM ──────────────────────────────────────
        'gradient_temp_c':        round(grad_temp, 1),
        'chiller_inlet_temp_c':   round(chiller_temp, 1),
        'scanning':               scanning,

        # ── RF SYSTEM ────────────────────────────────────────────
        'rf_amp_temp_c':          round(rf_temp, 1),

        # ── MAGNETIC FIELD ────────────────────────────────────────
        'field_nominal_t':        MRI_FIELD_NOMINAL,
        'field_deviation_mt':     round(field_dev_mt * 1000, 4),

        # ── ROOM SAFETY ──────────────────────────────────────────
        # IEC 60601-2-33 — O2 monitoring mandatory
        'o2_level_pct':           round(o2_level, 1),

        # ── FAULT ────────────────────────────────────────────────
        'fault_active':           fault,
        'fault_type':             fault_type,

        # ── MODBUS REGISTER VALUES ────────────────────────────────
        # Scaled integers for register storage
        'reg_helium':      int(helium_pct * 10),
        'reg_cryo_press':  int(cryo_pressure * 100),
        'reg_coldhead':    int(coldhead_k * 100),
        'reg_gradient':    int(grad_temp * 10),
        'reg_rf_temp':     int(rf_temp * 10),
        'reg_chiller':     int(chiller_temp * 10),
        'reg_field_dev':   int(abs(field_dev_mt) * 1000),
        'reg_o2':          int(o2_level * 10),
        'reg_status':      MRI_STATUS_CODE.get(status, 0),
        'reg_fault':       int(fault),
    }, helium_pct


def update_registers(datastore):
    """
    Updates Modbus holding registers every 2 seconds.
    Helium level persists across ticks — simulates real depletion.
    """
    tick       = 0
    helium_pct = 87.0   # start at 87% — realistic for in-service scanner

    while True:
        try:
            # Check control register — edge may have written
            control_val = datastore[0x00].getValues(
                3, 10, count=1
            )[0]

            data, helium_pct = simulate_mri(tick, helium_pct)

            # Handle maintenance command
            if control_val == 2:
                data['status'] = 'MAINTENANCE'

            registers = [
                data['reg_helium'],
                data['reg_cryo_press'],
                data['reg_coldhead'],
                data['reg_gradient'],
                data['reg_rf_temp'],
                data['reg_chiller'],
                data['reg_field_dev'],
                data['reg_o2'],
                data['reg_status'],
                data['reg_fault'],
            ]
            datastore[0x00].setValues(3, 0, registers)

            fault_str = (
                f' ⚠ {data["fault_type"]}'
                if data['fault_active'] else ''
            )

            # Helium level indicator
            he_icon = ('🟢' if helium_pct >= MRI_HELIUM_GOOD
                       else '🟡' if helium_pct >= MRI_HELIUM_WARN
                       else '🔴')

            print(
                f'[MRI] {DEVICE_ID} '
                f'{he_icon}He={data["helium_level_pct"]:.1f}% '
                f'Grad={data["gradient_temp_c"]:.1f}°C '
                f'ColdH={data["coldhead_temp_k"]:.2f}K '
                f'O2={data["o2_level_pct"]:.1f}% '
                f'[{data["status"]}]'
                f'{fault_str}'
            )

            tick += 1
            time.sleep(2)

        except Exception as e:
            print(f'[MRI] Error: {e}')
            time.sleep(2)


def run_mri_plc(port):
    print(f'[MRI] Starting — {DEVICE_ID}')
    print(f'[MRI] {DEVICE_DESC}')
    print(f'[MRI] Modbus TCP — localhost:{port}')
    print(f'[MRI] Register map:')
    print(f'[MRI]   40001=helium_pct  40002=cryo_pressure_bar')
    print(f'[MRI]   40003=coldhead_K  40004=gradient_temp_C')
    print(f'[MRI]   40005=rf_temp_C   40006=chiller_inlet_C')
    print(f'[MRI]   40007=field_dev   40008=o2_pct')
    print(f'[MRI]   40009=status      40010=fault')
    print(f'[MRI]   40011=CONTROL (edge writes here)')
    print()
    print(f'[MRI] Standards: IEC 60601-2-33, Siemens MAGNETOM specs')
    print(f'[MRI] Real parameters: helium level >60% required')
    print(f'[MRI]                  O2 monitoring — quench safety')
    print(f'[MRI]                  Cold head 4.2K — ZBO cryocooler')
    print()

    block   = ModbusSequentialDataBlock(0, [0] * 11)
    store   = ModbusSlaveContext(hr=block, zero_mode=True)
    context = ModbusServerContext(slaves=store, single=True)

    threading.Thread(
        target=update_registers,
        args=(context,),
        daemon=True
    ).start()

    print(f'[MRI] Modbus TCP listening on port {port}')
    StartTcpServer(context=context, address=('localhost', port))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Simulated MRI scanner — Modbus TCP server'
    )
    parser.add_argument(
        '--port', type=int, default=5025,
        help='Modbus TCP port (default: 5025)'
    )
    args = parser.parse_args()
    run_mri_plc(args.port)
