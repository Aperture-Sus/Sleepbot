import telebot
import pytz
from datetime import datetime, timedelta
import threading
import time as sleep_time
import logging
import sqlite3
from contextlib import closing

DB_NAME = 'sleep_bot.db'

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot('7898320721:AAHUS4O-bUMdn4JNT21OTPi4t3oXvBtB1Dk')


def init_db():
    with closing(sqlite3.connect(DB_NAME)) as conn:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    sleep_time TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    streak INTEGER DEFAULT 0,
                    last_checkin_date TEXT,
                    last_check_date TEXT,
                    today_checked BOOLEAN DEFAULT 0
                )
            """)

init_db()


def get_user_data(user_id):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row:
            # Проверка и корректировка значений
            sleep_time_str = row[2] if row[2] else '00:00'  # Если sleep_time пустой
            timezone_str = row[3] if row[3] else 'UTC+0'    # Если timezone пустой
            streak = row[4] if row[4] else 0                # Если streak пустой

            # Обработка часового пояса
            try:
                if timezone_str.startswith('UTC'):
                    # Парсим смещение (например, UTC+3)
                    offset_str = timezone_str[3:]
                    if offset_str.startswith(('+', '-')):
                        offset = int(offset_str)
                    else:
                        offset = int(f"+{offset_str}")

                    # Используем стандартный часовой пояс с фиксированным смещением
                    if offset == 0:
                        tz = pytz.UTC
                    else:
                        tz = pytz.timezone(f"Etc/GMT{'+' if offset < 0 else '-'}{abs(offset)}")
                else:
                    # Пробуем как стандартный часовой пояс
                    tz = pytz.timezone(timezone_str)
            except (ValueError, pytz.UnknownTimeZoneError):
                # Если не удалось распарсить, используем UTC
                tz = pytz.UTC

            return {
                'user_id': row[0],
                'chat_id': row[1],
                'sleep_time': datetime.strptime(sleep_time_str, '%H:%M').time(),
                'timezone': tz,
                'streak': streak,
                'last_checkin_date': datetime.strptime(row[5], '%Y-%m-%d').date() if row[5] else None,
                'last_check_date': datetime.strptime(row[6], '%Y-%m-%d').date() if row[6] else None,
                'today_checked': bool(row[7])
            }
        return None






def save_user_data(user_data):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        with conn:
            tz = user_data['timezone']
            if isinstance(tz, pytz.tzinfo.BaseTzInfo):
                if hasattr(tz, 'zone'):
                    tz_str = tz.zone
                else:
                    # Для FixedOffset
                    offset = tz._utcoffset.seconds // 3600 if tz._utcoffset else 0
                    tz_str = f"UTC{'+' if offset >=0 else ''}{offset}"
            else:
                tz_str = "UTC+0"  # По умолчанию

            conn.execute("""
                INSERT OR REPLACE INTO users 
                (user_id, chat_id, sleep_time, timezone, streak, last_checkin_date, last_check_date, today_checked)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_data['user_id'],
                user_data['chat_id'],
                user_data['sleep_time'].strftime('%H:%M'),
                tz_str,
                user_data.get('streak', 0),
                user_data.get('last_checkin_date', '').isoformat() if user_data.get('last_checkin_date') else None,
                user_data.get('last_check_date', '').isoformat() if user_data.get('last_check_date') else None,
                int(user_data.get('today_checked', False))
            ))


def format_timezone_name(tz):
    """Форматирует название часового пояса"""
    if isinstance(tz, pytz._FixedOffset):
        # Для FixedOffset
        offset = tz._offset.seconds // 3600
        return f"UTC{'+' if offset >=0 else ''}{offset}"
    elif hasattr(tz, 'zone'):
        # Для стандартных часовых поясов
        return tz.zone
    return "UTC+0"

def reset_streak(user_id, notify=True):
    data = get_user_data(user_id)
    if data:
        data['streak'] = 0
        data['last_checkin_date'] = None
        save_user_data(data)
        if notify:
            bot.send_message(
                data['chat_id'],
                "🔴 Стрик сброшен! Текущий стрик: 0",
                reply_markup=create_main_menu()
            )

def check_time_loop():
    """Фоновая проверка времени для всех пользователей"""
    while True:
        try:
            with closing(sqlite3.connect(DB_NAME)) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT user_id FROM users")
                for (user_id,) in cursor.fetchall():
                    try:
                        data = get_user_data(user_id)
                        if not data:
                            continue

                        # Получаем часовой пояс пользователя
                        tz = data['timezone']
                        if not tz:
                            tz = pytz.UTC  # Устанавливаем часовой пояс по умолчанию (UTC)
                            data['timezone'] = tz
                            save_user_data(data)

                        # Текущее время пользователя
                        user_now = datetime.now(tz)
                        current_time = user_now.time()

                        # Время сна пользователя
                        sleep_time_obj = data['sleep_time']
                        today = user_now.date()

                        # Проверка, можно ли отмечаться
                        if (current_time >= sleep_time_obj and
                                data.get('last_checkin_date') != today and
                                not data.get('today_checked', False)):
                            reset_streak(user_id, notify=True)
                            data['today_checked'] = True
                            save_user_data(data)

                        if today != data.get('last_check_date', datetime.min.date()):
                            data['today_checked'] = False
                            data['last_check_date'] = today
                            save_user_data(data)

                    except Exception as e:
                        logger.error(f"Ошибка проверки времени для {user_id}: {e}")

            sleep_time.sleep(60)

        except Exception as e:
            logger.error(f"Ошибка в основном цикле: {e}")
            sleep_time.sleep(10)




def create_main_menu():
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        "✅ Отметиться за час до сна",
        "📊 Мой стрик",
        "❗ Сбросить время",
    ]
    markup.add(*buttons)
    return markup


@bot.message_handler(commands=['start'])
def start(message):
    msg = bot.send_message(
        message.chat.id,
        "Привет! Во сколько ты планируешь ложиться спать? (Введи время в формате HH:MM)",
        reply_markup=telebot.types.ReplyKeyboardRemove()
    )
    bot.register_next_step_handler(msg, process_time_step)


def confirm_reset(message):
    if message.text.lower() in ["да", "да, сбросить настройки"]:
        reset_streak(message.from_user.id, notify=False)
        msg = bot.send_message(
            message.chat.id,
            "Текущий стрик сброшен. Введите новое время сна (HH:MM):",
            reply_markup=telebot.types.ReplyKeyboardRemove()
        )
        bot.register_next_step_handler(msg, process_time_step)
    else:
        show_main_menu(message.chat.id)


def process_time_step(message):
    try:
        if message.text.startswith('/'):
            raise ValueError

        sleep_time_obj = datetime.strptime(message.text, "%H:%M").time()
        user_data = {
            'user_id': message.from_user.id,
            'chat_id': message.chat.id,
            'sleep_time': sleep_time_obj,
            'timezone': pytz.UTC,  # Временное значение, будет обновлено
            'streak': 0,
            'last_checkin_date': None,
            'today_checked': False
        }
        save_user_data(user_data)

        markup = telebot.types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
        timezones = ["UTC+3", "UTC+5", "UTC+6", "UTC+0", "Другой"]
        for tz in timezones:
            markup.add(telebot.types.KeyboardButton(tz))

        msg = bot.send_message(
            message.chat.id,
            "Выбери свой часовой пояс:",
            reply_markup=markup
        )
        bot.register_next_step_handler(msg, process_timezone_step)
    except ValueError:
        msg = bot.send_message(
            message.chat.id,
            "⛔ Неправильный формат. Введи время в формате ЧЧ:ММ (например, 23:45)",
            reply_markup=telebot.types.ReplyKeyboardRemove()
        )
        bot.register_next_step_handler(msg, process_time_step)


def process_timezone_step(message):
    try:
        user_id = message.from_user.id
        tz_text = message.text.strip()
        data = get_user_data(user_id)

        if not data:
            logger.error(f"Данные пользователя {user_id} не найдены.")
            show_main_menu(message.chat.id)
            return

        logger.info(f"Пользователь {user_id} ввёл часовой пояс: {tz_text}")

        # Удаляем все пробелы и приводим к верхнему регистру
        tz_text = tz_text.replace(" ", "").upper()

        # Если ввод пустой, устанавливаем значение по умолчанию
        if not tz_text:
            tz_text = "UTC+0"
            logger.info(f"Установлен часовой пояс по умолчанию: {tz_text}")

        # Преобразуем смещение UTC в часовой пояс
        if tz_text.startswith("UTC") and len(tz_text) > 3:
            try:
                # Парсим смещение (может быть +5 или -5)
                offset_str = tz_text[3:]
                if offset_str.startswith(('+', '-')):
                    offset = int(offset_str)
                else:
                    offset = int(f"+{offset_str}")

                # Используем стандартный часовой пояс с фиксированным смещением
                if offset == 0:
                    tz = pytz.UTC
                else:
                    tz = pytz.timezone(f"Etc/GMT{'+' if offset < 0 else '-'}{abs(offset)}")

                data['timezone'] = tz
                data['last_check_date'] = datetime.now(tz).date()
                save_user_data(data)

                logger.info(f"Часовой пояс успешно сохранён: {format_timezone_name(tz)}")
                bot.send_message(
                    message.chat.id,
                    f"✅ Настройки сохранены!\n"
                    f"Время сна: {data['sleep_time'].strftime('%H:%M')}\n"
                    f"Часовой пояс: {format_timezone_name(tz)}\n"
                    f"Текущий стрик: 0",
                    reply_markup=create_main_menu()
                )
                return
            except ValueError as e:
                logger.error(f"Ошибка парсинга смещения: {e}")
                bot.send_message(
                    message.chat.id,
                    "⛔ Неверный формат смещения. Попробуй еще раз или выбери из списка:",
                    reply_markup=telebot.types.ReplyKeyboardMarkup(
                        one_time_keyboard=True,
                        resize_keyboard=True
                    ).add(*[telebot.types.KeyboardButton(tz) for tz in ["UTC+3", "UTC+5", "UTC+6", "UTC+0", "Другой"]])
                )
                bot.register_next_step_handler(message, process_timezone_step)
                return

        # Если не распознано как UTC±HH, пробуем как стандартный часовой пояс
        try:
            tz = pytz.timezone(tz_text)
            data['timezone'] = tz
            data['last_check_date'] = datetime.now(tz).date()
            save_user_data(data)

            logger.info(f"Часовой пояс успешно сохранён: {format_timezone_name(tz)}")
            bot.send_message(
                message.chat.id,
                f"✅ Настройки сохранены!\n"
                f"Время сна: {data['sleep_time'].strftime('%H:%M')}\n"
                f"Часовой пояс: {format_timezone_name(tz)}\n"
                f"Текущий стрик: 0",
                reply_markup=create_main_menu()
            )
        except pytz.UnknownTimeZoneError as e:
            logger.error(f"Неизвестный часовой пояс: {tz_text}, ошибка: {e}")
            bot.send_message(
                message.chat.id,
                "⛔ Неверный часовой пояс. Попробуй еще раз или выбери из списка:",
                reply_markup=telebot.types.ReplyKeyboardMarkup(
                    one_time_keyboard=True,
                    resize_keyboard=True
                ).add(*[telebot.types.KeyboardButton(tz) for tz in ["UTC+3", "UTC+5", "UTC+6", "UTC+0", "Другой"]])
            )
            bot.register_next_step_handler(message, process_timezone_step)

    except Exception as e:
        logger.error(f"Ошибка обработки часового пояса: {e}", exc_info=True)
        bot.send_message(
            message.chat.id,
            "❌ Произошла ошибка. Попробуйте еще раз (/start)"
        )


def process_custom_timezone(message):
    try:
        user_id = message.from_user.id
        tz_text = message.text.strip()
        data = get_user_data(user_id)

        if not data:
            show_main_menu(message.chat.id)
            return

        if tz_text.startswith("UTC"):
            offset = int(tz_text[3:])
            tz = pytz.FixedOffset(offset * 60)
        else:
            tz = pytz.timezone(tz_text)

        data['timezone'] = tz
        data['last_check_date'] = datetime.now(tz).date()
        save_user_data(data)

        bot.send_message(
            message.chat.id,
            f"✅ Настройки сохранены!\n"
            f"Время сна: {data['sleep_time'].strftime('%H:%M')}\n"
            f"Часовой пояс: {format_timezone_name(tz)}\n"
            f"Текущий стрик: 0",
            reply_markup=create_main_menu()
        )

    except (pytz.UnknownTimeZoneError, ValueError) as e:
        logger.error(f"Ошибка часового пояса: {e}")
        bot.send_message(
            message.chat.id,
            "❌ Не удалось распознать часовой пояс. Попробуй еще раз или выбери из списка (/start)"
        )
        start(message)


def show_main_menu(chat_id):
    bot.send_message(
        chat_id,
        "Выберите действие:",
        reply_markup=create_main_menu()
    )


@bot.message_handler(func=lambda m: m.text == "✅ Отметиться за час до сна")
def check_in(message):
    user_id = message.from_user.id
    data = get_user_data(user_id)

    if not data:
        bot.send_message(
            message.chat.id,
            "Сначала настройте время сна с помощью /start",
            reply_markup=telebot.types.ReplyKeyboardRemove()
        )
        return

    try:
        tz = data['timezone']
        now = datetime.now(tz)
        current_time = now.time()
        sleep_time_obj = data['sleep_time']
        today = now.date()

        # Рассчитываем время за час до сна
        sleep_datetime = datetime.combine(today, sleep_time_obj)
        one_hour_before = (sleep_datetime - timedelta(hours=1)).time()
        one_hour_after = (sleep_datetime + timedelta(hours=1)).time()

        logger.info(f"Текущее время: {current_time}, время сна: {sleep_time_obj}, часовой пояс: {tz}")
        logger.info(f"Можно отмечаться с {one_hour_before} до {sleep_time_obj}")

        if one_hour_before <= current_time <= sleep_time_obj:
            if data.get('last_checkin_date') != today:
                data['streak'] = data.get('streak', 0) + 1
                data['last_checkin_date'] = today
                save_user_data(data)
                bot.send_message(
                    message.chat.id,
                    f"✅ Отметка принята! Текущий стрик: {data['streak']}",
                    reply_markup=create_main_menu()
                )
            else:
                bot.send_message(
                    message.chat.id,
                    "Вы уже отметились сегодня. Попробуйте завтра!",
                    reply_markup=create_main_menu()
                )
        elif current_time > sleep_time_obj:
            bot.send_message(
                message.chat.id,
                "⏰ Уже поздно отмечаться! Время сна прошло.",
                reply_markup=create_main_menu()
            )
        else:
            bot.send_message(
                message.chat.id,
                f"⏳ Слишком рано! Отмечаться можно с {one_hour_before.strftime('%H:%M')} до {sleep_time_obj.strftime('%H:%M')}",
                reply_markup=create_main_menu()
            )
    except Exception as e:
        logger.error(f"Ошибка при отметке: {e}", exc_info=True)
        bot.send_message(
            message.chat.id,
            "❌ Произошла ошибка при обработке времени. Попробуйте позже.",
            reply_markup=create_main_menu()
        )


@bot.message_handler(func=lambda m: m.text == "📊 Мой стрик")
def show_streak(message):
    data = get_user_data(message.from_user.id)
    if not data:
        bot.send_message(
            message.chat.id,
            "У вас нет активного стрика. Сначала настройте время сна с помощью /start",
            reply_markup=telebot.types.ReplyKeyboardRemove()
        )
        return

    bot.send_message(
        message.chat.id,
        f"📊 Ваш текущий стрик: {data.get('streak', 0)}\n"
        f"⏰ Время сна: {data['sleep_time'].strftime('%H:%M')}\n"
        f"🌍 Часовой пояс: {format_timezone_name(data['timezone'])}",
        reply_markup=create_main_menu()
    )


@bot.message_handler(func=lambda m: m.text == "❗ Сбросить время")
def change_settings(message):
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(telebot.types.KeyboardButton("Да, я понимаю"))
    markup.add(telebot.types.KeyboardButton("Нет, оставить как есть"))

    bot.send_message(
        message.chat.id,
        "⚠️ Изменение времени сбросит ваш текущий стрик. Продолжить?",
        reply_markup=markup
    )
    bot.register_next_step_handler(message, confirm_settings_change)


def confirm_settings_change(message):
    if message.text.lower() in ["да", "да, я понимаю"]:
        # Удаляем пользователя из БД
        with closing(sqlite3.connect(DB_NAME)) as conn:
            with conn:
                conn.execute("DELETE FROM users WHERE user_id = ?", (message.from_user.id,))

        msg = bot.send_message(
            message.chat.id,
            "Все настройки сброшены. Введите новое время сна (HH:MM):",
            reply_markup=telebot.types.ReplyKeyboardRemove()
        )
        bot.register_next_step_handler(msg, process_time_step)
    else:
        show_main_menu(message.chat.id)


# Запускаем фоновый поток для проверки времени
threading.Thread(target=check_time_loop, daemon=True).start()

if __name__ == '__main__':
    logger.info("Запускаем бота...")
    bot.polling(none_stop=True)