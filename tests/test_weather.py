import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch, MagicMock

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from weather import app
from database import Base, get_db

# ✅ Use a separate test database — never touch the real one
TEST_DATABASE_URL = "sqlite:///./test_weather.db"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ✅ Override the real db with the test db
def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db


# ✅ Create and drop tables around each test
@pytest.fixture(autouse=True)
def setup_database():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


client = TestClient(app)
API_KEY = os.getenv("API_SECRET_KEY", "test-secret-key")
HEADERS = {"X-API-Key": API_KEY}


# ── Mock weather data ──────────────────────────────────────────────

MOCK_WEATHER_RESPONSE = {
    "name": "Bengaluru",
    "main": {
        "temp": 28.4,
        "feels_like": 30.1,
        "humidity": 65,
        "pressure": 1012
    },
    "weather": [{"description": "partly cloudy"}],
    "wind": {"speed": 3.5},
    "visibility": 6000,
    "sys": {
        "country": "IN",
        "sunrise": 1713056400,
        "sunset": 1713100800
    }
}

MOCK_FORECAST_RESPONSE = {
    "city": {"name": "Bengaluru", "country": "IN"},
    "list": [
        {
            "dt_txt": "2024-04-14 12:00:00",
            "main": {
                "temp": 28.4,
                "feels_like": 30.1,
                "humidity": 65
            },
            "weather": [{"description": "partly cloudy"}],
            "wind": {"speed": 3.5}
        },
        {
            "dt_txt": "2024-04-14 15:00:00",
            "main": {
                "temp": 30.1,
                "feels_like": 32.0,
                "humidity": 60
            },
            "weather": [{"description": "sunny"}],
            "wind": {"speed": 4.0}
        },
        {
            "dt_txt": "2024-04-15 12:00:00",
            "main": {
                "temp": 27.0,
                "feels_like": 29.0,
                "humidity": 70
            },
            "weather": [{"description": "cloudy"}],
            "wind": {"speed": 2.5}
        }
    ]
}


# ── Root ───────────────────────────────────────────────────────────

def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Weather API is running"}


# ── Auth ───────────────────────────────────────────────────────────

def test_weather_no_api_key():
    response = client.get("/weather?city=Bengaluru")
    assert response.status_code == 401

def test_weather_wrong_api_key():
    response = client.get("/weather?city=Bengaluru", headers={"X-API-Key": "wrong-key"})
    assert response.status_code == 401

def test_forecast_no_api_key():
    response = client.get("/forecast?city=Bengaluru")
    assert response.status_code == 401


# ── Weather ────────────────────────────────────────────────────────

@patch("weather.requests.get")
def test_weather_success(mock_get):
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: MOCK_WEATHER_RESPONSE
    )

    response = client.get("/weather?city=Bengaluru", headers=HEADERS)

    assert response.status_code == 200
    data = response.json()
    assert data["city"] == "Bengaluru"
    assert "temperature" in data
    assert "humidity" in data
    assert "wind_speed" in data
    assert "sunrise" in data
    assert "sunset" in data


@patch("weather.requests.get")
def test_weather_metric_units(mock_get):
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: MOCK_WEATHER_RESPONSE
    )

    response = client.get("/weather?city=Bengaluru&units=metric", headers=HEADERS)
    data = response.json()

    assert "°C" in data["temperature"]
    assert "m/s" in data["wind_speed"]


@patch("weather.requests.get")
def test_weather_imperial_units(mock_get):
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: MOCK_WEATHER_RESPONSE
    )

    response = client.get("/weather?city=Bengaluru&units=imperial", headers=HEADERS)
    data = response.json()

    assert "°F" in data["temperature"]
    assert "mph" in data["wind_speed"]


@patch("weather.requests.get")
def test_weather_city_not_found(mock_get):
    mock_get.return_value = MagicMock(
        status_code=404,
        json=lambda: {"message": "city not found"}
    )

    response = client.get("/weather?city=FakeCity123", headers=HEADERS)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@patch("weather.requests.get")
def test_weather_missing_city_param(mock_get):
    response = client.get("/weather", headers=HEADERS)
    assert response.status_code == 422   # FastAPI validation error


# ── Forecast ───────────────────────────────────────────────────────

@patch("weather.requests.get")
def test_forecast_success(mock_get):
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: MOCK_FORECAST_RESPONSE
    )

    response = client.get("/forecast?city=Bengaluru", headers=HEADERS)

    assert response.status_code == 200
    data = response.json()
    assert data["city"] == "Bengaluru"
    assert data["country"] == "IN"
    assert len(data["forecast"]) > 0


@patch("weather.requests.get")
def test_forecast_has_summary(mock_get):
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: MOCK_FORECAST_RESPONSE
    )

    response = client.get("/forecast?city=Bengaluru", headers=HEADERS)
    data = response.json()

    first_day = data["forecast"][0]
    assert "summary" in first_day
    assert "min_temp" in first_day["summary"]
    assert "max_temp" in first_day["summary"]
    assert "description" in first_day["summary"]


@patch("weather.requests.get")
def test_forecast_city_not_found(mock_get):
    mock_get.return_value = MagicMock(
        status_code=404,
        json=lambda: {"message": "city not found"}
    )

    response = client.get("/forecast?city=FakeCity123", headers=HEADERS)
    assert response.status_code == 404


# ── History ────────────────────────────────────────────────────────

@patch("weather.requests.get")
def test_history_is_saved(mock_get):
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: MOCK_WEATHER_RESPONSE
    )

    # Make a weather request
    client.get("/weather?city=Bengaluru", headers=HEADERS)

    # Check it was saved
    response = client.get("/history", headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["city"] == "Bengaluru"
    assert data[0]["endpoint"] == "weather"


@patch("weather.requests.get")
def test_history_by_city(mock_get):
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: MOCK_WEATHER_RESPONSE
    )

    client.get("/weather?city=Bengaluru", headers=HEADERS)
    client.get("/weather?city=Bengaluru", headers=HEADERS)

    response = client.get("/history/Bengaluru", headers=HEADERS)
    data = response.json()

    assert len(data) == 2
    assert all(d["city"] == "Bengaluru" for d in data)


@patch("weather.requests.get")
def test_history_limit(mock_get):
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: MOCK_WEATHER_RESPONSE
    )

    # Make 5 requests
    for _ in range(5):
        client.get("/weather?city=Bengaluru", headers=HEADERS)

    # Only get 3
    response = client.get("/history?limit=3", headers=HEADERS)
    assert len(response.json()) == 3


def test_history_no_api_key():
    response = client.get("/history")
    assert response.status_code == 401