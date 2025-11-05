# calendar_helper.py
# Small inline Jalali calendar builder for telegram InlineKeyboardMarkup
import jdatetime
import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def jalali_month_matrix(year, month):
    # returns list of lists of day numbers for week rows (starting Saturday)
    first = jdatetime.date(year, month, 1)
    # weekday in jdatetime: Monday=0 .. Sunday=6 but Persian week often Saturday first; 
    # we'll align so that calendar starts Saturday. jdatetime.weekday() returns 0=Monday
    offset = (first.togregorian().weekday() + 2) % 7  # transform to Saturday=0
    import calendar
    # number of days in jalali month: use jdatetime to get next month minus one
    try:
        next_month = jdatetime.date(year + (month // 12), (month % 12) + 1, 1)
    except Exception:
        # handle December-> next year
        if month == 12:
            next_month = jdatetime.date(year+1, 1, 1)
        else:
            raise
    last = next_month - jdatetime.timedelta(days=1)
    days = last.day
    # build rows
    rows = []
    week = [None]*7
    day = 1
    # map offset: place first day
    i = offset
    while day <= days:
        week[i] = day
        i += 1
        if i == 7:
            rows.append(week)
            week = [None]*7
            i = 0
        day += 1
    if any(x is not None for x in week):
        rows.append(week)
    return rows

def build_month_keyboard(year, month, prefix="cal"):
    rows = jalali_month_matrix(year, month)
    keyboard = []
    # header with month/year and prev/next
    header = [
        InlineKeyboardButton("⟨", callback_data=f"{prefix}|prev|{year}-{month}"),
        InlineKeyboardButton(f"{year}/{month}", callback_data="noop"),
        InlineKeyboardButton("⟩", callback_data=f"{prefix}|next|{year}-{month}"),
    ]
    keyboard.append(header)
    # week day names as short
    weekday_names = ["ش", "ی", "د", "س", "چ", "پ", "ج"]  # Sat..Fri short
    keyboard.append([InlineKeyboardButton(n, callback_data="noop") for n in weekday_names])

    for week in rows:
        row = []
        for d in week:
            if d is None:
                row.append(InlineKeyboardButton(" ", callback_data="noop"))
            else:
                # build callback data with actual jalali date
                jalali_date = f"{year:04d}-{month:02d}-{d:02d}"
                row.append(InlineKeyboardButton(str(d), callback_data=f"{prefix}|day|{jalali_date}"))
        keyboard.append(row)
    # cancel
    keyboard.append([InlineKeyboardButton("لغو", callback_data=f"{prefix}|cancel")])
    return InlineKeyboardMarkup(keyboard)
