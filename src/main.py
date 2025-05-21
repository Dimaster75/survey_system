import os
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd
import matplotlib.pyplot as plt
import telebot
from telebot import types

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация бота
TOKEN = '7256436061:AAGUitHwh16QtEFM0NgLYtiYvKC6zkqnuc8'
DB_FILE = 'financial_data.db'

# Категории по умолчанию
DEFAULT_CATEGORIES = {
    'expense': ['🍔 Еда', '🚗 Транспорт', '🏠 Жилье', '🎉 Развлечения', '🏥 Здоровье', '👕 Одежда', '❔ Другое'],
    'income': ['💰 Зарплата', '💻 Фриланс', '📈 Инвестиции', '🎁 Подарки', '❔ Другое']
}

# Инициализация бота
bot = telebot.TeleBot(TOKEN)

# Временное хранилище данных пользователей
user_data: Dict[int, Dict] = {}

class FinanceManager:
    def __init__(self):
        self.db_file = DB_FILE
        self._init_db()
    
    def _init_db(self):
        """Инициализирует базу данных и создает таблицы при необходимости"""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    category TEXT NOT NULL,
                    amount REAL NOT NULL,
                    date TIMESTAMP NOT NULL,
                    description TEXT
                )
            """)
            conn.commit()
    
    def _get_connection(self) -> sqlite3.Connection:
        """Возвращает соединение с базой данных"""
        return sqlite3.connect(self.db_file)
    
    def add_transaction(self, user_id: int, transaction_type: str, category: str,
                   amount: float, description: str = '') -> None:
        """Добавляет транзакцию в базу данных"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO transactions (user_id, type, category, amount, date, description)
                VALUES (?, ?, ?, ?, datetime('now'), ?)
            """, (user_id, transaction_type, category, amount, description))
            conn.commit()
    
    def get_statistics(self, user_id: int, period: str = 'week') -> Dict:
        """Возвращает статистику за указанный период"""
        now = datetime.now()
        date_condition = ""
        
        if period == 'day':
            date_condition = f"AND date(date) = date('{now.date()}')"
        elif period == 'week':
            start_date = now - timedelta(days=now.weekday())
            date_condition = f"AND date(date) >= date('{start_date.date()}')"
        elif period == 'month':
            date_condition = f"AND strftime('%m', date) = '{now.month:02d}'"
        
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Получаем расходы
            cursor.execute(f"""
                SELECT category, SUM(amount) as total 
                FROM transactions 
                WHERE user_id = ? AND type = 'expense' {date_condition}
                GROUP BY category
            """, (user_id,))
            expenses = {row['category']: row['total'] for row in cursor.fetchall()}
            
            # Получаем доходы
            cursor.execute(f"""
                SELECT category, SUM(amount) as total 
                FROM transactions 
                WHERE user_id = ? AND type = 'income' {date_condition}
                GROUP BY category
            """, (user_id,))
            income = {row['category']: row['total'] for row in cursor.fetchall()}
            
            # Общие суммы
            cursor.execute(f"""
                SELECT 
                    SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END) as total_expenses,
                    SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END) as total_income
                FROM transactions 
                WHERE user_id = ? {date_condition}
            """, (user_id,))
            totals = cursor.fetchone()
            
            return {
                'total_expenses': totals['total_expenses'] or 0,
                'expenses_by_category': expenses,
                'total_income': totals['total_income'] or 0,
                'income_by_category': income
            }
    
    def get_transactions(self, user_id: int, limit: int = 10) -> List[Dict]:
        """Возвращает последние транзакции пользователя"""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    id,
                    user_id,
                    type,
                    category,
                    amount,
                    strftime('%Y-%m-%d %H:%M:%S', date) as date,
                    description
                FROM transactions 
                WHERE user_id = ? 
                ORDER BY date DESC 
                LIMIT ?
            """, (user_id, limit))
        return [dict(row) for row in cursor.fetchall()]
    
    def generate_report(self, user_id: int, period: str = 'week') -> str:
        """Генерирует текстовый отчет"""
        stats = self.get_statistics(user_id, period)

        period_names = {'day': 'день', 'week': 'неделю', 'month': 'месяц'}
        report = [
            f"📊 Отчет за {period_names.get(period, period)}",
            f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            "\n💵 Доходы:"
        ]

        if stats['income_by_category']:
            for category, amount in stats['income_by_category'].items():
                report.append(f"  - {category}: {amount:.2f} ₽")
            report.append(f"  Всего: {stats['total_income']:.2f} ₽")
        else:
            report.append("  Нет данных")

        report.append("\n💸 Расходы:")
        if stats['expenses_by_category']:
            for category, amount in stats['expenses_by_category'].items():
                report.append(f"  - {category}: {amount:.2f} ₽")
            report.append(f"  Всего: {stats['total_expenses']:.2f} ₽")
        else:
            report.append("  Нет данных")

        balance = stats.get('total_income', 0) - stats.get('total_expenses', 0)
        report.append(f"\n💰 Баланс: {balance:.2f} ₽")

        return "\n".join(report)

    def plot_statistics(self, user_id: int, period: str = 'week') -> Optional[str]:
        """Создает и сохраняет график статистики"""
        stats = self.get_statistics(user_id, period)
        
        # Проверяем наличие данных
        if not stats['expenses_by_category'] and not stats['income_by_category']:
            return None

        plt.switch_backend('Agg')  # Важно для работы в некоторых окружениях
        plt.style.use('ggplot')
        
        # Создаем фигуру
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 6))
        fig.suptitle(f"Статистика за {self._get_period_name(period)}")
        
        # График расходов
        if stats['expenses_by_category']:
            expenses = stats['expenses_by_category']
            ax1.pie(
                expenses.values(),
                labels=expenses.keys(),
                autopct=lambda p: f'{p:.1f}%\n({p*sum(expenses.values())/100:.2f} ₽)',
                startangle=90
            )
            ax1.set_title('Расходы')
        
        # График доходов
        if stats['income_by_category']:
            income = stats['income_by_category']
            ax2.pie(
                income.values(),
                labels=income.keys(),
                autopct=lambda p: f'{p:.1f}%\n({p*sum(income.values())/100:.2f} ₽)',
                startangle=90
            )
            ax2.set_title('Доходы')
        
        plt.tight_layout()
        
        # Сохраняем в временный файл
        filename = f"chart_{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
        plt.savefig(filename, dpi=100, bbox_inches='tight')
        plt.close()
        
        return filename

    def _get_period_name(self, period: str) -> str:
        """Возвращает читаемое название периода"""
        period_names = {
            'day': 'день',
            'week': 'неделю',
            'month': 'месяц'
        }
        return period_names.get(period, period)

# Инициализация менеджера финансов
finance = FinanceManager()

# Обработчики команд
# Добавляем этот обработчик для главного меню
@bot.message_handler(commands=['menu'])
def show_main_menu(message):
    """Показывает главное меню с кнопками команд"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    
    buttons = [
        types.KeyboardButton('➕ Добавить доход'),
        types.KeyboardButton('➖ Добавить расход'),
        types.KeyboardButton('📊 Статистика'),
        types.KeyboardButton('📝 Отчёт'),
        types.KeyboardButton('📋 История'),
        types.KeyboardButton('ℹ️ Помощь')
    ]
    
    markup.add(*buttons)
    bot.send_message(
        message.chat.id,
        "📱 Главное меню:\nВыберите действие:",
        reply_markup=markup
    )

# Обновляем обработчик старта
@bot.message_handler(commands=['start'])
def start(message):
    """Обработчик команды /start с кнопками меню"""
    show_main_menu(message)
    bot.send_message(
        message.chat.id,
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        "Я твой финансовый помощник. Используй кнопки ниже или команды:\n\n"
        "/add_income - добавить доход\n"
        "/add_expense - добавить расход\n"
        "/stats - статистика\n"
        "/report - отчёты\n"
        "/history - история операций\n"
        "/menu - главное меню"
    )

# Добавляем обработчики для текстовых кнопок
@bot.message_handler(func=lambda m: m.text == '➕ Добавить доход')
def add_income_button(message):
    add_income(message)

@bot.message_handler(func=lambda m: m.text == '➖ Добавить расход')
def add_expense_button(message):
    add_expense(message)

@bot.message_handler(func=lambda m: m.text == '📊 Статистика')
def stats_button(message):
    stats_command(message)

@bot.message_handler(func=lambda m: m.text == '📝 Отчёт')
def report_button(message):
    report_command(message)

@bot.message_handler(func=lambda m: m.text == '📋 История')
def history_button(message):
    history_command(message)

@bot.message_handler(func=lambda m: m.text == 'ℹ️ Помощь')
def help_button(message):
    start(message)

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call: types.CallbackQuery):
    """Обработчик нажатий на кнопки"""
    user_id = call.from_user.id
    data = call.data

    if data.startswith(('expense_', 'income_')):
        transaction_type, category = data.split('_', 1)
        user_data[user_id]['state'] = 'awaiting_amount'
        user_data[user_id]['category'] = category

        bot.edit_message_text(
            f"📌 Категория: {category}\n\nВведите сумму:",
            call.message.chat.id,
            call.message.message_id
        )

    elif data.startswith('stats_'):
        period = data.split('_')[1]
        show_statistics(call, user_id, period)

    elif data.startswith('report_'):
        period = data.split('_')[1]
        show_report(call, user_id, period)

def show_statistics(call: types.CallbackQuery, user_id: int, period: str):
    """Показывает статистику с графиком"""
    report_text = finance.generate_report(user_id, period)
    chart_path = finance.plot_statistics(user_id, period)

    if chart_path:
        with open(chart_path, 'rb') as chart:
            bot.send_photo(
                call.message.chat.id,
                chart,
                caption=report_text
            )
        os.remove(chart_path)
    else:
        bot.send_message(call.message.chat.id, report_text + "\n\n⚠️ Недостаточно данных для графиков")

def show_report(call: types.CallbackQuery, user_id: int, period: str):
    """Показывает текстовый отчет"""
    report_text = finance.generate_report(user_id, period)
    bot.send_message(call.message.chat.id, report_text)

@bot.message_handler(func=lambda m: user_data.get(m.from_user.id, {}).get('state') == 'awaiting_amount')
def handle_amount(message: types.Message):
    """Обработчик ввода суммы"""
    user_id = message.from_user.id

    try:
        amount = float(message.text.replace(',', '.'))
        if amount <= 0:
            raise ValueError("Сумма должна быть положительной")

        user_data[user_id]['amount'] = amount
        user_data[user_id]['state'] = 'awaiting_description'

        bot.send_message(
            message.chat.id,
            "💬 Введите описание (или отправьте '-' чтобы пропустить):\n\n"
            "Пример: 'Обед в кафе' или 'Аванс за проект'"
        )

    except ValueError:
        bot.send_message(message.chat.id, "⚠️ Пожалуйста, введите корректную сумму (например: 1500 или 99.99)")

@bot.message_handler(func=lambda m: user_data.get(m.from_user.id, {}).get('state') == 'awaiting_description')
def handle_description(message: types.Message):
    """Обработчик ввода описания"""
    user_id = message.from_user.id
    description = message.text if message.text.strip() != '-' else ''

    transaction_data = user_data[user_id]
    finance.add_transaction(
        user_id=user_id,
        transaction_type=transaction_data['type'],
        category=transaction_data['category'],
        amount=transaction_data['amount'],
        description=description
    )

    transaction_type = "расход" if transaction_data['type'] == 'expense' else "доход"
    emoji = "📉" if transaction_data['type'] == 'expense' else "📈"

    bot.send_message(
        message.chat.id,
        f"{emoji} Успешно добавлен {transaction_type}:\n\n"
        f"🏷 Категория: {transaction_data['category']}\n"
        f"💳 Сумма: {transaction_data['amount']:.2f} ₽\n"
        f"📝 Описание: {description if description else 'нет'}"
    )

    del user_data[user_id]

@bot.message_handler(commands=['stats'])
def stats_command(message: types.Message):
    """Обработчик команды /stats"""
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("📅 День", callback_data="stats_day"),
        types.InlineKeyboardButton("📆 Неделя", callback_data="stats_week"),
        types.InlineKeyboardButton("🗓 Месяц", callback_data="stats_month")
    )
    bot.send_message(message.chat.id, "📊 Выберите период для статистики:", reply_markup=markup)

@bot.message_handler(commands=['report'])
def report_command(message: types.Message):
    """Обработчик команды /report"""
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("📅 День", callback_data="report_day"),
        types.InlineKeyboardButton("📆 Неделя", callback_data="report_week"),
        types.InlineKeyboardButton("🗓 Месяц", callback_data="report_month")
    )
    bot.send_message(message.chat.id, "📊 Выберите период для отчета:", reply_markup=markup)

@bot.message_handler(commands=['history'])
def history_command(message: types.Message):
    """Обработчик команды /history - показывает последние 10 операций"""
    user_id = message.from_user.id
    transactions = finance.get_transactions(user_id)
    
    if not transactions:
        bot.send_message(message.chat.id, "📭 У вас пока нет операций.")
        return
    
    history_text = ["📋 Последние 10 операций:\n"]
    
    for trans in transactions:
        operation_type = "📉 Расход" if trans['type'] == 'expense' else "📈 Доход"
        try:
            # Парсим дату из строки формата 'YYYY-MM-DD HH:MM:SS'
            date_obj = datetime.strptime(trans['date'], '%Y-%m-%d %H:%M:%S')
            date_str = date_obj.strftime('%d.%m %H:%M')
        except (ValueError, TypeError):
            # Если возникла ошибка, используем текущую дату
            date_str = "сегодня"
        
        description = f"\n   📝 {trans['description']}" if trans['description'] else ""
        
        history_text.append(
            f"{operation_type} | {trans['category']}\n"
            f"   💰 {trans['amount']:.2f} ₽ | ⏱ {date_str}{description}\n"
        )
    
    bot.send_message(message.chat.id, "\n".join(history_text))
    
@bot.message_handler(commands=['add_income', 'add_expense'])
def add_transaction_command(message):
    """Обработчик команд добавления доходов/расходов"""
    if message.text == '/add_income':
        add_income(message)
    else:
        add_expense(message)

def add_expense(message):
    """Добавление расхода (версия с исправлениями)"""
    user_id = message.from_user.id
    user_data[user_id] = {'state': 'awaiting_category', 'type': 'expense'}
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [types.InlineKeyboardButton(cat, callback_data=f"expense_{cat}") 
              for cat in DEFAULT_CATEGORIES['expense']]
    markup.add(*buttons)
    
    bot.send_message(
        message.chat.id, 
        "📉 Выберите категорию расхода:", 
        reply_markup=markup
    )

def add_income(message):
    """Добавление дохода (версия с исправлениями)"""
    user_id = message.from_user.id
    user_data[user_id] = {'state': 'awaiting_category', 'type': 'income'}
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [types.InlineKeyboardButton(cat, callback_data=f"income_{cat}") 
              for cat in DEFAULT_CATEGORIES['income']]
    markup.add(*buttons)
    
    bot.send_message(
        message.chat.id, 
        "📈 Выберите категорию дохода:", 
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith(('expense_', 'income_')))
def category_selected(call):
    """Обработчик выбора категории"""
    user_id = call.from_user.id
    data = call.data.split('_')
    
    user_data[user_id]['category'] = '_'.join(data[1:])  # На случай категорий из нескольких слов
    user_data[user_id]['state'] = 'awaiting_amount'
    
    bot.edit_message_text(
        f"📌 Категория: {user_data[user_id]['category']}\n\nВведите сумму:",
        call.message.chat.id,
        call.message.message_id
    )

@bot.message_handler(func=lambda m: user_data.get(m.from_user.id, {}).get('state') == 'awaiting_amount')
def handle_amount_input(message):
    """Обработчик ввода суммы"""
    user_id = message.from_user.id
    
    try:
        amount = float(message.text.replace(',', '.'))
        if amount <= 0:
            raise ValueError()
            
        user_data[user_id]['amount'] = amount
        user_data[user_id]['state'] = 'awaiting_description'
        
        bot.send_message(
            message.chat.id,
            "💬 Введите описание (или отправьте '-' чтобы пропустить):"
        )
        
    except ValueError:
        bot.send_message(
            message.chat.id,
            "⚠️ Пожалуйста, введите корректную сумму (например: 1500 или 99.99)"
        )

@bot.message_handler(func=lambda m: user_data.get(m.from_user.id, {}).get('state') == 'awaiting_description')
def handle_description_input(message):
    """Обработчик ввода описания"""
    user_id = message.from_user.id
    description = message.text if message.text.strip() != '-' else ''
    
    # Сохраняем транзакцию
    finance.add_transaction(
        user_id=user_id,
        transaction_type=user_data[user_id]['type'],
        category=user_data[user_id]['category'],
        amount=user_data[user_id]['amount'],
        description=description
    )
    
    # Отправляем подтверждение
    transaction_type = "расход" if user_data[user_id]['type'] == 'expense' else "доход"
    emoji = "📉" if user_data[user_id]['type'] == 'expense' else "📈"
    
    bot.send_message(
        message.chat.id,
        f"{emoji} Успешно добавлен {transaction_type}:\n\n"
        f"🏷 Категория: {user_data[user_id]['category']}\n"
        f"💳 Сумма: {user_data[user_id]['amount']:.2f} ₽\n"
        f"📝 Описание: {description if description else 'нет'}"
    )
    
    # Очищаем состояние пользователя
    del user_data[user_id]
    
    # Показываем снова главное меню
    show_main_menu(message)

# Запуск бота
if __name__ == '__main__':
    bot.infinity_polling()

if __name__ == '__main__':
    bot.infinity_polling()
