import os
import json
import logging
from datetime import datetime, timedelta
from calendar import monthrange
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes, ConversationHandler
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN", "YOUR_TOKEN_HERE")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
DATA_FILE = "data.json"

(
    ADD_CLIENT_NAME, ADD_CLIENT_USERNAME, ADD_CLIENT_PACKAGE,
    ADD_CLIENT_PAYMENT, ADD_CLIENT_RECEIPT,
    ADD_SUB_PACKAGE, ADD_SUB_PAYMENT, ADD_SUB_RECEIPT,
    ADD_EXPENSE_AMOUNT, ADD_EXPENSE_CATEGORY,
    TAKE_PAYMENT_PACKAGE, TAKE_PAYMENT_METHOD, TAKE_PAYMENT_RECEIPT,
    EDIT_CLIENT_FIELD, EDIT_CLIENT_VALUE,
    EDIT_SUB_FIELD, EDIT_SUB_VALUE,
) = range(17)

PACKAGES = {
    "1": {"name": "Разовое занятие", "sessions": 1, "price": 30},
    "4": {"name": "Абонемент 4 занятия", "sessions": 4, "price": 110},
    "8": {"name": "Абонемент 8 занятий", "sessions": 8, "price": 220},
}

SIGNUP_KEYWORDS = ["я буду", "приду", "запиши", "запишите", "хочу прийти", "оставь место", "буду", "иду", "+", "забронь"]
CANCEL_KEYWORDS = ["не буду", "не приду", "не смогу", "отменяю", "не пойду"]
DAY_NAMES = {"tuesday": "Вторник", "thursday": "Четверг"}
DAY_TIMES = {"tuesday": "18:00", "thursday": "17:00"}
DAY_WEEKDAYS = {"tuesday": 1, "thursday": 3}

def load():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "clients": {},
        "schedule": {
            "tuesday": {"time": "18:00", "signups": {}},
            "thursday": {"time": "17:00", "signups": {}}
        },
        "expenses": [],
        "sessions_log": []
    }

def save(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def is_admin(uid):
    return uid == ADMIN_ID

def today_str():
    return datetime.now().strftime("%d.%m.%Y")

def get_week_monday(dt=None):
    if dt is None:
        dt = datetime.now()
    monday = dt - timedelta(days=dt.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)

def get_training_date(day_key, week_monday=None):
    if week_monday is None:
        week_monday = get_week_monday()
    offset = DAY_WEEKDAYS[day_key]
    return (week_monday + timedelta(days=offset)).strftime("%d.%m.%Y")

def current_week_key():
    return get_week_monday().strftime("%d.%m.%Y")

def get_active_sub(client):
    for sub in reversed(client.get("subscriptions", [])):
        if sub["sessions_left"] > 0:
            if sub.get("end_date"):
                end = datetime.strptime(sub["end_date"], "%d.%m.%Y")
                if end >= datetime.now():
                    return sub
            else:
                return sub
    return None

def client_status_icon(client):
    sub = get_active_sub(client)
    if not sub:
        return "🔴"
    end = datetime.strptime(sub["end_date"], "%d.%m.%Y") if sub.get("end_date") else None
    if end:
        days_left = (end - datetime.now()).days
        if days_left <= 5:
            return "🟡"
    return "🟢"

def next_training_day():
    now = datetime.now()
    weekday = now.weekday()
    if weekday < 1:
        return "tuesday"
    elif weekday == 1:
        return "tuesday" if now.hour < 18 else "thursday"
    elif weekday < 3:
        return "thursday"
    elif weekday == 3:
        return "thursday" if now.hour < 17 else "tuesday"
    else:
        return "tuesday"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    context.user_data.clear()
    kb = [
        [InlineKeyboardButton("👥 Клиенты", callback_data="menu_clients")],
        [InlineKeyboardButton("📅 Расписание", callback_data="menu_schedule")],
        [InlineKeyboardButton("💰 Бухгалтерия", callback_data="menu_finance")],
    ]
    text = "🏋️ *Главное меню*\nВыбери раздел:"
    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def show_clients(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = load()
    active, inactive = [], []
    for uname, c in data["clients"].items():
        st = client_status_icon(c)
        if st == "🔴":
            inactive.append((uname, c, st))
        else:
            active.append((uname, c, st))
    kb = [[InlineKeyboardButton("➕ Добавить клиента", callback_data="client_add")]]
    for uname, c, st in active + inactive:
        sub = get_active_sub(c)
        sub_info = f"{sub['sessions_left']} зан." if sub else "нет абонемента"
        kb.append([InlineKeyboardButton(
            f"{st} {c['name']} — {sub_info}",
            callback_data=f"client_view_{uname}"
        )])
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="main_menu")])
    await query.edit_message_text("👥 *Клиенты*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def view_client(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uname = query.data.replace("client_view_", "")
    data = load()
    c = data["clients"].get(uname)
    if not c:
        await query.edit_message_text("Клиент не найден.")
        return
    st = client_status_icon(c)
    sub = get_active_sub(c)
    text = f"{st} *{c['name']}* (@{uname})\n\n"
    if sub:
        text += f"*Текущий абонемент:*\n{sub['package_name']}\n"
        text += f"Осталось занятий: {sub['sessions_left']}/{sub['sessions_total']}\n"
        if sub.get("end_date"):
            text += f"Действует до: {sub['end_date']}\n"
        pay = "💵 Наличные" if sub["payment"] == "cash" else "💳 Перевод"
        text += f"Оплата: {pay}\n\n"
    if c.get("subscriptions"):
        text += "*История абонементов:*\n"
        for i, s in enumerate(reversed(c["subscriptions"]), 1):
            pay = "💵" if s["payment"] == "cash" else "💳"
            status = "✅" if s["sessions_left"] > 0 else "☑️"
            text += f"{i}. {s['package_name']} {pay} {status} — {s.get('start_date','—')}\n"
    kb = [
        [InlineKeyboardButton("➕ Добавить абонемент", callback_data=f"addsub_{uname}")],
        [InlineKeyboardButton("✏️ Редактировать данные", callback_data=f"edit_client_{uname}")],
        [InlineKeyboardButton("◀️ Назад", callback_data="menu_clients")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def edit_client_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uname = query.data.replace("edit_client_", "")
    context.user_data["edit_uname"] = uname
    data = load()
    c = data["clients"].get(uname)
    sub = get_active_sub(c)
    kb = [
        [InlineKeyboardButton("👤 Изменить имя", callback_data="editfield_name")],
        [InlineKeyboardButton("📱 Изменить ник", callback_data="editfield_username")],
    ]
    if sub:
        kb.append([InlineKeyboardButton("🎫 Тип абонемента", callback_data="editfield_package")])
        kb.append([InlineKeyboardButton("🔢 Кол-во занятий", callback_data="editfield_sessions")])
        kb.append([InlineKeyboardButton("📅 Дата окончания", callback_data="editfield_enddate")])
        kb.append([InlineKeyboardButton("💳 Способ оплаты", callback_data="editfield_payment")])
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data=f"client_view_{uname}")])
    await query.edit_message_text(
        f"✏️ *Редактировать клиента*\n@{uname}\n\nЧто изменить?",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )

async def edit_field_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    field = query.data.replace("editfield_", "")
    context.user_data["edit_field"] = field
    uname = context.user_data["edit_uname"]
    if field == "package":
        kb = [
            [InlineKeyboardButton("1️⃣ Разовое — 30₾", callback_data="editval_pkg_1")],
            [InlineKeyboardButton("4️⃣ Абонемент 4 зан. — 110₾", callback_data="editval_pkg_4")],
            [InlineKeyboardButton("8️⃣ Абонемент 8 зан. — 220₾", callback_data="editval_pkg_8")],
        ]
        await query.edit_message_text("Выбери новый тип абонемента:", reply_markup=InlineKeyboardMarkup(kb))
        return EDIT_SUB_FIELD
    elif field == "payment":
        kb = [
            [InlineKeyboardButton("💵 Наличные", callback_data="editval_pay_cash")],
            [InlineKeyboardButton("💳 Перевод", callback_data="editval_pay_transfer")],
        ]
        await query.edit_message_text("Выбери способ оплаты:", reply_markup=InlineKeyboardMarkup(kb))
        return EDIT_SUB_FIELD
    elif field == "name":
        await query.edit_message_text("Введи новое *имя* клиента:", parse_mode="Markdown")
        return EDIT_CLIENT_VALUE
    elif field == "username":
        await query.edit_message_text("Введи новый *ник* (без @):", parse_mode="Markdown")
        return EDIT_CLIENT_VALUE
    elif field == "sessions":
        await query.edit_message_text("Введи новое *количество оставшихся занятий*:", parse_mode="Markdown")
        return EDIT_CLIENT_VALUE
    elif field == "enddate":
        await query.edit_message_text("Введи новую *дату окончания* (формат: 31.12.2025):", parse_mode="Markdown")
        return EDIT_CLIENT_VALUE

async def edit_client_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    field = context.user_data["edit_field"]
    uname = context.user_data["edit_uname"]
    value = update.message.text.strip()
    data = load()
    c = data["clients"].get(uname)
    if field == "name":
        data["clients"][uname]["name"] = value
    elif field == "username":
        new_uname = value.replace("@", "")
        data["clients"][new_uname] = data["clients"].pop(uname)
        data["clients"][new_uname]["username"] = new_uname
        uname = new_uname
        context.user_data["edit_uname"] = uname
    elif field == "sessions":
        try:
            sessions = int(value)
            sub = get_active_sub(c)
            if sub:
                idx = next(i for i, s in enumerate(c["subscriptions"]) if s is sub)
                data["clients"][uname]["subscriptions"][idx]["sessions_left"] = sessions
        except ValueError:
            await update.message.reply_text("Введи число!")
            return EDIT_CLIENT_VALUE
    elif field == "enddate":
        try:
            datetime.strptime(value, "%d.%m.%Y")
            sub = get_active_sub(c)
            if sub:
                idx = next(i for i, s in enumerate(c["subscriptions"]) if s is sub)
                data["clients"][uname]["subscriptions"][idx]["end_date"] = value
        except ValueError:
            await update.message.reply_text("Формат: 31.12.2025")
            return EDIT_CLIENT_VALUE
    save(data)
    kb = [[InlineKeyboardButton("◀️ К клиенту", callback_data=f"client_view_{uname}")]]
    await update.message.reply_text("✅ Данные обновлены!", reply_markup=InlineKeyboardMarkup(kb))
    context.user_data.clear()
    return ConversationHandler.END

async def edit_sub_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uname = context.user_data["edit_uname"]
    data = load()
    c = data["clients"].get(uname)
    sub = get_active_sub(c)
    if not sub:
        await query.edit_message_text("Активный абонемент не найден.")
        return ConversationHandler.END
    idx = next(i for i, s in enumerate(c["subscriptions"]) if s is sub)
    if query.data.startswith("editval_pkg_"):
        pkg_key = query.data.replace("editval_pkg_", "")
        pkg = PACKAGES[pkg_key]
        data["clients"][uname]["subscriptions"][idx]["package_key"] = pkg_key
        data["clients"][uname]["subscriptions"][idx]["package_name"] = pkg["name"]
        data["clients"][uname]["subscriptions"][idx]["sessions_total"] = pkg["sessions"]
        data["clients"][uname]["subscriptions"][idx]["price"] = pkg["price"]
    elif query.data.startswith("editval_pay_"):
        pay = query.data.replace("editval_pay_", "")
        data["clients"][uname]["subscriptions"][idx]["payment"] = pay
    save(data)
    kb = [[InlineKeyboardButton("◀️ К клиенту", callback_data=f"client_view_{uname}")]]
    await query.edit_message_text("✅ Данные обновлены!", reply_markup=InlineKeyboardMarkup(kb))
    context.user_data.clear()
    return ConversationHandler.END

async def add_client_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["adding_client"] = {}
    context.user_data["from_training"] = query.data.startswith("training_newclient_")
    if context.user_data["from_training"]:
        day = query.data.replace("training_newclient_", "")
        context.user_data["training_day"] = day
    await query.edit_message_text("Введи *имя* клиента:", parse_mode="Markdown")
    return ADD_CLIENT_NAME

async def add_client_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["adding_client"]["name"] = update.message.text.strip()
    await update.message.reply_text("Введи *ник* в Telegram (без @):", parse_mode="Markdown")
    return ADD_CLIENT_USERNAME

async def add_client_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uname = update.message.text.strip().replace("@", "")
    context.user_data["adding_client"]["username"] = uname
    kb = [
        [InlineKeyboardButton("1️⃣ Разовое — 30₾", callback_data="pkg_1")],
        [InlineKeyboardButton("4️⃣ Абонемент 4 зан. — 110₾", callback_data="pkg_4")],
        [InlineKeyboardButton("8️⃣ Абонемент 8 зан. — 220₾", callback_data="pkg_8")],
    ]
    await update.message.reply_text("Выбери *абонемент*:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return ADD_CLIENT_PACKAGE

async def add_client_package(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pkg_key = query.data.replace("pkg_", "")
    context.user_data["adding_client"]["package"] = pkg_key
    kb = [
        [InlineKeyboardButton("💵 Наличные", callback_data="pay_cash")],
        [InlineKeyboardButton("💳 Перевод", callback_data="pay_transfer")],
    ]
    await query.edit_message_text("Способ *оплаты*:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return ADD_CLIENT_PAYMENT

async def add_client_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pay = query.data.replace("pay_", "")
    context.user_data["adding_client"]["payment"] = pay
    if pay == "transfer":
        await query.edit_message_text("📎 Прикрепи *фото чека*:", parse_mode="Markdown")
        return ADD_CLIENT_RECEIPT
    else:
        return await save_new_client(query, context)

async def add_client_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        context.user_data["adding_client"]["receipt_file_id"] = update.message.photo[-1].file_id
    return await save_new_client(update.message, context)

async def save_new_client(msg_or_query, context):
    d = context.user_data["adding_client"]
    data = load()
    uname = d["username"]
    pkg = PACKAGES[d["package"]]
    subscription = {
        "package_key": d["package"],
        "package_name": pkg["name"],
        "sessions_total": pkg["sessions"],
        "sessions_left": pkg["sessions"],
        "price": pkg["price"],
        "payment": d["payment"],
        "receipt_file_id": d.get("receipt_file_id"),
        "start_date": None,
        "end_date": None,
        "added_date": today_str()
    }
    if uname in data["clients"]:
        data["clients"][uname]["subscriptions"].append(subscription)
        data["clients"][uname]["is_temp"] = False
        if d.get("name"):
            data["clients"][uname]["name"] = d["name"]
    else:
        data["clients"][uname] = {
            "name": d.get("name", uname),
            "username": uname,
            "subscriptions": [subscription],
            "is_temp": False,
            "added_date": today_str()
        }
    if context.user_data.get("from_training") and context.user_data.get("training_day"):
        day = context.user_data["training_day"]
        wk = current_week_key()
        if day not in data["schedule"]:
            data["schedule"][day] = {"time": DAY_TIMES[day], "signups": {}}
        if wk not in data["schedule"][day].get("signups", {}):
            data["schedule"][day]["signups"][wk] = {}
        if uname not in data["schedule"][day]["signups"][wk]:
            data["schedule"][day]["signups"][wk][uname] = {"status": "signed"}
    save(data)
    text = f"✅ Клиент *{data['clients'][uname]['name']}* (@{uname}) добавлен!"
    kb = [[InlineKeyboardButton("◀️ К клиентам", callback_data="menu_clients"),
           InlineKeyboardButton("🏠 Меню", callback_data="main_menu")]]
    if hasattr(msg_or_query, 'edit_message_text'):
        await msg_or_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else:
        await msg_or_query.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    context.user_data.clear()
    return ConversationHandler.END

async def addsub_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uname = query.data.replace("addsub_", "")
    context.user_data["addsub_username"] = uname
    kb = [
        [InlineKeyboardButton("1️⃣ Разовое — 30₾", callback_data="subpkg_1")],
        [InlineKeyboardButton("4️⃣ Абонемент 4 зан. — 110₾", callback_data="subpkg_4")],
        [InlineKeyboardButton("8️⃣ Абонемент 8 зан. — 220₾", callback_data="subpkg_8")],
    ]
    await query.edit_message_text("Выбери *абонемент*:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return ADD_SUB_PACKAGE

async def addsub_package(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pkg_key = query.data.replace("subpkg_", "")
    context.user_data["addsub_package"] = pkg_key
    kb = [
        [InlineKeyboardButton("💵 Наличные", callback_data="subpay_cash")],
        [InlineKeyboardButton("💳 Перевод", callback_data="subpay_transfer")],
    ]
    await query.edit_message_text("Способ *оплаты*:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return ADD_SUB_PAYMENT

async def addsub_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pay = query.data.replace("subpay_", "")
    context.user_data["addsub_payment"] = pay
    if pay == "transfer":
        await query.edit_message_text("📎 Прикрепи *фото чека*:", parse_mode="Markdown")
        return ADD_SUB_RECEIPT
    else:
        return await save_subscription(query, context)

async def addsub_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        context.user_data["addsub_receipt"] = update.message.photo[-1].file_id
    return await save_subscription(update.message, context)

async def save_subscription(msg_or_query, context):
    uname = context.user_data["addsub_username"]
    pkg_key = context.user_data["addsub_package"]
    pay = context.user_data["addsub_payment"]
    pkg = PACKAGES[pkg_key]
    data = load()
    subscription = {
        "package_key": pkg_key,
        "package_name": pkg["name"],
        "sessions_total": pkg["sessions"],
        "sessions_left": pkg["sessions"],
        "price": pkg["price"],
        "payment": pay,
        "receipt_file_id": context.user_data.get("addsub_receipt"),
        "start_date": None,
        "end_date": None,
        "added_date": today_str()
    }
    data["clients"][uname]["subscriptions"].append(subscription)
    save(data)
    text = f"✅ Абонемент *{pkg['name']}* добавлен клиенту @{uname}!"
    kb = [[InlineKeyboardButton("◀️ К клиенту", callback_data=f"client_view_{uname}"),
           InlineKeyboardButton("🏠 Меню", callback_data="main_menu")]]
    if hasattr(msg_or_query, 'edit_message_text'):
        await msg_or_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else:
        await msg_or_query.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    context.user_data.clear()
    return ConversationHandler.END

async def show_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = load()
    wk = current_week_key()
    kb = []
    for day_key, day_name in DAY_NAMES.items():
        if day_key in data["schedule"]:
            time = data["schedule"][day_key]["time"]
            signups = data["schedule"][day_key].get("signups", {}).get(wk, {})
            count = len(signups)
            date = get_training_date(day_key)
            kb.append([InlineKeyboardButton(
                f"📅 {day_name} {date} {time} — {count} чел.",
                callback_data=f"training_{day_key}"
            )])
    kb.append([InlineKeyboardButton("⚙️ Изменить расписание", callback_data="edit_schedule")])
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="main_menu")])
    await query.edit_message_text("📅 *Расписание*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def show_training(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    day_key = query.data.replace("training_", "")
    if "_" in day_key:
        day_key = day_key.split("_")[0]
    data = load()
    day = data["schedule"].get(day_key, {})
    wk = current_week_key()
    signups = day.get("signups", {}).get(wk, {})
    day_name = DAY_NAMES.get(day_key, day_key)
    time = day.get("time", "")
    date = get_training_date(day_key)
    text = f"📅 *{day_name} {date} {time}*\n\n"
    kb = []
    if not signups:
        text += "Никто не записался\n"
    else:
        for uname, info in signups.items():
            client = data["clients"].get(uname)
            status = info.get("status", "signed")
            if status == "attended": icon = "✅"
            elif status == "missed": icon = "❌"
            elif status == "cancelled": icon = "🚫"
            else: icon = "🔲"
            if client:
                name = client["name"]
                sub = get_active_sub(client)
                if client.get("is_temp"):
                    sub_info = "⚠️ Нет данных"
                elif not sub:
                    sub_info = "⚠️ Нет абонемента"
                else:
                    sub_info = f"{sub['sessions_left']} зан."
            else:
                name = uname
                sub_info = "⚠️ Нет данных"
            text += f"{icon} @{uname} ({name}) — {sub_info}\n"
            if status == "signed":
                kb.append([
                    InlineKeyboardButton(f"✅ {name}", callback_data=f"attend_yes_{day_key}_{uname}"),
                    InlineKeyboardButton("❌", callback_data=f"attend_no_{day_key}_{uname}"),
                    InlineKeyboardButton("🚫", callback_data=f"attend_cancel_{day_key}_{uname}"),
                ])
    kb.append([InlineKeyboardButton("✏️ Редактировать тренировку", callback_data=f"edit_training_{day_key}")])
    kb.append([InlineKeyboardButton("➕ Записать клиента", callback_data=f"training_addsignup_{day_key}")])
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="menu_schedule")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def edit_training(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    day_key = query.data.replace("edit_training_", "")
    data = load()
    wk = current_week_key()
    signups = data["schedule"].get(day_key, {}).get("signups", {}).get(wk, {})
    day_name = DAY_NAMES.get(day_key, day_key)
    date = get_training_date(day_key)
    kb = []
    for uname, info in signups.items():
        client = data["clients"].get(uname)
        name = client["name"] if client else uname
        status = info.get("status", "signed")
        if status == "attended": icon = "✅"
        elif status == "missed": icon = "❌"
        elif status == "cancelled": icon = "🚫"
        else: icon = "🔲"
        kb.append([InlineKeyboardButton(
            f"{icon} {name} @{uname}",
            callback_data=f"editstatus_{day_key}_{uname}"
        )])
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data=f"training_{day_key}")])
    await query.edit_message_text(
        f"✏️ *Редактировать тренировку*\n{day_name} {date}\n\nВыбери клиента:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )

async def edit_status_choose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.replace("editstatus_", "").split("_")
    day_key = parts[0]
    uname = parts[1]
    context.user_data["editstatus_day"] = day_key
    context.user_data["editstatus_uname"] = uname
    data = load()
    client = data["clients"].get(uname)
    name = client["name"] if client else uname
    wk = current_week_key()
    current = data["schedule"][day_key]["signups"][wk][uname].get("status", "signed")
    icons = {"attended": "✅ Пришла", "missed": "❌ Не пришла", "cancelled": "🚫 Отменила", "signed": "🔲 Записана"}
    kb = [
        [InlineKeyboardButton("✅ Пришла", callback_data="setstatus_attended")],
        [InlineKeyboardButton("❌ Не пришла", callback_data="setstatus_missed")],
        [InlineKeyboardButton("🚫 Отменила", callback_data="setstatus_cancelled")],
        [InlineKeyboardButton("◀️ Назад", callback_data=f"edit_training_{day_key}")],
    ]
    await query.edit_message_text(
        f"Изменить статус *{name}*?\nСейчас: {icons.get(current, current)}",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )

async def set_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    new_status = query.data.replace("setstatus_", "")
    day_key = context.user_data["editstatus_day"]
    uname = context.user_data["editstatus_uname"]
    data = load()
    wk = current_week_key()
    old_status = data["schedule"][day_key]["signups"][wk][uname].get("status", "signed")
    client = data["clients"].get(uname)
    if client and client.get("subscriptions"):
        all_subs = client["subscriptions"]
        last_sub_idx = len(all_subs) - 1
        if old_status in ["attended", "missed"] and new_status in ["cancelled", "signed"]:
            if last_sub_idx >= 0:
                data["clients"][uname]["subscriptions"][last_sub_idx]["sessions_left"] += 1
            data["sessions_log"] = [
                s for s in data.get("sessions_log", [])
                if not (s["username"] == uname and s["day"] == day_key and s["date"] == today_str())
            ]
        elif old_status in ["cancelled", "signed"] and new_status in ["attended", "missed"]:
            sub = get_active_sub(client)
            if sub:
                idx = next(i for i, s in enumerate(client["subscriptions"]) if s is sub)
                if not data["clients"][uname]["subscriptions"][idx]["start_date"]:
                    data["clients"][uname]["subscriptions"][idx]["start_date"] = today_str()
                    end = datetime.now() + timedelta(days=30)
                    data["clients"][uname]["subscriptions"][idx]["end_date"] = end.strftime("%d.%m.%Y")
                data["clients"][uname]["subscriptions"][idx]["sessions_left"] -= 1
                data["sessions_log"].append({"date": today_str(), "username": uname, "day": day_key})
    data["schedule"][day_key]["signups"][wk][uname]["status"] = new_status
    save(data)
    query.data = f"training_{day_key}"
    await show_training(update, context)

async def attend_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    action = parts[1]
    day_key = parts[2]
    uname = parts[3]
    data = load()
    wk = current_week_key()
    client = data["clients"].get(uname)
    if action == "yes":
        sub = get_active_sub(client) if client else None
        if not sub and client and not client.get("is_temp"):
            context.user_data["take_payment_uname"] = uname
            context.user_data["take_payment_day"] = day_key
            kb = [
                [InlineKeyboardButton("1️⃣ Разовое — 30₾", callback_data="takepkg_1")],
                [InlineKeyboardButton("4️⃣ Абонемент 4 зан. — 110₾", callback_data="takepkg_4")],
                [InlineKeyboardButton("8️⃣ Абонемент 8 зан. — 220₾", callback_data="takepkg_8")],
                [InlineKeyboardButton("◀️ Назад", callback_data=f"training_{day_key}")],
            ]
            await query.edit_message_text(
                f"💳 *Взять оплату за занятие*\n@{uname}\n\nВыбери абонемент:",
                reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown"
            )
            return TAKE_PAYMENT_PACKAGE
        else:
            data["schedule"][day_key]["signups"][wk][uname]["status"] = "attended"
            if sub:
                sub_idx = next(i for i, s in enumerate(client["subscriptions"]) if s is sub)
                if not data["clients"][uname]["subscriptions"][sub_idx]["start_date"]:
                    data["clients"][uname]["subscriptions"][sub_idx]["start_date"] = today_str()
                    end = datetime.now() + timedelta(days=30)
                    data["clients"][uname]["subscriptions"][sub_idx]["end_date"] = end.strftime("%d.%m.%Y")
                data["clients"][uname]["subscriptions"][sub_idx]["sessions_left"] -= 1
            data["sessions_log"].append({"date": today_str(), "username": uname, "day": day_key})
    elif action == "no":
        data["schedule"][day_key]["signups"][wk][uname]["status"] = "missed"
        if client:
            sub = get_active_sub(client)
            if sub:
                sub_idx = next(i for i, s in enumerate(client["subscriptions"]) if s is sub)
                if not data["clients"][uname]["subscriptions"][sub_idx]["start_date"]:
                    data["clients"][uname]["subscriptions"][sub_idx]["start_date"] = today_str()
                    end = datetime.now() + timedelta(days=30)
                    data["clients"][uname]["subscriptions"][sub_idx]["end_date"] = end.strftime("%d.%m.%Y")
                data["clients"][uname]["subscriptions"][sub_idx]["sessions_left"] -= 1
        data["sessions_log"].append({"date": today_str(), "username": uname, "day": day_key})
    elif action == "cancel":
        data["schedule"][day_key]["signups"][wk][uname]["status"] = "cancelled"
    save(data)
    query.data = f"training_{day_key}"
    await show_training(update, context)

async def take_payment_package(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pkg_key = query.data.replace("takepkg_", "")
    context.user_data["take_payment_pkg"] = pkg_key
    kb = [
        [InlineKeyboardButton("💵 Наличные", callback_data="takepay_cash")],
        [InlineKeyboardButton("💳 Перевод", callback_data="takepay_transfer")],
    ]
    await query.edit_message_text("Способ *оплаты*:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    return TAKE_PAYMENT_METHOD

async def take_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pay = query.data.replace("takepay_", "")
    context.user_data["take_payment_pay"] = pay
    if pay == "transfer":
        await query.edit_message_text("📎 Прикрепи *фото чека*:", parse_mode="Markdown")
        return TAKE_PAYMENT_RECEIPT
    else:
        return await save_take_payment(query, context)

async def take_payment_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        context.user_data["take_payment_receipt"] = update.message.photo[-1].file_id
    return await save_take_payment(update.message, context)

async def save_take_payment(msg_or_query, context):
    uname = context.user_data["take_payment_uname"]
    day_key = context.user_data["take_payment_day"]
    pkg_key = context.user_data["take_payment_pkg"]
    pay = context.user_data["take_payment_pay"]
    pkg = PACKAGES[pkg_key]
    data = load()
    wk = current_week_key()
    subscription = {
        "package_key": pkg_key,
        "package_name": pkg["name"],
        "sessions_total": pkg["sessions"],
        "sessions_left": pkg["sessions"] - 1,
        "price": pkg["price"],
        "payment": pay,
        "receipt_file_id": context.user_data.get("take_payment_receipt"),
        "start_date": today_str(),
        "end_date": (datetime.now() + timedelta(days=30)).strftime("%d.%m.%Y"),
        "added_date": today_str()
    }
    data["clients"][uname]["subscriptions"].append(subscription)
    data["schedule"][day_key]["signups"][wk][uname]["status"] = "attended"
    data["sessions_log"].append({"date": today_str(), "username": uname, "day": day_key})
    save(data)
    text = f"✅ Оплата принята! Абонемент *{pkg['name']}* добавлен @{uname}. Занятие списано."
    kb = [[InlineKeyboardButton("◀️ К тренировке", callback_data=f"training_{day_key}")]]
    if hasattr(msg_or_query, 'edit_message_text'):
        await msg_or_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else:
        await msg_or_query.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    context.user_data.clear()
    return ConversationHandler.END

async def training_addsignup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    day_key = query.data.replace("training_addsignup_", "")
    kb = [
        [InlineKeyboardButton("👤 Существующий клиент", callback_data=f"training_existing_{day_key}")],
        [InlineKeyboardButton("🆕 Новый клиент", callback_data=f"training_newclient_{day_key}")],
        [InlineKeyboardButton("◀️ Назад", callback_data=f"training_{day_key}")],
    ]
    await query.edit_message_text("Кого записать?", reply_markup=InlineKeyboardMarkup(kb))

async def training_existing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    day_key = query.data.replace("training_existing_", "")
    data = load()
    wk = current_week_key()
    already = data["schedule"].get(day_key, {}).get("signups", {}).get(wk, {})
    kb = []
    for uname, c in data["clients"].items():
        if uname not in already:
            kb.append([InlineKeyboardButton(
                f"{c['name']} @{uname}",
                callback_data=f"dosignup_{day_key}_{uname}"
            )])
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data=f"training_{day_key}")])
    await query.edit_message_text("Выбери клиента:", reply_markup=InlineKeyboardMarkup(kb))

async def do_signup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.replace("dosignup_", "").split("_")
    day_key = parts[0]
    uname = parts[1]
    data = load()
    wk = current_week_key()
    if wk not in data["schedule"][day_key].get("signups", {}):
        data["schedule"][day_key]["signups"][wk] = {}
    data["schedule"][day_key]["signups"][wk][uname] = {"status": "signed"}
    save(data)
    query.data = f"training_{day_key}"
    await show_training(update, context)

async def edit_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = load()
    kb = [[InlineKeyboardButton("➕ Добавить тренировку", callback_data="sched_add")]]
    for day_key in data["schedule"]:
        name = DAY_NAMES.get(day_key, day_key)
        time = data["schedule"][day_key]["time"]
        kb.append([
            InlineKeyboardButton(f"✏️ {name} {time}", callback_data=f"sched_edit_{day_key}"),
            InlineKeyboardButton("🗑 Удалить", callback_data=f"sched_del_{day_key}"),
        ])
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="menu_schedule")])
    await query.edit_message_text("⚙️ *Изменить расписание*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def show_finance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = [
        [InlineKeyboardButton("📉 Издержки", callback_data="finance_expenses")],
        [InlineKeyboardButton("📈 Прибыль", callback_data="finance_profit")],
        [InlineKeyboardButton("📊 Статистика", callback_data="finance_stats")],
        [InlineKeyboardButton("◀️ Назад", callback_data="main_menu")],
    ]
    await query.edit_message_text("💰 *Бухгалтерия*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

def get_period(context):
    if context.user_data.get("custom_period"):
        return context.user_data["period_from"], context.user_data["period_to"]
    now = datetime.now()
    start = datetime(now.year, now.month, 1)
    end = datetime(now.year, now.month, monthrange(now.year, now.month)[1], 23, 59, 59)
    return start, end

async def show_expenses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if "current" in query.data:
        context.user_data.pop("custom_period", None)
    data = load()
    start, end = get_period(context)
    expenses = [e for e in data["expenses"]
                if start <= datetime.strptime(e["date"], "%d.%m.%Y") <= end]
    total = sum(e["amount"] for e in expenses)
    period_label = f"{start.strftime('%d.%m')}–{end.strftime('%d.%m.%Y')}"
    text = f"📉 *Издержки* ({period_label})\n\n"
    if expenses:
        for e in expenses:
            text += f"{e['date']} | {e['category']} | {e['amount']}₾\n"
        text += f"\n*Итого: {total}₾*"
    else:
        text += "Расходов нет"
    kb = [
        [InlineKeyboardButton("➕ Добавить расход", callback_data="add_expense")],
        [InlineKeyboardButton("📅 Текущий месяц", callback_data="expenses_current"),
         InlineKeyboardButton("🗓 Выбрать период", callback_data="period_custom_expenses")],
        [InlineKeyboardButton("◀️ Назад", callback_data="menu_finance")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def show_profit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if "current" in query.data:
        context.user_data.pop("custom_period", None)
    data = load()
    start, end = get_period(context)
    revenue = 0
    for c in data["clients"].values():
        for sub in c.get("subscriptions", []):
            added = sub.get("added_date")
            if added:
                try:
                    d = datetime.strptime(added, "%d.%m.%Y")
                    if start <= d <= end:
                        revenue += sub["price"]
                except:
                    pass
    expenses_total = sum(
        e["amount"] for e in data["expenses"]
        if start <= datetime.strptime(e["date"], "%d.%m.%Y") <= end
    )
    profit = revenue - expenses_total
    period_label = f"{start.strftime('%d.%m')}–{end.strftime('%d.%m.%Y')}"
    text = (
        f"📈 *Прибыль* ({period_label})\n\n"
        f"💵 Выручка: *{revenue}₾*\n"
        f"📉 Издержки: *{expenses_total}₾*\n"
        f"──────────────\n"
        f"✅ Чистая прибыль: *{profit}₾*"
    )
    kb = [
        [InlineKeyboardButton("📅 Текущий месяц", callback_data="profit_current"),
         InlineKeyboardButton("🗓 Выбрать период", callback_data="period_custom_profit")],
        [InlineKeyboardButton("◀️ Назад", callback_data="menu_finance")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if "current" in query.data:
        context.user_data.pop("custom_period", None)
    data = load()
    start, end = get_period(context)
    count_1 = count_4 = count_8 = 0
    for c in data["clients"].values():
        for sub in c.get("subscriptions", []):
            added = sub.get("added_date")
            if added:
                try:
                    d = datetime.strptime(added, "%d.%m.%Y")
                    if start <= d <= end:
                        k = sub["package_key"]
                        if k == "1": count_1 += 1
                        elif k == "4": count_4 += 1
                        elif k == "8": count_8 += 1
                except:
                    pass
    total_subs = count_1 + count_4 + count_8
    visits = [s for s in data.get("sessions_log", [])
              if start <= datetime.strptime(s["date"], "%d.%m.%Y") <= end]
    total_visits = len(visits)
    unique_clients = len(set(s["username"] for s in visits))
    trainings_in_period = 0
    for day_key, day in data["schedule"].items():
        for wk, signups in day.get("signups", {}).items():
            try:
                wdate = datetime.strptime(wk, "%d.%m.%Y")
                if start <= wdate <= end:
                    attended = sum(1 for v in signups.values() if v.get("status") == "attended")
                    if attended > 0:
                        trainings_in_period += 1
            except:
                pass
    avg = round(total_visits / trainings_in_period, 1) if trainings_in_period > 0 else 0
    period_label = f"{start.strftime('%d.%m')}–{end.strftime('%d.%m.%Y')}"
    text = (
        f"📊 *Статистика* ({period_label})\n\n"
        f"🎫 Куплено абонементов: *{total_subs}*\n"
        f"  • Разовых: {count_1}\n"
        f"  • Абонементов 4 занятия: {count_4}\n"
        f"  • Абонементов 8 занятий: {count_8}\n\n"
        f"📍 Всего визитов: *{total_visits}*\n"
        f"👥 Уникальных клиентов: *{unique_clients}*\n"
        f"📈 Средняя посещаемость на тренировку: *{avg} чел.*"
    )
    kb = [
        [InlineKeyboardButton("📅 Текущий месяц", callback_data="stats_current"),
         InlineKeyboardButton("🗓 Выбрать период", callback_data="period_custom_stats")],
        [InlineKeyboardButton("◀️ Назад", callback_data="menu_finance")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def add_expense_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Введи *сумму* расхода (например: 500):", parse_mode="Markdown")
    return ADD_EXPENSE_AMOUNT

async def add_expense_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip().replace(",", "."))
        context.user_data["expense_amount"] = amount
        await update.message.reply_text("Введи *категорию* (например: Аренда зала):", parse_mode="Markdown")
        return ADD_EXPENSE_CATEGORY
    except ValueError:
        await update.message.reply_text("Введи число, например: 500")
        return ADD_EXPENSE_AMOUNT

async def add_expense_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    category = update.message.text.strip()
    data = load()
    data["expenses"].append({
        "date": today_str(),
        "category": category,
        "amount": context.user_data["expense_amount"]
    })
    save(data)
    kb = [[InlineKeyboardButton("◀️ К издержкам", callback_data="finance_expenses"),
           InlineKeyboardButton("🏠 Меню", callback_data="main_menu")]]
    await update.message.reply_text(
        f"✅ Расход добавлен: {category} — {context.user_data['expense_amount']}₾",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    context.user_data.clear()
    return ConversationHandler.END

async def group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ["group", "supergroup"]:
        return
    msg = update.message
    if not msg or not msg.text:
        return
    text_lower = msg.text.lower()
    username = msg.from_user.username or str(msg.from_user.id)
    if any(kw in text_lower for kw in CANCEL_KEYWORDS):
        return
    if not any(kw in text_lower for kw in SIGNUP_KEYWORDS):
        return
    has_tuesday = "вторник" in text_lower
    has_thursday = "четверг" in text_lower
    if has_tuesday and not has_thursday:
        day_key = "tuesday"
    elif has_thursday and not has_tuesday:
        day_key = "thursday"
    else:
        day_key = next_training_day()
    data = load()
    wk = current_week_key()
    if day_key not in data["schedule"]:
        return
    if wk not in data["schedule"][day_key].get("signups", {}):
        data["schedule"][day_key]["signups"][wk] = {}
    if username in data["schedule"][day_key]["signups"][wk]:
        return
    data["schedule"][day_key]["signups"][wk][username] = {"status": "signed"}
    if username not in data["clients"]:
        data["clients"][username] = {
            "name": msg.from_user.first_name or username,
            "username": username,
            "subscriptions": [],
            "is_temp": True,
            "added_date": today_str()
        }
    save(data)
    day_name = DAY_NAMES.get(day_key, day_key)
    date = get_training_date(day_key)
    time = data["schedule"][day_key]["time"]
    await msg.reply_text(f"✅ @{username}, записала тебя на {day_name} {date} в {time}!")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Отменено.")
    return ConversationHandler.END

def main():
    app = Application.builder().token(TOKEN).build()
    add_client_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(add_client_start, pattern="^client_add$"),
            CallbackQueryHandler(add_client_start, pattern="^training_newclient_"),
        ],
        states={
            ADD_CLIENT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_client_name)],
            ADD_CLIENT_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_client_username)],
            ADD_CLIENT_PACKAGE: [CallbackQueryHandler(add_client_package, pattern="^pkg_")],
            ADD_CLIENT_PAYMENT: [CallbackQueryHandler(add_client_payment, pattern="^pay_")],
            ADD_CLIENT_RECEIPT: [MessageHandler(filters.PHOTO | filters.TEXT, add_client_receipt)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )
    add_sub_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(addsub_start, pattern="^addsub_")],
        states={
            ADD_SUB_PACKAGE: [CallbackQueryHandler(addsub_package, pattern="^subpkg_")],
            ADD_SUB_PAYMENT: [CallbackQueryHandler(addsub_payment, pattern="^subpay_")],
            ADD_SUB_RECEIPT: [MessageHandler(filters.PHOTO | filters.TEXT, addsub_receipt)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )
    edit_client_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_client_menu, pattern="^edit_client_")],
        states={
            EDIT_CLIENT_FIELD: [CallbackQueryHandler(edit_field_start, pattern="^editfield_")],
            EDIT_CLIENT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_client_value)],
            EDIT_SUB_FIELD: [CallbackQueryHandler(edit_sub_field, pattern="^editval_")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )
    add_expense_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_expense_start, pattern="^add_expense$")],
        states={
            ADD_EXPENSE_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_expense_amount)],
            ADD_EXPENSE_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_expense_category)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )
    take_payment_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(take_payment_package, pattern="^takepkg_")],
        states={
            TAKE_PAYMENT_PACKAGE: [CallbackQueryHandler(take_payment_package, pattern="^takepkg_")],
            TAKE_PAYMENT_METHOD: [CallbackQueryHandler(take_payment_method, pattern="^takepay_")],
            TAKE_PAYMENT_RECEIPT: [MessageHandler(filters.PHOTO | filters.TEXT, take_payment_receipt)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", start))
    app.add_handler(add_client_conv)
    app.add_handler(add_sub_conv)
    app.add_handler(edit_client_conv)
    app.add_handler(add_expense_conv)
    app.add_handler(take_payment_conv)
    app.add_handler(CallbackQueryHandler(start, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(show_clients, pattern="^menu_clients$"))
    app.add_handler(CallbackQueryHandler(view_client, pattern="^client_view_"))
    app.add_handler(CallbackQueryHandler(show_schedule, pattern="^menu_schedule$"))
    app.add_handler(CallbackQueryHandler(show_training, pattern="^training_(tuesday|thursday)$"))
    app.add_handler(CallbackQueryHandler(attend_handler, pattern="^attend_"))
    app.add_handler(CallbackQueryHandler(edit_training, pattern="^edit_training_"))
    app.add_handler(CallbackQueryHandler(edit_status_choose, pattern="^editstatus_"))
    app.add_handler(CallbackQueryHandler(set_status, pattern="^setstatus_"))
    app.add_handler(CallbackQueryHandler(training_addsignup, pattern="^training_addsignup_"))
    app.add_handler(CallbackQueryHandler(training_existing, pattern="^training_existing_"))
    app.add_handler(CallbackQueryHandler(do_signup, pattern="^dosignup_"))
    app.add_handler(CallbackQueryHandler(edit_schedule, pattern="^edit_schedule$"))
    app.add_handler(CallbackQueryHandler(show_finance, pattern="^menu_finance$"))
    app.add_handler(CallbackQueryHandler(show_expenses, pattern="^finance_expenses$|^expenses_current$"))
    app.add_handler(CallbackQueryHandler(show_profit, pattern="^finance_profit$|^profit_current$"))
    app.add_handler(CallbackQueryHandler(show_stats, pattern="^finance_stats$|^stats_current$"))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS,
        group_message
    ))
    app.run_polling()

if __name__ == "__main__":
    main()


