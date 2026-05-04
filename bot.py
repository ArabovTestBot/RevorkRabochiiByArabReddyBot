import os import time import sqlite3 import logging from dotenv import load_dotenv import telebot from telebot import types

================= LOAD ENV =================

load_dotenv()

TOKEN = "8614082185:AAEsAEIQgFuJo7z2eXxe2g4Jetxyu4g-8aM" OWNER_ID = 7925843350  # fixed owner

if not TOKEN: raise ValueError("TOKEN не найден в .env")

bot = telebot.TeleBot(TOKEN)

================= LOGGING =================

logging.basicConfig( level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s" )

================= DB =================

conn = sqlite3.connect("bank.db", check_same_thread=False) cursor = conn.cursor()

cursor.execute(""" CREATE TABLE IF NOT EXISTS credits ( user_id TEXT PRIMARY KEY, username TEXT, total INTEGER, payment INTEGER, last_pay REAL ) """)

cursor.execute(""" CREATE TABLE IF NOT EXISTS requests ( user_id TEXT PRIMARY KEY, username TEXT, amount INTEGER, periods INTEGER, status TEXT, created_at REAL ) """)

cursor.execute(""" CREATE TABLE IF NOT EXISTS users ( user_id TEXT PRIMARY KEY, username TEXT, rating INTEGER DEFAULT 5 ) """)

cursor.execute(""" CREATE TABLE IF NOT EXISTS admins ( user_id INTEGER PRIMARY KEY ) """)

cursor.execute(""" CREATE TABLE IF NOT EXISTS admin_logs ( id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER, action TEXT, target TEXT, timestamp REAL ) """)

conn.commit()

cursor.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (OWNER_ID,)) conn.commit()

================= SETTINGS =================

PENALTY_RATE = 0.02 RATING_DROP = 1 DAY_SEC = 86400

================= UTILS =================

def is_admin(uid): cursor.execute("SELECT 1 FROM admins WHERE user_id=?", (uid,)) return cursor.fetchone() is not None

def log_admin(admin, action, target=""): cursor.execute( "INSERT INTO admin_logs (admin_id, action, target, timestamp) VALUES (?, ?, ?, ?)", (admin, action, target, time.time()) ) conn.commit()

def get_rating(user_id, username="no_username"): cursor.execute("SELECT rating FROM users WHERE user_id=?", (user_id,)) row = cursor.fetchone()

if row:
    return row[0]

cursor.execute(
    "INSERT INTO users (user_id, username, rating) VALUES (?, ?, ?)",
    (user_id, username, 5)
)
conn.commit()
return 5

def percent(r): if r >= 9: return 0.05 if r >= 7: return 0.08 if r >= 5: return 0.10 if r >= 3: return 0.15 return 0.20

================= OVERDUE =================

def check_overdue(): now = time.time()

cursor.execute("SELECT user_id, total, last_pay FROM credits")
rows = cursor.fetchall()

for uid, total, last_pay in rows:
    if not last_pay:
        continue

    overdue = int((now - last_pay) // DAY_SEC)

    if overdue > 0:
        penalty = int(total * PENALTY_RATE * overdue)
        new_total = total + penalty

        cursor.execute(
            "UPDATE credits SET total=?, last_pay=? WHERE user_id=?",
            (new_total, now, uid)
        )

        cursor.execute("SELECT rating FROM users WHERE user_id=?", (uid,))
        r = cursor.fetchone()

        if r:
            new_rating = max(1, r[0] - RATING_DROP * overdue)
            cursor.execute("UPDATE users SET rating=? WHERE user_id=?", (new_rating, uid))

conn.commit()

================= COMMANDS =================

@bot.message_handler(commands=['start']) def start(m): bot.reply_to(m, "🤖 Бот активен")

================= ADMIN PANEL =================

@bot.message_handler(commands=['admin']) def admin_panel(m): if not is_admin(m.from_user.id): return

kb = types.InlineKeyboardMarkup()
kb.add(
    types.InlineKeyboardButton("📄 Заявки", callback_data="admin_requests"),
    types.InlineKeyboardButton("📜 Логи", callback_data="admin_logs")
)
kb.add(
    types.InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")
)

bot.send_message(m.chat.id, "⚙️ Админ панель", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: True) def callback(c): if not is_admin(c.from_user.id): return

data = c.data

if data == "admin_requests":
    cursor.execute("SELECT user_id, username, amount FROM requests WHERE status='pending'")
    rows = cursor.fetchall()

    if not rows:
        return bot.send_message(c.message.chat.id, "Нет заявок")

    for uid, name, amount in rows:
        kb = types.InlineKeyboardMarkup()
        kb.add(
            types.InlineKeyboardButton("✅", callback_data=f"approve_{uid}"),
            types.InlineKeyboardButton("❌", callback_data=f"deny_{uid}")
        )

        bot.send_message(c.message.chat.id, f"👤 @{name}\n💰 {amount}", reply_markup=kb)

elif data == "admin_logs":
    cursor.execute("SELECT admin_id, action, target, timestamp FROM admin_logs ORDER BY id DESC LIMIT 10")
    rows = cursor.fetchall()

    text = "📜 ЛОГИ:\n\n"

    for a, ac, t, ts in rows:
        tm = time.strftime('%Y-%m-%d %H:%M', time.localtime(ts))
        text += f"{a} | {ac} | {t} | {tm}\n"

    bot.send_message(c.message.chat.id, text)

elif data == "admin_stats":
    cursor.execute("SELECT COUNT(*) FROM users")
    users = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM requests WHERE status='pending'")
    req = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM credits")
    credits = cursor.fetchone()[0]

    bot.send_message(
        c.message.chat.id,
        f"📊 Статистика:\n👤 Пользователи: {users}\n📄 Заявки: {req}\n💳 Кредиты: {credits}"
    )

elif data.startswith("approve_"):
    uid = data.split("_")[1]
    approve(uid, c)

elif data.startswith("deny_"):
    uid = data.split("_")[1]
    deny(uid, c)

================= APPROVE / DENY =================

def approve(uid, call): cursor.execute("SELECT username, amount, periods FROM requests WHERE user_id=?", (uid,)) r = cursor.fetchone() if not r: return

username, amount, periods = r

rating = get_rating(uid, username)
total = int(amount * (1 + percent(rating)))
payment = total // periods

cursor.execute("INSERT OR REPLACE INTO credits VALUES (?, ?, ?, ?, ?)",
               (uid, username, total, payment, time.time()))

cursor.execute("UPDATE requests SET status='approved' WHERE user_id=?", (uid,))
conn.commit()

bot.send_message(uid, f"✅ Одобрено\n💰 {total}\n💳 {payment}")
bot.answer_callback_query(call.id, "OK")

def deny(uid, call): cursor.execute("UPDATE requests SET status='rejected' WHERE user_id=?", (uid,)) conn.commit()

bot.send_message(uid, "❌ Отклонено")
bot.answer_callback_query(call.id, "OK")

================= LOOP =================

if name == "main": logging.info("Bot started")

while True:
    try:
        check_overdue()
        bot.polling(none_stop=True)
    except Exception as e:
        logging.error(e)
        time.sleep(5)
