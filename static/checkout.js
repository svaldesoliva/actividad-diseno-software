const wallet = document.getElementById("wallet-brick");
const form = document.getElementById("checkout-form");
const notice = document.getElementById("checkout-error");

function showFallback() {
  wallet.hidden = true;
  form.hidden = false;
  notice.hidden = false;
}

async function createPreference() {
  try {
    const response = await fetch(form.action, {
      method: "POST",
      headers: { Accept: "application/json" },
    });
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
    const mp = new window.MercadoPago(wallet.dataset.publicKey);
    await mp.bricks().create("wallet", wallet.id, {
      callbacks: {
        onReady: () => { form.hidden = !wallet.hidden; },
        onSubmit: createPreference,
        onError: showFallback,
      },
    });
  } catch {
    showFallback();
  }
}

renderWallet();
