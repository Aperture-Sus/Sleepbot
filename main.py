import telebot
import pytz
from datetime import datetime, time, timedelta, timezone
import threading
import time as sleep_time
import logging

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot("7898320721:AAHUS4O-bUMdn4JNT21OTPi4t3oXvBtB1Dk")

# Храним данные пользователей
user_data = {}


def format_timezone_name(tz):
    """Форматирует название часового пояса"""
    if isinstance(tz, pytz._FixedOffset):
        offset = tz.utcoffset(None).total_seconds() / 3600
        return f"UTC{'+' if offset >= 0 else ''}{int(offset)}"
    return tz.zone


def reset_streak(user_id):
    """Сбрасывает стрик пользователя"""
    if user_id in user_data:
        user_data[user_id]['streak'] = 0
        user_data[user_id]['last_checkin_date'] = None
        bot.send_message(
            user_data[user_id]['chat_id'],
            f"🔴 Стрик сброшен! Текущий стрик: 0",
            reply_markup=create_main_menu()
        )


def check_time_loop():
    """Фоновая проверка времени для всех пользователей"""
    while True:
        try:
            now_utc = datetime.now(timezone.utc)

            for user_id, data in list(user_data.items()):
                if 'timezone' not in data:
                    continue

                try:
                    tz = data['timezone']
                    user_now = datetime.now(tz)
                    current_time = user_now.time()
                    sleep_time_obj = data['sleep_time']
                    today = user_now.date()

                    # +++ ЗАМЕНЯЕМ УСЛОВИЕ НА ЭТО +++
                    if (current_time >= sleep_time_obj and
                            data.get('last_checkin_date') != today and
                            not data.get('today_checked', False)):
                        reset_streak(user_id)
                        bot.send_message(
                            data['chat_id'],
                            "⏰ Время сна прошло! Вы не отметились сегодня. Стрик сброшен. Попробуй завтра!"
                        )
                        data['today_checked'] = True

                    # Сброс флага проверки в новом дне
                    if today != data.get('last_check_date', datetime.min.date()):
                        data['today_checked'] = False
                        data['last_check_date'] = today

                except Exception as e:
                    logger.error(f"Ошибка проверки времени для {user_id}: {e}")

            sleep_time.sleep(60)

        except Exception as e:
            logger.error(f"Ошибка в основном цикле: {e}")
            sleep_time.sleep(10)


@bot.message_handler(commands=['start'])
def start(message):
    if message.from_user.id in user_data:
        markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(telebot.types.KeyboardButton("Да, сбросить настройки"))
        markup.add(telebot.types.KeyboardButton("Нет, оставить как есть"))

        msg = bot.send_message(
            message.chat.id,
            "⚠️ У вас уже есть настройки. Сбросить текущий стрик и начать заново?",
            reply_markup=markup
        )
        bot.register_next_step_handler(msg, confirm_reset)
        return

    msg = bot.send_message(
        message.chat.id,
        "Привет! Во сколько ты планируешь ложиться спать? (Введи время в формате HH:MM)",
        reply_markup=telebot.types.ReplyKeyboardRemove()
    )
    bot.register_next_step_handler(msg, process_time_step)


def confirm_reset(message):
    if message.text.lower() == "да, сбросить настройки":
        reset_streak(message.from_user.id)
        bot.send_message(
            message.chat.id,
            "Настройки сброшены. Текущий стрик: 0",
            reply_markup=telebot.types.ReplyKeyboardRemove()
        )
        start(message)
    else:
        show_main_menu(message.chat.id)


def process_time_step(message):
    try:
        sleep_time_obj = datetime.strptime(message.text, "%H:%M").time()
        user_data[message.from_user.id] = {
            'sleep_time': sleep_time_obj,
            'chat_id': message.chat.id,
            'streak': 0,
            'last_checkin_date': None,
            'today_checked': False
        }

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
        bot.send_message(
            message.chat.id,
            "Неправильный формат времени. Пожалуйста, введи время в формате HH:MM"
        )
        start(message)


def process_timezone_step(message):
    try:
        user_id = message.from_user.id
        tz_text = message.text.strip()

        if tz_text == "Другой":
            msg = bot.send_message(
                message.chat.id,
                "Введи свой часовой пояс (например UTC+5 или Asia/Almaty):",
                reply_markup=telebot.types.ReplyKeyboardRemove()
            )
            bot.register_next_step_handler(msg, process_custom_timezone)
            return

        if tz_text.startswith("UTC"):
            offset = int(tz_text[3:])
            tz = pytz.FixedOffset(offset * 60)
        else:
            tz = pytz.timezone(tz_text)

        user_data[user_id]['timezone'] = tz
        user_data[user_id]['last_check_date'] = datetime.now(tz).date()

        bot.send_message(
            message.chat.id,
            f"✅ Настройки сохранены!\n"
            f"Время сна: {user_data[user_id]['sleep_time'].strftime('%H:%M')}\n"
            f"Часовой пояс: {format_timezone_name(tz)}\n"
            f"Текущий стрик: 0",
            reply_markup=create_main_menu()
        )

    except (pytz.UnknownTimeZoneError, ValueError) as e:
        logger.error(f"Ошибка часового пояса: {e}")
        bot.send_message(
            message.chat.id,
            "Неверный часовой пояс. Попробуй еще раз."
        )
        start(message)


def process_custom_timezone(message):
    try:
        user_id = message.from_user.id
        tz_text = message.text.strip()

        if tz_text.startswith("UTC"):
            offset = int(tz_text[3:])
            tz = pytz.FixedOffset(offset * 60)
        else:
            tz = pytz.timezone(tz_text)

        user_data[user_id]['timezone'] = tz
        user_data[user_id]['last_check_date'] = datetime.now(tz).date()

        bot.send_message(
            message.chat.id,
            f"✅ Настройки сохранены!\n"
            f"Время сна: {user_data[user_id]['sleep_time'].strftime('%H:%M')}\n"
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


def create_main_menu():
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(telebot.types.KeyboardButton("✅ Отметиться за час до сна"))
    markup.add(telebot.types.KeyboardButton("📊 Мой стрик"))
    markup.add(telebot.types.KeyboardButton("⚙️ Изменить настройки"))
    return markup


def show_main_menu(chat_id):
    bot.send_message(
        chat_id,
        "Выберите действие:",
        reply_markup=create_main_menu()
    )


@bot.message_handler(func=lambda m: m.text == "✅ Отметиться за час до сна")
def check_in(message):
    user_id = message.from_user.id
    if user_id not in user_data:
        bot.send_message(
            message.chat.id,
            "Сначала настройте время сна с помощью /start",
            reply_markup=telebot.types.ReplyKeyboardRemove()
        )
        return

    data = user_data[user_id]
    tz = data['timezone']
    now = datetime.now(tz)
    current_time = now.time()
    sleep_time_obj = data['sleep_time']

    # Вычисляем время за час до сна
    one_hour_before = (datetime.combine(now.date(), sleep_time_obj) - timedelta(hours=1)).time()
    checkin_window_start = one_hour_before
    checkin_window_end = sleep_time_obj

    # Проверяем, что отметились в правильное время
    if checkin_window_start <= current_time < checkin_window_end:
        # Проверяем, что сегодня еще не отмечались
        if data.get('last_checkin_date') != now.date():
            data['streak'] = data.get('streak', 0) + 1
            data['last_checkin_date'] = now.date()
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
    elif current_time >= checkin_window_end:
            bot.send_message(
                message.chat.id,
                "⏰ Уже поздно отмечаться! Время сна прошло.",
                reply_markup=create_main_menu()
            )
    else:
        bot.send_message(
            message.chat.id,
            f"⏳ Слишком рано! Отмечаться можно за 1 час до сна ({checkin_window_start.strftime('%H:%M')}-{sleep_time_obj.strftime('%H:%M')})",
            reply_markup=create_main_menu()
        )


@bot.message_handler(func=lambda m: m.text == "📊 Мой стрик")
def show_streak(message):
    user_id = message.from_user.id
    if user_id not in user_data:
        bot.send_message(
            message.chat.id,
            "Сначала настройте время сна с помощью /start",
            reply_markup=telebot.types.ReplyKeyboardRemove()
        )
        return

    data = user_data[user_id]
    bot.send_message(
        message.chat.id,
        f"📊 Ваш текущий стрик: {data.get('streak', 0)}\n"
        f"⏰ Время сна: {data['sleep_time'].strftime('%H:%M')}\n"
        f"🌍 Часовой пояс: {format_timezone_name(data['timezone'])}",
        reply_markup=create_main_menu()
    )


@bot.message_handler(func=lambda m: m.text == "⚙️ Изменить настройки")
def change_settings(message):
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(telebot.types.KeyboardButton("Да, я понимаю"))
    markup.add(telebot.types.KeyboardButton("Нет, оставить как есть"))

    bot.send_message(
        message.chat.id,
        "⚠️ Изменение настроек сбросит ваш текущий стрик. Продолжить?",
        reply_markup=markup
    )
    bot.register_next_step_handler(message, confirm_settings_change)


def confirm_settings_change(message):
    if message.text.lower() == "да, я понимаю":
        reset_streak(message.from_user.id)
        bot.send_message(
            message.chat.id,
            "Текущий стрик сброшен. Введите новое время сна (HH:MM):",
            reply_markup=telebot.types.ReplyKeyboardRemove()
        )
        bot.register_next_step_handler(message, process_time_step)
    else:
        show_main_menu(message.chat.id)


# Запускаем фоновый поток для проверки времени
threading.Thread(target=check_time_loop, daemon=True).start()

if __name__ == '__main__':
    logger.info("Запускаем бота...")
    bot.polling(none_stop=True)