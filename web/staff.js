let selectedCustomer = null;
let inspectedRedemption = null;
const byId = (id) => document.getElementById(id);
if (location.protocol === "file:") byId("staff-file-notice").hidden = false;

function setMessage(id, value, error = false) {
  const element = byId(id);
  element.textContent = value;
  element.classList.toggle("error", error);
}

async function apiRequest(path, keyId, keyHeader, options = {}) {
  const key = byId(keyId).value.trim();
  if (!key) throw new Error("Introduce la clave correspondiente.");
  const response = await fetch(path, {
    ...options,
    cache: "no-store",
    headers: { "Content-Type": "application/json", [keyHeader]: key },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(typeof data.detail === "string" ? data.detail : "No fue posible completar la solicitud.");
    error.status = response.status;
    throw error;
  }
  return data;
}

function managerRequest(path, options) { return apiRequest(path, "admin-key", "X-Admin-Key", options); }
function cashierRequest(path, options) { return apiRequest(path, "cashier-key", "X-Cashier-Key", options); }
function setSelectedCustomer(customer) {
  selectedCustomer = customer;
  byId("new-customer-section").hidden = true;
  byId("cashier-customer").hidden = false;
  byId("purchase-section").hidden = false;
  byId("cashier-name").textContent = customer.full_name;
  byId("cashier-points").textContent = customer.points_balance;
  byId("cashier-id").textContent = customer.id;
  loadCashierPurchases(customer.id);
}

async function loadCashierPurchases(customerId) {
  const section = byId("cashier-purchases"), list = byId("cashier-purchases-list");
  section.hidden = false; list.replaceChildren();
  setMessage("cashier-purchases-message", "Cargando tickets…");
  try {
    const purchases = await cashierRequest(`/cashier/customers/${customerId}/purchases`);
    if (selectedCustomer?.id !== customerId) return;
    if (!purchases.length) { setMessage("cashier-purchases-message", "Todavía no hay tickets registrados."); return; }
    setMessage("cashier-purchases-message", "");
    const money = new Intl.NumberFormat("es-MX", { style: "currency", currency: "MXN" });
    const date = new Intl.DateTimeFormat("es-MX", { day: "numeric", month: "short", year: "numeric", timeZone: "America/Mexico_City" });
    purchases.forEach((purchase) => {
      const card = document.createElement("article"); card.className = "cashier-purchase";
      const title = document.createElement("strong"); title.textContent = purchase.external_reference || "Ticket sin número";
      const timestamp = purchase.purchased_at.endsWith("Z") || /[+-]\d\d:\d\d$/.test(purchase.purchased_at) ? purchase.purchased_at : `${purchase.purchased_at}Z`;
      const detail = document.createElement("p"); detail.textContent = `${date.format(new Date(timestamp))} · ${money.format(Number(purchase.total_amount))} · +${purchase.points_earned} puntos`;
      const products = document.createElement("p"); products.textContent = purchase.items.map((item) => `${Number(item.quantity)} × ${item.product_name}`).join(" · ");
      card.append(title, detail, products); list.append(card);
    });
  } catch (error) {
    if (selectedCustomer?.id === customerId) setMessage("cashier-purchases-message", error.message, true);
  }
}

byId("lookup-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  selectedCustomer = null;
  byId("cashier-customer").hidden = true;
  byId("cashier-purchases").hidden = true;
  byId("purchase-section").hidden = true;
  byId("new-customer-section").hidden = true;
  setMessage("lookup-message", "Buscando…");
  try {
    const phone = byId("lookup-phone").value.trim();
    const customer = await cashierRequest(`/cashier/customers?phone=${encodeURIComponent(phone)}`);
    setSelectedCustomer(customer);
    setMessage("lookup-message", "Cliente encontrado.");
  } catch (error) {
    if (error.status === 404) {
      byId("new-customer-phone").value = byId("lookup-phone").value.trim();
      byId("new-customer-section").hidden = false;
      setMessage("lookup-message", "Cliente no encontrado. Puedes registrarlo abajo.");
      byId("new-customer-name").focus();
    } else {
      setMessage("lookup-message", error.message, true);
    }
  }
});

byId("new-customer-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  setMessage("new-customer-message", "Registrando…");
  const phone = byId("new-customer-phone").value.trim();
  try {
    const customer = await cashierRequest("/customers", { method: "POST", body: JSON.stringify({
      full_name: byId("new-customer-name").value.trim(),
      phone,
      marketing_consent: byId("new-customer-consent").checked,
    }) });
    byId("lookup-phone").value = phone;
    setSelectedCustomer({ ...customer, points_balance: 0 });
    byId("new-customer-form").reset();
    setMessage("lookup-message", "Cliente registrado. Ya puedes registrar su compra.");
    setMessage("new-customer-message", "");
  } catch (error) { setMessage("new-customer-message", error.message, true); }
});

const purchaseItems = byId("purchase-items");

function purchaseLineCents(quantity, price) {
  const unitsThousandths = Math.round(Number(quantity) * 1000);
  const priceCents = Math.round(Number(price) * 100);
  return Math.round(unitsThousandths * priceCents / 1000);
}

function updatePurchaseTotal() {
  let cents = 0;
  purchaseItems.querySelectorAll(".purchase-item").forEach((row) => {
    const quantity = Number(row.querySelector(".item-quantity").value);
    const price = Number(row.querySelector(".item-price").value);
    if (Number.isFinite(quantity) && quantity > 0 && Number.isFinite(price) && price >= 0) {
      cents += purchaseLineCents(quantity, price);
    }
  });
  byId("purchase-total").textContent = `${(cents / 100).toFixed(2)} MXN`;
  return cents;
}

function refreshPurchaseRows() {
  const rows = [...purchaseItems.querySelectorAll(".purchase-item")];
  rows.forEach((row, index) => {
    row.querySelector(".purchase-item-heading strong").textContent = `Producto ${index + 1}`;
    row.querySelector(".remove-purchase-item").hidden = rows.length === 1;
  });
  updatePurchaseTotal();
}

function addPurchaseItem() {
  purchaseItems.append(byId("purchase-item-template").content.cloneNode(true));
  refreshPurchaseRows();
}

byId("add-purchase-item").addEventListener("click", () => {
  addPurchaseItem();
  purchaseItems.lastElementChild.querySelector(".item-product").focus();
});
purchaseItems.addEventListener("input", updatePurchaseTotal);
purchaseItems.addEventListener("click", (event) => {
  const removeButton = event.target.closest(".remove-purchase-item");
  if (!removeButton || purchaseItems.children.length === 1) return;
  removeButton.closest(".purchase-item").remove();
  refreshPurchaseRows();
});
addPurchaseItem();

byId("purchase-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!selectedCustomer) return;
  const rows = [...purchaseItems.querySelectorAll(".purchase-item")];
  const items = rows.map((row) => {
    const quantity = row.querySelector(".item-quantity").value;
    const unitPrice = row.querySelector(".item-price").value;
    const lineCents = purchaseLineCents(quantity, unitPrice);
    return {
      product_name: row.querySelector(".item-product").value.trim(),
      quantity,
      unit_price: unitPrice,
      line_total: (lineCents / 100).toFixed(2),
    };
  });
  if (!items.length || items.some((item) => !item.product_name || !Number.isFinite(Number(item.line_total)))) {
    setMessage("purchase-message", "Revisa los productos del ticket.", true);
    return;
  }
  const body = {
    external_reference: byId("ticket").value.trim(),
    total_amount: (updatePurchaseTotal() / 100).toFixed(2),
    items,
  };
  setMessage("purchase-message", "Registrando…");
  byId("purchase-submit").disabled = true;
  try {
    const purchase = await cashierRequest(`/customers/${selectedCustomer.id}/purchases`, { method: "POST", body: JSON.stringify(body) });
    setMessage("purchase-message", `Ticket procesado. ${purchase.points_earned} puntos asociados. ID: ${purchase.id}`);
    setSelectedCustomer(await cashierRequest(`/cashier/customers?phone=${encodeURIComponent(byId("lookup-phone").value.trim())}`));
    byId("purchase-form").reset();
    purchaseItems.replaceChildren();
    addPurchaseItem();
  } catch (error) { setMessage("purchase-message", error.message, true); }
  finally { byId("purchase-submit").disabled = false; }
});

function showRedemption(redemption) {
  inspectedRedemption = redemption;
  byId("redemption-details").hidden = false;
  byId("redemption-reward").textContent = redemption.reward_name;
  byId("redemption-customer").textContent = redemption.customer_name;
  byId("redemption-status").textContent = redemption.status === "fulfilled" ? "Ya entregado" : "Pendiente de entrega";
  byId("fulfill-redemption").disabled = redemption.status !== "redeemed";
}

byId("redemption-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  inspectedRedemption = null;
  byId("redemption-details").hidden = true;
  setMessage("redemption-message", "Verificando…");
  try {
    const code = byId("redemption-code").value.trim();
    const redemption = await cashierRequest(`/cashier/redemptions/${encodeURIComponent(code)}`);
    showRedemption(redemption);
    setMessage("redemption-message", "Canje encontrado.");
  } catch (error) { setMessage("redemption-message", error.message, true); }
});

byId("fulfill-redemption").addEventListener("click", async () => {
  if (!inspectedRedemption || inspectedRedemption.status !== "redeemed") return;
  if (!confirm(`¿Entregar ${inspectedRedemption.reward_name} a ${inspectedRedemption.customer_name}?`)) return;
  setMessage("redemption-message", "Confirmando…");
  try {
    const redemption = await cashierRequest(`/cashier/redemptions/${encodeURIComponent(inspectedRedemption.id)}/fulfill`, { method: "POST" });
    showRedemption(redemption);
    setMessage("redemption-message", "Entrega confirmada.");
  } catch (error) { setMessage("redemption-message", error.message, true); }
});

function renderResults(rows, formatter) {
  const container = byId("manager-results");
  container.replaceChildren();
  if (!rows.length) { container.textContent = "No hay resultados."; return; }
  rows.forEach((row) => {
    const card = document.createElement("article");
    card.className = "staff-result";
    const heading = document.createElement("strong");
    const description = document.createElement("p");
    const [title, detail] = formatter(row);
    heading.textContent = title; description.textContent = detail;
    card.append(heading, description); container.append(card);
  });
}

byId("load-audience").addEventListener("click", async () => {
  setMessage("manager-message", "Cargando…");
  try {
    const rows = await managerRequest(`/admin/audiences?segment=${encodeURIComponent(byId("segment").value)}`);
    renderResults(rows, (row) => [row.full_name, `${row.purchase_count} compras · ${row.points_balance} puntos · ${row.total_spend} MXN`]);
    setMessage("manager-message", `${rows.length} clientes en el segmento.`);
  } catch (error) { setMessage("manager-message", error.message, true); }
});

byId("load-actions").addEventListener("click", async () => {
  setMessage("manager-message", "Cargando…");
  try {
    const rows = await managerRequest("/admin/next-best-actions");
    renderResults(rows, (row) => [row.full_name, `${row.reason} ${row.suggested_message}`]);
    setMessage("manager-message", `${rows.length} recomendaciones.`);
  } catch (error) { setMessage("manager-message", error.message, true); }
});

byId("reward-form").addEventListener("submit", async (event) => {
  event.preventDefault(); setMessage("reward-message", "Guardando…");
  try {
    const reward = await managerRequest("/admin/rewards", { method: "POST", body: JSON.stringify({ name: byId("reward-name").value.trim(), points_cost: Number(byId("reward-cost").value) }) });
    setMessage("reward-message", `Reward creado: ${reward.name}.`);
    byId("reward-form").reset();
  } catch (error) { setMessage("reward-message", error.message, true); }
});

byId("campaign-form").addEventListener("submit", async (event) => {
  event.preventDefault(); setMessage("campaign-message", "Guardando…");
  try {
    const campaign = await managerRequest("/admin/campaigns/by-segment", { method: "POST", body: JSON.stringify({ name: byId("campaign-name").value.trim(), channel: byId("campaign-channel").value, segment: byId("segment").value, message: byId("campaign-text").value.trim() }) });
    setMessage("campaign-message", `Borrador creado para ${campaign.recipient_count} clientes. ID: ${campaign.id}`);
    byId("campaign-form").reset();
    await loadCampaigns();
  } catch (error) { setMessage("campaign-message", error.message, true); }
});

async function loadCampaigns() {
  setMessage("campaign-list-message", "Cargando…");
  try {
    const campaigns = await managerRequest("/admin/campaigns");
    const container = byId("campaign-list"); container.replaceChildren();
    if (!campaigns.length) container.textContent = "No hay campañas.";
    campaigns.forEach((campaign) => {
      const card = document.createElement("article"); card.className = "staff-result";
      const name = document.createElement("strong"); name.textContent = campaign.name;
      const detail = document.createElement("p"); detail.textContent = `${campaign.status} · ${campaign.channel} · ${campaign.recipient_count} destinatarios`;
      const stats = document.createElement("p");
      const statsButton = document.createElement("button"); statsButton.type = "button"; statsButton.textContent = "Ver resultados";
      statsButton.addEventListener("click", async () => {
        try {
          const result = await managerRequest(`/admin/campaigns/${campaign.id}/analytics`);
          stats.textContent = `${result.opened_count} aperturas · ${result.clicked_count} clics`;
        } catch (error) { setMessage("campaign-list-message", error.message, true); }
      });
      card.append(name, detail, statsButton, stats);
      if (campaign.status !== "active") {
        const activate = document.createElement("button"); activate.type = "button"; activate.className = "secondary"; activate.textContent = "Activar";
        activate.addEventListener("click", async () => {
          if (!confirm(`¿Activar la campaña ${campaign.name}?`)) return;
          try {
            await managerRequest(`/admin/campaigns/${campaign.id}/activate`, { method: "POST" });
            await loadCampaigns();
          } catch (error) { setMessage("campaign-list-message", error.message, true); }
        });
        card.append(activate);
      }
      container.append(card);
    });
    setMessage("campaign-list-message", `${campaigns.length} campañas.`);
  } catch (error) { setMessage("campaign-list-message", error.message, true); }
}
byId("load-campaigns").addEventListener("click", loadCampaigns);
