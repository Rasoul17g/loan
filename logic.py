# # logic.py
# import math
# import datetime
# from dateutil.relativedelta import relativedelta

# def add_months_preserve_day(date_obj, months):
#     # add months preserving day; cap to month end if needed
#     return date_obj + relativedelta(months=months)

# def calculate_amortization(principal, annual_rate, term_months, first_payment_date):
#     """
#     principal: float
#     annual_rate: percent (e.g., 18.5)
#     term_months: int
#     first_payment_date: datetime.date (gregorian)
#     returns: list of dicts for each installment
#     """
#     if term_months <= 0:
#         return []

#     r = annual_rate / 100 / 12  # monthly rate
#     if r == 0:
#         payment = round(principal / term_months, 2)
#     else:
#         payment = principal * r / (1 - (1 + r) ** -term_months)

#     schedule = []
#     balance = principal
#     for i in range(1, term_months + 1):
#         interest = round(balance * r, 10)
#         principal_part = payment - interest
#         # deal with last installment rounding
#         if i == term_months:
#             principal_part = balance
#             payment_amount = round(interest + principal_part, 2)
#         else:
#             payment_amount = round(payment, 2)
#             principal_part = round(principal_part, 2)

#         interest = round(interest, 2)
#         balance = round(balance - principal_part, 2)
#         due_date = add_months_preserve_day(first_payment_date, i - 1)

#         schedule.append({
#             "installment": i,
#             "due_date": due_date,
#             "payment": payment_amount,
#             "interest": interest,
#             "principal": principal_part,
#             "remaining": balance
#         })
#     return schedule
#----------------------------------------------------------------------
# logic.py
import math
import datetime
import jdatetime
from dateutil.relativedelta import relativedelta

def add_months_preserve_day(date_obj, months):
    """
    date_obj: datetime.date (گرگوری)
    months: int
    Return: datetime.date (گرگوری) — ماه‌ها را بر اساس تقویم جلالی/شمسی اضافه می‌کند و روز را حفظ می‌کند.
    """
    # تبدیل گرگوری -> جلالی
    jstart = jdatetime.date.fromgregorian(date=date_obj)

    # محاسبه تاریخ جلالی جدید با حفظ روز (یا کپ به آخر ماه جلالی اگر روز معتبر نباشد)
    new_j = add_months_jalali_preserve_day(jstart, months)

    # تبدیل برگردانده شده به گرگوری برای ذخیره/پردازش بعدی
    return new_j.togregorian()


def add_months_jalali_preserve_day(jdate, months):
    """
    jdate: jdatetime.date
    months: int
    return: jdatetime.date
    افزایشی امن روی ماه‌های جلالی با تلاش برای نگه داشتن روزِ همان‌قدر؛
    در صورت ناموجود بودن روز در ماه هدف، روز به سمت پایین تا اولین روز معتبر کاهش می‌یابد.
    """
    y = jdate.year
    m = jdate.month
    d = jdate.day

    total = m + months
    # محاسبه سال و ماه جدید در جلالی
    new_y = y + (total - 1) // 12
    new_m = (total - 1) % 12 + 1

    # تلاش برای ساخت تاریخ با همان روز؛ در صورت خطا روز را یکی یکی کم می‌کنیم (کپ به انتهای ماه)
    for try_day in range(d, 0, -1):
        try:
            return jdatetime.date(new_y, new_m, try_day)
        except ValueError:
            continue

    # به طور منطقی هرگز اینجا نخواهیم رسید چون روز=1 همیشه معتبر است
    raise ValueError("unable to construct valid jalali date")


def calculate_amortization(principal, annual_rate, term_months, first_payment_date):
    """
    principal: float
    annual_rate: percent (e.g., 18.5)
    term_months: int
    first_payment_date: datetime.date (گرگوری)
    returns: list of dicts for each installment (due_date is datetime.date (gregorian))
    """
    if term_months <= 0:
        return []

    r = annual_rate / 100 / 12  # monthly rate
    if r == 0:
        payment = round(principal / term_months, 2)
    else:
        payment = principal * r / (1 - (1 + r) ** -term_months)

    schedule = []
    balance = principal
    for i in range(1, term_months + 1):
        interest = round(balance * r, 10)
        principal_part = payment - interest
        # deal with last installment rounding
        if i == term_months:
            principal_part = balance
            payment_amount = round(interest + principal_part, 2)
        else:
            payment_amount = round(payment, 2)
            principal_part = round(principal_part, 2)

        interest = round(interest, 2)
        balance = round(balance - principal_part, 2)

        # <-- این خط حالا تاریخ درست (گرگوری) را باز می‌گرداند،
        #      زیرا add_months_preserve_day ماه‌ها را در تقویم جلالی اضافه می‌کند
        due_date = add_months_preserve_day(first_payment_date, i - 1)

        schedule.append({
            "installment": i,
            "due_date": due_date,
            "payment": payment_amount,
            "interest": interest,
            "principal": principal_part,
            "remaining": balance
        })
    return schedule
