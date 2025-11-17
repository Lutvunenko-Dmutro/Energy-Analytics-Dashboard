import psycopg2
import pandas as pd
import numpy as np
import random
import datetime
from psycopg2.extras import execute_values
import os
from dotenv import load_dotenv

# ---
# 1. НАЛАШТУВАННЯ СИМУЛЯЦІЇ
# ---

load_dotenv()

DB_CONFIG = {
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "host": os.getenv("DB_HOST", "localhost"), 
    "port": os.getenv("DB_PORT", "5432")
}

# Параметри симуляції
START_DATE = datetime.datetime(2025, 10, 1)
END_DATE = datetime.datetime(2025, 11, 16)
TIME_STEP = datetime.timedelta(minutes=15) 

print(f"Симуляція даних з {START_DATE} по {END_DATE}...")

def get_db_connection():
    """Створює та повертає з'єднання з БД."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        print("✅ Підключення до PostgreSQL успішне.")
        return conn
    except psycopg2.OperationalError as e:
        print(f"❌ НЕ ВДАЛОСЯ ПІДКЛЮЧИТИСЯ: {e}")
        print("Перевірте ваші логін/пароль/назву БД у DB_CONFIG.")
        return None

# ---
# 2. "ЧИТАЧ ДОВІДНИКІВ"
# ---

def fetch_static_data(conn):
    """Завантажує довідники (Підстанції, Генератори, Лінії, Регіони) з БД."""
    cursor = conn.cursor()
    
    with conn.cursor() as cursor:
        cursor.execute("SELECT substation_id, capacity_mw, region_id FROM Substations")
        substations = cursor.fetchall()
        
        cursor.execute("SELECT generator_id, generator_type, max_output_mw FROM Generators")
        generators = cursor.fetchall()
        
        cursor.execute("SELECT line_id, max_load_mw, from_substation_id FROM PowerLines")
        lines = cursor.fetchall()
        
        cursor.execute("SELECT region_id FROM Regions")
        regions = cursor.fetchall()

    print(f"Завантажено {len(substations)} підстанцій, {len(generators)} генераторів, {len(lines)} ліній.")
    return substations, generators, lines, regions

# ---
# 3. "МОДЕЛІ ПОВЕДІНКИ" (Логіка "фантазування")
# ---

def get_weather(timestamp, region_id):
    """Генерує реалістичну погоду."""
    day_of_year = timestamp.timetuple().tm_yday
    hour = timestamp.hour
    
    temp_base = 10 + 5 * np.sin(2 * np.pi * (day_of_year - 80) / 365.25)
    temp_daily = -3 * np.sin(2 * np.pi * hour / 24)
    temperature = round(temp_base + temp_daily + random.uniform(-1, 1), 2)
    
    conditions = "Сонячно"
    if hour < 6 or hour > 20:
        conditions = "Ніч"
    elif temperature < 8 or random.random() < 0.3:
        conditions = "Хмарно"
    
    return temperature, conditions

def get_price(timestamp, region_id):
    """Генерує ціну залежно від години (пік, ніч)."""
    hour = timestamp.hour
    if 0 <= hour < 7: # Ніч
        return 2000.00 + random.uniform(0, 100)
    if 18 <= hour < 23: # Вечірній пік
        return 5000.00 + random.uniform(0, 500)
    return 3500.00 + random.uniform(0, 300) # День

def get_generation(generator, weather_conditions, timestamp):
    """Генерує виробіток для генератора."""
    g_id, g_type, max_output_decimal = generator
    max_output = float(max_output_decimal) 
    
    hour = timestamp.hour
    output = 0.0
    
    if g_type == 'solar':
        if weather_conditions == "Сонячно" and 7 < hour < 19:
            output = max_output * (1 - abs(hour - 13) / 6) * random.uniform(0.8, 1.0)
        else:
            output = max_output * 0.1
    
    elif g_type == 'thermal':
        output = max_output * random.uniform(0.7, 0.9)
    
    elif g_type == 'wind':
        output = max_output * random.uniform(0.2, 1.0)
        
    return round(max(0, output), 2)

def get_load(substation, timestamp, temperature):
    """Генерує навантаження для підстанції (найскладніша логіка)."""
    sub_id, capacity_decimal, region_id = substation
    capacity = float(capacity_decimal)

    hour = timestamp.hour
    
    base_load = capacity * 0.3
    daily_pattern_raw = np.sin(2 * np.pi * (hour - 10) / 24) + 1
    daily_pattern = (daily_pattern_raw / 2) * capacity * 0.4
    
    weather_effect = 0
    if temperature < 5: 
        weather_effect = (5 - temperature) * (capacity * 0.02)
    if temperature > 22:
        weather_effect = (temperature - 22) * (capacity * 0.015)

    noise = capacity * 0.03 * random.uniform(-1, 1)
    
    total_load = base_load + daily_pattern + weather_effect + noise
    
    is_alert = False
    if random.random() < 0.001: 
        total_load = capacity * random.uniform(1.05, 1.2)
        is_alert = True
        
    return total_load, is_alert

# ---
# 4. "СИМУЛЯТОР ЖИТТЯ" (Головний цикл)
# ---

def run_simulation(conn, substations, generators, lines, regions):
    
    timestamps = pd.date_range(START_DATE, END_DATE, freq=TIME_STEP)
    
    print("Початок генерації... Це може зайняти хвилину.")
    generated_weather = []
    generated_prices = []
    generated_loads = []
    generated_gens = []
    generated_lines = []
    generated_alerts = []

    for ts in timestamps:
        
        weather_cache = {}
        for r in regions:
            region_id = r[0]
            temp, cond = get_weather(ts, region_id)
            price = get_price(ts, region_id)
            
            weather_cache[region_id] = (temp, cond)
            generated_weather.append((ts, region_id, float(temp), cond))
            generated_prices.append((ts, region_id, float(price)))
            
        for sub in substations:
            sub_id, capacity_decimal, region_id = sub
            
            temp, cond = weather_cache[region_id]
            
            load, is_alert = get_load(sub, ts, temp)
            generated_loads.append((ts, float(round(load, 2)), sub_id))
            
            if is_alert:
                capacity = float(capacity_decimal) 
                desc = f"Авто-детект: Перевантаження на {sub_id}! Навантаження: {load:.2f} МВт, Ліміт: {capacity} МВт"
                generated_alerts.append((ts, 'Перевантаження', desc, sub_id))

        for gen in generators:
            temp, cond = weather_cache[regions[0][0]] 
            gen_output = get_generation(gen, cond, ts)
            generated_gens.append((ts, float(gen_output), gen[0]))
            
        for line in lines:
            line_id, max_load_decimal, from_sub_id = line
            max_load = float(max_load_decimal) 
            
            line_load = max_load * 0.3 + random.uniform(0, max_load * 0.2)
            generated_lines.append((ts, float(round(line_load, 2)), line_id))

    print(f"✅ Генерацію завершено. {len(timestamps)} кроків часу оброблено.")
    
    # ---
    # 5. "ЕФЕКТИВНИЙ ЗАПИС" (Batch Insert)
    # ---
    
    print("Початок запису в базу даних (використовуємо batch insert)...")
    with conn.cursor() as cursor:
        execute_values(cursor, 
                       "INSERT INTO WeatherReports (timestamp, region_id, temperature, conditions) VALUES %s", 
                       generated_weather)
        print(f"Записано {len(generated_weather)} звітів про погоду.")
        
        execute_values(cursor, 
                       "INSERT INTO EnergyPricing (timestamp, region_id, price_per_mwh) VALUES %s", 
                       generated_prices)
        print(f"Записано {len(generated_prices)} звітів про ціни.")

        execute_values(cursor, 
                       "INSERT INTO LoadMeasurements (timestamp, actual_load_mw, substation_id) VALUES %s", 
                       generated_loads)
        print(f"Записано {len(generated_loads)} вимірювань навантаження.")

        execute_values(cursor, 
                       "INSERT INTO GenerationMeasurements (timestamp, actual_generation_mw, generator_id) VALUES %s", 
                       generated_gens)
        print(f"Записано {len(generated_gens)} вимірювань генерації.")
        
        execute_values(cursor, 
                       "INSERT INTO LineMeasurements (timestamp, actual_load_mw, line_id) VALUES %s", 
                       generated_lines)
        print(f"Записано {len(generated_lines)} вимірювань на лініях.")

        if generated_alerts:
             execute_values(cursor, 
                            "INSERT INTO Alerts (timestamp, alert_type, description, substation_id) VALUES %s", 
                            generated_alerts)
             print(f"🚨🚨🚨 Записано {len(generated_alerts)} ТРИВОГ! 🚨🚨🚨")

    conn.commit()
    print("✅ УСІ ДАНІ УСПІШНО ЗАПИСАНО В БАЗУ!")

# ---
# ЗАПУСК СКРИПТА
# ---
if __name__ == "__main__":
    conn = get_db_connection()
    if conn:
        try:
            substations, generators, lines, regions = fetch_static_data(conn)
            run_simulation(conn, substations, generators, lines, regions)
        except Exception as e:
            print(f"Сталася помилка: {e}")
            conn.rollback()
        finally:
            conn.close()
            print("З'єднання з базою даних закрито.")