import logging
import sqlite3
import re
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
            [KeyboardButton(text="➕ Добавить Steam аккаунт")],
            [KeyboardButton(text="📖 Как узнать ссылку?")],
        ],
        resize_keyboard=True,
    )
  else:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🕹 Мои игры и часы")],
            [
                KeyboardButton(text="💰 Баланс и оценка покупок"),
                KeyboardButton(text="🌍 Регион аккаунта"),
            ],
        ],
        resize_keyboard=True,
    )


class Form(StatesGroup):
  waiting_for_steam = State()


# Конвертация ссылки Steam в SteamID64
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

  url = f"https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/?key={STEAM_API_KEY}&vanityurl={user_input}"
  res = requests.get(url).json()
  if res.get("response", {}).get("success") == 1:
    return res["response"].get("steamid")

  return None


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
  kb = get_keyboard(message.from_user.id)
  steam_id = get_user_steam(message.from_user.id)

  if steam_id:
    text = (
        "С возвращением! 👋 Ваш Steam аккаунт уже привязан.\nИспользуйте кнопки"
        " ниже для просмотра статистики:"
    )
  else:
    text = (
        "Привет! 👋 Этот бот покажет всю статистику твоего Steam.\nНажми кнопку"
        " ниже, чтобы привязать свой аккаунт:"
    )
  await message.answer(text, reply_markup=kb)


@dp.message(F.text == "➕ Добавить Steam аккаунт")
async def ask_steam_input(message: types.Message, state: FSMContext):
  if get_user_steam(message.from_user.id):
    await message.answer(
        "❌ Вы уже привязали аккаунт. Повторная привязка не требуется.",
        reply_markup=get_keyboard(message.from_user.id),
    )
    return

  await state.set_state(Form.waiting_for_steam)
  await message.answer(
      "🔗 Отправь ссылку на свой профиль Steam (например:"
      " `https://steamcommunity.com/profiles/76561198...` или свою ссылку с"
      " `/id/...`).",
      parse_mode="Markdown",
  )


@dp.message(F.text == "📖 Как узнать ссылку?")
async def show_tutorial(message: types.Message):
  tutorial_text = (
      "📖 **Инструкция:**\n\n"
      "• Откройте профиль Steam в приложении или браузере.\n"
      "• Скопируйте ссылку на профиль (вида `https://steamcommunity.com/profiles/...`)\n"
      "• Нажмите **«➕ Добавить Steam аккаунт»** и отправьте ссылку боту."
  )
  await message.answer(
      tutorial_text,
      parse_mode="Markdown",
      reply_markup=get_keyboard(message.from_user.id),
  )


@dp.message(Form.waiting_for_steam)
async def process_steam_profile(message: types.Message, state: FSMContext):
  await state.clear()
  raw_input = message.text
  steam_id = resolve_steam_id(raw_input)

  if not steam_id:
    await message.answer(
        "❌ Не удалось найти профиль. Проверьте правильность ссылки.",
        reply_markup=get_keyboard(message.from_user.id),
    )
    return

  save_user_steam(message.from_user.id, steam_id)

  profile_url = f"https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/?key={STEAM_API_KEY}&steamids={steam_id}"
  try:
    p_data = requests.get(profile_url).json().get("response", {}).get("players")
    if not p_data:
      await message.answer(
          "❌ Профиль скрыт или не найден.",
          reply_markup=get_keyboard(message.from_user.id),
      )
      return

    player = p_data[0]
    name = player.get("personaname")

    await message.answer(
        f"✅ **Аккаунт {name} успешно привязан!**\nКнопка добавления скрыта,"
        " теперь вам доступны все функции ниже.",
        parse_mode="Markdown",
        reply_markup=get_keyboard(message.from_user.id),
    )
  except Exception as e:
    logging.error(e)
    await message.answer(
        "❌ Ошибка при привязке аккаунта.",
        reply_markup=get_keyboard(message.from_user.id),
    )


@dp.message(F.text == "🕹 Мои игры и часы")
async def show_user_games(message: types.Message):
  steam_id = get_user_steam(message.from_user.id)
  if not steam_id:
    await message.answer(
        "Сначала привяжите аккаунт!",
        reply_markup=get_keyboard(message.from_user.id),
    )
    return

  games_url = f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/?key={STEAM_API_KEY}&steamid={steam_id}&include_appinfo=true"
  try:
    res = requests.get(games_url).json().get("response", {})
    games = res.get("games", [])
    total_games = res.get("game_count", len(games))

    if not games:
      await message.answer(
          "❌ У вас скрыт список игр в настройках приватности Steam!",
          reply_markup=get_keyboard(message.from_user.id),
      )
      return

    games_sorted = sorted(
        games, key=lambda x: x.get("playtime_forever", 0), reverse=True
    )

    text = f"📚 **Всего игр на аккаунте:** {total_games}\n\n🕹 **Топ игр по часам:**\n"
    for g in games_sorted[:15]:
      g_name = g.get("name")
      hours = round(g.get("playtime_forever", 0) / 60, 1)
      text += f"• {g_name} — **{hours} ч.**\n"

    await message.answer(
        text, parse_mode="Markdown", reply_markup=get_keyboard(message.from_user.id)
    )
  except Exception as e:
    logging.error(e)
    await message.answer(
        "❌ Не удалось загрузить список игр.",
        reply_markup=get_keyboard(message.from_user.id),
    )


@dp.message(F.text == "💰 Баланс и оценка покупок")
async def show_account_value(message: types.Message):
  steam_id = get_user_steam(message.from_user.id)
  if not steam_id:
    await message.answer(
        "Сначала привяжите аккаунт!",
        reply_markup=get_keyboard(message.from_user.id),
    )
    return

  games_url = f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/?key={STEAM_API_KEY}&steamid={steam_id}&include_appinfo=true"
  try:
    games = requests.get(games_url).json().get("response", {}).get("games", [])
    paid_games = [g for g in games if g.get("playtime_forever", 0) > 0]
    rough_estimate = len(paid_games) * 450

    msg = (
        "💰 **Оценка аккаунта и баланса:**\n\n"
        "🔒 *Прямой баланс кошелька Steam скрыт официальными правилами безопасности"
        " Valve API.*\n\n"
        f"📦 Всего игр с наиигранным временем: **{len(paid_games)} шт.**\n"
        f"💵 Примерная оценочная стоимость купленных игр (в рублях): **~{rough_estimate:,} ₽**"
    )
    await message.answer(
        msg, parse_mode="Markdown", reply_markup=get_keyboard(message.from_user.id)
    )
  except Exception as e:
    logging.error(e)
    await message.answer(
        "❌ Ошибка при расчете стоимости.",
        reply_markup=get_keyboard(message.from_user.id),
    )


@dp.message(F.text == "🌍 Регион аккаунта")
async def show_account_region(message: types.Message):
  steam_id = get_user_steam(message.from_user.id)
  if not steam_id:
    await message.answer(
        "Сначала привяжите аккаунт!",
        reply_markup=get_keyboard(message.from_user.id),
    )
    return

  profile_url = f"https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/?key={STEAM_API_KEY}&steamids={steam_id}"
  try:
    player = (
        requests.get(profile_url).json().get("response", {}).get("players", [])[0]
    )
    country = player.get("loccountrycode", "Не указана")

    currency_map = {
        "RU": "Российский рубль (RUB) 🇷🇺",
        "KZ": "Казахстанский тенге (KZT) 🇰🇿",
        "UA": "Украинская гривна (UAH) 🇺🇦",
        "US": "Доллар США (USD) 🇺🇸",
        "TR": "Турецкая лира (TRY) 🇹🇷",
        "AR": "Аргентинский песо (ARS) 🇦🇷",
        "DE": "Евро (EUR) 🇪🇺",
        "GB": "Британский фунт (GBP) 🇬🇧",
    }

    region_info = currency_map.get(
        country, f"Регион по коду страны: {country}"
    )

    msg = (
        f"🌍 **Информация о регионе:**\n\n"
        f"• Страна профиля: **{country}**\n"
        f"• Предполагаемая валюта/регион магазина: **{region_info}**"
    )
    await message.answer(
        msg, parse_mode="Markdown", reply_markup=get_keyboard(message.from_user.id)
    )
  except Exception as e:
    logging.error(e)
    await message.answer(
        "❌ Не удалось определить регион.",
        reply_markup=get_keyboard(message.from_user.id),
    )


if __name__ == "__main__":
  import asyncio

  asyncio.run(dp.start_polling(bot))
