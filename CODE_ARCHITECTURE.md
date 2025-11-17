# 🏗️ Архітектура Коду та Технічна Реалізація

Цей документ містить детальний технічний опис системи моніторингу енергосистеми (v11.0). Тут розкрито внутрішню логіку компонентів, обґрунтування вибору технологій та опис алгоритмів, використаних у проекті.

## 📂 1. Структура Проекту (File Tree)

Система побудована за модульним принципом, де кожен файл відповідає за конкретний шар архітектури:

* **`01_create_schema_v3.sql`** — **(Database DDL)** Скрипт створення структури бази даних (таблиці, зв'язки, індекси). Це "скелет" системи.
* **`02_insert_static_data_v2.sql`** — **(Database DML)** Скрипт наповнення "довідників" (статична топологія: міста, координати підстанцій, характеристики ліній).
* **`03_generate_dynamic_data.py`** — **(Simulation / ETL)** Python-скрипт, що виступає в ролі емулятора IoT-системи. Генерує часові ряди та події.
* **`04_backend_api_v11.py`** — **(Backend / Business Logic)** API-сервер на базі FastAPI. Обробляє запити від клієнта, виконує аналітику та керує станом системи.
* **`index_v11.html`** — **(Frontend / Presentation)** Клієнтський SPA (Single Page Application) дашборд для візуалізації даних.
* **`requirements.txt`** — Список залежностей (бібліотек) для розгортання середовища Python.

## 💾 2. Рівень Даних (Database Layer)

База даних спроектована за схемою, наближеною до **«Зірка» (Star Schema)**. Це дозволяє ефективно виконувати аналітичні запити (OLAP) та швидко писати транзакції (OLTP).

### ER-Діаграма (Entity-Relationship)

```mermaid
erDiagram
    %% --- ДОВІДНИКИ (Dimensions) ---
    Regions {
        int region_id PK
        string region_name
    }
    Substations {
        int substation_id PK
        string substation_name
        decimal capacity_mw
        float latitude
        float longitude
        int region_id FK
    }
    PowerLines {
        int line_id PK
        string line_name
        decimal max_load_mw
        int from_substation_id FK
        int to_substation_id FK
    }
    Consumers {
        int consumer_id PK
        string consumer_name
        string consumer_type
        int substation_id FK
    }
    Generators {
        int generator_id PK
        string generator_type
        decimal max_output_mw
        int substation_id FK
    }

    %% --- ФАКТИ (Facts / Measurements) ---
    LoadMeasurements {
        bigint measurement_id PK
        timestamp timestamp
        decimal actual_load_mw
        int substation_id FK
    }
    GenerationMeasurements {
        bigint gen_measurement_id PK
        timestamp timestamp
        decimal actual_generation_mw
        int generator_id FK
    }
    LineMeasurements {
        bigint line_measurement_id PK
        timestamp timestamp
        decimal actual_load_mw
        int line_id FK
    }

    %% --- ПОДІЇ та ФАКТОРИ (Events & Analytics) ---
    Alerts {
        int alert_id PK
        timestamp timestamp
        string alert_type
        string description
        string status "NEW|RESOLVED"
        int substation_id FK
    }
    MaintenanceEvents {
        int event_id PK
        timestamp start_time
        timestamp end_time
        string object_type
        string reason
        int object_id FK
    }
    WeatherReports {
        timestamp timestamp PK
        int region_id PK
        decimal temperature
        string conditions
    }
    EnergyPricing {
        timestamp timestamp PK
        int region_id PK
        decimal price_per_mwh
    }

    %% --- ЗВ'ЯЗКИ (Relationships) ---
    Regions ||--|{ Substations : "містить"
    Regions ||--|{ WeatherReports : "має погоду"
    Regions ||--|{ EnergyPricing : "має тарифи"

    Substations ||--o{ PowerLines : "початок (from)"
    Substations ||--o{ PowerLines : "кінець (to)"
    Substations ||--o{ Generators : "має джерела"
    Substations ||--o{ Consumers : "живить"
    
    Substations ||--o{ LoadMeasurements : "моніторинг"
    Substations ||--o{ Alerts : "інциденти"
    
    Generators ||--o{ GenerationMeasurements : "виробіток"
    PowerLines ||--o{ LineMeasurements : "навантаження лінії"
    
    %% Логічні зв'язки для ремонтів (показані пунктиром, бо це поліморфний зв'язок)
    Substations |o..o{ MaintenanceEvents : "ремонт"
    PowerLines |o..o{ MaintenanceEvents : "ремонт"
