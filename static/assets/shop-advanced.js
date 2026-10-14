/* Account history, resilient device-local cart, and accessible navigation. */
'use strict';
const advancedText = {
  en: {
    account: 'My account', accountTitle: 'Your purchases & credits', orders: 'Orders', wallet: 'Credit activity',
    accountHint: 'Check order status here. Delivery details stay in your private Telegram chat.',
    refresh: 'Refresh', more: 'Load more', loading: 'Loading…', emptyOrders: 'Your orders will appear here after a purchase.',
    emptyWallet: 'No credit activity yet.', retry: 'Try again', availableOnly: 'Available only',
    sort: 'Sort products', featured: 'Recommended', priceAsc: 'Price: low to high', priceDesc: 'Price: high to low', name: 'Name: A–Z',
    delivery: 'Delivery type', deliveryAll: 'All delivery types', instant: 'Instant delivery', email: 'Email setup', manual: 'Prepared delivery', login_assist: 'Login assistance',
    reset: 'Clear filters', results: 'products', restored: 'Cart restored. Quantities updated to current availability.',
    allMethods: 'All methods', freeMethods: 'Free', paidMethods: 'Premium', ownedMethods: 'Unlocked',
    delivered: 'Delivered', awaiting_fulfillment: 'Awaiting setup', partially_delivered: 'Partially delivered',
    purchase: 'Product purchase', method_purchase: 'Method purchase', adjust: 'Balance adjustment', set: 'Balance adjustment',
    otp_purchase: 'OTP purchase', referral: 'Referral reward', creditActivity: 'Credit activity',
    offline: 'You are offline. Reconnect before purchasing.', online: 'Connection restored.', cartLimit: 'Your cart has reached its item limit.',
    payloadLimit: 'This cart is too large to send to Telegram. Remove a few items and try again.',
    clearCart: 'Empty cart', clearConfirm: 'Remove every item from your cart?', close: 'Close',
    loadFail: 'Could not load the shop. Check your connection and try again.', changeCart: 'Edit cart',
    balanceAfter: 'Balance after purchase', balanceLow: 'Not enough credits. Add credits before paying.',
    priceChanged: 'A price changed. Your cart has been refreshed; review it again before paying.'
  },
  id: {
    account: 'Akun saya', accountTitle: 'Pembelian & kredit Anda', orders: 'Pesanan', wallet: 'Aktivitas kredit',
    accountHint: 'Lihat status pesanan di sini. Detail pengiriman ada di chat Telegram pribadi Anda.',
    refresh: 'Muat ulang', more: 'Muat lebih banyak', loading: 'Memuat…', emptyOrders: 'Pesanan muncul di sini setelah pembelian.',
    emptyWallet: 'Belum ada aktivitas kredit.', retry: 'Coba lagi', availableOnly: 'Tersedia saja',
    sort: 'Urutkan produk', featured: 'Rekomendasi', priceAsc: 'Harga: rendah ke tinggi', priceDesc: 'Harga: tinggi ke rendah', name: 'Nama: A–Z',
    delivery: 'Jenis pengiriman', deliveryAll: 'Semua pengiriman', instant: 'Pengiriman instan', email: 'Setup email', manual: 'Pengiriman disiapkan', login_assist: 'Bantuan login',
    reset: 'Hapus filter', results: 'produk', restored: 'Keranjang dipulihkan. Jumlah disesuaikan dengan ketersediaan terbaru.',
    allMethods: 'Semua metode', freeMethods: 'Gratis', paidMethods: 'Premium', ownedMethods: 'Terbuka',
    delivered: 'Terkirim', awaiting_fulfillment: 'Menunggu setup', partially_delivered: 'Terkirim sebagian',
    purchase: 'Pembelian produk', method_purchase: 'Pembelian metode', adjust: 'Penyesuaian saldo', set: 'Penyesuaian saldo',
    otp_purchase: 'Pembelian OTP', referral: 'Hadiah referensi', creditActivity: 'Aktivitas kredit',
    offline: 'Anda offline. Hubungkan kembali sebelum membeli.', online: 'Koneksi pulih.', cartLimit: 'Keranjang sudah mencapai batas item.',
    payloadLimit: 'Keranjang terlalu besar untuk dikirim ke Telegram. Kurangi beberapa item.',
    clearCart: 'Kosongkan keranjang', clearConfirm: 'Hapus semua item dari keranjang?', close: 'Tutup',
    loadFail: 'Toko tidak dapat dimuat. Periksa koneksi Anda dan coba lagi.', changeCart: 'Edit keranjang',
    balanceAfter: 'Saldo setelah pembelian', balanceLow: 'Kredit tidak cukup. Tambah kredit sebelum membayar.',
    priceChanged: 'Harga berubah. Keranjang diperbarui; tinjau kembali sebelum membayar.'
  }
};
function ax(key) { return advancedText[lang]?.[key] || advancedText.en[key] || key; }
function byId(id) { return document.getElementById(id); }
function toast(message) {
  const box = byId('shopToast');
  box.textContent = message; box.hidden = false;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => { box.hidden = true; }, 4500);
}
function paintAdvancedLanguage() {
  document.querySelectorAll('[data-ax]').forEach(el => { el.textContent = ax(el.dataset.ax); });
  document.querySelectorAll('[data-ax-label]').forEach(el => { el.setAttribute('aria-label', ax(el.dataset.axLabel)); });
  if (accountState.loaded) renderAccount();
}
function filterCatalog() {
  return ShopCore.filterProducts(products, {
    q: search.value, category, favorites: favOnly, wishlist,
    sort: byId('productSort').value, available: byId('availableOnly').checked, delivery: byId('deliveryFilter').value
  });
}
function resetFilters() {
  search.value = ''; category = 'All'; favOnly = false;
  byId('productSort').value = 'featured'; byId('availableOnly').checked = false; byId('deliveryFilter').value = 'all';
  renderCats(); render();
}
function cartStorageKey() { return `fattle-cart-v2:${user.id}`; }
function restoreCart() {
  try {
    const stored = JSON.parse(localStorage.getItem(cartStorageKey()) || 'null');
    if (stored?.version === 2 && Number.isFinite(stored.savedAt) && Date.now() - stored.savedAt < 7 * 86400000) {
      cart = ShopCore.normalizeCart(stored.items, products);
      if (Object.keys(cart).length) toast(ax('restored'));
    }
  } catch { /* Storage can be unavailable in Telegram or private browsing. */ }
}
function saveCart() {
  if (!window.shopData || !user.id) return;
  cart = ShopCore.normalizeCart(cart, products);
  try {
    // Save only item IDs and quantities. Never save sessions, keys, emails or deliveries.
    if (Object.keys(cart).length) localStorage.setItem(cartStorageKey(), JSON.stringify({version: 2, savedAt: Date.now(), items: cart}));
    else localStorage.removeItem(cartStorageKey());
  } catch { /* Cart remains functional in memory. */ }
}
function clearSavedCart() { try { localStorage.removeItem(cartStorageKey()); } catch {} }
function emptyCart() {
  if (!Object.keys(cart).length || !confirm(ax('clearConfirm'))) return;
  cart = {}; renderCart(true); closeConfirm();
}
function addCartItem(id, vid) {
  const restrictions = window.shopData?.restrictions || {};
  if (restrictions.suspended || restrictions.purchase_blocked) return toast(t('productsRestricted'));
  const product = productById(id), v = ShopCore.variant(product, vid), key = `${id}:${vid}`;
  if (!cart[key] && Object.keys(cart).length >= ShopCore.MAX_LINES) return toast(ax('cartLimit'));
  const max = ShopCore.limit(product, v);
  if (!max || (cart[key] || 0) >= max) return;
  cart[key] = Math.min((cart[key] || 0) + 1, max);
  renderCart();
  try { tg?.HapticFeedback?.impactOccurred('light'); } catch {}
}
add = function (id) { const p = productById(id); if (p) addCartItem(id, selectedVariant(p)?.id); };
addExact = addCartItem;

// Serialise repeated taps on these server mutations within the current page.
const activeActions = new Set();
const originalMethodAction = methodAction, originalToggleFav = toggleFav;
methodAction = async function (id) {
  const key = 'method:' + id;
  if (activeActions.has(key)) return;
  activeActions.add(key);
  try { await originalMethodAction(id); } finally { activeActions.delete(key); }
};
toggleFav = async function (id) {
  const key = 'favorite:' + id;
  if (activeActions.has(key)) return;
  activeActions.add(key);
  try { await originalToggleFav(id); } finally { activeActions.delete(key); }
};

const accountState = {tab: 'orders', items: [], cursor: null, loaded: false, busy: false, error: '', revision: 0};
function switchAccountTab(tab) {
  if (accountState.tab === tab && accountState.loaded) return;
  accountState.tab = tab;
  loadAccount(true);
}
function renderAccount() {
  const s = accountState;
  byId('accountOrdersTab').classList.toggle('active', s.tab === 'orders');
  byId('accountWalletTab').classList.toggle('active', s.tab === 'wallet');
  byId('accountOrdersTab').setAttribute('aria-pressed', String(s.tab === 'orders'));
  byId('accountWalletTab').setAttribute('aria-pressed', String(s.tab === 'wallet'));
  byId('accountRefresh').disabled = s.busy;
  byId('accountMore').hidden = !s.cursor || !!s.error;
  byId('accountMore').disabled = s.busy;
  const date = value => {
    const d = new Date(value);
    return value && !Number.isNaN(d.getTime()) ? d.toLocaleString(lang === 'id' ? 'id-ID' : 'en-GB', {dateStyle: 'medium', timeStyle: 'short'}) : '—';
  };
  let html = s.items.map(row => s.tab === 'orders' ? `
    <article class="account-card"><div class="account-row"><b>#${esc(row.order_code)}</b><span class="order-status ${row.status === 'delivered' ? 'complete' : 'pending'}">${esc(ax(row.status))}</span></div>
    <time class="muted">${esc(date(row.created_at))}</time>
    <ul class="account-items">${(row.items || []).map(item => `<li>${esc(item.name || '')} <span class="muted">${esc(item.variant_label || '')} × ${Number(item.qty || 0)}</span></li>`).join('')}</ul>
    <strong>${money(row.total_credits)}</strong></article>` : `
    <article class="account-card account-row"><div><b>${esc(advancedText[lang]?.[row.action] || ax('creditActivity'))}</b><div class="muted">${esc(date(row.created_at))}</div></div>
    <strong class="${row.amount >= 0 ? 'credit-in' : ''}">${row.amount > 0 ? '+' : ''}${money(row.amount)}</strong></article>`).join('');
  if (s.error) html += `<div class="empty-state">${esc(s.error)}<br><button class="cat" onclick="loadAccount(${s.items.length ? 'false' : 'true'})">${ax('retry')}</button></div>`;
  else if (s.busy) html += `<div class="empty-state" role="status">${ax('loading')}</div>`;
  else if (!s.items.length) html = `<div class="empty-state">${ax(s.tab === 'orders' ? 'emptyOrders' : 'emptyWallet')}</div>`;
  byId('accountList').innerHTML = html;
}
async function loadAccount(reset = true) {
  if (!window.shopData) return;
  const s = accountState;
  if (!reset && (s.busy || !s.cursor)) return;
  const rev = ++s.revision;
  s.busy = true; s.error = '';
  if (reset) { s.items = []; s.cursor = null; }
  renderAccount();
  const query = new URLSearchParams({uid: String(user.id), limit: '20'});
  if (!reset && s.cursor) query.set('before', s.cursor);
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(`/api/account/${s.tab}?${query}`, {
      cache: 'no-store', signal: controller.signal, headers: {Authorization: `Bearer ${sig}`}
    });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : ax('loadFail'));
    if (rev !== s.revision) return;
    s.items = reset ? data.items : [...s.items, ...data.items]; s.cursor = data.next_cursor; s.loaded = true;
    if (typeof data.balance === 'number') { window.shopData.balance = data.balance; balance.textContent = '💳 ' + money(data.balance); }
  } catch (err) {
    if (rev === s.revision) s.error = err.name === 'AbortError' ? ax('loadFail') : err.message;
  } finally {
    clearTimeout(timer);
    if (rev === s.revision) { s.busy = false; renderAccount(); }
  }
}
showSection = function (section) {
  for (const name of ['shop', 'methods', 'account']) {
    byId(name + 'Section').classList.toggle('active', name === section);
    byId(name + 'SectionBtn').classList.toggle('active', name === section);
    byId(name + 'SectionBtn').setAttribute('aria-pressed', String(name === section));
  }
  document.querySelector('.dock').style.display = section === 'shop' ? 'flex' : 'none';
  brand.textContent = section === 'methods' ? t('methodsHeroTitle') : (window.shopName || t('shop'));
  if (section === 'account' && !accountState.loaded && !accountState.busy) loadAccount();
  try { tg?.HapticFeedback?.selectionChanged(); } catch {}
};
function dismissSheets() {
  const open = [...document.querySelectorAll('.sheet.open')].pop();
  if (open) open.classList.remove('open');
}
let lastSheetFocus = null;
const sheetObserver = new MutationObserver(() => {
  const sheets = [...document.querySelectorAll('.sheet.open')], open = sheets.at(-1);
  document.body.classList.toggle('has-sheet', !!open);
  document.querySelectorAll('.sheet').forEach(el => {
    el.setAttribute('aria-hidden', String(el !== open));
    el.inert = el !== open;
  });
  const wrap = byId('app'), dock = document.querySelector('.dock');
  wrap.inert = !!open; dock.inert = !!open;
  if (open) {
    if (!lastSheetFocus) lastSheetFocus = document.activeElement;
    if (!open.contains(document.activeElement)) open.querySelector('button,input,select')?.focus();
    try { tg?.BackButton?.show(); } catch {}
  } else {
    lastSheetFocus?.focus(); lastSheetFocus = null;
    try { tg?.BackButton?.hide(); } catch {}
  }
});
document.querySelectorAll('.sheet').forEach(el => {
  el.setAttribute('role', 'dialog'); el.setAttribute('aria-modal', 'true'); el.setAttribute('aria-hidden', 'true'); el.inert = true;
  const heading = el.querySelector('h2'); if (heading?.id) el.setAttribute('aria-labelledby', heading.id);
  const close = el.querySelector('.sheet-head button'); if (close) close.dataset.axLabel = 'close';
  sheetObserver.observe(el, {attributes: true, attributeFilter: ['class']});
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') dismissSheets();
  const open = [...document.querySelectorAll('.sheet.open')].at(-1);
  if (event.key !== 'Tab' || !open) return;
  const nodes = [...open.querySelectorAll('button:not(:disabled),input:not(:disabled),select,a[href],[tabindex="0"]')].filter(el => el.getClientRects().length);
  const first = nodes[0], last = nodes.at(-1);
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
});
try { tg?.BackButton?.onClick(dismissSheets); } catch {}
window.addEventListener('offline', () => toast(ax('offline')));
window.addEventListener('online', () => toast(ax('online')));
const cartOpener = document.querySelector('.cartinfo');
cartOpener.tabIndex = 0; cartOpener.setAttribute('role', 'button');
cartOpener.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openCart(); } });
