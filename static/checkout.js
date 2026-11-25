const cartForm = document.querySelector(".product-actions");
const addButton = cartForm.querySelector(".add-button");
const counter = cartForm.querySelector(".cart-quantity");
const quantity = counter.querySelector("output");
const [decreaseButton, increaseButton] = counter.querySelectorAll("button");
const total = document.getElementById("cart-total-value");
const cartError = document.getElementById("cart-error");
const wallet = document.getElementById("wallet-brick");
const checkoutForm = document.getElementById("checkout-form");
const checkoutUrl = new URL(checkoutForm.action);
const payButton = checkoutForm.querySelector("button");
const notice = document.getElementById("checkout-error");

let cartUpdating = false;
let walletState = "idle";

function refreshCheckout() {
  const hasItems = Number(quantity.value) > 0;
  payButton.disabled = !hasItems || cartUpdating;
  if (!wallet) return;

  const ready = walletState === "ready";
  wallet.hidden = !hasItems || walletState === "failed";
  wallet.inert = cartUpdating || !ready;
  wallet.classList.toggle("wallet-pending", !ready);
  checkoutForm.hidden = hasItems && ready;
  notice.hidden = !hasItems || walletState !== "failed";

  if (hasItems && walletState === "idle") {
    walletState = "loading";
    renderWallet();
  }
}

cartForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (cartUpdating) return;
  cartUpdating = true;
  cartForm.setAttribute("aria-busy", "true");
  cartError.hidden = true;
  refreshCheckout();

  try {
    const action = event.submitter?.getAttribute("formaction") || cartForm.action;
    const response = await fetch(action, { method: "POST", headers: { Accept: "application/json" } });
    if (response.redirected) {
      window.location.reload();
      return;
    }
    if (!response.ok) throw new Error("No se pudo actualizar el carrito");

    const cart = await response.json();
    const focused = document.activeElement;
    quantity.value = cart.quantity;
    total.textContent = cart.total;
    checkoutUrl.searchParams.set("revision", cart.revision);
    checkoutForm.action = checkoutUrl.href;
    addButton.hidden = cart.quantity > 0;
    counter.hidden = cart.quantity === 0;
    increaseButton.disabled = cart.quantity >= Number(cartForm.dataset.maxQuantity);

    if (addButton.hidden && focused === addButton) {
      increaseButton.focus({ preventScroll: true });
    } else if (counter.hidden && counter.contains(focused)) {
      addButton.focus({ preventScroll: true });
    } else if (increaseButton.disabled && focused === increaseButton) {
      decreaseButton.focus({ preventScroll: true });
    }
  } catch {
    cartError.hidden = false;
  } finally {
    cartUpdating = false;
    cartForm.removeAttribute("aria-busy");
    refreshCheckout();
  }
});

function showFallback() {
  walletState = "failed";
  refreshCheckout();
}

async function createPreference() {
  try {
    const response = await fetch(checkoutForm.action, {
      method: "POST",
      headers: { Accept: "application/json" },
    });
    if (response.redirected) {
      window.location.reload();
      throw new Error("El carrito cambió");
    }
    if (!response.ok) {
      throw new Error("No se pudo crear la preferencia");
    }
    const { preference_id } = await response.json();
    return preference_id;
  } catch (error) {
    showFallback();
    throw error;
  }
}

async function renderWallet() {
  try {
    if (!window.MercadoPago) {
      await new Promise((resolve, reject) => {
        const sdk = document.createElement("script");
        sdk.src = "https://sdk.mercadopago.com/js/v2";
        sdk.onload = resolve;
        sdk.onerror = reject;
        document.head.append(sdk);
      });
    }
    const mp = new window.MercadoPago(wallet.dataset.publicKey);
    await mp.bricks().create("wallet", wallet.id, {
      customization: {
        customStyle: { borderRadius: "10px" },
      },
      callbacks: {
        onReady: () => {
          walletState = "ready";
          refreshCheckout();
        },
        onSubmit: createPreference,
        onError: showFallback,
      },
    });
  } catch {
    showFallback();
  }
}

refreshCheckout();
