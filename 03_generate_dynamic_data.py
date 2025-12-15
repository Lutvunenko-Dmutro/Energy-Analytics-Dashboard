import os
import random
import datetime
import logging
import numpy as np
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from contextlib import contextmanager
from typing import List, Tuple, Dict, Any, Optional
from dotenv import load_dotenv

# --- 1. CONFIGURATION & LOGGING (Шліфування) ---
load_dotenv()

# Налаштування логування замість print
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "postgres"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "password"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432")
}

# Константи винесені окремо (Чистка)
START_DATE = datetime.datetime(2025, 11, 1)
END_DATE = datetime.datetime(2025, 11, 30)
FREQ = "60min"

# Профілі навантаження (нормалізовані коефіцієнти)
LOAD_PROFILES = {
    'RESIDENTIAL': {
        0: 0.4, 1: 0.35, 2: 0.32, 3: 0.32, 4: 0.35, 5: 0.45, 
        6: 0.60, 7: 0.80, 8: 0.90, 9: 0.85, 10: 0.75, 
        11: 0.70, 12: 0.70, 13: 0.70, 14: 0.72, 15: 0.75, 
        16: 0.85, 17: 0.95, 18: 1.00, 19: 0.98, 20: 0.95, 
        21: 0.90, 22: 0.75, 23: 0.55
    },
    'INDUSTRIAL': {
        0: 0.60, 1: 0.55, 2: 0.55, 3: 0.55, 4: 0.58, 5: 0.65, 
        6: 0.75, 7: 0.85, 8: 0.95, 9: 0.98, 10: 0.98, 
        11: 0.98, 12: 0.90, 13: 0.95, 14: 0.98, 15: 0.98, 
        16: 0.95, 17: 0.85, 18: 0.75, 19: 0.70, 20: 0.65, 
        21: 0.60, 22: 0.60, 23: 0.60
    },
    'COMMERCIAL': {
        0: 0.20, 1: 0.20, 2: 0.20, 3: 0.20, 4: 0.25, 5: 0.30, 
        6: 0.40, 7: 0.60, 8: 0.80, 9: 0.95, 10: 1.00, 
        11: 1.00, 12: 1.00, 13: 1.00, 14: 1.00, 15: 1.00, 
        16: 0.95, 17: 0.80, 18: 0.60, 19: 0.50, 20: 0.40, 
        21: 0.30, 22: 0.25, 23: 0.20
    }
}

# --- 2. DATABASE UTILS (Шліфування) ---
@contextmanager
def get_db_cursor():
    """Контекстний менеджер для безпечної роботи з БД."""
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        yield conn, conn.cursor()
        conn.commit()
    except Exception as e:
        logger.error(f"Database operation failed: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()

# --- 3. BUSINESS LOGIC HELPER FUNCTIONS (Чистка & Декомпозиція) ---

def calculate_weather(hour: int, current_temps: Dict[int, float]) -> Dict[int, Tuple[float, str]]:
    """Розраховує погоду для кожного регіону на поточну годину."""
    weather_map = {}
    for region_id, current_temp in current_temps.items():
        day_trend = -0.1
        daily_cycle = 4 * np.sin((hour - 9) * np.pi / 12)
        noise = np.random.normal(0, 0.5)
        
        # Оновлюємо базову температуру (дрейф)
        current_temps[region_id] += day_trend / 24 + np.random.normal(0, 0.1)
        
        final_temp = float(current_temps[region_id] + daily_cycle + noise)
        condition = "Сонячно" if (6 < hour < 18 and random.random() > 0.3) else "Хмарно"
        
        weather_map[region_id] = (round(final_temp, 2), condition)
    return weather_map

def calculate_energy_price(hour: int, is_weekend: bool, region_id: int) -> float:
    """Визначає ціну за МВт на основі часу доби."""
    base_price = 2500 if is_weekend else 3000
    # Використовуємо профіль Residential як базовий коефіцієнт попиту
    demand_factor = LOAD_PROFILES['RESIDENTIAL'].get(hour, 0.5)
    price = base_price * demand_factor * random.uniform(0.95, 1.05)
    return round(price, 2)

def calculate_substation_load(
    capacity: float, 
    profile_type: str, 
    hour: int, 
    temp: float, 
    is_weekend: bool
) -> Tuple[float, Optional[Tuple]]:
    """
    Розраховує навантаження на підстанцію.
    Повертає: (actual_load, alert_tuple_or_None)
    """
    base_factor = LOAD_PROFILES[profile_type].get(hour, 0.5)
    
    # Коригування на вихідні
    if is_weekend:
        if profile_type == 'INDUSTRIAL': base_factor *= 0.6
        elif profile_type == 'COMMERCIAL': base_factor *= 0.8
        else: base_factor *= 1.05
    
    # Температурний фактор (обігрів)
    if temp < 15:
        base_factor += (15 - temp) * 0.02
    
    # Випадкові коливання
    base_factor += np.random.normal(0, 0.05)
    base_factor = max(0.1, min(base_factor, 1.2)) # Обмеження (clipping)
    
    actual_load = float(capacity * base_factor)
    
    # Генерація аварії
    alert = None
    if actual_load > capacity * 0.98 and random.random() < 0.2:
        alert = ('Перевантаження', f'Навантаження {base_factor*100:.1f}%', 'NEW')
        
    return round(actual_load, 2), alert

def calculate_generator_output(gen_type: str, max_mw: float, hour: int) -> float:
    """Розрахунок генерації в залежності від типу джерела."""
    if gen_type == 'solar':
        if 7 <= hour <= 17:
            sun_curve = np.sin((hour - 7) * np.pi / 10)
            # ВИПРАВЛЕННЯ ТУТ: огортаємо результат у float()
            val = max_mw * sun_curve * random.uniform(0.2, 1.0)
            return float(val) 
        return 0.0
    
    if gen_type == 'wind':
        ws = random.weibullvariate(2, 5)
        if 3 < ws < 25:
            val = max_mw * min(1, (ws**3)/(12**3))
            return float(val) # Тут теж про всяк випадок
        return 0.0
        
    if gen_type == 'nuclear':
        return float(max_mw * 0.98)
        
    if gen_type == 'thermal':
        val = max_mw * LOAD_PROFILES['RESIDENTIAL'].get(hour, 0.5) * random.uniform(0.8, 1.0)
        return float(val)
    
    return float(max_mw * 0.5)

# --- 4. MAIN ORCHESTRATOR (Чистка) ---

def generate_professional_data():
    logger.info("Початок процесу генерації даних...")
    
    with get_db_cursor() as (conn, cursor):
        # 1. Очищення
        logger.info("🧹 Очищення старих таблиць...")
        tables = ["LoadMeasurements", "GenerationMeasurements", "Alerts", 
                  "WeatherReports", "EnergyPricing", "LineMeasurements"]
        cursor.execute(f"TRUNCATE TABLE {', '.join(tables)} CASCADE;")
        
        # 2. Завантаження метаданих
        cursor.execute("SELECT substation_id, capacity_mw, region_id FROM Substations")
        substations = cursor.fetchall() # List[(id, cap, region)]
        
        cursor.execute("SELECT generator_id, generator_type, max_output_mw FROM Generators")
        generators = cursor.fetchall()
        
        cursor.execute("SELECT line_id, max_load_mw FROM PowerLines")
        lines = cursor.fetchall()
        
        cursor.execute("SELECT region_id FROM Regions")
        regions = [r[0] for r in cursor.fetchall()]

        # Призначення профілів
        sub_profiles = {}
        for sub in substations:
            sid = sub[0]
            r = random.random()
            if r < 0.5: sub_profiles[sid] = 'RESIDENTIAL'
            elif r < 0.8: sub_profiles[sid] = 'INDUSTRIAL'
            else: sub_profiles[sid] = 'COMMERCIAL'

        # 3. Головний цикл генерації
        logger.info(f"🚀 Генерація серії даних: {START_DATE.date()} -> {END_DATE.date()}")
        
        timestamps = pd.date_range(START_DATE, END_DATE, freq=FREQ)
        
        # Буфери для пакетної вставки (Batch Insert)
        data_weather = []
        data_prices = []
        data_loads = []
        data_generation = []
        data_lines = []
        data_alerts = []
        
        # Стан температури (stateful variable)
        current_temps = {rid: 10.0 for rid in regions} 

        for ts in timestamps:
            hour = ts.hour
            is_weekend = ts.weekday() >= 5
            
            # А. Погода і Ціни
            weather_map = calculate_weather(hour, current_temps) # Оновлює і повертає поточну погоду
            
            for rid in regions:
                temp, cond = weather_map[rid]
                data_weather.append((ts, rid, temp, cond))
                
                price = calculate_energy_price(hour, is_weekend, rid)
                data_prices.append((ts, rid, price))

            # Б. Навантаження підстанцій
            for sid, cap, rid in substations:
                p_type = sub_profiles[sid]
                temp, _ = weather_map[rid]
                
                actual_load, alert_info = calculate_substation_load(float(cap), p_type, hour, temp, is_weekend)
                data_loads.append((ts, actual_load, sid))
                
                if alert_info:
                    # Розпаковка кортежу alert_info
                    a_type, a_desc, a_status = alert_info
                    data_alerts.append((ts, a_type, a_desc, sid, a_status))

            # В. Генерація
            for gid, gtype, max_g in generators:
                gen_val = calculate_generator_output(gtype, float(max_g), hour)
                data_generation.append((ts, round(gen_val, 2), gid))

            # Г. Лінії
            for lid, max_l in lines:
                # Спрощена модель: лінія залежить від загального профілю споживання
                line_load = float(max_l) * LOAD_PROFILES['RESIDENTIAL'][hour] * random.uniform(0.6, 0.9)
                data_lines.append((ts, round(line_load, 2), lid))

        # 4. Збереження в БД
        logger.info("💾 Запис даних у базу...")
        
        insert_map = [
            ("WeatherReports", "timestamp, region_id, temperature, conditions", data_weather),
            ("EnergyPricing", "timestamp, region_id, price_per_mwh", data_prices),
            ("LoadMeasurements", "timestamp, actual_load_mw, substation_id", data_loads),
            ("GenerationMeasurements", "timestamp, actual_generation_mw, generator_id", data_generation),
            ("LineMeasurements", "timestamp, actual_load_mw, line_id", data_lines),
        ]
        
        for table, columns, data in insert_map:
            query = f"INSERT INTO {table} ({columns}) VALUES %s"
            execute_values(cursor, query, data)
            
        if data_alerts:
            query_alerts = "INSERT INTO Alerts (timestamp, alert_type, description, substation_id, status) VALUES %s"
            execute_values(cursor, query_alerts, data_alerts)

    logger.info(f"✅ Успішно! Згенеровано {len(data_loads)} записів навантаження.")

if __name__ == "__main__":
    try:
        generate_professional_data()
    except Exception as e:
        logger.critical(f"Критична помилка виконання: {e}")
