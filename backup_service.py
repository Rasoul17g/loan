# backup_service.py
import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base, User, Loan, Installment

# مسیر دیتابیس اصلی شما
MAIN_DB_URL = "sqlite:///loans.db"

# مسیر دیتابیس دوم (بکاپ)
BACKUP_DB_URL = "sqlite:///backup.db"


def get_session(db_url):
    engine = create_engine(db_url, echo=False)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def sync_user(main_user, backup_session):
    user = backup_session.query(User).filter_by(chat_id=main_user.chat_id).first()
    if not user:
        user = User(
            chat_id=main_user.chat_id,
            name=main_user.name,
            timezone=main_user.timezone
        )
        backup_session.add(user)
        backup_session.commit()
    return user


def sync_loan(main_loan, backup_user, backup_session):
    loan = backup_session.query(Loan).filter_by(id=main_loan.id).first()
    if not loan:
        loan = Loan(
            id=main_loan.id,
            user_id=backup_user.id,
            bank=main_loan.bank,
            loan_name=main_loan.loan_name,
            principal=main_loan.principal,
            annual_interest_rate=main_loan.annual_interest_rate,
            term_months=main_loan.term_months,
            payment_cycle=main_loan.payment_cycle,
            first_payment_date=main_loan.first_payment_date,
            reminder_days_before=main_loan.reminder_days_before,
            created_at=main_loan.created_at,
            updated_at=main_loan.updated_at,
        )
        backup_session.add(loan)
    else:
        # آپدیت مقادیر
        loan.bank = main_loan.bank
        loan.loan_name = main_loan.loan_name
        loan.principal = main_loan.principal
        loan.annual_interest_rate = main_loan.annual_interest_rate
        loan.term_months = main_loan.term_months
        loan.payment_cycle = main_loan.payment_cycle
        loan.first_payment_date = main_loan.first_payment_date
        loan.reminder_days_before = main_loan.reminder_days_before
        loan.updated_at = datetime.datetime.utcnow()

    # بررسی وضعیت وام
    unpaid = sum(1 for inst in main_loan.installments if not inst.is_paid)
    if unpaid == 0:
        loan.status = "completed"
    else:
        loan.status = "active"

    return loan


def sync_installments(main_loan, backup_loan, backup_session):
    backup_existing = {
        inst.id: inst for inst in backup_session.query(Installment).filter_by(loan_id=backup_loan.id).all()
    }

    for inst in main_loan.installments:
        if inst.id in backup_existing:
            b = backup_existing[inst.id]
            b.sequence_number = inst.sequence_number
            b.due_date = inst.due_date
            b.amount_total = inst.amount_total
            b.amount_principal = inst.amount_principal
            b.amount_interest = inst.amount_interest
            b.is_paid = inst.is_paid
            b.paid_amount = inst.paid_amount
            b.paid_at = inst.paid_at
        else:
            new_inst = Installment(
                id=inst.id,
                loan_id=backup_loan.id,
                sequence_number=inst.sequence_number,
                due_date=inst.due_date,
                amount_total=inst.amount_total,
                amount_principal=inst.amount_principal,
                amount_interest=inst.amount_interest,
                is_paid=inst.is_paid,
                paid_amount=inst.paid_amount,
                paid_at=inst.paid_at
            )
            backup_session.add(new_inst)


def mark_deleted_loans(backup_session, active_loan_ids):
    """Loans that exist in backup but not in main database should become status=deleted"""
    old_loans = backup_session.query(Loan).all()
    for loan in old_loans:
        if loan.id not in active_loan_ids:
            loan.status = "deleted"


def run_backup():
    print("🔄 شروع بکاپ‌گیری ...")

    main_session = get_session(MAIN_DB_URL)
    backup_session = get_session(BACKUP_DB_URL)

    main_users = main_session.query(User).all()
    active_loan_ids = []

    for m_user in main_users:
        b_user = sync_user(m_user, backup_session)

        for m_loan in m_user.loans:
            b_loan = sync_loan(m_loan, b_user, backup_session)
            backup_session.commit()

            active_loan_ids.append(m_loan.id)
            sync_installments(m_loan, b_loan, backup_session)
            backup_session.commit()

    # پیدا کردن وام‌هایی که حذف شده‌اند
    mark_deleted_loans(backup_session, active_loan_ids)
    backup_session.commit()

    print("✅ بکاپ با موفقیت انجام شد.")


if __name__ == "__main__":
    run_backup()
