# data_client.py
# Real Data Client — DMI Danish Meteorological Institute
#
# Fetches real Danish outdoor temperature and humidity
# Used to drive realistic hospital room environment simulation
#
# Why real data matters:
#   Hospital HVAC systems respond to outdoor conditions
#   Summer heat increases cooling load — room temp harder to control
#   Winter cold can cause humidity issues — condensation on equipment
#   Real data makes environment simulation credible
#
# DMI Open Data:
#   Register free at dmi.dk/friedata
#   No cost — government open data
#   Same data used by Danish meteorologists

import requests
import threading
import time
from datetime import datetime

from config import (
    DMI_API_KEY, DMI_STATION, DMI_URL,
    DEFAULT_OUTDOOR_TEMP, DEFAULT_OUTDOOR_HUMIDITY
)

# ── SHARED STATE ──────────────────────────────────────────────────────────────
_outdoor_data = {
    'temp_c':       DEFAULT_OUTDOOR_TEMP,
    'humidity_pct': DEFAULT_OUTDOOR_HUMIDITY,
    'last_updated': None,
    'source':       'default',
}
_lock = threading.Lock()


def fetch_dmi_data():
    """
    Fetches real outdoor conditions from DMI API.
    Aarhus Airport station — representative of Danish hospital environment.

    Falls back to seasonal defaults if API unavailable.
    Real hospital monitoring systems do the same —
    last-known-good is better than no data.
    """
    global _outdoor_data

    # Seasonal defaults — based on real Aarhus monthly averages
    # Used as fallback if DMI API key not configured
    month = datetime.now().month
    seasonal_temp = {
        1: 1.5,  2: 1.8,  3: 4.2,  4: 8.5,
        5: 13.2, 6: 16.4, 7: 18.1, 8: 17.8,
        9: 14.2, 10: 9.8, 11: 5.3, 12: 2.6
    }
    seasonal_humidity = {
        1: 85, 2: 82, 3: 78, 4: 72,
        5: 68, 6: 70, 7: 72, 8: 74,
        9: 78, 10: 82, 11: 86, 12: 87
    }

    # Try DMI API if key is configured
    if DMI_API_KEY and DMI_API_KEY != 'YOUR_FREE_DMI_API_KEY':
        try:
            url = DMI_URL.format(
                key=DMI_API_KEY,
                station=DMI_STATION
            )
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                features = r.json().get('features', [])
                if features:
                    props    = features[0].get('properties', {})
                    temp     = float(props.get('value', seasonal_temp[month]))
                    humidity = float(
                        features[1].get('properties', {}).get(
                            'value', seasonal_humidity[month]
                        )
                        if len(features) > 1
                        else seasonal_humidity[month]
                    )
                    with _lock:
                        _outdoor_data = {
                            'temp_c':       round(temp, 1),
                            'humidity_pct': round(humidity, 1),
                            'last_updated': datetime.now().isoformat(),
                            'source':       'DMI_API',
                        }
                    print(
                        f'[DATA] DMI real data: '
                        f'outdoor={temp:.1f}°C '
                        f'humidity={humidity:.0f}%'
                    )
                    return
        except Exception as e:
            print(f'[DATA] DMI API error: {e} — using seasonal defaults')

    # Use seasonal defaults
    temp     = seasonal_temp[month]
    humidity = seasonal_humidity[month]
    with _lock:
        _outdoor_data = {
            'temp_c':       temp,
            'humidity_pct': humidity,
            'last_updated': datetime.now().isoformat(),
            'source':       f'seasonal_default_month_{month}',
        }
    print(
        f'[DATA] Seasonal defaults: '
        f'outdoor={temp:.1f}°C '
        f'humidity={humidity:.0f}% '
        f'(month {month} — Aarhus average)'
    )


def get_outdoor_data():
    """Thread-safe read of current outdoor conditions."""
    with _lock:
        return dict(_outdoor_data)


def outdoor_data_loop():
    """Refresh outdoor data every 10 minutes."""
    while True:
        fetch_dmi_data()
        time.sleep(600)


def start_background_refresh():
    """Start background data refresh thread."""
    fetch_dmi_data()
    threading.Thread(
        target=outdoor_data_loop,
        daemon=True
    ).start()
    print('[DATA] DMI data refresh started — updating every 10 minutes')
