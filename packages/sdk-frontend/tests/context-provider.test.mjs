import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { JSDOM } from 'jsdom';
import { ContextProvider } from '../dist/index.js';

describe('ContextProvider DOM auto-discovery and context scanning', () => {
  test('discovers data-ghost-id targets on home catalog page with empty initial targets', () => {
    const dom = new JSDOM(`
      <!DOCTYPE html>
      <html>
        <body>
          <header>
            <nav>
              <a href="/cart" data-ghost-id="nav.cart" data-ghost-nav="cart">Cart</a>
              <a href="/orders" data-ghost-id="nav.orders" data-ghost-nav="orders">Orders</a>
              <a href="/settings" data-ghost-id="nav.settings" data-ghost-nav="settings">Settings</a>
            </nav>
          </header>
          <main>
            <div class="grid">
              <a href="/product/prod_1" data-ghost-id="catalog.product.prod_1">Nike Air Max</a>
              <a href="/product/prod_2" data-ghost-id="catalog.product.prod_2">Adidas Ultraboost</a>
              <a href="/product/prod_3" data-ghost-id="catalog.product.prod_3">Puma Suede</a>
            </div>
          </main>
        </body>
      </html>
    `, { url: 'http://localhost:3000/' });

    globalThis.window = dom.window;
    globalThis.document = dom.window.document;
    globalThis.HTMLElement = dom.window.HTMLElement;
    globalThis.HTMLInputElement = dom.window.HTMLInputElement;
    globalThis.HTMLTextAreaElement = dom.window.HTMLTextAreaElement;
    globalThis.HTMLSelectElement = dom.window.HTMLSelectElement;

    const provider = new ContextProvider({});
    const context = provider.scanContext('/');

    assert.equal(context.page, '/');
    assert.deepEqual(context.availableTargets, [
      'nav.cart',
      'nav.orders',
      'nav.settings',
      'catalog.product.prod_1',
      'catalog.product.prod_2',
      'catalog.product.prod_3',
    ]);
    // Action links should not pollute values
    assert.deepEqual(context.values, {});
  });

  test('auto-observes form controls and checkboxes on settings page', () => {
    const dom = new JSDOM(`
      <!DOCTYPE html>
      <html>
        <body>
          <a href="/cart" data-ghost-id="nav.cart">Cart</a>
          <div class="settings">
            <input type="checkbox" checked data-ghost-id="settings.theme_toggle" />
            <input type="checkbox" checked data-ghost-id="settings.notif_email" />
            <input type="checkbox" data-ghost-id="settings.notif_sms" />
            <input type="text" value="New York" data-ghost-id="settings.city" />
            <div data-ghost-id="settings.saved_address">
              <div>Default Address</div>
              <div>123 Main St</div>
            </div>
          </div>
        </body>
      </html>
    `, { url: 'http://localhost:3000/settings' });

    globalThis.window = dom.window;
    globalThis.document = dom.window.document;
    globalThis.HTMLElement = dom.window.HTMLElement;
    globalThis.HTMLInputElement = dom.window.HTMLInputElement;
    globalThis.HTMLTextAreaElement = dom.window.HTMLTextAreaElement;
    globalThis.HTMLSelectElement = dom.window.HTMLSelectElement;

    const provider = new ContextProvider({});
    const context = provider.scanContext('/settings');

    assert.equal(context.page, '/settings');
    assert.ok(context.availableTargets.includes('settings.theme_toggle'));
    assert.ok(context.availableTargets.includes('settings.notif_email'));
    assert.ok(context.availableTargets.includes('settings.notif_sms'));
    assert.ok(context.availableTargets.includes('settings.city'));
    assert.ok(context.availableTargets.includes('settings.saved_address'));

    // Checkboxes should record boolean values
    assert.equal(context.values['settings.theme_toggle'], true);
    assert.equal(context.values['settings.notif_email'], true);
    assert.equal(context.values['settings.notif_sms'], false);
    // Text input should record string value
    assert.equal(context.values['settings.city'], 'New York');
    // Multiline container div should not pollute values
    assert.equal(context.values['settings.saved_address'], undefined);
  });

  test('excludes sensitive inputs (password, hidden, file) and hidden elements', () => {
    const dom = new JSDOM(`
      <!DOCTYPE html>
      <html>
        <body>
          <input type="password" value="secret123" data-ghost-id="auth.password" />
          <input type="hidden" value="csrf_token" data-ghost-id="auth.csrf" />
          <input type="file" data-ghost-id="upload.file" />
          <button hidden data-ghost-id="hidden.btn">Hidden</button>
          <button aria-hidden="true" data-ghost-id="aria.hidden.btn">Aria Hidden</button>
          <input type="text" value="SAFE" data-ghost-id="safe.input" />
        </body>
      </html>
    `, { url: 'http://localhost:3000/' });

    globalThis.window = dom.window;
    globalThis.document = dom.window.document;
    globalThis.HTMLElement = dom.window.HTMLElement;
    globalThis.HTMLInputElement = dom.window.HTMLInputElement;
    globalThis.HTMLTextAreaElement = dom.window.HTMLTextAreaElement;
    globalThis.HTMLSelectElement = dom.window.HTMLSelectElement;

    const provider = new ContextProvider({});
    const context = provider.scanContext('/');

    assert.deepEqual(context.availableTargets, ['safe.input']);
    assert.deepEqual(context.values, { 'safe.input': 'SAFE' });
    assert.equal(context.values['auth.password'], undefined);
    assert.equal(context.values['auth.csrf'], undefined);
  });

  test('auto-discovers leaf text values (e.g. order confirmation ID)', () => {
    const dom = new JSDOM(`
      <!DOCTYPE html>
      <html>
        <body>
          <span data-ghost-id="checkout.confirmed_id">ORD-998811</span>
          <p data-ghost-id="product.price">$199.99</p>
          <button data-ghost-id="checkout.submit">Pay Now</button>
        </body>
      </html>
    `, { url: 'http://localhost:3000/checkout' });

    globalThis.window = dom.window;
    globalThis.document = dom.window.document;
    globalThis.HTMLElement = dom.window.HTMLElement;
    globalThis.HTMLInputElement = dom.window.HTMLInputElement;
    globalThis.HTMLTextAreaElement = dom.window.HTMLTextAreaElement;
    globalThis.HTMLSelectElement = dom.window.HTMLSelectElement;

    const provider = new ContextProvider({});
    const context = provider.scanContext('/checkout');

    assert.ok(context.availableTargets.includes('checkout.confirmed_id'));
    assert.ok(context.availableTargets.includes('product.price'));
    assert.ok(context.availableTargets.includes('checkout.submit'));

    assert.equal(context.values['checkout.confirmed_id'], 'ORD-998811');
    assert.equal(context.values['product.price'], '$199.99');
    // Button label should not be in values
    assert.equal(context.values['checkout.submit'], undefined);
  });

  test('merges programmatic targets and custom observers', () => {
    const dom = new JSDOM(`
      <!DOCTYPE html>
      <html>
        <body>
          <div data-ghost-id="dom.target">DOM Target</div>
          <div id="custom-target">Custom El</div>
        </body>
      </html>
    `, { url: 'http://localhost:3000/' });

    globalThis.window = dom.window;
    globalThis.document = dom.window.document;
    globalThis.HTMLElement = dom.window.HTMLElement;
    globalThis.HTMLInputElement = dom.window.HTMLInputElement;
    globalThis.HTMLTextAreaElement = dom.window.HTMLTextAreaElement;
    globalThis.HTMLSelectElement = dom.window.HTMLSelectElement;

    const provider = new ContextProvider({
      'custom.programmatic': {
        page: '*',
        resolve: () => dom.window.document.getElementById('custom-target'),
        observe: () => 'custom_observed_val',
      },
    });
    const context = provider.scanContext('/');

    assert.ok(context.availableTargets.includes('dom.target'));
    assert.ok(context.availableTargets.includes('custom.programmatic'));
    assert.equal(context.values['custom.programmatic'], 'custom_observed_val');
  });
});

