"""Reusable, failure-isolated WhatsApp notifications for tournament events."""

from datetime import datetime
import json
import logging
from threading import Thread
from urllib import error, request

from sqlalchemy.exc import IntegrityError

from .. import db
from ..models import Match, NotificationDelivery

logger = logging.getLogger(__name__)


class WhatsAppNotificationService:
    """Send Meta WhatsApp Cloud API text messages after tournament commits."""

    MATCH_RESULT = "match_result"
    CHAMPION = "champion"

    @staticmethod
    def _settings():
        # The Flask config is read lazily to keep this service reusable from
        # request handlers and application contexts alike.
        from flask import current_app

        config = {
            "access_token": current_app.config.get("WHATSAPP_ACCESS_TOKEN"),
            "phone_number_id": current_app.config.get("WHATSAPP_PHONE_NUMBER_ID"),
            "recipients": current_app.config.get("WHATSAPP_RECIPIENTS"),
            "graph_api_version": current_app.config.get("WHATSAPP_GRAPH_API_VERSION"),
        }
        if not all(config.values()):
            return None

        recipients = [
            recipient.strip().lstrip("+")
            for recipient in config["recipients"].split(",")
            if recipient.strip()
        ]
        if not recipients:
            return None

        config["recipients"] = recipients
        return config

    @classmethod
    def send_match_result(cls, match):
        cls._send_safely(cls.MATCH_RESULT, match, cls._match_result_message)

    @classmethod
    def send_champion(cls, match):
        cls._send_safely(cls.CHAMPION, match, cls._champion_message)

    @classmethod
    def enqueue_match_result(cls, match_id):
        cls._enqueue(cls.MATCH_RESULT, match_id)

    @classmethod
    def enqueue_champion(cls, match_id):
        cls._enqueue(cls.CHAMPION, match_id)

    @classmethod
    def _enqueue(cls, event_type, match_id):
        """Schedule delivery without holding up the admin request."""
        try:
            from flask import current_app

            app = current_app._get_current_object()
            Thread(
                target=cls._deliver_event,
                args=(app, event_type, match_id),
                daemon=True,
            ).start()
        except Exception as exc:
            logger.warning(
                "WhatsApp notification could not be queued for event '%s', match %s: %s",
                event_type, match_id, cls._safe_error_message(exc)
            )

    @classmethod
    def _deliver_event(cls, app, event_type, match_id):
        """Deliver with a thread-local Flask context and SQLAlchemy session."""
        with app.app_context():
            try:
                match = db.session.get(Match, match_id)
                if not match:
                    logger.warning(
                        "WhatsApp notification skipped because match %s was not found.",
                        match_id
                    )
                    return

                if event_type == cls.MATCH_RESULT:
                    cls.send_match_result(match)
                elif event_type == cls.CHAMPION:
                    cls.send_champion(match)
            except Exception as exc:
                db.session.rollback()
                logger.warning(
                    "WhatsApp background delivery failed for event '%s', match %s: %s",
                    event_type, match_id, cls._safe_error_message(exc)
                )
            finally:
                db.session.remove()

    @classmethod
    def _send_safely(cls, event_type, match, message_builder):
        try:
            cls._send_event(event_type, match, message_builder(match))
        except Exception as exc:
            # This is the outer isolation boundary for notification-only
            # failures, including message construction and delivery storage.
            db.session.rollback()
            logger.warning(
                "WhatsApp notification failed for event '%s', match %s: %s",
                event_type, match.id, cls._safe_error_message(exc)
            )

    @classmethod
    def _send_event(cls, event_type, match, message):
        settings = cls._settings()
        if not settings:
            logger.warning("WhatsApp notification skipped because it is not configured.")
            return

        for recipient in settings["recipients"]:
            try:
                cls._send_to_recipient(event_type, match.id, recipient, message, settings)
            except Exception as exc:
                # A database or provider error in the notification subsystem
                # must not turn an already-persisted tournament result into a
                # failed admin request.
                db.session.rollback()
                logger.warning(
                    "WhatsApp notification failed for event '%s', match %s, recipient %s: %s",
                    event_type, match.id, recipient, cls._safe_error_message(exc)
                )

    @classmethod
    def _send_to_recipient(cls, event_type, match_id, recipient, message, settings):
        delivery = NotificationDelivery.query.filter_by(
            event_type=event_type, match_id=match_id, recipient=recipient
        ).first()

        if delivery and delivery.status == "sent":
            return

        if not delivery:
            delivery = NotificationDelivery(
                event_type=event_type,
                match_id=match_id,
                recipient=recipient,
                status="pending",
            )
            db.session.add(delivery)
            try:
                db.session.commit()
            except IntegrityError:
                # Another request created the same unique delivery record.
                db.session.rollback()
                delivery = NotificationDelivery.query.filter_by(
                    event_type=event_type, match_id=match_id, recipient=recipient
                ).first()
                if delivery and delivery.status == "sent":
                    return

        try:
            cls._post_text(recipient, message, settings)
        except Exception as exc:  # Delivery must never affect tournament data.
            logger.warning(
                "WhatsApp notification failed for event '%s', match %s, recipient %s: %s",
                event_type, match_id, recipient, cls._safe_error_message(exc)
            )
            if delivery:
                delivery.status = "failed"
                delivery.error_message = cls._safe_error_message(exc)
                db.session.commit()
            return

        if delivery:
            delivery.status = "sent"
            delivery.sent_at = datetime.utcnow()
            delivery.error_message = None
            db.session.commit()

    @staticmethod
    def _post_text(recipient, message, settings):
        endpoint = (
            f"https://graph.facebook.com/{settings['graph_api_version']}/"
            f"{settings['phone_number_id']}/messages"
        )
        payload = json.dumps({
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "text",
            "text": {"preview_url": False, "body": message},
        }).encode("utf-8")
        api_request = request.Request(
            endpoint,
            data=payload,
            headers={
                "Authorization": f"Bearer {settings['access_token']}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with request.urlopen(api_request, timeout=10) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError(f"Meta WhatsApp API returned HTTP {response.status}")

    @staticmethod
    def _safe_error_message(exc):
        if isinstance(exc, error.HTTPError):
            return f"Meta WhatsApp API returned HTTP {exc.code}"
        if isinstance(exc, error.URLError):
            return "Could not reach Meta WhatsApp API"
        return f"{type(exc).__name__}: {str(exc)[:300]}"

    @staticmethod
    def _match_result_message(match):
        return (
            "Titan Football League\n"
            "Match Result\n\n"
            f"{match.home_team.name} {match.home_score}\u2013{match.away_score} {match.away_team.name}\n\n"
            f"Competition: {WhatsAppNotificationService._stage_name(match.stage)}\n"
            f"Season: {match.season.name}\n"
            "Status: Completed"
        )

    @staticmethod
    def _champion_message(match):
        champion = match.home_team if match.home_score > match.away_score else match.away_team
        return (
            "TITAN FOOTBALL LEAGUE\n\n"
            "CHAMPIONS!\n\n"
            f"{champion.name} have won the Titan Football League!\n\n"
            "Final:\n"
            f"{match.home_team.name} {match.home_score}\u2013{match.away_score} {match.away_team.name}\n\n"
            "Congratulations to the champion!"
        )

    @staticmethod
    def _stage_name(stage):
        names = {
            "group": "Group Stage",
            "r16": "Round of 16",
            "quarter": "Quarterfinal",
            "semi": "Semifinal",
            "third": "Third Place",
            "final": "Final",
        }
        return names.get(stage, stage.replace("_", " ").title())
