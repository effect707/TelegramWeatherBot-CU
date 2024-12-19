import logging
import os
import asyncio
from typing import List
import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv('TELEGRAM_API_TOKEN')
ACCUWEATHER_API_KEY = os.getenv('ACCUWEATHER_API_TOKEN')

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

class WeatherFlow(StatesGroup):
    input_start = State()
    input_end = State()
    input_midpoints = State()
    choose_forecast = State()

async def fetch_location_key(city: str) -> str:
    url = "http://dataservice.accuweather.com/locations/v1/cities/search"
    params = {"apikey": ACCUWEATHER_API_KEY, "q": city, "language": "ru"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            if response.status != 200:
                logging.error(f"Не удалось получить ключ локации для {city}: {response.status}")
                return None
            data = await response.json()
            return data[0]["Key"] if data else None

async def fetch_weather_forecast(location_key: str) -> list:
    url = f"http://dataservice.accuweather.com/forecasts/v1/daily/5day/{location_key}"
    params = {"apikey": ACCUWEATHER_API_KEY, "metric": "true", "language": "ru"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            if response.status != 200:
                logging.error(f"Не удалось получить прогноз для {location_key}: {response.status}")
                return []
            data = await response.json()
            return data.get("DailyForecasts", [])

async def generate_forecast(cities: List[str], days: int):
    forecasts = []
    for city in cities:
        loc_key = await fetch_location_key(city)
        if not loc_key:
            forecasts.append({"location": city, "forecast": "Нет данных"})
            continue

        forecast_data = await fetch_weather_forecast(loc_key)
        forecast_data = forecast_data[:days]

        city_forecast = [
            {
                "date": entry["Date"].split("T")[0],
                "temperature": f"{entry['Temperature']['Minimum']['Value']} - {entry['Temperature']['Maximum']['Value']} °C",
                "conditions": entry["Day"]["IconPhrase"]
            }
            for entry in forecast_data
        ]
        forecasts.append({"location": city, "forecast": city_forecast})
    return forecasts

def format_forecast(forecast_data):
    result = ""
    for city_data in forecast_data:
        result += f"Прогноз погоды для {city_data['location']}:\n"
        if city_data['forecast'] == "Нет данных":
            result += " Данные недоступны для этого города🛑.\n\n"
        else:
            for day in city_data['forecast']:
                result += f"{day['date']}: {day['temperature']}, {day['conditions']}\n"
        result += "\n"
    return result

@dp.message(Command("start"))
async def start_command(message: Message):
    await message.answer("Привет👋! Я могу предоставить прогноз погоды для вашего маршрута. Используйте /weather, чтобы узнать погоду.")

@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer("Команды:\n/start - Начать работу с ботом🎬\n/help - Показать справкуℹ️\n/weather - Получить прогноз погоды🍺")

@dp.message(Command("weather"))
async def weather_command(message: Message, state: FSMContext):
    await message.answer("Введите начальный город:")
    await state.set_state(WeatherFlow.input_start)

@dp.message(WeatherFlow.input_start)
async def handle_start_city(message: Message, state: FSMContext):
    await state.update_data(start_city=message.text)
    await message.answer("Введите конечный город:")
    await state.set_state(WeatherFlow.input_end)

@dp.message(WeatherFlow.input_end)
async def handle_end_city(message: Message, state: FSMContext):
    await state.update_data(end_city=message.text)
    builder = InlineKeyboardBuilder()
    builder.button(text="Добавить промежуточные точки", callback_data="add_midpoints")
    builder.button(text="Пропустить", callback_data="skip_midpoints")
    await message.answer("Хотите добавить промежуточные города?➕", reply_markup=builder.as_markup())
    await state.set_state(WeatherFlow.input_midpoints)

@dp.callback_query(WeatherFlow.input_midpoints, lambda call: call.data == "add_midpoints")
async def add_midpoints(call: CallbackQuery):
    await call.message.answer("Введите промежуточные города через запятую:")
    await call.answer()

@dp.callback_query(WeatherFlow.input_midpoints, lambda call: call.data == "skip_midpoints")
async def skip_midpoints(call: CallbackQuery, state: FSMContext):
    await state.update_data(midpoints=[])
    await call.message.answer("Маршрут будет построен без промежуточных точек.")
    await call.answer()
    await request_forecast_days(call.message, state)

@dp.message(WeatherFlow.input_midpoints)
async def handle_midpoints(message: Message, state: FSMContext):
    midpoints = [city.strip() for city in message.text.split(",") if city.strip()]
    await state.update_data(midpoints=midpoints)
    await request_forecast_days(message, state)

async def request_forecast_days(msg: Message, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.button(text="3 дня", callback_data="3_days")
    builder.button(text="5 дней", callback_data="5_days")
    await msg.answer("Выберите длительность прогноза:", reply_markup=builder.as_markup())
    await state.set_state(WeatherFlow.choose_forecast)

@dp.callback_query(WeatherFlow.choose_forecast, lambda call: call.data in {"3_days", "5_days"})
async def forecast_days_selected(call: CallbackQuery, state: FSMContext):
    days = 3 if call.data == "3_days" else 5
    await state.update_data(days=days)

    user_data = await state.get_data()
    cities = [user_data["start_city"]] + user_data.get("midpoints", []) + [user_data["end_city"]]

    try:
        forecasts = await generate_forecast(cities, days)
        await call.message.answer(format_forecast(forecasts))
    except Exception:
        logging.exception("Ошибка при обработке прогноза")
        await call.message.answer("Произошла ошибка. Пожалуйста, попробуйте позже.")

    await state.clear()

if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))

