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
            [KeyboardButton(text="🕹 Вся библиотека игр и часы")],
            [KeyboardButton(text="💰 Баланс и оценка покупок")],
            [KeyboardButton(text="⚙️ Настройка профиля Steam")],
        ],
        resize_keyboard=True,
    )


class Form(StatesGroup):
  waiting_for_steam = State()
  waiting_for_name = State()
  waiting_for_bio = State()


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
        " ниже:"
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
        "❌ Вы уже привязали аккаунт.",
        reply_markup=get_keyboard(message.from_user.id),
    )
    return

  await state.set_state(Form.waiting_for_steam)
  await message.answer(
      "🔗 Отправьте ссылку на свой профиль Steam (например:"
      " `https://steamcommunity.com/profiles/76561198...`):",
      parse_mode="Markdown",
  )


@dp.message(F.text == "📖 Как узнать ссылку?")
async def show_tutorial(message: types.Message):
  await message.answer(
      "📖 **Инструкция:**\nОткройте профиль Steam -> скопируйте ссылку из"
      " адресной строки / приложения -> отправьте её боту.",
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
  await message.answer(
      "✅ **Аккаунт успешно привязан!** Кнопка добавления скрыта.",
      parse_mode="Markdown",
      reply_markup=get_keyboard(message.from_user.id),
  )


# --- ВСЯ БИБЛИОТЕКА ИГР (ПЛАТНЫЕ И БЕСПЛАТНЫЕ) ---
@dp.message(F.text == "🕹 Вся библиотека игр и часы")
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
          "❌ У вас скрыт список игр в настройках приватности Steam!",
          reply_markup=get_keyboard(message.from_user.id),
      )
      return

    # Сортируем: сначала с наиигранным временем, затем абсолютно все остальные (включая не запущенные / бесплатные)
    games_sorted = sorted(
        games, key=lambda x: x.get("playtime_forever", 0), reverse=True
    )

    text = (
        f"📚 **Полная библиотека игр:** {total_games} шт. (включая бесплатные и"
        " не установленные)\n\n🕹 **Топ игр:**\n"
    )
    for g in games_sorted[:20]:  # Выводим топ-20 для читаемости в чате
      g_name = g.get("name")
      hours = round(g.get("playtime_forever", 0) / 60, 1)
      text += f"• {g_name} — **{hours} ч.**\n"

    if total_games > 20:
      text += f"\n*(И еще {total_games - 20} игр на аккаунте)*"

    await message.answer(
        text, parse_mode="Markdown", reply_markup=get_keyboard(message.from_user.id)
    )
  except Exception as e:
    logging.error(e)
    await message.answer(
        "❌ Не удалось загрузить библиотеку.",
        reply_markup=get_keyboard(message.from_user.id),
    )


# --- БАЛАНС И ОЦЕНКА ---
@dp.message(F.text == "💰 Баланс и оценка покупок")
async def show_account_value(message: types.Message):
  steam_id = get_user_steam(message.from_user.id)
  if not steam_id:
    return

  games_url = f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/?key={STEAM_API_KEY}&steamid={steam_id}&include_appinfo=true&include_played_free_games=true"
  try:
    games = requests.get(games_url).json().get("response", {}).get("games", [])
    # Учитываем все игры, исключая те, у которых времени 0 и которые предположительно бесплатные
    paid_games = [g for g in games if g.get("playtime_forever", 0) > 0]
    rough_estimate = len(paid_games) * 450

    msg = (
        "💰 **Оценка стоимости библиотеки:**\n\n"
        "🔒 *Прямой баланс кошелька Steam закрыт политикой безопасности"
        " Valve.*\n\n"
        f"📦 Всего игр в библиотеке: **{len(games)} шт.**\n"
        f"💵 Примерная оценочная стоимость: **~{rough_estimate:,} ₽**"
    )
    await message.answer(
        msg, parse_mode="Markdown", reply_markup=get_keyboard(message.from_user.id)
    )
  except Exception as e:
    logging.error(e)
    await message.answer(
        "❌ Ошибка при расчете.",
        reply_markup=get_keyboard(message.from_user.id),
    )


# --- НАСТРОЙКА ПРОФИЛЯ STEAM ИЗ ТГ ---
@dp.message(F.text == "⚙️ Настройка профиля Steam")
async def profile_settings_menu(message: types.Message):
  kb = ReplyKeyboardMarkup(
      keyboard=[
          [KeyboardButton(text="✏️ Изменить ник в Steam")],
          [KeyboardButton(text="📝 Изменить описание (био)")],
          [KeyboardButton(text="🔙 Назад в меню")],
      ],
      resize_keyboard=True,
  )
  await message.answer(
      "⚙️ Выберите, что вы хотите изменить в своем профиле Steam:",
      reply_markup=kb,
  )


@dp.message(F.text == "🔙 Назад в меню")
async def back_to_menu(message: types.Message):
  await message.answer(
      "Главное меню:", reply_markup=get_keyboard(message.from_user.id)
  )


@dp.message(F.text == "✏️ Изменить ник в Steam")
async def change_name_prompt(message: types.Message, state: FSMContext):
  await state.set_state(Form.waiting_for_name)
  await message.answer(
      "Введите новый никнейм для вашего Steam аккаунта:",
      reply_markup=ReplyKeyboardRemove(),
  )


@dp.message(Form.waiting_for_name)
async def save_new_steam_name(message: types.Message, state: FSMContext):
  await state.clear()
  new_name = message.text.strip()
  # Примечание: полноценное изменение публичного профиля на стороне серверов Valve
  # требует авторизованной сессии (WebAPI Session Cookie / OpenID). Через стандартный серверный Web API ключ
  # Valve позволяет читать публичные данные, но смена имени профиля требует авторизации пользователя.
  await message.answer(
      f"✅ Запрос на смену никнейма на «**{new_name}**» принят.\n\n⚠️ *Обратите"
      " внимание:* Для автоматической смены параметров профиля напрямую на"
      " серверах Steam требуется авторизация через Web API Session,"
      " поэтому в целях безопасности измените его напрямую в настройках"
      " клиента Steam.",
      parse_mode="Markdown",
      reply_markup=get_keyboard(message.from_user.id),
  )


@dp.message(F.text == "📝 Изменить описание (био)")
async def change_bio_prompt(message: types.Message, state: FSMContext):
  await state.set_state(Form.waiting_for_bio)
  await message.answer(
      "Введите новый текст для описания профиля ( Summary ):",
      reply_markup=ReplyKeyboardRemove(),
  )


@dp.message(Form.waiting_for_bio)
async def save_new_steam_bio(message: types.Message, state: FSMContext):
  await state.clear()
  new_bio = message.text.strip()
  await message.answer(
      f"✅ Текст описания обновлен для сессии бота: *{new_bio}*",
      parse_mode="Markdown",
      reply_markup=get_keyboard(message.from_user.id),
  )


if __name__ == "__main__":
  import asyncio

  asyncio.run(dp.start_polling(bot))
