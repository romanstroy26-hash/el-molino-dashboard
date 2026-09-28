"""LabsMobile adapter for El Molino's existing one-time-code flow."""

from __future__ import annotations

import os
from typing import Callable

import httpx
from phone_numbers import mexican_sms_number


LABSMOBILE_SEND_URL = "https://api.labsmobile.com/json/send"


class SmsDeliveryError(Exception):
    """The provider did not accept an SMS; never include credentials or codes."""


def make_labsmobile_message_sender(username: str, token: str, *, test_mode: bool = False) -> Callable[[str, str], None]:
    if not username or not token:
        raise ValueError("Faltan credenciales de LabsMobile")

    def send_message(phone: str, message: str) -> None:
        destination = mexican_sms_number(phone)
        payload = {
            "message": message,
            "recipient": [{"msisdn": destination}],
        }
        if test_mode:
            payload["test"] = 1
        try:
            response = httpx.post(
                LABSMOBILE_SEND_URL,
                auth=(username, token),
                json=payload,
                timeout=10.0,
            )
            response.raise_for_status()
            result = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise SmsDeliveryError("No se pudo enviar el SMS") from error
        if not isinstance(result, dict) or str(result.get("code")) != "0":
            raise SmsDeliveryError("El proveedor rechazó el SMS")

    return send_message


def make_labsmobile_sender(username: str, token: str, *, test_mode: bool = False) -> Callable[[str, str], None]:
    send_message = make_labsmobile_message_sender(username, token, test_mode=test_mode)

    def send_code(phone: str, code: str) -> None:
        send_message(phone, f"El Molino: tu código de acceso es {code}. Válido por 10 minutos.")

    return send_code


def sender_from_env() -> Callable[[str, str], None] | None:
    username = os.getenv("LABSMOBILE_USERNAME")
    token = os.getenv("LABSMOBILE_API_TOKEN")
    if not username and not token:
        return None
    if not username or not token:
        raise RuntimeError("Configura LABSMOBILE_USERNAME y LABSMOBILE_API_TOKEN juntos")
    return make_labsmobile_sender(username, token, test_mode=os.getenv("LABSMOBILE_TEST_MODE") == "1")


def message_sender_from_env() -> Callable[[str, str], None] | None:
    username = os.getenv("LABSMOBILE_USERNAME")
    token = os.getenv("LABSMOBILE_API_TOKEN")
    if not username and not token:
        return None
    if not username or not token:
        raise RuntimeError("Configura LABSMOBILE_USERNAME y LABSMOBILE_API_TOKEN juntos")
    return make_labsmobile_message_sender(username, token, test_mode=os.getenv("LABSMOBILE_TEST_MODE") == "1")
