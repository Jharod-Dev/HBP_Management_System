from flask import current_app
from flask_mail import Message


def send_reservation_decision(reservation):
    sender = current_app.config.get("MAIL_DEFAULT_SENDER")
    mail = current_app.extensions.get("mail")
    if not sender or mail is None:
        return False

    message = Message(
        subject=f"Reservation {reservation['status'].title()}",
        recipients=[reservation["email"]],
        sender=sender,
        body=(
            f"Hello {reservation['first_name']} {reservation['last_name']},\n\n"
            f"Your reservation for {reservation['unit_name']} is "
            f"{reservation['status'].lower()}.\n"
            f"Start: {reservation['start_time']}\n"
            f"End: {reservation['end_time']}\n\n"
            "Please contact Howard's Billiards Place if you need assistance."
        ),
    )
    try:
        mail.send(message)
    except Exception:
        current_app.logger.exception("Reservation decision email could not be sent.")
        return False
    return True
