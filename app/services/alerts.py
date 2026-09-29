from __future__ import annotations

import html
import logging
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import urlencode

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.signing import SigningNotConfigured, make_token, verify_token
from app.models import PriceAlert, PriceHistory

logger = logging.getLogger(__name__)


CONFIRM_TTL_SECONDS = 48 * 3600


class AlertLimitExceeded(Exception):
    """El email alcanzo el maximo de alertas activas o de altas diarias."""


def create_alert(
    db: Session,
    query: str,
    target_price: float,
    email: str,
    store_filter: str | None = None,
    note: str | None = None,
) -> tuple[PriceAlert, bool]:
    """Crea una alerta pendiente y envia el email de confirmacion (doble opt-in).

    Sin confirmacion no se envia ninguna notificacion de precio: evita usar el
    servicio para enviar correos a terceros. Retorna (alerta, email_enviado).
    """
    email = email.strip().lower()
    active = (
        db.query(func.count(PriceAlert.id))
        .filter(PriceAlert.email == email, PriceAlert.active.is_(True))
        .scalar()
    )
    if active >= settings.alert_max_active_per_email:
        raise AlertLimitExceeded("Se alcanzo el maximo de alertas activas para este email.")
    since = datetime.now(timezone.utc) - timedelta(days=1)
    recent = (
        db.query(func.count(PriceAlert.id))
        .filter(PriceAlert.email == email, PriceAlert.created_at >= since)
        .scalar()
    )
    if recent >= settings.alert_max_new_per_email_per_day:
        raise AlertLimitExceeded("Se alcanzo el maximo de alertas nuevas por dia para este email.")

    alert = PriceAlert(
        query=query.strip().lower(),
        target_price=target_price,
        email=email,
        store_filter=store_filter.strip() if store_filter else None,
        note=note.strip() if note else None,
        confirmed=False,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    sent, _ = _send_confirmation_email(alert)
    return alert, sent


def confirm_alert(db: Session, alert_id: int, token: str) -> PriceAlert | None:
    if not verify_token("alert-confirm", alert_id, token):
        return None
    alert = db.query(PriceAlert).filter(PriceAlert.id == alert_id).first()
    if not alert or not alert.active:
        return None
    if not alert.confirmed:
        alert.confirmed = True
        alert.confirmed_at = datetime.now(timezone.utc)
        db.commit()
    return alert


def unsubscribe_alert(db: Session, alert_id: int, token: str) -> bool:
    if not verify_token("alert-unsubscribe", alert_id, token):
        return False
    alert = db.query(PriceAlert).filter(PriceAlert.id == alert_id).first()
    if not alert:
        return False
    alert.active = False
    db.commit()
    return True


def _alert_link(action: str, alert: PriceAlert, token: str) -> str:
    base = settings.public_api_url.rstrip("/")
    return f"{base}/alerts/{action}?{urlencode({'id': alert.id, 'token': token})}"


def confirmation_link(alert: PriceAlert) -> str:
    return _alert_link("confirm", alert, make_token("alert-confirm", alert.id, CONFIRM_TTL_SECONDS))


def unsubscribe_link(alert: PriceAlert) -> str:
    return _alert_link("unsubscribe", alert, make_token("alert-unsubscribe", alert.id))


def _send_confirmation_email(alert: PriceAlert) -> tuple[bool, str]:
    try:
        link = confirmation_link(alert)
    except SigningNotConfigured as exc:
        logger.error("[Alertas] %s", exc)
        return False, "Firma de enlaces no configurada."
    query = html.escape(alert.query)
    safe_link = html.escape(link, quote=True)
    body = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px">
      <h2>Confirma tu alerta de precio</h2>
      <p>Se solicito una alerta para <strong>{query}</strong> bajo CLP ${alert.target_price:,.0f}.</p>
      <p><a href="{safe_link}">Confirmar alerta</a> (el enlace vence en 48 horas).</p>
      <p><small>Si no la solicitaste, ignora este mensaje: no recibiras mas correos.</small></p>
    </div>
    """
    sent, message = _send_email(to=alert.email, subject="Confirma tu alerta de precio", body_html=body)
    if not sent and settings.app_env == "local":
        logger.info("[Alertas] (solo local) Enlace de confirmacion: %s", link)
    return sent, message


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
    confirmed_alerts = [alert for alert in list_alerts(db, active_only=True) if alert.confirmed]
    for alert in confirmed_alerts:
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
        notified, message = _send_alert_email({**result, "unsubscribe_link": unsubscribe_link(alert)})
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
      <p><small><a href="{html.escape(data['unsubscribe_link'], quote=True)}">Cancelar esta alerta</a></small></p>
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
