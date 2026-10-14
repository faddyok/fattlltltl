/* Pure cart/catalog rules shared by the shop UI and Node regression tests. */
(function (root) {
  'use strict';
  const MAX_LINES = 50;
  function variants(product) {
    if (!product) return [];
    return product.variants?.length ? product.variants : [{
      id: 'default', label: 'Standard', price: Number(product.price || 0), stock: Number(product.stock || 0)
    }];
  }
  function variant(product, id) { return variants(product).find(v => v.id === id); }
  function limit(product, item) {
    if (!product || !item) return 0;
    if (['email', 'login_assist'].includes(product.fulfillment_mode)) return 1;
    if (product.fulfillment_mode === 'manual') return 20;
    return Math.max(0, Math.min(20, Math.floor(Number(item.stock) || 0)));
  }
  function normalizeCart(value, products) {
    const out = {};
    if (!value || typeof value !== 'object' || Array.isArray(value)) return out;
    const catalog = new Map(products.map(p => [p.id, p]));
    for (const [key, qty] of Object.entries(value).slice(0, MAX_LINES)) {
      const parts = key.split(':');
      if (parts.length !== 2 || !Number.isInteger(qty) || qty <= 0) continue;
      const product = catalog.get(parts[0]);
      const item = variant(product, parts[1]);
      const count = Math.min(qty, limit(product, item));
      if (count > 0) out[key] = count;
    }
    return out;
  }
  function available(product) { return variants(product).some(v => limit(product, v) > 0); }
  function price(product) {
    const all = variants(product);
    const inStock = all.filter(v => limit(product, v) > 0);
    return Math.min(...(inStock.length ? inStock : all).map(v => Number(v.price) || 0));
  }
  function filterProducts(products, options = {}) {
    const query = (options.q || '').trim().toLocaleLowerCase();
    const favoriteIds = options.wishlist || new Set();
    const result = products.filter(p =>
      (!options.category || options.category === 'All' || (p.category || 'General') === options.category) &&
      (!options.favorites || favoriteIds.has(p.id)) &&
      (!options.available || available(p)) &&
      (!options.delivery || options.delivery === 'all' || (p.fulfillment_mode || 'instant') === options.delivery) &&
      `${p.name || ''} ${p.description || ''} ${p.category || ''}`.toLocaleLowerCase().includes(query)
    );
    const compare = {
      'price-asc': (a, b) => price(a) - price(b),
      'price-desc': (a, b) => price(b) - price(a),
      name: (a, b) => (a.name || '').localeCompare(b.name || ''),
      featured: (a, b) => Number(!!b.featured) - Number(!!a.featured) || Number(!!b.bestseller) - Number(!!a.bestseller)
    }[options.sort];
    if (compare) result.sort(compare);
    return result;
  }
  const api = { MAX_LINES, variants, variant, limit, normalizeCart, available, filterProducts };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.ShopCore = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
