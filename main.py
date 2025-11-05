# main.py
import logging
import asyncio
import datetime
import jdatetime
import pytz

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, ConversationHandler,
    MessageHandler, CallbackQueryHandler, filters
)

from db import init_db, SessionLocal
from models import User, Loan, Installment
from logic import calculate_amortization
from calendar_helper import build_month_keyboard
from config import BOT_TOKEN, TIMEZONE

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Conversation states
(ADD_BANK, ADD_PRINCIPAL, ADD_RATE, ADD_TERM, ADD_CALENDAR, ADD_REMINDER) = range(6)

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

# Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = get_session()
    user = session.query(User).filter_by(chat_id=chat_id).first()
    if not user:
        user = User(chat_id=chat_id, name=update.effective_user.first_name or "User")
        session.add(user)
        session.commit()
    await update.message.reply_text(
        "سلام! خوش اومدی.\nبرای افزودن وام /addloan و برای دیدن وام‌ها /myloans رو بزن."
    )

# Add loan conversation
async def addloan_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Support both /addloan (message) and inline button (callback query)
    if getattr(update, "callback_query", None):
        query = update.callback_query
        await query.answer()
        context.user_data.clear()
        # ارسال پیام جدید به‌جای ادیت، تا محدودیت‌های ادیت مزاحم نشوند
        await query.message.reply_text("نام بانک را وارد کنید:")
    else:
        await update.message.reply_text("نام بانک را وارد کنید:")
    return ADD_BANK

async def addloan_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['bank'] = update.message.text.strip()
    await update.message.reply_text("مبلغ اصل وام (اعداد فقط، بدون ویرگول):")
    return ADD_PRINCIPAL

async def addloan_principal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['principal'] = float(update.message.text.strip())
    except:
        await update.message.reply_text("مبلغ نامعتبر است، لطفاً فقط عدد وارد کنید.")
        return ADD_PRINCIPAL
    await update.message.reply_text("نرخ بهره سالانه (مثلاً 18.5):")
    return ADD_RATE

async def addloan_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['rate'] = float(update.message.text.strip())
    except:
        await update.message.reply_text("نرخ نامعتبر است، دوباره وارد کن.")
        return ADD_RATE
    await update.message.reply_text("مدت وام به ماه (مثلاً 36):")
    return ADD_TERM

async def addloan_term(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['term'] = int(update.message.text.strip())
    except:
        await update.message.reply_text("مدت نامعتبر است، عدد ماه وارد کن.")
        return ADD_TERM

    # show initial jalali month keyboard for selection
    now_j = jdatetime.date.today()
    kb = build_month_keyboard(now_j.year, now_j.month, prefix="cal")
    await update.message.reply_text("تاریخ اولین پرداخت را از تقویم زیر انتخاب کن (شمسی):", reply_markup=kb)
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
    data = query.data  # rem|1
    try:
        days = int(data.split("|")[1])
    except:
        days = 1
    context.user_data['reminder_days'] = days

    # Save loan to DB
    session = get_session()
    chat_id = query.message.chat.id
    user = session.query(User).filter_by(chat_id=chat_id).first()
    loan = Loan(
        user_id=user.id,
        bank=context.user_data.get('bank', '---'),
        loan_name=context.user_data.get('bank', 'Loan'),
        principal=context.user_data.get('principal', 0.0),
        annual_interest_rate=context.user_data.get('rate', 0.0),
        term_months=context.user_data.get('term', 1),
        first_payment_date=jalali_to_gregorian_date(context.user_data['first_payment_jalali']),
        reminder_days_before=days
    )
    session.add(loan)
    session.commit()

    # generate installments
    schedule = calculate_amortization(loan.principal, loan.annual_interest_rate, loan.term_months, loan.first_payment_date)
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

    # confirmation message + menu
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن وام جدید", callback_data="menu|add")],
        [InlineKeyboardButton("💼 وام‌های من", callback_data="menu|myloans")]
    ])
    text = (
        f"✅ وام با موفقیت ثبت شد!\n\n"
        f"بانک: {loan.bank}\n"
        f"اصل: {format_currency(loan.principal)}\n"
        f"نرخ سالیانه: {loan.annual_interest_rate}%\n"
        f"مدت: {loan.term_months} ماه\n"
        f"تاریخ اولین قسط (شمسی): {context.user_data['first_payment_jalali']}\n"
        f"یادآوری: {days} روز قبل"
    )
    await query.edit_message_text(text, reply_markup=kb)
    return ConversationHandler.END

# Menu callback (after confirmation)
async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data  # menu|add or menu|myloans

    if data == "menu|add":
        # این مسیر در handler اختصاصی شروع مکالمه مدیریت می‌شود.
        # اینجا فقط برای سازگاری قدیمی پیام راهنما می‌فرستیم (بدون تغییر state).
        context.user_data.clear()
        await query.message.reply_text("نام بانک را وارد کنید:")
        return

    elif data == "menu|myloans":
        await myloans_list(update, context)
        return ConversationHandler.END

    else:
        await query.message.reply_text("دستور ناشناخته.")

# myloans command / handler
async def myloans_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # پشتیبانی از هر دو حالت: CommandHandler یا CallbackQuery
    if isinstance(update, Update) and update.callback_query:
        query = update.callback_query
        await query.answer()
        chat_id = query.message.chat.id
        send_func = query.edit_message_text
    else:
        chat_id = update.effective_chat.id
        send_func = update.message.reply_text

    session = get_session()
    user = session.query(User).filter_by(chat_id=chat_id).first()
    if not user:
        await send_func("📋 شما هنوز ثبت‌نام نکردید. اول دستور /start رو بزن.")
        return

    loans = session.query(Loan).filter_by(user_id=user.id).all()
    if not loans:
        await send_func("💼 هنوز هیچ وامی ثبت نکردی. با دستور /addloan شروع کن.")
        return

    text_lines = ["💼 فهرست وام‌های شما:"]
    buttons = []
    for loan in loans:
        text_lines.append(f"🔸 {loan.id}. {loan.bank} — {loan.loan_name}")
        buttons.append([InlineKeyboardButton(f"جزئیات وام {loan.id}", callback_data=f"loan|detail|{loan.id}")])

    keyboard = InlineKeyboardMarkup(buttons)
    await send_func("\n".join(text_lines), reply_markup=keyboard)

# entry point to start add-loan conversation via inline button (menu|add)
async def menu_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # start fresh conversation state
    context.user_data.clear()
    await query.edit_message_text("نام بانک را وارد کنید:")
    return ADD_BANK

# pay callback (mark installment paid)
async def pay_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|")
    inst_id = int(parts[1])
    session = get_session()
    inst = session.query(Installment).filter_by(id=inst_id).first()
    if not inst:
        await query.edit_message_text("قسط پیدا نشد.")
        return
    if inst.is_paid:
        await query.edit_message_text("این قسط قبلاً پرداخت شده است.")
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
            f"تاریخ {jd.year}/{jd.month}/{inst.due_date.day} — {status}"
        )

    # دکمه‌ها برای پرداخت یا بازگشت
    buttons = []
    for inst in insts:
        if not inst.is_paid:
            buttons.append([InlineKeyboardButton(f"💵 پرداخت قسط {inst.sequence_number}", callback_data=f"pay|{inst.id}")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu|myloans")])

    await query.edit_message_text("\n".join(text_lines), reply_markup=InlineKeyboardMarkup(buttons))


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
            # check if today is exactly due date and unpaid AND it's last installment -> send congrats? 
            # For final installment, if due_date == today, we might want to congratulate when paid. 
    session.close()

# Setup application
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("addloan", addloan_start),
            CallbackQueryHandler(addloan_start, pattern=r"^menu\|add$")
        ],
        states={
            ADD_BANK: [MessageHandler(filters.TEXT & ~filters.COMMAND, addloan_bank)],
            ADD_PRINCIPAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, addloan_principal)],
            ADD_RATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, addloan_rate)],
            ADD_TERM: [MessageHandler(filters.TEXT & ~filters.COMMAND, addloan_term)],
            ADD_CALENDAR: [CallbackQueryHandler(calendar_callback, pattern=r"^cal\|")],
            # reminder callback
        },
        fallbacks=[],
        allow_reentry=True
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(reminder_callback, pattern=r"^rem\|"))
    # exclude menu|add here so ConversationHandler entry point handles it
    app.add_handler(CallbackQueryHandler(menu_callback, pattern=r"^menu\|(?!add$)"))
    app.add_handler(CallbackQueryHandler(loan_detail_callback, pattern=r"^loan\|detail\|"))
    app.add_handler(CallbackQueryHandler(pay_callback, pattern=r"^pay\|"))
    app.add_handler(CommandHandler("myloans", myloans_list))

    # schedule daily job: run every 24h (first run after 10 seconds) — adjust if needed
    app.job_queue.run_repeating(daily_reminder_job, interval=24*60*60, first=10)

    logger.info("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
