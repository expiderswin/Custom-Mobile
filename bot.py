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
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

# Настройки
TELEGRAM_TOKEN = "8912839996:AAGO4qR0gNIEpLgLMlhDeD5EsqINAvU7FvE"
STEAM_API_KEY = "EB93B90EE4E48B486251A750035A6223"
CHANNEL_ID = "@steamstats"  # Юзернейм канала для проверки подписки

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


# --- ПРОВЕРКА ПОДПИСКИ НА КАНАЛ ---
async def check_subscription(user_id: int) -> bool:
  try:
    member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
    if member.status in ["creator", "administrator", "member"]:
      return True
    return False
  except Exception as e:
    logging.error(f"Ошибка проверки подписки: {e}")
    return False


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
                KeyboardButton(text="Инвентарь и скины (CS2)"),
                KeyboardButton(text="Профиль и статус"),
            ],
            [KeyboardButton(text="Баланс и оценка покупок")],
        ],
        resize_keyboard=True,
    )


def get_sub_keyboard():
  return InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="Подписаться на канал", url="https://t.me/steamstats"
              )
          ],
          [
              InlineKeyboardButton(
                  text="Проверить подписку", callback_data="check_sub"
              )
          ],
      ]
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


# --- УНИВЕРСАЛЬНЫЙ ФИЛЬТР ПОДПИСКИ ДЛЯ ВСЕХ СООБЩЕНИЙ ---
@dp.message()
async def sub_middleware_and_handler(message: types.Message, state: FSMContext):
  user_id = message.from_user.id

  is_subscribed = await check_subscription(user_id)
  if not is_subscribed:
    await message.answer(
        "Для доступа к пространству бота необходимо подписаться на официальный"
        " канал сообщества.\n\nПодпишитесь и нажмите кнопку проверки ниже.",
        reply_markup=get_sub_keyboard(),
    )
    return

  text = message.text

  if text == "/start":
    user_steam = get_user_steam(user_id)
    if user_steam:
      txt = (
          "С возвращением. Цифровой след твоего пути в мирах Steam уже соединен с"
          " этим пространством. Выбери направление."
      )
    else:
      txt = (
          "Приветствую. Время бесконечно, но твой профиль Steam еще не привязан."
          " Укажи свою ссылку, чтобы начать летопись."
      )
    await message.answer(txt, reply_markup=get_keyboard(user_id))

  elif text == "Привязать Steam аккаунт":
    await state.set_state(Form.waiting_for_steam)
    await message.answer(
        "Отправь ссылку на свой профиль Steam (например:"
        " `https://steamcommunity.com/profiles/76561198...`).",
        parse_mode="Markdown",
    )

  elif text == "Как узнать ссылку?":
    await message.answer(
        "Инструкция: открой свой профиль Steam в приложении или браузере, скопируй"
        " адрес страницы и отправь его сюда.",
        reply_markup=get_keyboard(user_id),
    )

  elif await state.get_state() == Form.waiting_for_steam.state:
    await state.clear()
    steam_id = resolve_steam_id(text)
    if not steam_id:
      await message.answer(
          "Не удалось распознать профиль. Проверь корректность ссылки.",
          reply_markup=get_keyboard(user_id),
      )
      return
    save_user_steam(user_id, steam_id)
    await message.answer(
        "Связь установлена. Цифровое отражение твоего аккаунта зафиксировано в"
        " памяти системы.",
        reply_markup=get_keyboard(user_id),
    )

  elif text == "Вся библиотека игр":
    await show_user_games(message)

  elif text == "Во что поиграть?":
    await random_game_choice(message)

  elif text == "Топ задротских игр":
    await top_played_games(message)

  elif text == "Инвентарь и скины (CS2)":
    await show_steam_inventory(message)

  elif text == "Профиль и статус":
    await show_profile_status(message)

  elif text == "Баланс и оценка покупок":
    await show_account_value(message)


# --- ОБРАБОТКА КНОПКИ ПРОВЕРКИ ПОДПИСКИ ---
@dp.callback_query(F.data == "check_sub")
async def process_check_sub(callback: types.CallbackQuery):
  user_id = callback.from_user.id
  is_subscribed = await check_subscription(user_id)

  if is_subscribed:
    await callback.message.edit_text(
        "Подписка подтверждена. Добро пожаловать в систему."
    )
    await callback.message.answer(
        "Главное меню:", reply_markup=get_keyboard(user_id)
    )
  else:
    await callback.answer(
        "Вы всё еще не подписаны на канал!", show_alert=True
    )


# --- ЛОГИКА ФУНКЦИЙ БОТА ---
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
    await message.answer(msg, reply_markup=get_keyboard(message.from_user.id))
  except Exception as e:
    logging.error(e)
    await message.answer("Судьба молчит. Не удалось сделать выбор.")


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

    await message.answer(text, reply_markup=get_keyboard(message.from_user.id))
  except Exception as e:
    logging.error(e)
    await message.answer("Не удалось проанализировать хроники времени.")


async def show_steam_inventory(message: types.Message):
  steam_id = get_user_steam(message.from_user.id)
  if not steam_id:
    return

  # Запрос инвентаря Counter-Strike 2 (AppID: 730)
  url = f"https://steamcommunity.com/inventory/{steam_id}/730/2?l=russian&count=75"
  try:
    await message.answer(
        "Сканирую хранилище материальных ценностей... Ожидай материализации"
        " образов."
    )
    response = requests.get(url).json()

    if not response.get("success"):
      await message.answer(
          "Инвентарь скрыт настройками приватности или временно недоступен."
      )
      return

    descriptions = response.get("descriptions", [])
    if not descriptions:
      await message.answer("В этом хранилище не найдено предметов.")
      return

    count = 0
    for item in descriptions:
      if count >= 5:  # Ограничение в 5 предметов за раз, чтобы не перегружать чат
        break

      icon_hash = item.get("icon_url")
      if not icon_hash:
        continue

      icon_url = f"https://steamcommunity-a.akamaihd.net/economy/image/{icon_hash}"
      name = item.get("name", "Неизвестный предмет")
      item_type = item.get("type", "Артефакт")

      caption = f"Артефакт: {name}\nКлассификация: {item_type}"
      await message.answer_photo(photo=icon_url, caption=caption)
      count += 1

    await message.answer(
        "Материализация завершена.", reply_markup=get_keyboard(message.from_user.id)
    )
  except Exception as e:
    logging.error(e)
    await message.answer("Не удалось извлечь образы инвентаря из архивов.")


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
    await message.answer(msg, reply_markup=get_keyboard(message.from_user.id))
  except Exception as e:
    logging.error(e)
    await message.answer("Образ профиля затуманен. Нет данных.")


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
    await message.answer(msg, reply_markup=get_keyboard(message.from_user.id))
  except Exception as e:
    logging.error(e)
    await message.answer("Невозможно исчислить эквивалент ценности.")


if __name__ == "__main__":
  import asyncio

  asyncio.run(dp.start_polling(bot))
