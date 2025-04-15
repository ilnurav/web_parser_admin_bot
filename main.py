import os
import sqlite3
from dotenv import load_dotenv
import pandas as pd
import telebot
from telebot import types

# Загрузка переменных окружения
load_dotenv()

# Инициализация бота
bot = telebot.TeleBot(os.getenv("BOT_TOKEN"))


# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('sites.db')
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        url TEXT NOT NULL UNIQUE,
        xpath TEXT NOT NULL
    )
    ''')
    conn.commit()
    conn.close()


# Обработчик команды /start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    item = types.KeyboardButton("Загрузить файл")
    markup.add(item)
    bot.send_message(message.chat.id, "Выберите действие:", reply_markup=markup)


# Обработчик кнопки "Загрузить файл"
@bot.message_handler(func=lambda message: message.text == "Загрузить файл")
def request_file(message):
    msg = bot.send_message(message.chat.id, "Пожалуйста, прикрепите Excel-файл с данными о сайтах.")
    bot.register_next_step_handler(msg, handle_file)


# Обработчик загруженного файла
@bot.message_handler(content_types=['document'])
def handle_file(message):
    try:
        # Проверяем, что это Excel файл
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        file_extension = message.document.file_name.split('.')[-1].lower()
        if file_extension not in ['xlsx', 'xls']:
            bot.reply_to(message, "Пожалуйста, загрузите файл в формате Excel (.xlsx или .xls)")
            return

        # Сохраняем файл
        with open('sites.xlsx', 'wb') as new_file:
            new_file.write(downloaded_file)

        # Чтение файла с помощью pandas
        df = pd.read_excel('sites.xlsx')

        # Проверка наличия необходимых столбцов
        required_columns = ['title', 'url', 'xpath']
        if not all(col in df.columns for col in required_columns):
            bot.reply_to(message, 'Ошибка: файл должен содержать столбцы title, url и xpath')
            return

        # Сохранение в базу данных
        conn = sqlite3.connect('sites.db')
        df.to_sql('sites', conn, if_exists='append', index=False)
        conn.close()

        # Отправка содержимого файла пользователю
        bot.reply_to(message, f'Данные успешно сохранены:\n{df.to_string(index=False)}')

        # (*) Дополнительно: парсинг цен и вычисление средней
        parse_prices_and_calculate(message, df)

    except Exception as e:
        bot.reply_to(message, f'Ошибка при обработке файла: {str(e)}')


# (*) Функция для парсинга цен и вычисления средней
def parse_prices_and_calculate(message, df):
    try:
        import requests
        from lxml import html

        results = []
        for _, row in df.iterrows():
            try:
                response = requests.get(row['url'], timeout=10)
                tree = html.fromstring(response.content)
                price_text = tree.xpath(row['xpath'])[0].text

                # Очистка цены от лишних символов
                price = float(''.join(c for c in price_text if c.isdigit() or c == '.'))
                results.append({'title': row['title'], 'price': price})

            except Exception as e:
                bot.reply_to(message, f'Ошибка при парсинге {row["title"]}: {str(e)}')
                continue

        if results:
            df_prices = pd.DataFrame(results)
            avg_prices = df_prices.groupby('title')['price'].mean().reset_index()
            bot.reply_to(message, f'Средние цены:\n{avg_prices.to_string(index=False)}')

    except Exception as e:
        bot.reply_to(message, f'Ошибка при расчете средних цен: {str(e)}')


if __name__ == '__main__':
    init_db()
    print("Бот запущен...")
    bot.polling(none_stop=True)