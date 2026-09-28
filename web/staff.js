let selectedCustomer = null;
let inspectedRedemption = null;
let loadedWansoftTicketId = null;
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
  resetWansoftPreview();
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

function resetWansoftPreview() {
  loadedWansoftTicketId = null;
  byId("wansoft-preview").hidden = true;
  byId("wansoft-items").replaceChildren();
}

byId("ticket").addEventListener("input", () => { resetWansoftPreview(); setMessage("wansoft-message", ""); });
byId("load-wansoft-ticket").addEventListener("click", async () => {
  resetWansoftPreview();
  const ticketId = byId("ticket").value.trim();
  const customerId = selectedCustomer?.id;
  if (!/^\d+$/.test(ticketId) || Number(ticketId) < 1) {
    setMessage("wansoft-message", "Introduce el número de ticket Wansoft.", true);
    return;
  }
  setMessage("wansoft-message", "Buscando ticket…");
  try {
    const ticket = await cashierRequest(`/cashier/wansoft-tickets/${encodeURIComponent(ticketId)}`);
    if (byId("ticket").value.trim() !== ticketId || selectedCustomer?.id !== customerId) return;
    loadedWansoftTicketId = ticketId;
    const money = new Intl.NumberFormat("es-MX", { style: "currency", currency: "MXN" });
    const day = ticket.purchased_at.slice(0, 10).split("-").reverse().join("/");
    byId("wansoft-summary").textContent = `${ticket.sucursal} · ${day} · ${money.format(Number(ticket.total_amount))} · ${ticket.items.length} productos`;
    const list = byId("wansoft-items");
    ticket.items.forEach((item) => {
      const row = document.createElement("li");
      row.textContent = `${Number(item.quantity)} × ${item.product_name} · ${money.format(Number(item.line_total))}`;
      list.append(row);
    });
    byId("wansoft-preview").hidden = false;
    setMessage("wansoft-message", "Revisa el ticket y asígnalo al cliente.");
  } catch (error) { setMessage("wansoft-message", error.message, true); }
});

byId("assign-wansoft-ticket").addEventListener("click", async () => {
  const ticketId = loadedWansoftTicketId;
  const customerId = selectedCustomer?.id;
  if (!ticketId || !customerId || byId("ticket").value.trim() !== ticketId) return;
  byId("assign-wansoft-ticket").disabled = true;
  setMessage("wansoft-message", "Asignando puntos…");
  try {
    const purchase = await cashierRequest(`/cashier/customers/${customerId}/wansoft-tickets/${encodeURIComponent(ticketId)}`, { method: "POST" });
    setMessage("purchase-message", `Ticket Wansoft ${ticketId}: ${purchase.points_earned} puntos asociados.`);
    byId("purchase-form").reset();
    purchaseItems.replaceChildren(); addPurchaseItem();
    setSelectedCustomer(await cashierRequest(`/cashier/customers?phone=${encodeURIComponent(byId("lookup-phone").value.trim())}`));
    setMessage("wansoft-message", "");
  } catch (error) { setMessage("wansoft-message", error.message, true); }
  finally { byId("assign-wansoft-ticket").disabled = false; }
});

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
    resetWansoftPreview();
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

let reconciliationRows = [];
const reconciliationLabels = {
  pending_import: "Pendiente de importar",
  amount_mismatch: "Importe diferente",
  items_mismatch: "Productos diferentes",
  unverifiable: "Número no verificable",
};

function visibleReconciliationRows() {
  const filter = byId("reconciliation-filter").value;
  return reconciliationRows.filter((row) => row.status !== "matched" && (filter === "all" || row.status === filter));
}

function renderReconciliation() {
  const container = byId("reconciliation-results"); container.replaceChildren();
  const review = reconciliationRows.filter((row) => row.status !== "matched");
  const visible = visibleReconciliationRows();
  const verified = reconciliationRows.length - review.length;
  setMessage("reconciliation-message", `${verified} de ${reconciliationRows.length} tickets coinciden. ${review.length} requieren revisión. Mostrando ${visible.length}.`);
  byId("export-reconciliation").disabled = visible.length === 0;
  if (!visible.length && review.length) container.textContent = "No hay tickets en este filtro.";
  const money = new Intl.NumberFormat("es-MX", { style: "currency", currency: "MXN" });
  visible.forEach((row) => {
      const card = document.createElement("article");
      card.className = `staff-result reconciliation-result ${row.status}`;
      const badge = document.createElement("span"); badge.className = "reconciliation-badge";
      badge.textContent = reconciliationLabels[row.status] || "Revisar";
      const title = document.createElement("strong"); title.textContent = `Ticket ${row.external_reference}`;
      const detail = document.createElement("p");
      const actual = row.wansoft_amount === null ? "sin venta Wansoft cargada" : `Wansoft ${money.format(Number(row.wansoft_amount))}`;
      detail.textContent = `${row.customer_name} · acreditado ${money.format(Number(row.credited_amount))} · ${actual}`;
      card.append(badge, title, detail);
      if (row.item_differences?.length) {
        const differences = document.createElement("ul"); differences.className = "reconciliation-differences";
        row.item_differences.forEach((difference) => {
          const item = document.createElement("li"); item.textContent = difference; differences.append(item);
        });
        card.append(differences);
      }
      container.append(card);
  });
}

function csvCell(value) {
  let text = String(value ?? "");
  if (/^[\s\u0000-\u001f]*[=+\-@]/.test(text)) text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
}

byId("reconciliation-filter").addEventListener("change", renderReconciliation);
byId("export-reconciliation").addEventListener("click", () => {
  const rows = visibleReconciliationRows();
  if (!rows.length) return;
  const columns = ["Ticket", "Estado", "Cliente", "Fecha", "Acreditado MXN", "Wansoft MXN", "Diferencias de productos"];
  const lines = [columns, ...rows.map((row) => [row.external_reference, reconciliationLabels[row.status] || row.status,
    row.customer_name, row.purchased_at, row.credited_amount, row.wansoft_amount ?? "",
    (row.item_differences || []).join(" | ")])];
  const blob = new Blob(["\uFEFF", lines.map((line) => line.map(csvCell).join(",")).join("\r\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url; link.download = `el-molino-tickets-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

byId("load-reconciliation").addEventListener("click", async () => {
  setMessage("reconciliation-message", "Comparando tickets…");
  byId("reconciliation-tools").hidden = true;
  byId("reconciliation-results").replaceChildren();
  reconciliationRows = [];
  try {
    const rows = await managerRequest("/admin/wansoft-reconciliation");
    if (!rows.length) {
      setMessage("reconciliation-message", "Todavía no hay tickets acreditados.");
      return;
    }
    reconciliationRows = rows;
    byId("reconciliation-filter").value = "all";
    byId("reconciliation-tools").hidden = rows.every((row) => row.status === "matched");
    renderReconciliation();
  } catch (error) { setMessage("reconciliation-message", error.message, true); }
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
        const previewButton = document.createElement("button"); previewButton.type = "button"; previewButton.className = "secondary"; previewButton.textContent = "Revisar y activar";
        const previewBox = document.createElement("div"); previewBox.className = "campaign-preview"; previewBox.hidden = true;
        const previewCount = document.createElement("strong");
        const previewText = document.createElement("p");
        const previewNote = document.createElement("p"); previewNote.textContent = "La activación solo muestra la campaña en el Club. El envío de SMS requiere otra acción.";
        const activate = document.createElement("button"); activate.type = "button"; activate.textContent = "Activar en el Club";
        previewBox.append(previewCount, previewText, previewNote, activate);
        const showPreview = async () => {
          const preview = await managerRequest(`/admin/campaigns/${campaign.id}/preview`);
          previewCount.textContent = `${preview.eligible_count} destinatarios con consentimiento · ${preview.excluded_count} excluidos`;
          previewText.textContent = preview.message || "Sin mensaje";
          activate.disabled = preview.eligible_count === 0;
          previewBox.hidden = false;
          return preview;
        };
        previewButton.addEventListener("click", async () => {
          try { await showPreview(); }
          catch (error) { setMessage("campaign-list-message", error.message, true); }
        });
        activate.addEventListener("click", async () => {
          try {
            const preview = await showPreview();
            if (!preview.eligible_count || !confirm(`¿Mostrar ${campaign.name} a ${preview.eligible_count} clientes en el Club?`)) return;
            await managerRequest(`/admin/campaigns/${campaign.id}/activate`, { method: "POST" });
            await loadCampaigns();
          } catch (error) { setMessage("campaign-list-message", error.message, true); }
        });
        card.append(previewButton, previewBox);
      } else if (campaign.channel === "sms") {
        const previewButton = document.createElement("button"); previewButton.type = "button"; previewButton.className = "secondary"; previewButton.textContent = "Revisar envío SMS";
        const auditButton = document.createElement("button"); auditButton.type = "button"; auditButton.className = "secondary"; auditButton.textContent = "Ver estado de SMS";
        const auditBox = document.createElement("div"); auditBox.className = "campaign-audit"; auditBox.hidden = true;
        const auditSummary = document.createElement("p");
        const auditList = document.createElement("div"); auditList.className = "staff-results";
        const auditMore = document.createElement("button"); auditMore.type = "button"; auditMore.className = "secondary"; auditMore.textContent = "Mostrar más";
        auditBox.append(auditSummary, auditList, auditMore);
        let auditOffset = 0;
        const deliveryLabels = { accepted: "Aceptado por LabsMobile", uncertain: "Sin confirmación", invalid_phone: "Teléfono inválido", excluded: "Sin consentimiento vigente", seen_in_club: "Visto en el Club", pending: "Pendiente" };
        const loadAudit = async (reset = false) => {
          if (reset) { auditOffset = 0; auditList.replaceChildren(); }
          const report = await managerRequest(`/admin/campaigns/${campaign.id}/deliveries?offset=${auditOffset}`);
          report.rows.forEach((delivery) => {
            const row = document.createElement("div"); row.className = "campaign-audit-row";
            const customer = document.createElement("strong"); customer.textContent = `${delivery.customer_name} · ${delivery.phone_masked}`;
            const outcome = document.createElement("span"); outcome.textContent = deliveryLabels[delivery.status] || delivery.status;
            row.append(customer, outcome); auditList.append(row);
          });
          auditOffset += report.rows.length;
          auditSummary.textContent = `Mostrando ${auditOffset} de ${report.total_count} destinatarios.`;
          auditMore.hidden = auditOffset >= report.total_count;
          auditBox.hidden = false;
        };
        auditButton.addEventListener("click", async () => {
          try { await loadAudit(true); }
          catch (error) { setMessage("campaign-list-message", error.message, true); }
        });
        auditMore.addEventListener("click", async () => {
          try { await loadAudit(); }
          catch (error) { setMessage("campaign-list-message", error.message, true); }
        });
        const previewBox = document.createElement("div"); previewBox.className = "campaign-preview"; previewBox.hidden = true;
        const previewCount = document.createElement("strong");
        const previewText = document.createElement("p");
        const previewNote = document.createElement("p"); previewNote.textContent = "Cada envío puede generar cargos en LabsMobile. Los intentos sin confirmación no se reenvían automáticamente.";
        const sendButton = document.createElement("button"); sendButton.type = "button"; sendButton.textContent = "Enviar hasta 5 SMS";
        const sendResult = document.createElement("p");
        previewBox.append(previewCount, previewText, previewNote, sendButton, sendResult);
        const showPreview = async () => {
          const preview = await managerRequest(`/admin/campaigns/${campaign.id}/preview`);
          previewCount.textContent = `${preview.pending_sms_count} pendientes · ${preview.sent_sms_count} aceptados · ${preview.uncertain_sms_count} sin confirmación · ${preview.invalid_phone_count} teléfonos inválidos · ${preview.excluded_count} sin consentimiento vigente`;
          previewText.textContent = preview.message || "Sin mensaje";
          sendButton.disabled = preview.pending_sms_count === 0 || !preview.message || preview.message.length > 160;
          previewNote.textContent = preview.message?.length > 160
            ? "El SMS supera 160 caracteres; crea otra campaña con un texto más corto."
            : "Cada envío puede generar cargos en LabsMobile. Los intentos sin confirmación no se reenvían automáticamente.";
          previewBox.hidden = false;
          return preview;
        };
        previewButton.addEventListener("click", async () => {
          try { await showPreview(); }
          catch (error) { setMessage("campaign-list-message", error.message, true); }
        });
        sendButton.addEventListener("click", async () => {
          try {
            const preview = await showPreview();
            if (sendButton.disabled || !confirm(`¿Enviar hasta ${Math.min(preview.pending_sms_count, 5)} SMS de ${campaign.name}? Puede generar cargos.`)) return;
            sendButton.disabled = true;
            const result = await managerRequest(`/admin/campaigns/${campaign.id}/send-sms`, { method: "POST" });
            sendResult.textContent = `${result.sent} aceptados · ${result.uncertain} sin confirmación · ${result.invalid_phone} teléfonos inválidos · ${result.remaining} pendientes.`;
            await showPreview();
            if (!auditBox.hidden) await loadAudit(true);
          } catch (error) { setMessage("campaign-list-message", error.message, true); }
        });
        card.append(previewButton, auditButton, previewBox, auditBox);
      }
      container.append(card);
    });
    setMessage("campaign-list-message", `${campaigns.length} campañas.`);
  } catch (error) { setMessage("campaign-list-message", error.message, true); }
}
byId("load-campaigns").addEventListener("click", loadCampaigns);
