from __future__ import annotations

import html
import logging
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import PriceAlert, PriceHistory

logger = logging.getLogger(__name__)


def create_alert(
    db: Session,
    query: str,
    target_price: float,
    email: str,
    store_filter: str | None = None,
    note: str | None = None,
) -> PriceAlert:
    alert = PriceAlert(
        query=query.strip().lower(),
        target_price=target_price,
        email=email.strip().lower(),
        store_filter=store_filter.strip() if store_filter else None,
        note=note.strip() if note else None,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


def list_alerts(db: Session, email: str | None = None, active_only: bool = True) -> list[PriceAlert]:
    query = db.query(PriceAlert)
    if active_only:
        query = query.filter(PriceAlert.active.is_(True))
    if email:
        query = query.filter(PriceAlert.email == email.strip().lower())
    return query.order_by(PriceAlert.created_at.desc()).all()


def delete_alert(db: Session, alert_id: int) -> bool:
    alert = db.query(PriceAlert).filter(PriceAlert.id == alert_id).first()
    if not alert:
        return False
    alert.active = False
    db.commit()
    return True


def check_alerts(db: Session) -> list[dict]:
    """Usa solo observaciones recientes y desactiva tras notificar con exito."""
    fired = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.price_freshness_hours)
    for alert in list_alerts(db, active_only=True):
        query = (
            db.query(PriceHistory)
            .filter(func.lower(PriceHistory.query) == alert.query)
            .filter(PriceHistory.price.between(10, alert.target_price))
            .filter(PriceHistory.recorded_at >= cutoff)
        )
        if alert.store_filter:
            query = query.filter(PriceHistory.store.ilike(f"%{alert.store_filter}%"))
        match = query.order_by(PriceHistory.price.asc()).first()
        if not match:
            continue
        result = {
            "alert_id": alert.id,
            "query": alert.query,
            "target_price": alert.target_price,
            "found_price": match.price,
            "store": match.store,
            "link": match.link,
            "email": alert.email,
        }
        notified, message = _send_alert_email(result)
        result["notified"] = notified
        result["notification_message"] = message
        if notified:
            alert.triggered = True
            alert.triggered_at = datetime.now(timezone.utc)
            alert.active = False
            db.commit()
        fired.append(result)
    return fired


def send_test_email(to_email: str) -> tuple[bool, str]:
    return _send_email(
        to=to_email,
        subject="Comprador Inteligente - email configurado",
        body_html="<h2>Comprador Inteligente</h2><p>La configuracion SMTP funciona correctamente.</p>",
    )


def _send_alert_email(data: dict) -> tuple[bool, str]:
    savings = data["target_price"] - data["found_price"]
    percentage = round(savings / data["target_price"] * 100, 1)
    query = html.escape(str(data["query"]))
    store = html.escape(str(data["store"]))
    link = html.escape(str(data.get("link") or ""), quote=True)
    link_html = f'<p><a href="{link}">Ver producto en la tienda</a></p>' if link else ""
    body = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px">
      <h2>Alerta de precio</h2>
      <p><strong>{query}</strong> se encontro a CLP ${data['found_price']:,.0f} en {store}.</p>
      <p>Objetivo: CLP ${data['target_price']:,.0f}. Ahorro estimado: CLP ${savings:,.0f} ({percentage}%).</p>
      {link_html}
      <p><small>Confirma stock, especificacion, despacho y precio final antes de comprar.</small></p>
    </div>
    """
    return _send_email(
        to=data["email"],
        subject=f"Alerta de precio: {data['query']}",
        body_html=body,
    )


def _send_email(to: str, subject: str, body_html: str) -> tuple[bool, str]:
    if not settings.alert_email_from or not settings.alert_email_password:
        return False, "SMTP no configurado; la alerta permanecera activa."
    try:
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = f"Comprador Inteligente <{settings.alert_email_from}>"
        message["To"] = to
        message.attach(MIMEText(body_html, "html", "utf-8"))
        with smtplib.SMTP(settings.alert_email_smtp, settings.alert_email_port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.login(settings.alert_email_from, settings.alert_email_password)
            server.sendmail(settings.alert_email_from, [to], message.as_string())
        return True, "Email enviado correctamente."
    except smtplib.SMTPAuthenticationError:
        return False, "Autenticacion SMTP rechazada."
    except Exception as exc:
        logger.error("[Alertas] No se pudo enviar email: %s", exc)
        return False, "No se pudo enviar el email; la alerta permanecera activa."
