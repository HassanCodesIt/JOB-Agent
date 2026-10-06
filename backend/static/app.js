/* ==========================================================================
   Command - shared behaviour layer (vanilla JS, no framework)
   ========================================================================== */

(function () {
    'use strict';

    var EMAIL_SLOTS_FALLBACK = ['1', '2'];

    function slotKeys(emails) {
        var keys = Object.keys(emails || {}).sort(function (a, b) { return Number(a) - Number(b); });
        return keys.length ? keys : EMAIL_SLOTS_FALLBACK;
    }

    function qs(selector, root) {
        return (root || document).querySelector(selector);
    }

    function qsa(selector, root) {
        return Array.prototype.slice.call((root || document).querySelectorAll(selector));
    }

    function on(element, event, handler, options) {
        if (element) element.addEventListener(event, handler, options);
    }

    function icon(name, size) {
        var px = size || 18;
        return '<svg class="icon" width="' + px + '" height="' + px + '"><use href="#i-' + name + '"></use></svg>';
    }

    function escapeHtml(value) {
        return String(value === null || value === undefined ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    /* ---------------------------------------------------------------- toast */

    var toastTimer = null;

    function toast(message, options) {
        var opts = options || {};
        var host = qs('#toastHost');
        if (!host) return;

        host.innerHTML = '<div class="toast' + (opts.error ? ' error' : '') + '">' +
            '<span>' + (opts.error ? '!' : '✓') + '</span>' +
            escapeHtml(message) +
            '</div>';

        window.clearTimeout(toastTimer);
        toastTimer = window.setTimeout(function () {
            host.innerHTML = '';
        }, opts.duration || 2600);
    }

    /* --------------------------------------------------------------- modals */

    function showLoading(text, title) {
        var overlay = qs('#loadingOverlay');
        if (!overlay) return;
        qs('#loadingText').innerText = text || 'One moment.';
        qs('#loadingTitle').innerText = title || 'Working…';
        overlay.hidden = false;
    }

    function hideLoading() {
        var overlay = qs('#loadingOverlay');
        if (overlay) overlay.hidden = true;
    }

    function showStatus(title, message, success) {
        var modal = qs('#statusModal');
        if (!modal) {
            toast(message, { error: !success });
            return;
        }
        qs('#statusTitle').innerText = title || (success ? 'Done' : 'Something went wrong');
        qs('#statusMessage').innerText = message || '';
        var box = qs('#statusIconBox');
        box.className = 'modal-icon ' + (success === false ? 'danger' : 'success');
        box.innerHTML = icon(success === false ? 'trash' : 'check', 19);
        modal.classList.add('active');
    }

    function closeStatusModal() {
        var modal = qs('#statusModal');
        if (modal) modal.classList.remove('active');
    }

    function openModal(id) {
        var modal = qs(id);
        if (modal) modal.classList.add('active');
    }

    function closeModal(id) {
        var modal = qs(id);
        if (modal) modal.classList.remove('active');
    }

    /* ---------------------------------------------------- confirm / prompt */

    function confirmDialog(options) {
        var opts = options || {};
        var modal = qs('#confirmModal');
        if (!modal) return Promise.resolve(window.confirm(opts.message || 'Are you sure?'));

        qs('#confirmTitle').innerText = opts.title || 'Are you sure?';
        qs('#confirmMessage').innerText = opts.message || '';
        var yes = qs('[data-confirm-yes]');
        var no = qs('[data-confirm-no]');
        yes.innerText = opts.confirmText || 'Confirm';
        no.innerText = opts.cancelText || 'Cancel';

        return new Promise(function (resolve) {
            function cleanup(result) {
                modal.classList.remove('active');
                yes.removeEventListener('click', onYes);
                no.removeEventListener('click', onNo);
                resolve(result);
            }
            function onYes() { cleanup(true); }
            function onNo() { cleanup(false); }
            yes.addEventListener('click', onYes);
            no.addEventListener('click', onNo);
            modal.classList.add('active');
        });
    }

    function promptDialog(options) {
        var opts = options || {};
        var modal = qs('#promptModal');
        if (!modal) return Promise.resolve(window.prompt(opts.message || '', opts.value || ''));

        qs('#promptTitle').innerText = opts.title || 'Add instructions';
        qs('#promptMessage').innerText = opts.message || '';
        var field = qs('#promptInputField');
        var yes = qs('[data-prompt-yes]');
        var no = qs('[data-prompt-no]');
        yes.innerText = opts.confirmText || 'Apply';
        field.value = opts.value || '';
        field.placeholder = opts.placeholder || '';

        return new Promise(function (resolve) {
            function cleanup(result) {
                modal.classList.remove('active');
                yes.removeEventListener('click', onYes);
                no.removeEventListener('click', onNo);
                field.removeEventListener('keydown', onKey);
                resolve(result);
            }
            function onYes() { cleanup(field.value.trim()); }
            function onNo() { cleanup(null); }
            function onKey(event) {
                if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) onYes();
            }
            yes.addEventListener('click', onYes);
            no.addEventListener('click', onNo);
            field.addEventListener('keydown', onKey);
            modal.classList.add('active');
            window.setTimeout(function () { field.focus(); }, 40);
        });
    }

    /* ---------------------------------------------------------------- fetch */

    function request(url, options) {
        return fetch(url, options).then(function (response) {
            return response.json()
                .catch(function () { return {}; })
                .then(function (data) {
                    if (!response.ok) {
                        var detail = data && data.detail ? data.detail : 'Request failed (' + response.status + ')';
                        var error = new Error(typeof detail === 'string' ? detail : 'Request failed');
                        error.status = response.status;
                        error.data = data;
                        throw error;
                    }
                    return data;
                });
        });
    }

    function postJson(url, payload) {
        return request(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload || {})
        });
    }

    /* --------------------------------------------------- profile summary */

    // The profile summary is a single readable block in a fixed, labelled
    // format. It round-trips: "apply" pushes it into the individual profile
    // fields, and editing any of those fields rebuilds the block. Both
    // directions use this one definition so the two can never drift apart.
    var PROFILE_SECTIONS = [
        { key: 'full_name', label: 'Full Name', field: 'fullName' },
        { key: 'email', label: 'Email', field: 'userEmail' },
        { key: 'phone', label: 'Phone', field: 'userPhone' },
        { key: 'github_link', label: 'GitHub', field: 'userGithub' },
        { key: 'linkedin_link', label: 'LinkedIn', field: 'userLinkedin' },
        { key: 'portfolio_link', label: 'Portfolio', field: 'userPortfolio' },
        { key: 'skills', label: 'Skills', field: 'userSkills' },
        { key: 'experience', label: 'Experience', field: 'userExperience' },
        { key: 'projects', label: 'Projects', field: 'userProjects' },
        { key: 'standard_answers', label: 'Bio', field: 'userStandardAnswers' },
        { key: 'system_prompt', label: 'Drafting Instructions', field: 'systemPrompt' }
    ];

    function buildProfileSummary(values) {
        return PROFILE_SECTIONS.map(function (section) {
            return section.label + ': ' + String(values[section.key] || '').trim();
        }).join('\n');
    }

    function isStubValue(value) {
        var v = String(value || '').toLowerCase().replace(/[.,;!:"'`·]/g, ' ').replace(/\s+/g, ' ').trim();
        if (!v) return true;
        var stubs = ['not provided', 'not provided in resume', 'not available', 'not mentioned',
            'not listed', 'not found', 'none', 'n/a', 'na', 'nil', 'null', 'see resume',
            'see attached resume', 'no data', 'no link', 'unknown', 'does not include'];
        var match = false;
        stubs.forEach(function (s) { if (v === s) match = true; });
        return match;
    }

    function normalizeLink(value, key) {
        if (key !== 'github_link' && key !== 'linkedin_link' && key !== 'portfolio_link') return value;
        var url = String(value || '').trim();
        if (!url || url.indexOf(' ') !== -1) return url;

        if (key === 'linkedin_link') {
            if (/^in\//i.test(url)) url = 'linkedin.com/' + url;
            url = url.replace(/^linkedin\.com\//i, 'www.linkedin.com/');
        }

        if (!/^https?:\/\//i.test(url)) {
            try {
                if (/^(www\.)?[a-z0-9-]+(\.[a-z0-9-]+)+/i.test(url)) url = 'https://' + url;
            } catch (e) { /* leave as typed */ }
        }

        if (key === 'linkedin_link' && !/\/$/.test(url)) url += '/';
        return url;
    }

    function parseProfileSummary(text) {
        var values = {};
        var lines = String(text || '').split(/\r?\n/);
        var current = null;
        var buffer = [];

        function flush() {
            if (current) {
                var value = buffer.join('\n').trim();
                // "Not provided / N/A / None …" values are treated as absent:
                // the field is left untouched instead of being overwritten.
                if (!isStubValue(value)) values[current] = normalizeLink(value, current);
                current = null;
                buffer = [];
            }
        }

        lines.forEach(function (line) {
            // Skip markdown code fences (```, ~~~, ```json …) entirely.
            if (/^[`~]{3,}\w*\s*$/.test(line.trim())) return;
            // Skip blank lines.
            if (!line.trim()) return;

            var heading = line.replace(/^#+\s*/, '').trim();
            // Accept (and strip) leading bullet markers: * , -, •, 1.
            var bullet = heading.match(/^\s*([*\-•]|\d+[.)])\s+/);
            var candidate = bullet ? heading.slice(bullet[0].length) : heading;

            var matched = null;
            var labelLen = 0;
            var clean = candidate;
            PROFILE_SECTIONS.forEach(function (section) {
                var label = section.label.toLowerCase() + ':';
                if (!matched && clean.toLowerCase().indexOf(label) === 0) {
                    matched = section.key;
                    labelLen = label.length;
                }
            });

            if (matched) {
                flush();
                current = matched;
                var rest = clean.slice(labelLen).replace(/^:\s*/, '').trim();
                if (rest) buffer.push(rest);
            } else if (current) {
                buffer.push(line);
            }
        });
        flush();

        return values;
    }

    function buildProfilePrompt(current) {
        var lines = [
            'Read my resume and write my candidate profile. Return ONLY the labelled',
            'sections below, keeping the exact section names and the "Label: value"',
            'format. Keep every value on one line where possible, and do not invent',
            'anything that is not in the resume.'
        ];

        PROFILE_SECTIONS.forEach(function (section) {
            lines.push('');
            lines.push(section.label + ': ' + (current[section.key] ? '(refine what is already here)' : ''));
        });

        lines.push('');
        lines.push('Cover projects in detail: name, tech stack, what you built, and the outcome.');
        return lines.join('\n');
    }

    function collectProfileValues(root) {
        var values = {};
        PROFILE_SECTIONS.forEach(function (section) {
            var field = qs('#' + section.field, root) || qs('[name="' + section.field + '"]', root);
            values[section.key] = field ? field.value : '';
        });
        return values;
    }

    function applyProfileValues(values, root) {
        PROFILE_SECTIONS.forEach(function (section) {
            // Only touch fields the block actually contains, so an AI output
            // that omits a section never zeroes it out.
            if (!(section.key in values)) return;
            var field = qs('#' + section.field, root) || qs('[name="' + section.field + '"]', root);
            if (field) field.value = values[section.key] || '';
        });
    }

    /* ------------------------------------------------------- account switch */

    function renderAccountMenu(state) {
        var wrap = qs('#accountSwitcher');
        if (!wrap) return;

        var trigger = qs('.account-trigger', wrap);
        var menu = qs('.account-menu', wrap);
        var label = qs('#accountLabel');
        var avatar = qs('#accountAvatar');

        var emails = (state && state.emails) || {};
        var slots = slotKeys(emails);
        var activeIndex = state && state.index ? String(state.index) : slots[0];
        var activeEmail = emails[activeIndex] || '';

        if (label) label.innerText = activeEmail || 'Not configured';
        if (avatar) avatar.innerText = activeEmail ? activeEmail.slice(0, 1).toUpperCase() : '–';

        if (menu) menu.remove();

        menu = document.createElement('div');
        menu.className = 'account-menu';
        menu.innerHTML = '<div class="account-menu-label">Connected accounts</div>' +
            slots.map(function (slot) {
                var email = emails[slot] || '';
                var isActive = slot === activeIndex;
                return '<button type="button" data-slot="' + slot + '"' + (isActive ? ' class="selected"' : '') + '>' +
                    '<span class="account-avatar">' + escapeHtml(email ? email.slice(0, 1).toUpperCase() : '–') + '</span>' +
                    '<span><strong>' + escapeHtml(email || 'Not connected') + '</strong>' +
                    '<small>' + (isActive ? 'Active account' : 'Gmail connected') + '</small></span>' +
                    (isActive ? '<span class="account-check">✓</span>' : '') +
                    '</button>';
            }).join('') +
            '<button type="button" class="connect-account" id="openConnectAccount">' +
            icon('plus', 15) + ' Connect another account</button>';

        wrap.appendChild(menu);

        menu.style.display = 'none';

        on(trigger, 'click', function (event) {
            event.stopPropagation();
            var open = trigger.classList.toggle('open');
            trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
            menu.style.display = open ? 'block' : 'none';
        });

        qsa('button[data-slot]', menu).forEach(function (button) {
            on(button, 'click', function () {
                var slot = button.getAttribute('data-slot');
                if (slot === activeIndex) {
                    trigger.classList.remove('open');
                    menu.style.display = 'none';
                    return;
                }
                postJson('/api/switch-email', { index: parseInt(slot, 10) })
                    .then(function () {
                        toast('Now sending from ' + (emails[slot] || 'account ' + slot));
                        window.setTimeout(function () { window.location.reload(); }, 700);
                    })
                    .catch(function (error) {
                        toast(error.message, { error: true });
                    });
            });
        });

        on(qs('#openConnectAccount', menu), 'click', function () {
            trigger.classList.remove('open');
            menu.style.display = 'none';
            openConnectAccountModal();
        });
    }

    function openConnectAccountModal() {
        var modal = qs('#connectAccountModal');
        if (!modal) return;

        var emailField = qs('#connectEmail');
        var passwordField = qs('#connectPassword');
        if (emailField) emailField.value = '';
        if (passwordField) passwordField.value = '';

        modal.classList.add('active');

        loadAccountSlots();
        window.setTimeout(function () { if (emailField) emailField.focus(); }, 60);
    }

    function loadAccountSlots() {
        var host = qs('#accountSlots');
        if (!host) return;

        request('/api/accounts')
            .then(function (data) {
                var accounts = data.accounts || {};
                var slots = Object.keys(accounts).sort(function (a, b) { return Number(a) - Number(b); });
                var free = data.free_slots || [];

                host.innerHTML = '<span class="account-menu-label">Connected accounts</span>' +
                    slots.map(function (slot) {
                        var account = accounts[slot] || {};
                        return '<div class="account-slot">' +
                            '<strong>Slot ' + slot + '</strong>' +
                            '<span>' + escapeHtml(account.email || 'Hidden') + '</span>' +
                            '<em>Connected</em>' +
                            '</div>';
                    }).join('') +
                    '<div class="account-slot free">' +
                    '<strong>Next</strong>' +
                    '<span>Slot ' + (free[0] || '–') + ' will be used</span>' +
                    '<em>Open</em>' +
                    '</div>';

                var button = qs('#btnConnectAccount');
                if (button) {
                    button.disabled = !free.length;
                    button.innerText = free.length ? 'Connect account' : 'No free slots';
                }
            })
            .catch(function (error) {
                host.innerHTML = '<div class="account-menu-note">Could not load account slots: ' + escapeHtml(error.message) + '</div>';
            });
    }

    function setupConnectAccount() {
        var modal = qs('#connectAccountModal');
        if (!modal) return;

        qsa('[data-close-account]', modal).forEach(function (button) {
            on(button, 'click', function () { modal.classList.remove('active'); });
        });

        qsa('[data-toggle-secret]', modal).forEach(function (button) {
            on(button, 'click', function () {
                var input = qs('#' + button.getAttribute('data-toggle-secret'));
                if (input) input.type = input.type === 'password' ? 'text' : 'password';
            });
        });

        on(qs('#btnConnectAccount'), 'click', async function (event) {
            var button = event.currentTarget;
            var original = button.innerText;
            var email = (qs('#connectEmail') || {}).value || '';
            var password = (qs('#connectPassword') || {}).value || '';

            email = email.trim();
            password = password.trim();

            if (!email || !password) {
                toast('Enter both the email address and app password.', { error: true });
                return;
            }

            button.disabled = true;
            button.innerText = 'Connecting…';

            try {
                var data = await postJson('/api/accounts', { email: email, password: password });
                modal.classList.remove('active');
                toast('Connected ' + data.email);
                postJson('/api/switch-email', { index: data.index })
                    .then(function () { window.setTimeout(function () { window.location.reload(); }, 700); })
                    .catch(function () { window.location.reload(); });
            } catch (error) {
                toast(error.message, { error: true });
                button.disabled = false;
                button.innerText = original;
            }
        });
    }

    function loadAccountSwitcher() {
        request('/api/current-email')
            .then(renderAccountMenu)
            .catch(function (error) {
                var label = qs('#accountLabel');
                if (label) label.innerText = 'Unavailable';
                console.warn('Could not load sending addresses:', error.message);
            });
    }

    /* ------------------------------------------------------------ global UI */

    function setupMobileNav() {
        var toggle = qs('#menuToggle');
        var scrim = qs('#sidebarScrim');
        on(toggle, 'click', function () {
            document.body.classList.toggle('nav-open');
        });
        on(scrim, 'click', function () {
            document.body.classList.remove('nav-open');
        });
        qsa('.sidebar a').forEach(function (link) {
            on(link, 'click', function () {
                document.body.classList.remove('nav-open');
            });
        });
    }

    function setupSearch() {
        var input = qs('#globalSearch');
        if (!input) return;

        var targets = qsa('[data-search]');
        if (!targets.length) {
            input.closest('.search-box').style.display = 'none';
            return;
        }

        on(input, 'input', function () {
            var query = input.value.trim().toLowerCase();
            targets.forEach(function (row) {
                var haystack = (row.getAttribute('data-search') || '').toLowerCase();
                row.hidden = query.length > 0 && haystack.indexOf(query) === -1;
            });
        });

        document.addEventListener('keydown', function (event) {
            var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement && document.activeElement.tagName);
            if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
                event.preventDefault();
                input.focus();
                input.select();
            } else if (event.key === '/' && !typing) {
                event.preventDefault();
                input.focus();
            }
        });
    }

    function setupSync() {
        qsa('[data-sync]').forEach(function (button) {
            on(button, 'click', function () {
                if (button.disabled) return;
                button.disabled = true;
                showLoading('Scanning Gmail and refreshing your workspace...', 'Syncing');
                request('/sync/', { method: 'POST' })
                    .then(function () {
                        window.setTimeout(function () { window.location.reload(); }, 500);
                    })
                    .catch(function (error) {
                        hideLoading();
                        button.disabled = false;
                        showStatus('Sync failed', error.message, false);
                    });
            });
        });
    }

    function setupModalDismiss() {
        document.addEventListener('click', function (event) {
            var modal = event.target.closest && event.target.closest('.modal');
            if (modal && event.target === modal) modal.classList.remove('active');
            if (event.target.matches && event.target.matches('[data-close-modal]')) closeStatusModal();

            var switcher = qs('#accountSwitcher');
            if (switcher && !switcher.contains(event.target)) {
                var trigger = qs('.account-trigger', switcher);
                var menu = qs('.account-menu', switcher);
                if (trigger) trigger.classList.remove('open');
                if (menu) menu.style.display = 'none';
            }
        });

        document.addEventListener('keydown', function (event) {
            if (event.key !== 'Escape') return;
            qsa('.modal.active, .process-overlay:not([hidden])').forEach(function (node) {
                if (node.id === 'loadingOverlay') return;
                node.classList.remove('active');
            });
            var trigger = qs('.account-trigger.open');
            if (trigger) trigger.classList.remove('open');
            var menu = qs('.account-menu');
            if (menu) menu.style.display = 'none';
        });
    }

    /* ------------------------------------------------------------- exports */

    window.ui = {
        qs: qs,
        qsa: qsa,
        on: on,
        icon: icon,
        escapeHtml: escapeHtml,
        toast: toast,
        showLoading: showLoading,
        hideLoading: hideLoading,
        showStatus: showStatus,
        closeStatusModal: closeStatusModal,
        openModal: openModal,
        closeModal: closeModal,
        confirm: confirmDialog,
        prompt: promptDialog,
        request: request,
        postJson: postJson,
        profileSections: PROFILE_SECTIONS,
        buildProfileSummary: buildProfileSummary,
        parseProfileSummary: parseProfileSummary,
        buildProfilePrompt: buildProfilePrompt,
        collectProfileValues: collectProfileValues,
        applyProfileValues: applyProfileValues
    };

    // Legacy globals so existing page scripts keep working unchanged.
    window.showLoading = showLoading;
    window.hideLoading = hideLoading;
    window.showStatus = showStatus;
    window.closeModal = closeStatusModal;
    window.notify = toast;

    document.addEventListener('DOMContentLoaded', function () {
        setupMobileNav();
        setupSearch();
        setupSync();
        setupModalDismiss();
        setupConnectAccount();
        loadAccountSwitcher();
    });
})();
