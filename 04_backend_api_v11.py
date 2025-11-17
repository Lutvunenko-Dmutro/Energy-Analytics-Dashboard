import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import datetime
import os
from dotenv import load_dotenv

# ---
# 1. НАЛАШТУВАННЯ
# ---

app = FastAPI(
    title="Energy System API v11.0 (Operational)",
    description="Професійний API з інтерактивним керуванням тривогами."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"], 
    allow_headers=["*"]
)

load_dotenv()

DB_CONFIG = {
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "host": os.getenv("DB_HOST", "localhost"), 
    "port": os.getenv("DB_PORT", "5432")
}

def get_db_connection():
    """Створює підключення до БД (використовуючи RealDictCursor)."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        print(f"❌ НЕ ВДАЛОСЬ ПІДКЛЮЧИТИСЯ ДО БД: {e}")
        return None

def convert_decimals(data):
    """Конвертує Decimal та Datetime у float/str."""
    for row in data:
        for key, value in row.items():
            if isinstance(value, datetime.datetime):
                row[key] = value.isoformat()
            elif hasattr(value, 'default'): 
                row[key] = float(value)
    return data

# ---
# 2. - Інтерактивні Тривоги
# ---

@app.get("/api/v11/alerts/active")
def get_active_alerts():
    """
    Повертає ТІЛЬКИ активні ('NEW') тривоги.
    """
    print("Запит: /api/v11/alerts/active")
    sql_query = """
        SELECT 
            a.alert_id, 
            a.timestamp, 
            s.substation_name, 
            s.capacity_mw AS substation_limit, 
            a.description AS alert_description
        FROM Alerts a
        JOIN Substations s ON a.substation_id = s.substation_id
        WHERE 
            a.status = 'NEW' 
        ORDER BY 
            a.timestamp DESC;
    """
    conn = get_db_connection()
    if not conn: return {"error": "DB Connection failed"}
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(sql_query)
            data = cursor.fetchall()
        print(f"✅ Знайдено {len(data)} активних тривог.")
        return convert_decimals(data)
    except Exception as e:
        print(f"❌ ПОМИЛКА SQL-ЗАПИТУ (Active Alerts): {e}")
        return {"error": f"Помилка запиту: {e}"}
    finally:
        if conn: conn.close()

@app.post("/api/v11/alerts/{alert_id}/resolve")
def resolve_alert(alert_id: int):
    """
    "Закриває" тривогу (встановлює статус 'RESOLVED').
    Це POST-запит.
    """
    print(f"Запит: /api/v11/alerts/{alert_id}/resolve (POST)")
    sql_query = """
        UPDATE Alerts 
        SET status = 'RESOLVED' 
        WHERE alert_id = %s 
          AND status = 'NEW';
    """
    conn = get_db_connection()
    if not conn: return {"error": "DB Connection failed"}
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql_query, (alert_id,))
            conn.commit() 
            
            if cursor.rowcount > 0:
                print(f"✅ Тривога {alert_id} успішно закрита.")
                return {"message": f"Alert {alert_id} resolved successfully."}
            else:
                print(f"⚠️ Тривога {alert_id} не знайдена або вже закрита.")
                return {"message": f"Alert {alert_id} not found or already resolved."}
                
    except Exception as e:
        conn.rollback()
        print(f"❌ ПОМИЛКА SQL-ЗАПИТУ (Resolve Alert): {e}")
        return {"error": f"Помилка запиту: {e}"}
    finally:
        if conn: conn.close()


@app.get("/api/v10/analysis/sankey")
def get_sankey_data_plotly():
    print("Запит: /api/v10/analysis/sankey (для Plotly)")
    conn = get_db_connection()
    if not conn: return {"error": "DB Connection failed"}
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            sql_generation_flow = "SELECT 'Г: ' || g.generator_type AS \"from\", 'Р: ' || r.region_name AS \"to\", SUM(gm.actual_generation_mw) AS \"value\" FROM GenerationMeasurements gm JOIN Generators g ON gm.generator_id = g.generator_id JOIN Substations s ON g.substation_id = s.substation_id JOIN Regions r ON s.region_id = r.region_id GROUP BY 1, 2;"
            cursor.execute(sql_generation_flow)
            gen_flow = cursor.fetchall()
            sql_consumption_flow = "SELECT 'Р: ' || r.region_name AS \"from\", 'С: ' || c.consumer_type AS \"to\", SUM(lm.actual_load_mw) AS \"value\" FROM LoadMeasurements lm JOIN Consumers c ON lm.substation_id = c.substation_id JOIN Substations s ON c.substation_id = s.substation_id JOIN Regions r ON s.region_id = r.region_id GROUP BY 1, 2;"
            cursor.execute(sql_consumption_flow)
            con_flow = cursor.fetchall()
            all_flows = gen_flow + con_flow
            nodes = []
            links_data = []
            for row in all_flows:
                if row['from'] not in nodes: nodes.append(row['from'])
                if row['to'] not in nodes: nodes.append(row['to'])
                links_data.append(row)
            links = {"source": [], "target": [], "value": [], "label": []}
            for link in links_data:
                links['source'].append(nodes.index(link['from']))
                links['target'].append(nodes.index(link['to']))
                links['value'].append(float(link['value']))
                links['label'].append(f"{link['from']} -> {link['to']}")
        print("✅ Запит Sankey (Plotly) виконано.")
        return {"nodes": {"label": nodes}, "links": links}
    except Exception as e:
        print(f"❌ ПОМИЛКА SQL-ЗАПИТУ (Sankey Plotly): {e}")
        return {"error": f"Помилка запиту: {e}"}
    finally:
        if conn: conn.close()

@app.get("/api/v8/analysis/heatmap")
def get_heatmap_data():
    print("Запит: /api/v8/analysis/heatmap")
    sql_query = "SELECT EXTRACT(ISODOW FROM timestamp) AS day_of_week, EXTRACT(HOUR FROM timestamp) AS hour_of_day, AVG(actual_load_mw) AS avg_load FROM LoadMeasurements GROUP BY 1, 2 ORDER BY 1, 2;"
    conn = get_db_connection()
    if not conn: return {"error": "DB Connection failed"}
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(sql_query)
            data = cursor.fetchall()
        print("✅ Запит Heatmap виконано.")
        return convert_decimals(data)
    except Exception as e:
        print(f"❌ ПОМИЛКА SQL-ЗАПИТУ (Heatmap): {e}")
        return {"error": f"Помилка запиту: {e}"}
    finally:
        if conn: conn.close()

@app.get("/api/v7/map/full_network")
def get_full_network_map_data():
    print("Запит: /api/v7/map/full_network (Супер-API)")
    conn = get_db_connection()
    if not conn: return {"error": "DB Connection failed"}
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            sql_nodes = """
                WITH LatestLoads AS (SELECT DISTINCT ON (substation_id) substation_id, actual_load_mw FROM LoadMeasurements ORDER BY substation_id, timestamp DESC)
                SELECT s.substation_id, s.substation_name, s.latitude, s.longitude, s.capacity_mw, COALESCE(ll.actual_load_mw, 0) AS current_load,
                       CASE WHEN s.capacity_mw > 0 THEN (COALESCE(ll.actual_load_mw, 0) / s.capacity_mw) * 100 ELSE 0 END AS load_percent
                FROM Substations s LEFT JOIN LatestLoads ll ON s.substation_id = ll.substation_id
                WHERE s.latitude IS NOT NULL AND s.longitude IS NOT NULL;
            """
            cursor.execute(sql_nodes)
            nodes = cursor.fetchall()
            sql_edges = """
                WITH LatestLineLoads AS (SELECT DISTINCT ON (line_id) line_id, actual_load_mw FROM LineMeasurements ORDER BY line_id, timestamp DESC)
                SELECT pl.line_id, pl.from_substation_id, pl.to_substation_id, pl.line_name, pl.max_load_mw, COALESCE(lll.actual_load_mw, 0) AS current_load,
                       CASE WHEN pl.max_load_mw > 0 THEN (COALESCE(lll.actual_load_mw, 0) / pl.max_load_mw) * 100 ELSE 0 END AS load_percent
                FROM PowerLines pl LEFT JOIN LatestLineLoads lll ON pl.line_id = lll.line_id;
            """
            cursor.execute(sql_edges)
            edges = cursor.fetchall()
        print("✅ Запит гео-топології мережі виконано.")
        return {"nodes": convert_decimals(nodes), "edges": convert_decimals(edges)}
    except Exception as e:
        print(f"❌ ПОМИЛКА SQL-ЗАПИТУ (Geo-Network): {e}")
        return {"error": f"Помилка запиту: {e}"}
    finally:
        if conn: conn.close()

@app.get("/api/v5/analysis/consumer_types")
def get_consumer_type_analysis():
    print("Запит: /api/v5/analysis/consumer_types")
    sql_query = "SELECT consumer_type, COUNT(*) AS consumer_count FROM Consumers GROUP BY consumer_type;"
    conn = get_db_connection()
    if not conn: return {"error": "DB Connection failed"}
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(sql_query)
            data = cursor.fetchall()
        return convert_decimals(data)
    except Exception as e:
        print(f"❌ ПОМИЛКА SQL-ЗАПИТУ (Consumer Analysis): {e}")
        return {"error": f"Помилка запиту: {e}"}
    finally:
        if conn: conn.close()

@app.get("/api/v5/maintenance/calendar")
def get_maintenance_calendar():
    print("Запит: /api/v5/maintenance/calendar")
    sql_query = """
        SELECT me.start_time, me.end_time, me.reason, me.object_type,
               CASE WHEN me.object_type = 'Підстанція' THEN s.substation_name
                    WHEN me.object_type = 'Лінія' THEN pl.line_name
                    ELSE 'N/A' END AS object_name
        FROM MaintenanceEvents me
        LEFT JOIN Substations s ON me.object_id = s.substation_id AND me.object_type = 'Підстанція'
        LEFT JOIN PowerLines pl ON me.object_id = pl.line_id AND me.object_type = 'Лінія'
        ORDER BY me.start_time ASC;
    """
    conn = get_db_connection()
    if not conn: return {"error": "DB Connection failed"}
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(sql_query)
            data = cursor.fetchall()
        return convert_decimals(data)
    except Exception as e:
        print(f"❌ ПОМИЛКА SQL-ЗАПИТУ (Maintenance): {e}")
        return {"error": f"Помилка запиту: {e}"}
    finally:
        if conn: conn.close()

@app.get("/api/v4/forecast/live")
def get_live_forecast_fast():
    print("Запит: /api/v4/forecast/live (ШВИДКА ВЕРСІЯ)")
    conn = get_db_connection()
    if not conn: return {"error": "DB Connection failed"}
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            sql_history_48h = """
                WITH time_window AS (SELECT (MAX(timestamp) - INTERVAL '48 hours') AS start_time, (MAX(timestamp)) AS end_time FROM LoadMeasurements)
                SELECT lm.timestamp, lm.actual_load_mw, s.capacity_mw AS substation_limit
                FROM LoadMeasurements lm JOIN Substations s ON lm.substation_id = s.substation_id
                CROSS JOIN time_window tw
                WHERE lm.timestamp BETWEEN tw.start_time AND tw.end_time AND s.substation_id = 10 ORDER BY lm.timestamp;
            """
            cursor.execute(sql_history_48h)
            history_data = cursor.fetchall()
            sql_forecast = """
                WITH LatestTime AS (SELECT MAX(timestamp) AS max_ts FROM LoadMeasurements),
                History AS (SELECT timestamp, actual_load_mw FROM LoadMeasurements WHERE substation_id = 10 AND timestamp BETWEEN (SELECT max_ts - INTERVAL '7 days' FROM LatestTime) AND (SELECT max_ts FROM LatestTime)),
                TypicalDay AS (SELECT (EXTRACT(HOUR FROM timestamp) * 4 + EXTRACT(MINUTE FROM timestamp) / 15)::int AS quarter_hour_index, AVG(actual_load_mw) AS avg_load FROM History GROUP BY 1),
                ForecastWindow AS (SELECT (SELECT max_ts FROM LatestTime) + (n || ' minutes')::interval AS forecast_timestamp FROM generate_series(15, 24 * 60, 15) n)
                SELECT fw.forecast_timestamp AS timestamp, td.avg_load AS forecast_load
                FROM ForecastWindow fw JOIN TypicalDay td ON (EXTRACT(HOUR FROM fw.forecast_timestamp) * 4 + EXTRACT(MINUTE FROM fw.forecast_timestamp) / 15)::int = td.quarter_hour_index
                ORDER BY fw.forecast_timestamp;
            """
            cursor.execute(sql_forecast)
            forecast_data = cursor.fetchall()
        print("✅ Запит прогнозу виконано ШВИДКО.")
        return {"history": convert_decimals(history_data), "forecast": convert_decimals(forecast_data)}
    except Exception as e:
        print(f"❌ ПОМИЛКА SQL-ЗАПИТУ (Fast Forecast): {e}")
        return {"error": f"Помилка запиту: {e}"}
    finally:
        if conn: conn.close()

@app.get("/api/v4/finance/hourly_cost")
def get_hourly_cost():
    print("Запит: /api/v4/finance/hourly_cost")
    conn = get_db_connection()
    if not conn: return {"error": "DB Connection failed"}
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            sql_query = """
                WITH HourlyData AS (SELECT date_trunc('hour', lm.timestamp) AS hour, s.region_id, SUM(lm.actual_load_mw * 0.25) AS total_mwh_consumed FROM LoadMeasurements lm JOIN Substations s ON lm.substation_id = s.substation_id GROUP BY 1, 2),
                     HourlyPrices AS (SELECT date_trunc('hour', timestamp) AS hour, region_id, AVG(price_per_mwh) AS avg_price_per_mwh FROM EnergyPricing GROUP BY 1, 2)
                SELECT hd.hour, SUM(hd.total_mwh_consumed * hp.avg_price_per_mwh) AS total_hourly_cost
                FROM HourlyData hd JOIN HourlyPrices hp ON hd.hour = hp.hour AND hd.region_id = hp.region_id
                WHERE hd.hour >= (SELECT MAX(timestamp) - INTERVAL '7 days' FROM LoadMeasurements)
                GROUP BY hd.hour ORDER BY hd.hour;
            """
            cursor.execute(sql_query)
            data = cursor.fetchall()
        return convert_decimals(data)
    except Exception as e:
        print(f"❌ ПОМИЛКА SQL-ЗАПИТУ (Finance): {e}")
        return {"error": f"Помилка запиту: {e}"}
    finally:
        if conn: conn.close()

@app.get("/api/v1/load/hourly")
def get_hourly_load_pattern():
    print("Запит: /api/v1/load/hourly")
    conn = get_db_connection()
    if not conn: return {"error": "DB Connection failed"}
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            sql_query = "SELECT EXTRACT(HOUR FROM timestamp) AS hour_of_day, AVG(actual_load_mw) AS avg_load FROM LoadMeasurements GROUP BY hour_of_day ORDER BY hour_of_day;"
            cursor.execute(sql_query)
            data = cursor.fetchall()
        return convert_decimals(data)
    except Exception as e:
        print(f"❌ ПОМИЛКА SQL-ЗАПИТУ (Hourly Load): {e}")
        return {"error": f"Помилка запиту: {e}"}
    finally:
        if conn: conn.close()

@app.get("/api/v2/generation/mix")
def get_generation_mix():
    print("Запит: /api/v2/generation/mix")
    conn = get_db_connection()
    if not conn: return {"error": "DB Connection failed"}
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            sql_query = "SELECT g.generator_type, SUM(gm.actual_generation_mw) AS total_generated FROM GenerationMeasurements gm JOIN Generators g ON gm.generator_id = g.generator_id GROUP BY g.generator_type;"
            cursor.execute(sql_query)
            data = cursor.fetchall()
        return convert_decimals(data)
    except Exception as e:
        print(f"❌ ПОМИЛКА SQL-ЗАПИТУ (Gen Mix): {e}")
        return {"error": f"Помилка запиту: {e}"}
    finally:
        if conn: conn.close()

@app.get("/api/v2/correlation/load-temp")
def get_load_temp_correlation():
    print("Запит: /api/v2/correlation/load-temp")
    conn = get_db_connection()
    if not conn: return {"error": "DB Connection failed"}
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            sql_query = """
                WITH time_window AS (SELECT (MAX(timestamp) - INTERVAL '7 days') AS start_time, (MAX(timestamp)) AS end_time FROM LoadMeasurements),
                HourlyLoad AS (SELECT date_trunc('hour', timestamp) AS hour, AVG(actual_load_mw) AS avg_load FROM LoadMeasurements, time_window WHERE timestamp BETWEEN time_window.start_time AND time_window.end_time GROUP BY hour),
                HourlyWeather AS (SELECT date_trunc('hour', timestamp) AS hour, AVG(temperature) AS avg_temp FROM WeatherReports, time_window WHERE timestamp BETWEEN time_window.start_time AND time_window.end_time GROUP BY hour)
                SELECT hl.hour, hl.avg_load, hw.avg_temp FROM HourlyLoad hl JOIN HourlyWeather hw ON hl.hour = hw.hour ORDER BY hl.hour;
            """
            cursor.execute(sql_query)
            data = cursor.fetchall()
        return convert_decimals(data)
    except Exception as e:
        print(f"❌ ПОМИЛКА SQL-ЗАПИТУ (Correlation): {e}")
        return {"error": f"Помилка запиту: {e}"}
    finally:
        if conn: conn.close()


print("Сервер API (FastAPI) v11.0 (Operational) готовий до запуску.")
print("Використовуйте команду в терміналі:")
print("python -m uvicorn 04_backend_api_v11:app --reload")