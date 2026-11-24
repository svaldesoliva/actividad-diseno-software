# Actividad Diseño de Software

Tienda de demostración para comprar una botella de Agua Vital con gas de 1,6 litros por $1.000 CLP. FastAPI sirve las páginas HTML, Bootstrap aporta el estilo base y Checkout Pro procesa el pago de prueba.

## Ejecutar en local

Desde la carpeta `actividad-mercado-pago`, con Python 3.11 o posterior:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python -m uvicorn main:app
```

Abre [http://127.0.0.1:8000](http://127.0.0.1:8000) para ver la tienda.

## Habilitar el pago de prueba

1. En Mercado Pago Developers, entra a **Tus integraciones** y crea una aplicación para Chile con **Checkout Pro**. En **Credenciales → Prueba**, copia el **Access Token** a `MP_TEST_ACCESS_TOKEN` y la **Public Key** a `MP_TEST_PUBLIC_KEY` en `.env`. El token permite a FastAPI crear la preferencia. La clave pública activa el botón oficial. [Cuentas de prueba](https://www.mercadopago.cl/developers/es/docs/checkout-pro-preferences/test-accounts?scope=prod) · [Botón oficial](https://www.mercadopago.cl/developers/es/docs/checkout-pro-preferences/web-integration/add-frontend-sdk)
2. Crea un comprador de prueba de Chile desde **Cuentas de prueba**. Usa esa cuenta al pagar.
3. Con FastAPI corriendo, abre un túnel HTTPS en otra terminal. Si usas Cloudflare Tunnel, instala `cloudflared` y ejecuta `cloudflared tunnel --url http://127.0.0.1:8000`. Copia la dirección HTTPS que imprime a `APP_BASE_URL` en `.env`, sin añadir ninguna ruta. Si el túnel cambia de dirección, actualiza ese valor. [Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/) · [URLs de retorno](https://www.mercadopago.cl/developers/es/docs/checkout-pro-preferences/configure-back-urls)
4. Reinicia FastAPI. En una ventana privada, inicia sesión en Mercado Pago con el valor del campo **Usuario** del comprador de prueba y su contraseña. Si Mercado Pago pide un código, usa el **Código de verificación** que aparece junto al usuario en el panel. Luego abre la tienda en esa misma pestaña y pulsa **Pagar con Mercado Pago**. Si la dirección termina en `/expired`, vuelve a la tienda en esa pestaña y pulsa el botón para abrir un checkout nuevo. [Inicio de sesión de compradores de prueba](https://www.mercadopago.cl/developers/es/docs/checkout-pro-preferences/integration-test/test-purchases)
5. Si tu comprador tiene guardada la **Mastercard de prueba terminada en 2580**, selecciónala, ingresa el código `123` y elige una cuota. Si agregas una tarjeta de prueba, escribe `APRO` como titular para aprobar o `OTHE` para rechazar. Tras la aprobación, **Volver a la tienda** abre la pantalla de resultado. [Tarjetas y escenarios de prueba](https://www.mercadopago.cl/developers/es/docs/checkout-pro-preferences/integration-test/test-purchases)

Guarda el token solo en el entorno del servidor. El archivo `.env` está excluido de Git.

## Qué ocurre al comprar

1. Wallet Brick, el botón oficial de Mercado Pago, envía `POST /comprar` a FastAPI al hacer clic.
2. FastAPI fija el producto, el precio y la cantidad y crea una preferencia con `POST /checkout/preferences`. El SDK recibe el ID de esa preferencia y abre Checkout Pro. Si el SDK no carga o falta la clave pública, el botón HTML abre directamente la URL de Checkout Pro que devuelve la misma API.
3. Al volver a `/resultado/{reference}`, FastAPI toma el ID de pago del retorno y consulta el estado a Mercado Pago. Comprueba que coincidan la referencia de compra, el monto y la moneda antes de mostrar el resultado.

El estado se consulta al regresar a la tienda. Si el pago sigue pendiente, puedes recargar la página de resultado para consultarlo otra vez.
