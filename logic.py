# logic.py
import math
import datetime
from dateutil.relativedelta import relativedelta

def add_months_preserve_day(date_obj, months):
    # add months preserving day; cap to month end if needed
    return date_obj + relativedelta(months=months)

def calculate_amortization(principal, annual_rate, term_months, first_payment_date):
    """
    principal: float
    annual_rate: percent (e.g., 18.5)
    term_months: int
    first_payment_date: datetime.date (gregorian)
    returns: list of dicts for each installment
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
