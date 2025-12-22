# main.py
import logging
import asyncio
import datetime
import jdatetime
import pytz

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    Application, CommandHandler, ContextTypes, ConversationHandler,
    MessageHandler, CallbackQueryHandler, filters
)

from db import init_db, SessionLocal
from models import User, Loan, Installment
from logic import calculate_amortization
from calendar_helper import build_month_keyboard
from config import BOT_TOKEN, TIMEZONE , ADMIN_CHAT_ID

# backup service (make sure backup_service.py exists and is configured to use loans.db and backup.db)
import backup_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Conversation states
(ADD_BANK, ADD_PRINCIPAL, ADD_RATE, ADD_TERM, ADD_CALENDAR, ADD_REMINDER, ADD_PREV_PAID, DELETE_SELECT) = range(8)

# Backup interval in hours (fixed)
BACKUP_INTERVAL_HOURS = 6  # every 6 hours

# Helpers
def get_session():
    return SessionLocal()

def jalali_to_gregorian_date(jalali_str):
    # jalali_str like "1403-08-25"
    y, m, d = [int(x) for x in jalali_str.split("-")]
    jdate = jdatetime.date(y, m, d)
    gdate = jdate.togregorian()
    return gdate  # datetime.date

def format_currency(n):
    return f"{n:,.2f}"


def get_local_today():
    tz = pytz.timezone(TIMEZONE)
    return datetime.datetime.now(tz).date()


def due_range_label(days: int) -> str:
    mapping = {
        1: "۱ روز آینده",
        3: "۳ روز آینده",
        7: "۷ روز آینده",
    }
    return mapping.get(days, f"{days} روز آینده")

def main_reply_keyboard():
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton("➕ افزودن وام جدید"),
                KeyboardButton("💼 وام‌های من"),
            ],
            [KeyboardButton("📅 سررسیدهای نزدیک"),
             KeyboardButton("🗑️ حذف وام"),
            ],
            
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        selective=False,
    )

#sned_messege_to_admin
async def notify_admin_new_user(context, user):
    """
    ارسال پیام به ADMIN_CHAT_ID درباره کاربر جدید.
    context: ContextTypes.DEFAULT_TYPE (از داخل هندلرها pass می‌کنیم)
    user: شیء User (SQLAlchemy) که تازه ساخته شده
    """
    if not ADMIN_CHAT_ID:
        return

    try:
        # ساخت متن اطلاع‌رسانی
        name = user.name or "نام‌ناشناس"
        chat_id = user.chat_id
        # زمان محلی
        from config import TIMEZONE
        import pytz, datetime
        tz = pytz.timezone(TIMEZONE)
        now_local = datetime.datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

        text = (
            f"🔔 کاربر جدید وارد شد!\n"
            f"👤 نام: {name}\n"
            f"🆔 Chat ID: {chat_id}\n"
            f"⏱ زمان (local): {now_local}"
        )

        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=text)
    except Exception as e:
        # لاگ کن ولی خطا را بالا نیاور
        logger.exception("Failed to notify admin about new user: %s", e)
        return

def main_menu_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن وام جدید", callback_data="menu|add")],
        [InlineKeyboardButton("💼 وام‌های من", callback_data="menu|myloans")],
        [InlineKeyboardButton("📅 سررسیدهای نزدیک", callback_data="menu|due")],
        [InlineKeyboardButton("ℹ️ راهنما", callback_data="menu|help")],
        [InlineKeyboardButton("🗑️ حذف وام", callback_data="menu|delete")],
    ])


def due_range_markup():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1 روز آینده", callback_data="due|1"),
            InlineKeyboardButton("3 روز آینده", callback_data="due|3"),
            InlineKeyboardButton("7 روز آینده", callback_data="due|7"),
        ],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="menu|home")],
    ])

# Handlers
# async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     chat_id = update.effective_chat.id
#     session = get_session()
#     user = session.query(User).filter_by(chat_id=chat_id).first()
#     if not user:
#         user = User(chat_id=chat_id, name=update.effective_user.first_name or "User")
#         session.add(user)
#         session.commit()
#     await update.message.reply_text(
#         "سلام! خوش اومدی 👋\nاز دکمه‌های پایین برای افزودن یا مشاهده وام استفاده کن.",
#         reply_markup=main_reply_keyboard()
#     )
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = get_session()
    user = session.query(User).filter_by(chat_id=chat_id).first()
    if not user:
        # کاربر جدید: ایجاد رکورد
        user = User(chat_id=chat_id, name=update.effective_user.first_name or "User")
        session.add(user)
        session.commit()
        # اطلاع‌رسانی به ادمین (غیر بلاک‌کننده)
        try:
            # اگر context در دسترس است، از تابع async استفاده کن
            await notify_admin_new_user(context, user)
        except Exception:
            # اطمینان از اینکه خطا ارسال پیام به ادمین باعث قطع ادامه نشود
            logger.exception("Error while notifying admin about new user")
    # اگر کاربر قبلا وجود داشته، کاری انجام نده (مثل قبلا بود)
    await update.message.reply_text(
        "سلام! خوش اومدی 👋\nاز دکمه‌های پایین برای افزودن یا مشاهده وام استفاده کن.",
        reply_markup=main_reply_keyboard()
    )
    session.close()


async def addloan_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    if getattr(update, "callback_query", None):
        try:
            await update.callback_query.edit_message_text("❌ فرآیند ثبت وام لغو شد.")
        except:
            pass
    else:
        await update.message.reply_text("❌ فرآیند ثبت وام لغو شد.", reply_markup=main_reply_keyboard())
    return ConversationHandler.END

# Add loan conversation
async def addloan_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Support both /addloan (message) and inline button (callback query)
    if getattr(update, "callback_query", None):
        query = update.callback_query
        await query.answer()
        context.user_data.clear()
        # ارسال پیام جدید به‌جای ادیت، تا محدودیت‌های ادیت مزاحم نشوند
        await query.message.reply_text("نام بانک را وارد کنید: \n(برای لغو، /cancel را بزنید) ")
    else:
        context.user_data.clear()
        await update.message.reply_text("نام بانک را وارد کنید: \n(برای لغو، /cancel را بزنید) ")
    return ADD_BANK

async def addloan_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['bank'] = update.message.text.strip()
    await update.message.reply_text("مبلغ اصل وام (اعداد فقط، بدون ویرگول): \n(برای لغو، /cancel را بزنید) ")
    return ADD_PRINCIPAL

async def addloan_principal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['principal'] = float(update.message.text.strip())
    except:
        await update.message.reply_text("مبلغ نامعتبر است، لطفاً فقط عدد وارد کنید. \n(برای لغو، /cancel را بزنید)")
        return ADD_PRINCIPAL
    await update.message.reply_text("نرخ بهره سالانه (مثلاً 18.5): \n(برای لغو، /cancel را بزنید)")
    return ADD_RATE

async def addloan_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['rate'] = float(update.message.text.strip())
    except:
        await update.message.reply_text("نرخ نامعتبر است، دوباره وارد کن.\n(برای لغو، /cancel را بزنید)")
        return ADD_RATE
    await update.message.reply_text("مدت وام به ماه (مثلاً 36):\n(برای لغو، /cancel را بزنید)")
    return ADD_TERM

async def addloan_term(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['term'] = int(update.message.text.strip())
    except:
        await update.message.reply_text("مدت نامعتبر است، عدد ماه وارد کن.\n(برای لغو، /cancel را بزنید)")
        return ADD_TERM

    # show initial jalali month keyboard for selection
    now_j = jdatetime.date.today()
    kb = build_month_keyboard(now_j.year, now_j.month, prefix="cal")
    await update.message.reply_text("تاریخ اولین پرداخت را از تقویم زیر انتخاب کن (شمسی):\n(برای لغو، /cancel را بزنید)", reply_markup=kb)
    return ADD_CALENDAR

# calendar callbacks
async def calendar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data  # e.g., cal|day|1403-08-25 or cal|prev|1403-08
    if data == "noop":
        return
    parts = data.split("|")
    prefix = parts[0]
    if parts[1] == "cancel":
        await query.edit_message_text("ثبت وام لغو شد.")
        return ConversationHandler.END
    if parts[1] == "prev" or parts[1] == "next":
        _, dir_, ym = parts
        y, m = [int(x) for x in ym.split("-")]
        if dir_ == "prev":
            if m == 1:
                y -= 1; m = 12
            else:
                m -= 1
        else:
            if m == 12:
                y += 1; m = 1
            else:
                m += 1
        kb = build_month_keyboard(y, m, prefix="cal")
        await query.edit_message_reply_markup(kb)
        return
    if parts[1] == "day":
        jalali_date = parts[2]
        # save selected date in user_data
        context.user_data['first_payment_jalali'] = jalali_date
        # Ask for reminder days (1/2/3)
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("1 روز قبل", callback_data="rem|1"),
             InlineKeyboardButton("2 روز قبل", callback_data="rem|2"),
             InlineKeyboardButton("3 روز قبل", callback_data="rem|3")]
        ])
        await query.edit_message_text(
            f"📅 تاریخ اولین قسط ثبت شد: {jalali_date}\n\n"
            f"الان انتخاب کن چند روز قبل از سررسید قسط، ربات بهت پیام یادآوری بده 👇",
            reply_markup=markup
        )
        return

# reminder callback (from inline keyboard after calendar)
async def reminder_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    days = int(query.data.split("|")[1])
    context.user_data['reminder_days'] = days

    # مرحله جدید → سؤال درباره اقساط قبلی
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("بله، پرداخت‌شده در نظر بگیر", callback_data="prevpaid|yes"),
        ],
        [
            InlineKeyboardButton("خیر", callback_data="prevpaid|no"),
        ]
    ])

    await query.edit_message_text(
        "❓ آیا تا امروز تمام اقساط قبلی این وام را پرداخت کرده‌ای؟",
        reply_markup=keyboard
    )

    return ADD_PREV_PAID

async def prevpaid_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    choice = query.data.split("|")[1]

    session = get_session()
    chat_id = query.message.chat.id
    user = session.query(User).filter_by(chat_id=chat_id).first()

    # ساخت وام
    loan = Loan(
        user_id=user.id,
        bank=context.user_data['bank'],
        loan_name=context.user_data['bank'],
        principal=context.user_data['principal'],
        annual_interest_rate=context.user_data['rate'],
        term_months=context.user_data['term'],
        first_payment_date=jalali_to_gregorian_date(context.user_data['first_payment_jalali']),
        reminder_days_before=context.user_data['reminder_days']
    )
    session.add(loan)
    session.commit()

    # ساخت اقساط
    schedule = calculate_amortization(
        loan.principal,
        loan.annual_interest_rate,
        loan.term_months,
        loan.first_payment_date
    )

    for row in schedule:
        inst = Installment(
            loan_id=loan.id,
            sequence_number=row['installment'],
            due_date=row['due_date'],
            amount_total=row['payment'],
            amount_principal=row['principal'],
            amount_interest=row['interest'],
            is_paid=False
        )
        session.add(inst)
    session.commit()

    # اگر کاربر گفت اقساط قبلی پرداخت شده‌اند
    if choice == "yes":
        today = get_local_today()
        past_insts = session.query(Installment).filter(
            Installment.loan_id == loan.id,
            Installment.due_date < today
        ).all()

        for p in past_insts:
            p.is_paid = True
            p.paid_amount = p.amount_total
            p.paid_at = datetime.datetime.utcnow()

        session.commit()

    # پیام موفقیت
    text = (
        f"✅ وام با موفقیت ثبت شد!\n\n"
        f"بانک: {loan.bank}\n"
        f"اصل: {format_currency(loan.principal)}\n"
        f"نرخ سالیانه: {loan.annual_interest_rate}%\n"
        f"مدت: {loan.term_months} ماه\n"
        f"تاریخ اولین قسط (شمسی): {context.user_data['first_payment_jalali']}\n"
        f"یادآوری: {loan.reminder_days_before} روز قبل"
    )

    await query.edit_message_text(text, reply_markup=main_menu_markup())
    await context.bot.send_message(chat_id=chat_id, text="از منوی پایین ادامه بده 👇", reply_markup=main_reply_keyboard())

    session.close()
    return ConversationHandler.END

# Menu callback (after confirmation)
async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data  # menu|add or menu|myloans

    if data == "menu|myloans":
        await myloans_list(update, context)
        return ConversationHandler.END

    elif data == "menu|help":
        await query.edit_message_text(
            "برای ثبت وام جدید، دکمه «➕ افزودن وام جدید» رو بزن.\n"
            "برای دیدن وام‌ها، دکمه «💼 وام‌های من» رو انتخاب کن.\n"
            "در هر مرحله اگر به منوی اصلی برگشتی، دوباره از همین گزینه‌ها استفاده کن.",
            reply_markup=main_menu_markup()
        )
        await query.message.reply_text(
            "از دکمه‌های پایین هم می‌تونی استفاده کنی 👇",
            reply_markup=main_reply_keyboard()
        )
        return ConversationHandler.END

    elif data == "menu|due":
        await query.edit_message_text(
            "کدام بازه زمانی را می‌خواهی؟",
            reply_markup=due_range_markup()
        )
        return

    elif data == "menu|home":
        await query.edit_message_text(
            "یکی از گزینه‌های زیر را انتخاب کن:",
            reply_markup=main_menu_markup()
        )
        return ConversationHandler.END

    else:
        await query.message.reply_text("دستور ناشناخته.", reply_markup=main_reply_keyboard())

# Upcoming due date helpers
async def open_due_menu_from_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "کدام بازه زمانی را می‌خواهی؟",
        reply_markup=due_range_markup()
    )


def collect_upcoming_installments(session, user_id: int, days: int):
    today = get_local_today()
    end = today + datetime.timedelta(days=days)
    q = (
        session.query(Installment)
        .join(Loan)
        .filter(
            Loan.user_id == user_id,
            Installment.is_paid.is_(False),
            Installment.due_date >= today,
            Installment.due_date <= end,
        )
        .order_by(Installment.due_date.asc(), Installment.sequence_number.asc())
    )
    return q.all()


async def due_range_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|")
    try:
        days = int(parts[1])
    except (IndexError, ValueError):
        await query.edit_message_text("بازه نامعتبر است. دوباره انتخاب کن.", reply_markup=due_range_markup())
        return

    session = get_session()
    try:
        user = session.query(User).filter_by(chat_id=query.message.chat.id).first()
        if not user:
            await query.edit_message_text("ابتدا /start را اجرا کن تا ثبت‌نام شوی.", reply_markup=main_menu_markup())
            return

        installments = collect_upcoming_installments(session, user.id, days)
        label = due_range_label(days)
        if not installments:
            text = f"⏰ در بازه {label} هیچ قسط سررسیدی نداری."
        else:
            lines = [f"⏰ سررسیدهای {label}:"]
            for inst in installments:
                jd = jdatetime.date.fromgregorian(date=inst.due_date)
                loan = inst.loan
                lines.append(
                    f"• {jd.year}/{jd.month}/{jd.day} — وام #{loan.id} ({loan.bank})\n"
                    f"  قسط {inst.sequence_number}: {format_currency(inst.amount_total)} تومان"
                )
            text = "\n".join(lines)

        await query.edit_message_text(text, reply_markup=due_range_markup())
    finally:
        session.close()
#delete_loan
async def delete_loan_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_session()
    chat_id = update.effective_chat.id
    user = session.query(User).filter_by(chat_id=chat_id).first()

    if not user:
        await update.message.reply_text("اول /start را بزن.", reply_markup=main_reply_keyboard())
        return

    loans = session.query(Loan).filter_by(user_id=user.id).all()
    if not loans:
        await update.message.reply_text("هیچ وامی برای حذف وجود ندارد.", reply_markup=main_reply_keyboard())
        return

    # ساخت دکمه‌های انتخاب وام
    keyboard = []
    for loan in loans:
        display = loan.loan_name or loan.bank or f"وام #{loan.id}"
        keyboard.append([InlineKeyboardButton(f"حذف {display}", callback_data=f"delete|select|{loan.id}")])

    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu|home")])

    await update.message.reply_text("کدام وام را می‌خواهی حذف کنی؟", reply_markup=InlineKeyboardMarkup(keyboard))



# myloans command / handler
async def myloans_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query if getattr(update, "callback_query", None) else None
    if query:
        await query.answer()
        chat_id = query.message.chat.id
    else:
        chat_id = update.effective_chat.id

    session = get_session()
    user = session.query(User).filter_by(chat_id=chat_id).first()
    if not user:
        text = "📋 شما هنوز ثبت‌نام نکردید. اول دستور /start رو بزن."
        if query:
            await query.edit_message_text(text, reply_markup=main_menu_markup())
        else:
            await update.message.reply_text(text, reply_markup=main_menu_markup())
        return

    loans = session.query(Loan).filter_by(user_id=user.id).all()
    if not loans:
        text = "💼 هنوز هیچ وامی ثبت نکردی. از دکمه «➕ افزودن وام جدید» استفاده کن."
        if query:
            await query.edit_message_text(text, reply_markup=main_menu_markup())
        else:
            await update.message.reply_text(text, reply_markup=main_reply_keyboard())
        return

    text_lines = ["💼 فهرست وام‌های شما:"]
    buttons = []
    for loan in loans:
        display_name = loan.loan_name or loan.bank or f"وام #{loan.id}"
        bank_part = f" — {loan.bank}" if loan.bank and loan.bank != loan.loan_name else ""
        text_lines.append(f"🔸 وام شماره {loan.id} — {display_name}{bank_part}")
        buttons.append([InlineKeyboardButton(f"وام شماره {loan.id} — {display_name}", callback_data=f"loan|detail|{loan.id}")])

    buttons.append([InlineKeyboardButton("➕ افزودن وام جدید", callback_data="menu|add")])
    buttons.append([InlineKeyboardButton("🔙 منوی اصلی", callback_data="menu|home")])
    keyboard = InlineKeyboardMarkup(buttons)
    if query:
        await query.edit_message_text("\n".join(text_lines), reply_markup=keyboard)
    else:
        await update.message.reply_text("\n".join(text_lines), reply_markup=keyboard)


# pay callback (mark installment paid)
async def pay_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|")
    inst_id = int(parts[1])
    session = get_session()
    inst = session.query(Installment).filter_by(id=inst_id).first()
    if not inst:
        await query.edit_message.reply_text("قسط پیدا نشد.")
        return
    if inst.is_paid:
        await query.edit_message.reply_text("این قسط قبلاً پرداخت شده است.")
        return
    inst.is_paid = True
    inst.paid_at = datetime.datetime.utcnow()
    inst.paid_amount = inst.amount_total
    session.commit()

    # check if loan completed
    loan = inst.loan
    remaining = session.query(Installment).filter_by(loan_id=loan.id, is_paid=False).count()
    chat_id = loan.user.chat_id
    if remaining == 0:
        # send congrats
        await context.bot.send_message(chat_id=chat_id, text=f"🎉 تبریک! همه‌ی اقساط وام #{loan.id} پرداخت شد. ممنون از اطلاع‌رسانی.")
    else:
        await query.edit_message_text(f"قسط {inst.sequence_number} با موفقیت علامت زده شد به‌عنوان پرداخت‌شده.")

async def loan_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|")
    loan_id = int(parts[2])
    session = get_session()
    loan = session.query(Loan).filter_by(id=loan_id).first()
    if not loan:
        await query.edit_message_text("⚠️ وام پیدا نشد.")
        return

    insts = session.query(Installment).filter_by(loan_id=loan_id).order_by(Installment.sequence_number).all()
    text_lines = [
        f"💼 جزئیات وام #{loan.id}",
        f"🏦 بانک: {loan.bank}",
        f"💰 اصل وام: {format_currency(loan.principal)}",
        f"📈 نرخ بهره: {loan.annual_interest_rate}%",
        f"📅 مدت: {loan.term_months} ماه",
        "",
        "📊 لیست اقساط:"
    ]

    for inst in insts:
        jd = jdatetime.date.fromgregorian(date=inst.due_date)
        status = "✅ پرداخت‌شده" if inst.is_paid else "❌ در انتظار پرداخت"
        text_lines.append(
            f"قسط {inst.sequence_number}: {format_currency(inst.amount_total)} تومان — "
            f"تاریخ {jd.year}/{jd.month}/{jd.day} — {status}"  # ← از jd.day استفاده شود
        )

    # دکمه‌ها برای پرداخت یا بازگشت
    buttons = []
    for inst in insts:
        if not inst.is_paid:
            buttons.append([InlineKeyboardButton(f"💵 پرداخت قسط {inst.sequence_number}", callback_data=f"pay|{inst.id}")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu|myloans")])

    await query.edit_message_text("\n".join(text_lines), reply_markup=InlineKeyboardMarkup(buttons))

#delete_loan
async def delete_loan_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    loan_id = int(query.data.split("|")[2])
    context.user_data["delete_target_id"] = loan_id

    await query.edit_message_text(
        f"❗ آیا مطمئن هستی که می‌خوای وام شماره {loan_id} را حذف کنی؟",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ بله حذف کن", callback_data="delete|yes")],
            [InlineKeyboardButton("❌ نه، منصرف شدم", callback_data="delete|no")],
        ])
    )

async def delete_loan_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    loan_id = context.user_data.get("delete_target_id")
    session = get_session()
    loan = session.query(Loan).filter_by(id=loan_id).first()

    if loan:
        session.delete(loan)
        session.commit()
        await query.edit_message_text(
            f"🗑️ وام شماره {loan_id} با موفقیت حذف شد.",
            reply_markup=main_menu_markup()
        )
    else:
        await query.edit_message_text("⚠️ وام پیدا نشد.", reply_markup=main_menu_markup())

    session.close()

async def delete_loan_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "❌ عملیات حذف لغو شد.",
        reply_markup=main_menu_markup()
    )




async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "یکی از گزینه‌های زیر را انتخاب کن:"
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(text, reply_markup=main_menu_markup())
    elif update.message:
        await update.message.reply_text(text, reply_markup=main_menu_markup())


# Scheduled job: send reminders daily
async def daily_reminder_job(context: ContextTypes.DEFAULT_TYPE):
    session = get_session()
    today_utc = datetime.datetime.utcnow().date()
    # iterate loans and installments, and check if any installment's due_date - reminder_days_before == today
    loans = session.query(Loan).all()
    for loan in loans:
        for inst in loan.installments:
            if inst.is_paid:
                continue
            remind_on = inst.due_date - datetime.timedelta(days=loan.reminder_days_before)
            if remind_on == today_utc:
                # send reminder
                chat_id = loan.user.chat_id
                jd = jdatetime.date.fromgregorian(date=inst.due_date)
                text = (
                    f"🔔 یادآوری پرداخت قسط\n"
                    f"وام #{loan.id} — {loan.bank}\n"
                    f"قسط {inst.sequence_number} به مبلغ {format_currency(inst.amount_total)} در تاریخ {jd.year}/{jd.month}/{inst.due_date.day} سررسید می‌شود.\n"
                    f"اگر پرداخت کردی، دکمه 'پرداخت شد' را بزن."
                )
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("پرداخت شد ✅", callback_data=f"pay|{inst.id}")],
                    [InlineKeyboardButton("مشاهده وام", callback_data=f"loan|detail|{loan.id}")]
                ])
                try:
                    await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=kb)
                except Exception as e:
                    logger.error("Error sending reminder: %s", e)
    session.close()

# -----------------------
# Backup runner (run sync backup in executor)
# -----------------------
async def _run_backup_in_executor():
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, backup_service.run_backup)
    except Exception:
        logger.exception("Backup job raised exception")

# -----------------------
# Setup application
# -----------------------
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("addloan", addloan_start),
            CallbackQueryHandler(addloan_start, pattern=r"^menu\|add$"),
            MessageHandler(
                filters.TEXT & ~filters.COMMAND & filters.Regex(r"^➕ افزودن وام جدید$"),
                addloan_start
            ),
        ],
        states={
            ADD_BANK: [MessageHandler(filters.TEXT & ~filters.COMMAND, addloan_bank)],
            ADD_PRINCIPAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, addloan_principal)],
            ADD_RATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, addloan_rate)],
            ADD_TERM: [MessageHandler(filters.TEXT & ~filters.COMMAND, addloan_term)],
            ADD_CALENDAR: [CallbackQueryHandler(calendar_callback, pattern=r"^cal\|")],
            # reminder callback
        },
        fallbacks=[
            CommandHandler("cancel", addloan_cancel),
            MessageHandler(filters.Regex(r"^لغو$"), addloan_cancel)
        ],
        allow_reentry=True
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    app.add_handler(CommandHandler("menu", show_main_menu))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(r"^💼 وام‌های من$"),
        myloans_list
    ))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(r"^📅 سررسیدهای نزدیک$"),
        open_due_menu_from_message
    ))
    app.add_handler(MessageHandler(
    filters.TEXT & ~filters.COMMAND & filters.Regex(r"^🗑️ حذف وام$"),
    delete_loan_start
))

    app.add_handler(CallbackQueryHandler(delete_loan_start, pattern=r"^menu\|delete$"))
    app.add_handler(CallbackQueryHandler(delete_loan_confirm, pattern=r"^delete\|select\|"))
    app.add_handler(CallbackQueryHandler(delete_loan_execute, pattern=r"^delete\|yes$"))
    app.add_handler(CallbackQueryHandler(delete_loan_cancel, pattern=r"^delete\|no$"))

    app.add_handler(CallbackQueryHandler(reminder_callback, pattern=r"^rem\|"))
    app.add_handler(CallbackQueryHandler(due_range_callback, pattern=r"^due\|"))
    # exclude menu|add here so ConversationHandler entry point handles it
    app.add_handler(CallbackQueryHandler(menu_callback, pattern=r"^menu\|(?!add$)"))
    app.add_handler(CallbackQueryHandler(loan_detail_callback, pattern=r"^loan\|detail\|"))
    app.add_handler(CallbackQueryHandler(pay_callback, pattern=r"^pay\|"))
    app.add_handler(CommandHandler("myloans", myloans_list))
    app.add_handler(CallbackQueryHandler(prevpaid_callback, pattern=r"^prevpaid\|"))

    # schedule daily job: run reminders (existing)
    app.job_queue.run_repeating(daily_reminder_job, interval=24*60*60, first=10)

    # schedule backup job (fixed interval)
    # run the synchronous backup in a thread to avoid blocking the event loop
    app.job_queue.run_repeating(lambda ctx: asyncio.create_task(_run_backup_in_executor()), interval=int(BACKUP_INTERVAL_HOURS*3600), first=10)

    logger.info("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()