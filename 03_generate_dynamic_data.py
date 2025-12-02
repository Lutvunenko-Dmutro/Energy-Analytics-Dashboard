import psycopg2
import pandas as pd
import numpy as np
import random
import datetime
from psycopg2.extras import execute_values
import os
from dotenv import load_dotenv

# --- НАЛАШТУВАННЯ ---
load_dotenv()
DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "postgres"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "password"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432")
}

START_DATE = datetime.datetime(2025, 11, 1)
END_DATE = datetime.datetime(2025, 11, 30)
FREQ = "60min" 

# --- ПРОФІЛІ ---
PROFILE_RESIDENTIAL = {
    0: 0.4, 1: 0.35, 2: 0.32, 3: 0.32, 4: 0.35, 5: 0.45, 
    6: 0.60, 7: 0.80, 8: 0.90, 9: 0.85, 10: 0.75, 
    11: 0.70, 12: 0.70, 13: 0.70, 14: 0.72, 15: 0.75, 
    16: 0.85, 17: 0.95, 18: 1.00, 19: 0.98, 20: 0.95, 
    21: 0.90, 22: 0.75, 23: 0.55
}
PROFILE_INDUSTRIAL = {
    0: 0.60, 1: 0.55, 2: 0.55, 3: 0.55, 4: 0.58, 5: 0.65, 
    6: 0.75, 7: 0.85, 8: 0.95, 9: 0.98, 10: 0.98, 
    11: 0.98, 12: 0.90, 13: 0.95, 14: 0.98, 15: 0.98, 
    16: 0.95, 17: 0.85, 18: 0.75, 19: 0.70, 20: 0.65, 
    21: 0.60, 22: 0.60, 23: 0.60
}
PROFILE_COMMERCIAL = {
    0: 0.20, 1: 0.20, 2: 0.20, 3: 0.20, 4: 0.25, 5: 0.30, 
    6: 0.40, 7: 0.60, 8: 0.80, 9: 0.95, 10: 1.00, 
    11: 1.00, 12: 1.00, 13: 1.00, 14: 1.00, 15: 1.00, 
    16: 0.95, 17: 0.80, 18: 0.60, 19: 0.50, 20: 0.40, 
    21: 0.30, 22: 0.25, 23: 0.20
}

def get_db_connection():
    try:
        return psycopg2.connect(**DB_CONFIG)
    except Exception as e:
        print(f"Connection error: {e}")
        return None

def generate_professional_data():
    conn = get_db_connection()
    if not conn: return

    cursor = conn.cursor()
    print("🧹 Очищення старих даних...")
    cursor.execute("TRUNCATE TABLE LoadMeasurements, GenerationMeasurements, Alerts, WeatherReports, EnergyPricing, LineMeasurements CASCADE;")
    
    # Завантаження ВСІХ довідників
    cursor.execute("SELECT substation_id, capacity_mw, region_id FROM Substations")
    substations = cursor.fetchall()
    
    cursor.execute("SELECT generator_id, generator_type, max_output_mw FROM Generators")
    generators = cursor.fetchall()
    
    # ДОДАНО: Завантаження ліній
    cursor.execute("SELECT line_id, max_load_mw FROM PowerLines")
    lines = cursor.fetchall()

    cursor.execute("SELECT region_id FROM Regions")
    regions = [r[0] for r in cursor.fetchall()]

    # Типізація підстанцій
    sub_profiles = {}
    for sub in substations:
        sid = sub[0]
        r = random.random()
        if r < 0.5: sub_profiles[sid] = ('RESIDENTIAL', PROFILE_RESIDENTIAL)
        elif r < 0.8: sub_profiles[sid] = ('INDUSTRIAL', PROFILE_INDUSTRIAL)
        else: sub_profiles[sid] = ('COMMERCIAL', PROFILE_COMMERCIAL)
            
    print(f"🚀 Генерація даних з лініями ({START_DATE.date()} - {END_DATE.date()})...")
    
    timestamps = pd.date_range(START_DATE, END_DATE, freq=FREQ)
    
    batch_l, batch_g, batch_w, batch_p, batch_a, batch_lines = [], [], [], [], [], []
    current_temps = {rid: 10.0 for rid in regions} 
    
    for ts in timestamps:
        hour = ts.hour
        is_weekend = ts.weekday() >= 5
        
        # 1. ПОГОДА & ЦІНИ
        weather_map = {}
        for rid in regions:
            day_trend = -0.1
            daily_cycle = 4 * np.sin((hour - 9) * np.pi / 12)
            noise = np.random.normal(0, 0.5)
            current_temps[rid] += day_trend / 24 + np.random.normal(0, 0.1)
            final_temp = float(current_temps[rid] + daily_cycle + noise)
            cond = "Сонячно" if (6 < hour < 18 and random.random() > 0.3) else "Хмарно"
            
            weather_map[rid] = (final_temp, cond)
            batch_w.append((ts, rid, round(final_temp, 2), cond))
            
            price_base = 3000 if not is_weekend else 2500
            price_profile = PROFILE_RESIDENTIAL[hour]
            price = float(price_base * price_profile * random.uniform(0.95, 1.05))
            batch_p.append((ts, rid, round(price, 2)))

        # === 2. НАВАНТАЖЕННЯ ===
        for sub in substations:
            sid, cap, rid = sub
            cap = float(cap)
            
            temp_data = weather_map.get(rid)
            current_temp = temp_data[0]
            
            type_data = sub_profiles.get(sid)
            p_type = type_data[0]
            daily_profile = type_data[1]
            
            base_factor = daily_profile[hour]
            
            if is_weekend:
                if p_type == 'INDUSTRIAL':
                    base_factor = base_factor * 0.65
                elif p_type == 'COMMERCIAL':
                    base_factor = base_factor * 0.85
                else:
                    base_factor = base_factor * 1.05
            
            if current_temp < 15:
                diff = 15 - current_temp
                base_factor = base_factor + (diff * 0.015)
            
            noise = random.uniform(-0.03, 0.03)
            final_factor = base_factor + noise
            
            if final_factor < 0.1: final_factor = 0.1
            if final_factor > 1.1: final_factor = 1.1
            
            actual_load = cap * final_factor
            batch_l.append((ts, round(actual_load, 2), sid))
            
            if actual_load > (cap * 0.95):
                if random.randint(1, 100) <= 15:
                    msg = f"Критичне навантаження: {round(final_factor*100, 1)}%"
                    batch_a.append((ts, 'Перевантаження', msg, sid, 'NEW'))

        # === 3. ГЕНЕРАЦІЯ ===
        for gen in generators:
            gid, gtype, max_g = gen
            max_g = float(max_g)
            current_gen = 0.0
            
            if gtype == 'solar':
                if hour > 6 and hour < 19:
                    peak_hour = 12
                    efficiency = 1 - (abs(hour - peak_hour) / 7)
                    if efficiency < 0: efficiency = 0
                    
                    weather_coef = random.uniform(0.4, 1.0)
                    current_gen = max_g * efficiency * weather_coef
                else:
                    current_gen = 0.0
                    
            elif gtype == 'wind':
                wind_coef = random.uniform(0.1, 0.9)
                current_gen = max_g * wind_coef
                
            elif gtype == 'nuclear':
                current_gen = max_g * 0.95
                
            elif gtype == 'thermal':
                coef = PROFILE_RESIDENTIAL[hour]
                current_gen = max_g * coef * random.uniform(0.9, 1.0)
                
            else:
                current_gen = max_g * 0.5
            
            batch_g.append((ts, round(current_gen, 2), gid))

        # === 4. ЛІНІЇ ===
        for line in lines:
            lid, max_load = line
            max_load = float(max_load)
            
            base_load = PROFILE_RESIDENTIAL[hour]
            variation = random.uniform(0.9, 1.1)
            
            line_val = max_load * base_load * 0.7 * variation
            batch_lines.append((ts, round(line_val, 2), lid))

    # ЗАПИС
    print("💾 Збереження в базу даних...")
    execute_values(cursor, "INSERT INTO WeatherReports (timestamp, region_id, temperature, conditions) VALUES %s", batch_w)
    execute_values(cursor, "INSERT INTO EnergyPricing (timestamp, region_id, price_per_mwh) VALUES %s", batch_p)
    execute_values(cursor, "INSERT INTO LoadMeasurements (timestamp, actual_load_mw, substation_id) VALUES %s", batch_l)
    execute_values(cursor, "INSERT INTO GenerationMeasurements (timestamp, actual_generation_mw, generator_id) VALUES %s", batch_g)
    execute_values(cursor, "INSERT INTO LineMeasurements (timestamp, actual_load_mw, line_id) VALUES %s", batch_lines) # Запис ліній
    if batch_a:
        execute_values(cursor, "INSERT INTO Alerts (timestamp, alert_type, description, substation_id, status) VALUES %s", batch_a)
    
    conn.commit()
    conn.close()
    print(f"✅ Успішно! Згенеровано {len(batch_l)} записів.")

if __name__ == "__main__":
    generate_professional_data()
