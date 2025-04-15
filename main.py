import os
import sqlite3
from dotenv import load_dotenv
import pandas as pd
import telebot
from telebot import types
import requests
# from lxml import html

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
    item_load = types.KeyboardButton("Загрузить файл")
    item_parse = types.KeyboardButton("Парсинг")
    markup.add(item_load, item_parse)
    bot.send_message(message.chat.id, "Выберите действие:", reply_markup=markup)


# Обработчик кнопки "Загрузить файл"
@bot.message_handler(func=lambda message: message.text == "Загрузить файл")
def request_file(message):
    msg = bot.send_message(message.chat.id, "Пожалуйста, прикрепите Excel-файл со следующими полями:\n"
                                            "1. title - название\n"
                                            "2. url - ссылка на сайт-источник\n"
                                            "3. xpath - путь к элементу с ценой")
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
            bot.reply_to(message, "Ошибка: Пожалуйста, загрузите файл в формате Excel (.xlsx или .xls)")
            return

        # Сохраняем временный файл
        temp_file = f"temp_{message.chat.id}.xlsx"
        with open(temp_file, 'wb') as new_file:
            new_file.write(downloaded_file)

        # Чтение файла с помощью pandas
        try:
            df = pd.read_excel(temp_file, engine='openpyxl')  # Явно указываем движок
        except Exception as e:
            bot.reply_to(message, f"Ошибка чтения: {str(e)}")
            return
        # try:git commit -m "First commit"
        #     df = pd.read_excel(temp_file)
        # except Exception as e:
        #     bot.reply_to(message, f"Ошибка при чтении Excel-файла: {str(e)}")
        #     os.remove(temp_file)
        #     return

        # Проверка наличия необходимых столбцов
        required_columns = ['title', 'url', 'xpath']
        missing_columns = [col for col in required_columns if col not in df.columns]

        if missing_columns:
            bot.reply_to(message, f"Ошибка: В файле отсутствуют обязательные столбцы: {', '.join(missing_columns)}")
            os.remove(temp_file)
            return

        # Проверка на пустые значения
        if df[required_columns].isnull().values.any():
            bot.reply_to(message, "Ошибка: В файле есть пустые значения в обязательных столбцах")
            os.remove(temp_file)
            return

        # Сохранение в базу данных
        conn = sqlite3.connect('sites.db')
        cursor = conn.cursor()

        # Очищаем старые данные (опционально, можно убрать, если нужно накапливать)
        cursor.execute("DELETE FROM sites")

        # Добавляем новые данные
        for _, row in df.iterrows():
            try:
                cursor.execute("INSERT INTO sites (title, url, xpath) VALUES (?, ?, ?)",
                               (row['title'], row['url'], row['xpath']))
                conn.commit()
            except sqlite3.IntegrityError:
                bot.reply_to(message, f"Предупреждение: URL {row['url']} уже существует в базе и не был добавлен")
                continue

        # Получаем все данные из БД для отображения
        cursor.execute("SELECT * FROM sites")
        db_data = cursor.fetchall()
        conn.close()

        # Создаем DataFrame из данных БД
        db_df = pd.DataFrame(db_data, columns=['id', 'title', 'url', 'xpath'])

        # Отправляем содержимое файла пользователю
        bot.send_message(message.chat.id, "✅ Файл успешно загружен и проверен. Содержимое файла:")
        bot.send_message(message.chat.id, f"```\n{df.to_string(index=False)}\n```", parse_mode='Markdown')

        bot.send_message(message.chat.id, "📦 Данные в базе данных:")
        bot.send_message(message.chat.id, f"```\n{db_df.to_string(index=False)}\n```", parse_mode='Markdown')

        # Удаляем временный файл
        os.remove(temp_file)

    except Exception as e:
        bot.reply_to(message, f'❌ Произошла ошибка: {str(e)}')
        if 'temp_file' in locals() and os.path.exists(temp_file):
            os.remove(temp_file)


# Обработчик кнопки "Парсинг"
@bot.message_handler(func=lambda message: message.text == "Парсинг")
def start_parsing(message):
    try:
        conn = sqlite3.connect('sites.db')
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sites")
        sites = cursor.fetchall()
        conn.close()

        if not sites:
            bot.reply_to(message, "❌ В базе данных нет сайтов для парсинга. Сначала загрузите файл.")
            return

        bot.send_message(message.chat.id, "⏳ Начинаю парсинг цен...")

        results = []
        errors = []

        for site in sites:
            id_, title, url, xpath = site
            try:
                # Заголовки, чтобы сайты не блокировали запрос
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }

                response = requests.get(url, headers=headers, timeout=10)
                response.raise_for_status()  # Проверка на ошибки HTTP

                tree = html.fromstring(response.content)
                price_element = tree.xpath(xpath)

                if not price_element:
                    errors.append(f"{title}: элемент не найден по XPath")
                    continue

                price_text = price_element[0].text.strip()

                # Очистка цены от лишних символов
                price_value = ''.join(c for c in price_text if c.isdigit() or c == '.')

                if not price_value:
                    errors.append(f"{title}: не удалось извлечь цену из текста")
                    continue

                price = float(price_value)
                results.append({'title': title, 'price': price, 'url': url})

                # Отправка промежуточного результата
                bot.send_message(message.chat.id, f"🔹 {title}: {price} руб. [Успешно]")

            except Exception as e:
                errors.append(f"{title}: {str(e)}")
                continue

        # Формирование итогового отчета
        report = "📊 Результаты парсинга:\n\n"

        if results:
            df_results = pd.DataFrame(results)
            report += "Успешно обработано:\n"
            report += df_results[['title', 'price']].to_string(index=False) + "\n\n"

            # Средняя цена
            avg_price = df_results['price'].mean()
            report += f"Средняя цена: {avg_price:.2f} руб.\n\n"

        if errors:
            report += "Ошибки:\n" + "\n".join(f"❌ {error}" for error in errors)

        bot.send_message(message.chat.id, report)

    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка при парсинге: {str(e)}")


if __name__ == '__main__':
    init_db()
    print("Бот запущен...")
    bot.polling(none_stop=True)