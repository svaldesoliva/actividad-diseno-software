import logging
import os
import re
from hashlib import sha256
from pathlib import Path
from secrets import token_hex
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
MP_API = "https://api.mercadopago.com"
PRODUCT = {
    "id": "vital-con-gas-16l",
    "title": "Agua Vital con gas",
    "unit_price": 1000,
    "currency_id": "CLP",
}
CART_COOKIE = "agua_vital_cart"
MAX_CART_QUANTITY = 99
CART_REVISION_PATTERN = r"[0-9a-f]{16}"

app = FastAPI()
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")
logger = logging.getLogger("uvicorn.error")


def asset_url(filename: str) -> str:
    revision = sha256((ROOT / "static" / filename).read_bytes()).hexdigest()[:12]
    return f"/static/{filename}?v={revision}"


templates.env.globals["asset_url"] = asset_url


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


def price_label(amount: int) -> str:
    return f"${amount:,}".replace(",", ".")


def cart_state(request: Request) -> tuple[int, str]:
    cookie = request.cookies.get(CART_COOKIE, "")
    match = re.fullmatch(rf"([1-9][0-9]{{0,2}})-({CART_REVISION_PATTERN})", cookie)
    if match and int(match[1]) <= MAX_CART_QUANTITY:
        return int(match[1]), match[2]
    return 0, ""


@app.get("/")
def storefront(request: Request):
    quantity, revision = cart_state(request)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "product": PRODUCT,
            "price": price_label(PRODUCT["unit_price"]),
            "quantity": quantity,
            "max_quantity": MAX_CART_QUANTITY,
            "revision": revision,
            "total": price_label(quantity * PRODUCT["unit_price"]),
            "mp_public_key": os.getenv("MP_TEST_PUBLIC_KEY", "").strip(),
        },
        headers={"Cache-Control": "no-store"},
    )


@app.get("/carrito")
def cart_redirect():
    return RedirectResponse("/#compra", status_code=303)


@app.post("/carrito/{action}")
def update_cart(request: Request, action: Literal["agregar", "quitar"]):
    quantity, revision = cart_state(request)
    change = 1 if action == "agregar" else -1
    updated_quantity = min(MAX_CART_QUANTITY, max(0, quantity + change))
    changed = updated_quantity != quantity
    if changed:
        revision = token_hex(8) if updated_quantity else ""

    if request.headers.get("accept") == "application/json":
        response = JSONResponse(
            {
                "quantity": updated_quantity,
                "total": price_label(updated_quantity * PRODUCT["unit_price"]),
                "revision": revision,
            },
            headers={"Cache-Control": "no-store"},
        )
    else:
        response = RedirectResponse("/#compra", status_code=303)

    if not updated_quantity:
        response.delete_cookie(CART_COOKIE)
    elif changed:
        response.set_cookie(
            CART_COOKIE,
            f"{updated_quantity}-{revision}",
            httponly=True,
            secure=request.url.scheme == "https",
        )
    return response


@app.post("/comprar")
def buy(request: Request, revision: str = ""):
    quantity, cart_revision = cart_state(request)
    if not quantity or revision != cart_revision:
        return RedirectResponse("/#compra", status_code=303)

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
    expected_total = quantity * PRODUCT["unit_price"]
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
                "items": [{**PRODUCT, "quantity": quantity}],
                "external_reference": f"{reference}-{expected_total}-{cart_revision}",
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

    external_reference = payment.get("external_reference")
    snapshot = re.fullmatch(
        rf"{reference.hex}-([1-9][0-9]{{0,11}})-({CART_REVISION_PATTERN})",
        external_reference if isinstance(external_reference, str) else "",
    )
    expected_total, cart_revision = None, ""
    if snapshot:
        expected_total, cart_revision = int(snapshot[1]), snapshot[2]
    elif external_reference == reference.hex:
        expected_total = PRODUCT["unit_price"]

    if (
        expected_total is None
        or payment.get("transaction_amount") != expected_total
        or payment.get("currency_id") != PRODUCT["currency_id"]
    ):
        return result_page(
            request, "Pago sin verificar", "El pago consultado no coincide con este intento.", "warning", 404
        )

    status = payment.get("status")
    if status in ("in_process", "authorized"):
        status = "pending"
    if isinstance(status, str) and status in PAYMENT_RESULTS:
        response = result_page(request, *PAYMENT_RESULTS[status])
        if status == "approved" and cart_revision and cart_revision == cart_state(request)[1]:
            response.delete_cookie(CART_COOKIE)
        return response
    return result_page(
        request, "Pago sin confirmar", "Mercado Pago devolvió un estado sin confirmación.", "warning"
    )
