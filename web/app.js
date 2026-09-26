let savedCustomer = null;
try { savedCustomer = JSON.parse(localStorage.getItem("el_molino_customer") || "null"); } catch { localStorage.removeItem("el_molino_customer"); }
const state = { phone: "", token: localStorage.getItem("el_molino_token"), customer: savedCustomer };
const openedCampaigns = new Set();
const loginView = document.querySelector("#login-view"), clubView = document.querySelector("#club-view");
const message = document.querySelector("#login-message");

function showMessage(text, error = false) { message.textContent = text; message.classList.toggle("error", error); }
function headers() { return { "Content-Type": "application/json", Authorization: `Bearer ${state.token}` }; }
async function request(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(typeof data.detail === "string" ? data.detail : "No fue posible completar la solicitud.");
    error.status = response.status;
    throw error;
  }
  return data;
}
function setSession(session) {
  state.token = session.access_token; state.customer = session.customer;
  localStorage.setItem("el_molino_token", state.token); localStorage.setItem("el_molino_customer", JSON.stringify(state.customer));
}
function clearSession() { localStorage.removeItem("el_molino_token"); localStorage.removeItem("el_molino_customer"); state.token = null; state.customer = null; openedCampaigns.clear(); }
const sessionRetry = document.querySelector("#session-retry");
sessionRetry.addEventListener("click", showClub);

document.querySelector("#phone-form").addEventListener("submit", async (event) => {
  event.preventDefault(); state.phone = document.querySelector("#phone").value.trim(); showMessage("Enviando código…");
  try {
    await request("/auth/request-code", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ phone: state.phone }) });
    document.querySelector("#phone-form").hidden = true; document.querySelector("#code-form").hidden = false; document.querySelector("#code").focus();
    showMessage("Revisa el SMS con tu código de acceso.");
  } catch (error) { showMessage(error.message, true); }
});
document.querySelector("#code-form").addEventListener("submit", async (event) => {
  event.preventDefault(); showMessage("Verificando…");
  try {
    setSession(await request("/auth/verify-code", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ phone: state.phone, code: document.querySelector("#code").value }) }));
    await showClub();
  } catch (error) { showMessage(error.message, true); }
});
document.querySelector("#change-phone").addEventListener("click", () => { document.querySelector("#code-form").hidden = true; document.querySelector("#phone-form").hidden = false; showMessage(""); });
document.querySelector("#show-registration").addEventListener("click", () => {
  document.querySelector("#phone-form").hidden = true;
  document.querySelector("#code-form").hidden = true;
  document.querySelector("#show-registration").hidden = true;
  document.querySelector("#registration-form").hidden = false;
  document.querySelector("#back-to-login").hidden = false;
  showMessage("");
});
document.querySelector("#back-to-login").addEventListener("click", () => {
  document.querySelector("#registration-form").hidden = true;
  document.querySelector("#registration-code-form").hidden = true;
  document.querySelector("#back-to-login").hidden = true;
  document.querySelector("#phone-form").hidden = false;
  document.querySelector("#show-registration").hidden = false;
  showMessage("");
});
document.querySelector("#registration-form").addEventListener("submit", async (event) => {
  event.preventDefault(); showMessage("Enviando código…");
  state.registrationPhone = document.querySelector("#registration-phone").value.trim();
  try {
    await request("/auth/register/request-code", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ phone: state.registrationPhone }) });
    document.querySelector("#registration-form").hidden = true;
    document.querySelector("#registration-code-form").hidden = false;
    document.querySelector("#registration-code").focus();
    showMessage("Revisa el SMS con tu código de registro.");
  } catch (error) { showMessage(error.message, true); }
});
document.querySelector("#registration-code-form").addEventListener("submit", async (event) => {
  event.preventDefault(); showMessage("Creando tu cuenta…");
  try {
    const session = await request("/auth/register/verify-code", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
      phone: state.registrationPhone,
      code: document.querySelector("#registration-code").value,
      full_name: document.querySelector("#registration-name").value.trim(),
      marketing_consent: document.querySelector("#registration-consent").checked,
    }) });
    setSession(session); await showClub();
  } catch (error) { showMessage(error.message, true); }
});
document.querySelector("#logout").addEventListener("click", () => { clearSession(); clubView.hidden = true; loginView.hidden = false; });
document.querySelector("#profile-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const notice = document.querySelector("#profile-message"); notice.textContent = "Guardando…"; notice.classList.remove("error");
  try {
    const customer = await request(`/customers/${state.customer.id}`, { method: "PATCH", headers: headers(), body: JSON.stringify({ full_name: document.querySelector("#profile-name").value, email: document.querySelector("#profile-email").value || null, marketing_consent: document.querySelector("#marketing-consent").checked }) });
    await request(`/customers/${state.customer.id}/profile`, { method: "PATCH", headers: headers(), body: JSON.stringify({ preferred_channel: document.querySelector("#preferred-channel").value || null }) });
    state.customer = customer; localStorage.setItem("el_molino_customer", JSON.stringify(customer)); document.querySelector("#customer-name").textContent = customer.full_name; notice.textContent = "Perfil guardado.";
  } catch (error) { notice.textContent = error.message; notice.classList.add("error"); }
});

async function showClub() {
  sessionRetry.hidden = true;
  try {
    const customer = await request(`/customers/${state.customer.id}`, { headers: headers() });
    const points = await request(`/customers/${state.customer.id}/points`, { headers: headers() });
    const rewards = await request(`/customers/${state.customer.id}/rewards`, { headers: headers() });
    const purchases = await request(`/customers/${state.customer.id}/purchases`, { headers: headers() });
    const redemptions = await request(`/customers/${state.customer.id}/redemptions`, { headers: headers() });
    const campaigns = await request(`/customers/${state.customer.id}/campaigns`, { headers: headers() });
    const profile = await request(`/customers/${state.customer.id}/profile`, { headers: headers() });
    state.customer = customer; localStorage.setItem("el_molino_customer", JSON.stringify(customer));
    document.querySelector("#customer-name").textContent = customer.full_name;
    document.querySelector("#points-balance").textContent = points.balance;
    document.querySelector("#profile-name").value = customer.full_name; document.querySelector("#profile-email").value = customer.email || "";
    document.querySelector("#marketing-consent").checked = customer.marketing_consent; document.querySelector("#preferred-channel").value = profile.preferred_channel || "";
    renderCampaigns(campaigns); renderRewards(rewards, points.balance); renderPurchases(purchases); renderRedemptions(redemptions); loginView.hidden = true; clubView.hidden = false; showMessage("");
    request(`/customers/${customer.id}/events`, { method: "POST", headers: headers(), body: JSON.stringify({ event_type: "app_open" }) }).catch(() => {});
  } catch (error) {
    loginView.hidden = false; clubView.hidden = true;
    if (error.status === 401 || error.status === 403) {
      clearSession();
      showMessage("Tu sesión terminó. Ingresa de nuevo.", true);
    } else {
      showMessage("No pudimos cargar tu Club. Revisa tu conexión e inténtalo de nuevo.", true);
      sessionRetry.hidden = false;
    }
  }
}
function renderCampaigns(campaigns) {
  const section = document.querySelector("#campaign-section"), container = document.querySelector("#campaigns"); container.replaceChildren(); section.hidden = !campaigns.length;
  campaigns.forEach((campaign) => {
    const item = document.createElement("article"); item.className = "campaign";
    const channel = document.createElement("p"); channel.className = "eyebrow"; channel.textContent = campaign.channel;
    const title = document.createElement("h3"); title.textContent = campaign.name;
    const message = document.createElement("p"); message.textContent = campaign.message || "Tenemos una sorpresa para ti.";
    const interest = document.createElement("button"); interest.type = "button"; interest.textContent = "Me interesa";
    interest.addEventListener("click", async () => {
      interest.disabled = true;
      try {
        await request(`/customers/${state.customer.id}/campaigns/${campaign.id}/events`, { method: "POST", headers: headers(), body: JSON.stringify({ event_type: "clicked" }) });
        interest.textContent = "Gracias por tu interés";
      } catch (error) { interest.disabled = false; interest.textContent = "Intentar de nuevo"; }
    });
    item.append(channel, title, message, interest); container.append(item);
    if (!openedCampaigns.has(campaign.id)) {
      openedCampaigns.add(campaign.id);
      request(`/customers/${state.customer.id}/campaigns/${campaign.id}/events`, { method: "POST", headers: headers(), body: JSON.stringify({ event_type: "opened" }) }).catch(() => openedCampaigns.delete(campaign.id));
    }
  });
}
function renderRewards(rewards, balance) {
  const container = document.querySelector("#rewards"), notice = document.querySelector("#rewards-message"); container.replaceChildren(); notice.textContent = "";
  if (!rewards.length) { notice.textContent = "Pronto habrá rewards disponibles."; return; }
  rewards.forEach((reward) => {
    const item = document.createElement("article"); item.className = "reward";
    const details = document.createElement("div");
    const title = document.createElement("h3"); title.textContent = reward.name;
    const description = document.createElement("p"); description.textContent = reward.description || "Disfruta este beneficio en tu próxima visita.";
    const cost = document.createElement("strong"); cost.textContent = `${reward.points_cost} puntos`;
    details.append(title, description, cost); item.append(details);
    const button = document.createElement("button"); button.textContent = balance >= reward.points_cost ? "Canjear" : "Aún no alcanza"; button.disabled = balance < reward.points_cost;
    button.onclick = async () => { if (!confirm(`¿Canjear ${reward.name} por ${reward.points_cost} puntos?`)) return; try { await request(`/customers/${state.customer.id}/rewards/${reward.id}/redeem`, { method: "POST", headers: headers() }); await showClub(); } catch (error) { notice.textContent = error.message; notice.classList.add("error"); } };
    item.append(button); container.append(item);
  });
}
function renderPurchases(purchases) {
  const container = document.querySelector("#purchases"); container.replaceChildren();
  if (!purchases.length) { container.textContent = "Tus compras aparecerán aquí después de registrar un ticket en caja."; return; }
  const money = new Intl.NumberFormat("es-MX", { style: "currency", currency: "MXN" });
  const date = new Intl.DateTimeFormat("es-MX", { day: "numeric", month: "long", year: "numeric", timeZone: "America/Mexico_City" });
  purchases.forEach((purchase) => {
    const card = document.createElement("article"); card.className = "purchase";
    const heading = document.createElement("div"); heading.className = "purchase-heading";
    const title = document.createElement("h3");
    const timestamp = purchase.purchased_at.endsWith("Z") || /[+-]\d\d:\d\d$/.test(purchase.purchased_at) ? purchase.purchased_at : `${purchase.purchased_at}Z`;
    title.textContent = date.format(new Date(timestamp));
    const amount = document.createElement("strong"); amount.textContent = money.format(Number(purchase.total_amount));
    heading.append(title, amount);
    const products = document.createElement("p"); products.className = "purchase-products";
    products.textContent = purchase.items.map((item) => `${Number(item.quantity)} × ${item.product_name}`).join(" · ");
    const points = document.createElement("span"); points.className = "purchase-points";
    points.textContent = `+${purchase.points_earned} puntos`;
    card.append(heading, products, points); container.append(card);
  });
}
function renderRedemptions(redemptions) {
  const container = document.querySelector("#redemptions"); container.replaceChildren();
  if (!redemptions.length) { container.textContent = "Todavía no has canjeado un reward."; return; }
  redemptions.forEach((redemption) => {
    const item = document.createElement("article"); item.className = "reward";
    const details = document.createElement("div");
    const title = document.createElement("h3"); title.textContent = redemption.reward_name;
    const status = document.createElement("p"); status.textContent = redemption.status === "fulfilled" ? "Entregado" : "Muestra este código en caja";
    const code = document.createElement("strong"); code.textContent = redemption.id;
    details.append(title, status, code); item.append(details); container.append(item);
  });
}
if (location.protocol === "file:") showMessage("Vista previa. Para iniciar sesión, abre Club.bat y visita http://127.0.0.1:8000/.");
else if (state.token && state.customer) showClub();
if (location.protocol !== "file:" && "serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js");
