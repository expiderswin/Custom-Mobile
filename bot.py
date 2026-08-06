import logging
import sqlite3
import re
import random
import requests
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

# Настройки
TELEGRAM_TOKEN = "8912839996:AAGO4qR0gNIEpLgLMlhDeD5EsqINAvU7FvE"
STEAM_API_KEY = "EB93B90EE4E48B486251A750035A6223"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- БАЗА ДАННЫХ (SQLite) ---
conn = sqlite3.connect("bot_database.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    steam_id TEXT
)
""")
conn.commit()


def get_user_steam(telegram_id):
  cursor.execute(
      "SELECT steam_id FROM users WHERE telegram_id = ?", (telegram_id,)
  )
  row = cursor.fetchone()
  return row[0] if row else None


def save_user_steam(telegram_id, steam_id):
  cursor.execute(
      "INSERT OR REPLACE INTO users (telegram_id, steam_id) VALUES (?, ?)",
      (telegram_id, steam_id),
  )
  conn.commit()


# --- КЛАВИАТУРЫ ---
def get_keyboard(telegram_id):
  steam_id = get_user_steam(telegram_id)
  if not steam_id:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Привязать Steam аккаунт")],
            [KeyboardButton(text="Как узнать ссылку?")],
        ],
        resize_keyboard=True,
    )
  else:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Вся библиотека игр")],
            [
                KeyboardButton(text="Во что поиграть?"),
                KeyboardButton(text="Топ задротских игр"),
            ],
            [
                KeyboardButton(text="Баланс и оценка покупок"),
                KeyboardButton(text="Профиль и статус"),
            ],
        ],
        resize_keyboard=True,
    )


class Form(StatesGroup):
  waiting_for_steam = State()


def resolve_steam_id(user_input: str) -> str:
  user_input = user_input.strip()
  if re.match(r"^\d{17}$", user_input):
    return user_input
  if "steamcommunity.com" in user_input:
    match_profile = re.search(r"/profiles/(\d{17})", user_input)
    if match_profile:
      return match_profile.group(1)
    match_id = re.search(r"/id/([^/]+)", user_input)
    if match_id:
      vanity_name = match_id.group(1)
      url = f"https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/?key={STEAM_API_KEY}&vanityurl={vanity_name}"
      res = requests.get(url).json()
      if res.get("response", {}).get("success") == 1:
        return res["response"].get("steamid")
  return None


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
  user_steam = get_user_steam(message.from_user.id)
  if user_steam:
    text = (
        "С возвращением. Цифровой след твоего пути в мирах Steam уже соединен с"
        " этим пространством. Выбери направление."
    )
  else:
    text = (
        "Приветствую. Время бесконечно, но твой профиль Steam еще не привязан."
        " Укажи свою ссылку, чтобы начать летопись."
    )
  await message.answer(text, reply_markup=get_keyboard(message.from_user.id))


@dp.message(F.text == "Привязать Steam аккаунт")
async def ask_steam_input(message: types.Message, state: FSMContext):
  await state.set_state(Form.waiting_for_steam)
  await message.answer(
      "Отправь ссылку на свой профиль Steam (например:"
      " `https://steamcommunity.com/profiles/76561198...`).",
      parse_mode="Markdown",
  )


@dp.message(F.text == "Как узнать ссылку?")
async def show_tutorial(message: types.Message):
  await message.answer(
      "Инструкция: открой свой профиль Steam в приложении или браузере, скопируй"
      " адрес страницы и отправь его сюда.",
      reply_markup=get_keyboard(message.from_user.id),
  )


@dp.message(Form.waiting_for_steam)
async def process_steam_profile(message: types.Message, state: FSMContext):
  await state.clear()
  steam_id = resolve_steam_id(message.text)
  if not steam_id:
    await message.answer(
        "Не удалось распознать профиль. Проверь корректность ссылки.",
        reply_markup=get_keyboard(message.from_user.id),
    )
    return

  save_user_steam(message.from_user.id, steam_id)
  await message.answer(
      "Связь установлена. Цифровое отражение твоего аккаунта зафиксировано в"
      " памяти системы.",
      reply_markup=get_keyboard(message.from_user.id),
  )


# --- 1. ВСЯ БИБЛИОТЕКА ИГР ---
@dp.message(F.text == "Вся библиотека игр")
async def show_user_games(message: types.Message):
  steam_id = get_user_steam(message.from_user.id)
  if not steam_id:
    return

  games_url = f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/?key={STEAM_API_KEY}&steamid={steam_id}&include_appinfo=true&include_played_free_games=true"
  try:
    res = requests.get(games_url).json().get("response", {})
    games = res.get("games", [])
    total_games = res.get("game_count", len(games))

    if not games:
      await message.answer(
          "Список игр скрыт настройками приватности твоего профиля Steam."
      )
      return

    games_sorted = sorted(
        games, key=lambda x: x.get("playtime_forever", 0), reverse=True
    )

    chunks = []
    current_chunk = (
        f"Полная летопись твоих миров. Всего собрано элементов:"
        f" {total_games}\n\n"
    )

    for i, g in enumerate(games_sorted, 1):
      g_name = g.get("name")
      hours = round(g.get("playtime_forever", 0) / 60, 1)
      line = f"{i}. Название: {g_name} | Потрачено времени: {hours} ч.\n"

      if len(current_chunk) + len(line) > 3800:
        chunks.append(current_chunk)
        current_chunk = line
      else:
        current_chunk += line

    if current_chunk:
      chunks.append(current_chunk)

    for chunk in chunks:
      await message.answer(chunk)

    remaining = max(0, total_games - len(games_sorted))
    await message.answer(
        f"Отображено записей: {len(games_sorted)} | Скрыто или ожидает часа:"
        f" {remaining}",
        reply_markup=get_keyboard(message.from_user.id),
    )
  except Exception as e:
    logging.error(e)
    await message.answer("Не удалось извлечь библиотеку из архивов Steam.")


# --- 2. РАНДОМАЙЗЕР: ВО ЧТО ПОИГРАТЬ? ---
@dp.message(F.text == "Во что поиграть?")
async def random_game_choice(message: types.Message):
  steam_id = get_user_steam(message.from_user.id)
  if not steam_id:
    return

  games_url = f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/?key={STEAM_API_KEY}&steamid={steam_id}&include_appinfo=true&include_played_free_games=true"
  try:
    games = requests.get(games_url).json().get("response", {}).get("games", [])
    if not games:
      await message.answer("Твоя библиотека пуста или скрыта завесой тайны.")
      return

    chosen = random.choice(games)
    g_name = chosen.get("name")
    hours = round(chosen.get("playtime_forever", 0) / 60, 1)
    app_id = chosen.get("appid")
    store_link = f"https://store.steampowered.com/app/{app_id}"

    msg = (
        "Случай выбрал твою новую реальность на этот вечер:\n\n"
        f"Игра: {g_name}\n"
        f"Прожито в ней ранее: {hours} ч.\n\n"
        f"Портал в магазин: {store_link}"
    )
    await message.answer(
        msg,
        reply_markup=get_keyboard(message.from_user.id),
    )
  except Exception as e:
    logging.error(e)
    await message.answer("Судьба молчит. Не удалось сделать выбор.")


# --- 3. ТОП ЗАДРОТСКИХ ИГР ---
@dp.message(F.text == "Топ задротских игр")
async def top_played_games(message: types.Message):
  steam_id = get_user_steam(message.from_user.id)
  if not steam_id:
    return

  games_url = f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/?key={STEAM_API_KEY}&steamid={steam_id}&include_appinfo=true&include_played_free_games=true"
  try:
    games = requests.get(games_url).json().get("response", {}).get("games", [])
    if not games:
      await message.answer("Информация скрыта.")
      return

    games_sorted = sorted(
        games, key=lambda x: x.get("playtime_forever", 0), reverse=True
    )
    top_5 = games_sorted[:5]

    text = "Пять вершин, которым ты отдал больше всего земного времени:\n\n"
    for i, g in enumerate(top_5, 1):
      g_name = g.get("name")
      hours = round(g.get("playtime_forever", 0) / 60, 1)
      text += f"{i}. Игра: {g_name} — Потрачено часов: {hours}\n"

    await message.answer(
        text,
        reply_markup=get_keyboard(message.from_user.id),
    )
  except Exception as e:
    logging.error(e)
    await message.answer("Не удалось проанализировать хроники времени.")


# --- 4. ПРОФИЛЬ И СТАТУС ---
@dp.message(F.text == "Профиль и статус")
async def show_profile_status(message: types.Message):
  steam_id = get_user_steam(message.from_user.id)
  if not steam_id:
    return

  profile_url = f"https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/?key={STEAM_API_KEY}&steamids={steam_id}"
  try:
    player = (
        requests.get(profile_url).json().get("response", {}).get("players", [])[0]
    )
    name = player.get("personaname")
    state_code = player.get("personastate", 0)
    states = {
        0: "Оффлайн (вне сеанса)",
        1: "В сети (активен)",
        2: "Занят",
        3: "Отошел",
        4: "Спит",
        5: "Ищет сделку",
        6: "Ищет игру",
    }
    status_text = states.get(state_code, "Неизвестное состояние")
    profile_link = player.get("profileurl")

    msg = (
        f"Отражение твоего цифрового «Я»:\n\n"
        f"Имя: {name}\n"
        f"Текущий статус: {status_text}\n"
        f"Ссылка на первоисточник: {profile_link}"
    )
    await message.answer(
        msg,
        reply_markup=get_keyboard(message.from_user.id),
    )
  except Exception as e:
    logging.error(e)
    await message.answer("Образ профиля затуманен. Нет данных.")


# --- 5. БАЛАНС И ОЦЕНКА ---
@dp.message(F.text == "Баланс и оценка покупок")
async def show_account_value(message: types.Message):
  steam_id = get_user_steam(message.from_user.id)
  if not steam_id:
    return

  games_url = f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/?key={STEAM_API_KEY}&steamid={steam_id}&include_appinfo=true&include_played_free_games=true"
  try:
    games = requests.get(games_url).json().get("response", {}).get("games", [])
    paid_games = [g for g in games if g.get("playtime_forever", 0) > 0]
    rough_estimate = len(paid_games) * 450

    msg = (
        "Материальное измерение твоей коллекции:\n\n"
        "Кошелек скрыт от внешнего мира законами протокола Valve.\n\n"
        f"Всего миров на счету: {len(games)}\n"
        f"Оценочная стоимость активных миров: ~{rough_estimate:,} условных единиц"
        " ценности"
    )
    await message.answer(
        msg,
        reply_markup=get_keyboard(message.from_user.id),
    )
  except Exception as e:
    logging.error(e)
    await message.answer("Невозможно исчислить эквивалент ценности.")


if __name__ == "__main__":
  import asyncio

  asyncio.run(dp.start_polling(bot))
