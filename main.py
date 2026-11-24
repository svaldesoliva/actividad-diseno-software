import logging
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
MP_API = "https://api.mercadopago.com"
PRODUCT = {
    "id": "vital-con-gas-16l",
    "title": "Agua Vital con gas",
    "quantity": 1,
    "unit_price": 1000,
    "currency_id": "CLP",
}
PRICE_LABEL = f"${PRODUCT['unit_price']:,}".replace(",", ".")

app = FastAPI()
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")
logger = logging.getLogger("uvicorn.error")


def mercado_pago(method: str, path: str, token: str, **kwargs) -> dict:
    response = httpx.request(
        method,
        f"{MP_API}{path}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10.0,
        **kwargs,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("Respuesta inesperada de Mercado Pago")
    return data


def result_page(
    request: Request, title: str, message: str, tone: str, http_status: int = 200
):
    return templates.TemplateResponse(
        request,
        "resultado.html",
        {"title": title, "message": message, "tone": tone},
        status_code=http_status,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@app.get("/")
def storefront(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "product": PRODUCT,
            "price": PRICE_LABEL,
            "mp_public_key": os.getenv("MP_TEST_PUBLIC_KEY", "").strip(),
        },
    )


@app.post("/comprar")
def buy(request: Request):
    token = os.getenv("MP_TEST_ACCESS_TOKEN", "").strip()
    base_url = os.getenv("APP_BASE_URL", "").strip().rstrip("/")
    if not token or not re.fullmatch(r"https://[\w-]+(?:\.[\w-]+)+(?::\d+)?", base_url):
        return result_page(
            request,
            "Checkout sin configurar",
            "Completa MP_TEST_ACCESS_TOKEN y APP_BASE_URL en el archivo .env.",
            "warning",
            503,
        )

    reference = uuid4().hex
    return_url = f"{base_url}/resultado/{reference}"
    try:
        seller = mercado_pago("GET", "/users/me", token)
        tags = seller.get("tags")
        if not isinstance(tags, list) or "test_user" not in tags or seller.get("site_id") != "MLC":
            return result_page(
                request,
                "Se requiere un vendedor de prueba",
                "Usa el Access Token de prueba de una aplicación de Checkout Pro de Chile.",
                "warning",
                503,
            )

        preference = mercado_pago(
            "POST",
            "/checkout/preferences",
            token,
            json={
                "items": [PRODUCT],
                "external_reference": reference,
                "back_urls": dict.fromkeys(("success", "pending", "failure"), return_url),
                "auto_return": "approved",
            },
        )
        if request.headers.get("accept") == "application/json":
            preference_id = preference.get("id")
            if not isinstance(preference_id, str) or not preference_id:
                raise ValueError("Preferencia sin identificador")
            return {"preference_id": preference_id}

        checkout_url = preference.get("init_point")
        if not isinstance(checkout_url, str):
            raise ValueError("Preferencia sin URL de checkout")
        checkout = urlsplit(checkout_url)
        host = checkout.hostname or ""
        if checkout.scheme != "https" or not host.endswith(
            (".mercadopago.cl", ".mercadopago.com")
        ):
            raise ValueError("URL de checkout inesperada")

    except httpx.HTTPStatusError as error:
        logger.warning("Mercado Pago respondió HTTP %s al abrir el checkout", error.response.status_code)
        return result_page(
            request,
            "No se pudo abrir el checkout",
            "Revisa las credenciales de prueba y la URL de retorno e inténtalo otra vez.",
            "danger",
            502,
        )
    except (httpx.RequestError, ValueError) as error:
        logger.warning("Error al abrir el checkout: %s", type(error).__name__)
        return result_page(
            request,
            "No se pudo abrir el checkout",
            "Inténtalo otra vez en unos minutos.",
            "danger",
            502,
        )

    return RedirectResponse(checkout_url, status_code=303)


PAYMENT_RESULTS = {
    "approved": ("Pago de prueba aprobado", "Mercado Pago aprobó la compra simulada.", "success"),
    "rejected": ("Pago rechazado", "Puedes volver a la tienda e intentar otra compra.", "danger"),
    "cancelled": ("Pago cancelado", "Puedes volver a la tienda e intentar otra compra.", "warning"),
    "pending": ("Pago pendiente", "Mercado Pago aún está procesando la compra.", "warning"),
}


@app.get("/resultado/{reference}")
def payment_result(request: Request, reference: UUID, payment_id: str = ""):
    if not re.fullmatch(r"[0-9]{1,24}", payment_id):
        return result_page(
            request,
            "Pago sin confirmar",
            "Mercado Pago no devolvió un identificador de pago para este intento.",
            "warning",
        )

    token = os.getenv("MP_TEST_ACCESS_TOKEN", "").strip()
    if not token:
        return result_page(
            request, "Pago sin verificar", "Completa el Access Token de prueba en .env.", "warning", 503
        )

    try:
        payment = mercado_pago("GET", f"/v1/payments/{payment_id}", token)
    except (httpx.HTTPError, ValueError) as error:
        logger.warning("Error al consultar el pago: %s", type(error).__name__)
        return result_page(
            request,
            "Pago sin verificar",
            "No pudimos consultar el pago. Puedes recargar esta página para volver a intentarlo.",
            "warning",
            502,
        )

    if (
        payment.get("external_reference") != reference.hex
        or payment.get("transaction_amount") != PRODUCT["unit_price"]
        or payment.get("currency_id") != PRODUCT["currency_id"]
    ):
        return result_page(
            request, "Pago sin verificar", "El pago consultado no coincide con este intento.", "warning", 404
        )

    status = payment.get("status")
    if status in ("in_process", "authorized"):
        status = "pending"
    if isinstance(status, str) and status in PAYMENT_RESULTS:
        return result_page(request, *PAYMENT_RESULTS[status])
    return result_page(
        request, "Pago sin confirmar", "Mercado Pago devolvió un estado sin confirmación.", "warning"
    )
