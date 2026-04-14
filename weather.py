import json
import requests
from fastapi import FastAPI, HTTPException, Security, Depends
from fastapi.security import APIKeyHeader, APIKeyQuery
from dotenv import load_dotenv
from pydantic import BaseModel
from sqlalchemy.orm import Session
import os
from datetime import datetime
from database import engine, get_db, Base
from models import SearchHistory

load_dotenv()

app = FastAPI()

Base.metadata.create_all(bind=engine)

API_KEY = os.getenv("OPENWEATHER_API_KEY")
if not API_KEY:
    raise ValueError("OPENWEATHER_API_KEY is not set")

API_SECRET_KEY = os.getenv("API_SECRET_KEY")
if not API_SECRET_KEY:
    raise ValueError("API_SECRET_KEY is not set")

#Auth Setup
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=True)

def verify_api_key(api_key: str = Security(API_KEY_HEADER)):
    if api_key != API_SECRET_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return api_key

# ✅ Pydantic Models
class WeatherResponse(BaseModel):
    city:        str
    temperature: str
    description: str
    humidity:    str
    wind_speed:  str
    pressure:    str
    visibility:  str
    sunrise:     str
    sunset:      str


class ForecastEntry(BaseModel):
    time:        str
    temp:        str
    feels_like:  str
    humidity:    str
    description: str
    wind_speed:  str


class DaySummary(BaseModel):
    min_temp:    str
    max_temp:    str
    description: str


class DayForecast(BaseModel):
    date:    str
    summary: DaySummary
    entries: list[ForecastEntry]


class ForecastResponse(BaseModel):
    city:     str
    country:  str
    forecast: list[DayForecast]

class SearchHistoryResponse(BaseModel):
    id: int
    city: str
    units: str
    endpoint: str
    created_at: datetime

    class Config:
        from_attributes = True


# ✅ Weather function (unchanged)
def get_weather(city: str, units: str = "metric") -> WeatherResponse:
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "q": city,
        "appid": API_KEY,
        "units": units
    }
    response = requests.get(url, params=params)

    if response.status_code == 401:
        raise HTTPException(status_code=401, detail="Invalid API key")
    elif response.status_code == 404:
        raise HTTPException(status_code=404, detail="City not found")
    elif response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=f"Error fetching weather: {response.status_code}")

    data = response.json()

    temp_unit     = "°C" if units == "metric" else "°F" if units == "imperial" else "K"
    speed_unit    = "m/s" if units == "metric" else "mph"
    pressure_unit = "hPa"
    vis_unit      = "m" if units == "metric" else "mi"

    def to_hhmm(utc_ts):
        return datetime.utcfromtimestamp(utc_ts).strftime('%H:%M')

    return WeatherResponse(
        city        = data["name"],
        temperature = f"{data['main']['temp']}{temp_unit}",
        description = data["weather"][0]["description"],
        humidity    = f"{data['main']['humidity']}%",
        wind_speed  = f"{data['wind']['speed']} {speed_unit}",
        pressure    = f"{data['main']['pressure']} {pressure_unit}",
        visibility  = f"{data.get('visibility', 'N/A')} {vis_unit}",
        sunrise     = to_hhmm(data["sys"]["sunrise"]),
        sunset      = to_hhmm(data["sys"]["sunset"])
    )


# ✅ Forecast helper
def summarise_day(entries: list[ForecastEntry], temp_unit: str) -> DaySummary:
    temps = [float(e.temp.replace(temp_unit, "")) for e in entries]
    descriptions = [e.description for e in entries]
    most_common_desc = max(set(descriptions), key=descriptions.count)

    return DaySummary(
        min_temp    = f"{min(temps)}{temp_unit}",
        max_temp    = f"{max(temps)}{temp_unit}",
        description = most_common_desc
    )


# ✅ Forecast function
def get_forecast(city: str, units: str = "metric") -> ForecastResponse:
    url = "https://api.openweathermap.org/data/2.5/forecast"
    params = {
        "q": city,
        "appid": API_KEY,
        "units": units
    }
    response = requests.get(url, params=params)

    if response.status_code == 401:
        raise HTTPException(status_code=401, detail="Invalid API key")
    elif response.status_code == 404:
        raise HTTPException(status_code=404, detail="City not found")
    elif response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=f"Error fetching forecast: {response.status_code}")

    data = response.json()

    temp_unit  = "°C" if units == "metric" else "°F" if units == "imperial" else "K"
    speed_unit = "m/s" if units == "metric" else "mph"

    forecast_by_day: dict[str, list[ForecastEntry]] = {}
    for entry in data["list"]:
        date = entry["dt_txt"].split(" ")[0]

        if date not in forecast_by_day:
            forecast_by_day[date] = []

        forecast_by_day[date].append(ForecastEntry(
            time        = entry["dt_txt"].split(" ")[1][:5],
            temp        = f"{entry['main']['temp']}{temp_unit}",
            feels_like  = f"{entry['main']['feels_like']}{temp_unit}",
            humidity    = f"{entry['main']['humidity']}%",
            description = entry["weather"][0]["description"],
            wind_speed  = f"{entry['wind']['speed']} {speed_unit}"
        ))

    forecast = [
        DayForecast(
            date    = date,
            summary = summarise_day(entries, temp_unit),
            entries = entries
        )
        for date, entries in forecast_by_day.items()
    ]

    return ForecastResponse(
        city     = data["city"]["name"],
        country  = data["city"]["country"],
        forecast = forecast
    )


# Root Endpoint
@app.get("/")
def root():
    return {"message": "Weather API is running"}


# Weather Endpoint
@app.get("/weather", response_model=WeatherResponse)
def weather(
    city: str, 
    units: str = "metric", 
    api_key: str = Security(verify_api_key),
    db: Session = Depends(get_db)
):
    result = get_weather(city, units)

    db.add(SearchHistory(
        city= city,
        units= units,
        endpoint= "weather",
        result= json.dumps(result.model_dump())
    ))
    db.commit()

    return result


# Forecast Endpoint
@app.get("/forecast", response_model=ForecastResponse)
def forecast(
    city: str, 
    units: str = "metric", 
    api_key: str = Security(verify_api_key),
    db: Session = Depends(get_db)
):
    result = get_forecast(city, units)

    db.add(SearchHistory(
        city= city,
        units= units,
        endpoint= "forecast",
        result= json.dumps(result.model_dump())
    ))
    db.commit()

    return result

@app.get("/history",response_model = list[SearchHistoryResponse])
def history(
    limit: int = 10,
    api_key: str = Security(verify_api_key),
    db: Session = Depends(get_db)
):
    return db.query(SearchHistory)\
        .order_by(SearchHistory.created_at.desc())\
        .limit(limit)\
        .all()

@app.get("/history/{city}", response_model = list[SearchHistoryResponse])
def history_by_city(
    city: str,
    limit: int = 10,
    api_key: str = Security(verify_api_key),
    db: Session = Depends(get_db)
):
    return db.query(SearchHistory)\
        .filter(SearchHistory.city.ilike(f"%{city}%"))\
        .order_by(SearchHistory.created_at.desc())\
        .limit(limit)\
        .all()
        