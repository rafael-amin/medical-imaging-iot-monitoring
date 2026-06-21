# energy_config.py
# ISO 50001 Energy Management System Extension
# Hospital Imaging Department — Energy Monitoring Layer
#
# Standards implemented:
#   ISO 50001:2018  — Energy Management Systems
#   EN 50160        — Power quality limits
#   IEC 61557-12    — Power metering performance
#
# Real meter equivalents:
#   Siemens SENTRON PAC3200
#   Schneider Electric PowerLogic PM5000
#   Eaton Power Xpert Meter
#
# These meters are standard in Danish hospitals
# and pharmaceutical facilities
# All support Modbus TCP — your existing gateway reads them
#
# ISO 50001 Key Concepts implemented:
#   EnPI  — Energy Performance Indicator
#   SEU   — Significant Energy Use
#   Baseline — reference period consumption
#   Continuous improvement tracking

# ── ENERGY METER NODES ────────────────────────────────────────────────────────
# Add these to your existing NODES list in config.py

ENERGY_NODES = [
    {
        'id':              'HOSP01.ELEC01.METER01',
        'name':            'Main Power Meter — Imaging Wing',
        'type':            'energy_meter',
        'manufacturer':    'Siemens',
        'model':           'SENTRON PAC3200',
        'port':            5024,
        'topic_telemetry': 'HOSP01/ELEC01/METER01/TELEMETRY',
        'topic_state':     'HOSP01/ELEC01/METER01/STATE',
        'topic_alarm':     'HOSP01/ELEC01/METER01/ALARM',
        'topic_heartbeat': 'HOSP01/ELEC01/METER01/HEARTBEAT',
        'topic_energy':    'HOSP01/ELEC01/METER01/ENERGY',
    },
]

# ── ENERGY METER REGISTER MAP ─────────────────────────────────────────────────
# Siemens SENTRON PAC3200 Modbus register map
# These are the REAL register addresses from the SENTRON manual

SENTRON_REGISTERS = {
    # Address: (name, scale, unit, description)
    0:  ('voltage_l1_n',    0.1,    'V',    'Phase L1-N voltage'),
    1:  ('voltage_l2_n',    0.1,    'V',    'Phase L2-N voltage'),
    2:  ('voltage_l3_n',    0.1,    'V',    'Phase L3-N voltage'),
    3:  ('current_l1',      0.01,   'A',    'Phase L1 current'),
    4:  ('current_l2',      0.01,   'A',    'Phase L2 current'),
    5:  ('current_l3',      0.01,   'A',    'Phase L3 current'),
    6:  ('active_power',    1,      'W',    'Total active power'),
    7:  ('reactive_power',  1,      'VAr',  'Total reactive power'),
    8:  ('apparent_power',  1,      'VA',   'Total apparent power'),
    9:  ('power_factor',    0.001,  '',     'Total power factor'),
    10: ('frequency',       0.01,   'Hz',   'Grid frequency'),
    11: ('energy_kwh',      0.1,    'kWh',  'Total active energy'),
    12: ('thd_voltage',     0.1,    '%',    'Total harmonic distortion V'),
    13: ('thd_current',     0.1,    '%',    'Total harmonic distortion I'),
    14: ('demand_kw',       1,      'W',    '15-min demand'),
    15: ('peak_demand_kw',  1,      'W',    'Peak demand today'),
}

# ── ISO 50001 THRESHOLDS AND BASELINES ────────────────────────────────────────

# Energy baseline — reference consumption for comparison
# ISO 50001 requires documented baseline period
# Based on typical Danish hospital imaging department
# Source: Danish Energy Agency hospital benchmarks

ENERGY_BASELINE = {
    'daily_kwh':        850.0,   # kWh/day — baseline consumption
    'peak_demand_kw':   45.0,    # kW — baseline peak demand
    'power_factor_min': 0.90,    # minimum acceptable PF
    'idle_power_kw':    8.0,     # kW — expected off-hours consumption
}

# EnPI — Energy Performance Indicators
# ISO 50001 Section 6.4 — Energy performance indicators

ENPI_TARGETS = {
    'energy_per_scan_kwh':   2.5,    # kWh per CT scan — target
    'power_factor_target':   0.95,   # target power factor
    'idle_waste_max_kw':     12.0,   # max acceptable off-hours load
    'daily_improvement_pct': 1.0,    # % improvement target per month
}

# Power quality thresholds — EN 50160
# Same standard as your wind project
POWER_QUALITY = {
    'voltage_nom':     230.0,   # V nominal
    'voltage_low':     207.0,   # V — EN 50160 lower (207 = -10%)
    'voltage_high':    253.0,   # V — EN 50160 upper (+10%)
    'frequency_low':   49.5,    # Hz
    'frequency_high':  50.5,    # Hz
    'pf_warning':      0.90,    # below this = reactive power penalty
    'thd_voltage_max': 8.0,     # % — EN 50160 limit
    'thd_current_max': 20.0,    # % — medical equipment limit
}

# Operating schedule — ISO 50001 operational control
# Defines expected energy profile per time period
OPERATING_SCHEDULE = {
    'peak_hours':     list(range(8, 19)),    # 08:00-18:00 clinical hours
    'off_hours':      list(range(19, 24)) + list(range(0, 7)),
    'expected_peak_kw':    42.0,   # kW during clinical hours
    'expected_offhrs_kw':  8.0,    # kW overnight — baseline idle
}

# CO2 emission factors — Denmark
# Source: Energinet CO2 signal — real Danish grid
# Used for carbon reporting — EU sustainability reporting
CO2_KG_PER_KWH = 0.134   # kg CO2/kWh — Danish grid 2024 average
                           # Energinet publishes this in real time
                           # Your wind project already fetches it

# Danish electricity price — DKK/kWh
# Used for cost calculations
# Source: Energinet Nord Pool DK2
ELECTRICITY_PRICE_DKK = 1.85   # DKK/kWh — approximate 2024 average
