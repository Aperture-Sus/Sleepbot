import telebot

bot = telebot.TeleBot('7898320721:AAHUS4O-bUMdn4JNT21OTPi4t3oXvBtB1Dk')

@bot.message_handler(commands=['start'])
def main(message):
    bot.send_message(message.chat.id, f'Привет, {message.from_user.username}. '
                                      f'Напишите во сколько часов вы хотите спать:')

bot.infinity_polling()