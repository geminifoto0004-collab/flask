// Desktop WEB: instant modal shell + background detail hydration.
// The click path never waits on Render/TiDB. It reuses the already-loaded card thumbnail
// immediately, then hydrates the full text/detail from an in-memory prefetched HTML cache.
(function () {
    const desktopQuery = window.matchMedia
        ? window.matchMedia('(min-width: 1024px) and (hover: hover) and (pointer: fine)')
        : null;
    const overlay = document.getElementById('guestDesktopDetailOverlay');
    const panel = overlay?.querySelector('.guest-desktop-detail-panel');
    const closeButton = document.getElementById('guestDesktopDetailClose');
    const loading = document.getElementById('guestDesktopDetailLoading');
    const layout = document.getElementById('guestDesktopDetailLayout');
    const media = document.getElementById('guestDesktopDetailMedia');
    const info = document.getElementById('guestDesktopDetailInfo');
    if (!overlay || !panel || !loading || !layout || !media || !info) return;

    const detailCache = new Map();
    const detailInflight = new Map();
    let requestController = null;
    let activeUrl = '';
    let requestVersion = 0;
    let detailViewer = null;
    let activeIndex = 0;
    const detailCacheAt = new Map();

    function isDesktop() {
        return !!(desktopQuery && desktopQuery.matches);
    }

    function absoluteUrl(url) {
        try { return new URL(url, location.href).href; } catch (_) { return String(url || ''); }
    }

    function cardForUrl(url) {
        const target = absoluteUrl(url);
        return Array.from(document.querySelectorAll('[data-guest-card]')).find(function (card) {
            return absoluteUrl(card.getAttribute('href')) === target;
        }) || null;
    }

    function closeDetail() {
        requestVersion++;
        detailViewer?.destroy(); detailViewer = null;
        panel.classList.remove('has-unified-detail');
        if (requestController) {
            try { requestController.abort(); } catch (_) {}
            requestController = null;
        }
        activeUrl = '';
        overlay.hidden = true;
        overlay.setAttribute('aria-hidden', 'true');
        document.body.classList.remove('guest-desktop-detail-open');
        media.replaceChildren();
        info.replaceChildren();
        layout.hidden = true;
        loading.hidden = false;
        loading.textContent = 'Cargando…';
    }

    function initGallery(root) {
        const gallery = root.querySelector('[data-guest-detail-gallery]');
        if (!gallery) return;
        const shell = gallery.closest('.guest-gallery-shell');
        const prev = shell?.querySelector('[data-detail-nav="-1"]');
        const next = shell?.querySelector('[data-detail-nav="1"]');
        const count = Math.max(1, Number(gallery.dataset.imageCount || gallery.children.length || 1));
        let pointerDown = false;
        let pointerId = null;
        let startX = 0;
        let startScrollLeft = 0;
        let moved = false;

        function indexNow() {
            const width = gallery.clientWidth || 1;
            return Math.max(0, Math.min(count - 1, Math.round(gallery.scrollLeft / width)));
        }
        function sync() {
            const index = indexNow();
            if (prev) prev.disabled = index <= 0;
            if (next) next.disabled = index >= count - 1;
        }
        function move(delta, event) {
            if (event) { event.preventDefault(); event.stopPropagation(); }
            const width = gallery.clientWidth || 1;
            const target = Math.max(0, Math.min(count - 1, indexNow() + delta));
            gallery.scrollTo({left: target * width, behavior:'smooth'});
            window.setTimeout(sync, 220);
        }
        prev?.addEventListener('click', event => move(-1, event));
        next?.addEventListener('click', event => move(1, event));
        gallery.addEventListener('scroll', sync, {passive:true});
        gallery.addEventListener('pointerdown', function (event) {
            if (event.pointerType === 'touch' || event.button !== 0) return;
            pointerDown = true;
            pointerId = event.pointerId;
            startX = event.clientX;
            startScrollLeft = gallery.scrollLeft;
            moved = false;
            try { gallery.setPointerCapture(pointerId); } catch (_) {}
        });
        gallery.addEventListener('pointermove', function (event) {
            if (!pointerDown || event.pointerId !== pointerId) return;
            const dx = event.clientX - startX;
            if (!moved && Math.abs(dx) > 6) moved = true;
            if (!moved) return;
            event.preventDefault();
            gallery.scrollLeft = startScrollLeft - dx;
        }, {passive:false});
        function finish(event) {
            if (!pointerDown || (event && event.pointerId !== pointerId)) return;
            pointerDown = false;
            try { if (pointerId !== null) gallery.releasePointerCapture(pointerId); } catch (_) {}
            pointerId = null;
            if (!moved) return;
            const width = gallery.clientWidth || 1;
            gallery.scrollTo({left:indexNow() * width, behavior:'smooth'});
            window.setTimeout(sync, 220);
        }
        gallery.addEventListener('pointerup', finish);
        gallery.addEventListener('pointercancel', finish);
        gallery.addEventListener('lostpointercapture', finish);
        sync();
    }

    function showInstantCardShell(url) {
        panel.classList.remove("has-unified-detail");
        const card = cardForUrl(url);
        media.replaceChildren();
        info.replaceChildren();

        if (card) {
            const currentImage = card.querySelectorAll('.guest-cover img')[activeIndex] || card.querySelector('.guest-cover img');
            if (currentImage && !window.OrderGuestDetail) {
                const shell = document.createElement('div');
                shell.className = 'guest-gallery-shell';
                const gallery = document.createElement('div');
                gallery.className = 'guest-gallery';
                gallery.dataset.guestDetailGallery = '';
                gallery.dataset.imageCount = '1';
                const slide = document.createElement('div');
                slide.className = 'guest-slide';
                const img = document.createElement('img');
                img.alt = currentImage.alt || '';
                img.decoding = 'async';
                img.loading = 'eager';
                img.src = currentImage.currentSrc || currentImage.src || currentImage.dataset.src || '';
                slide.appendChild(img);
                gallery.appendChild(slide);
                shell.appendChild(gallery);
                media.appendChild(shell);
            }

            const head = document.createElement('section');
            head.className = 'guest-order-head';
            const number = document.createElement('h1');
            number.textContent = String(card.dataset.guestOrderKey || '').trim();
            const status = document.createElement('p');
            status.dataset.guestZh = card.dataset.guestStatusZh || '';
            status.dataset.guestEs = card.dataset.guestStatusEs || '';
            status.textContent = window.getTrackingLanguage?.() === 'zh_cn'
                ? status.dataset.guestZh
                : status.dataset.guestEs;
            head.append(number, status);
            info.appendChild(head);

            const body = card.querySelector('.guest-card-body');
            if (body) {
                const quick = document.createElement('section');
                quick.className = 'guest-panel';
                quick.appendChild(body.cloneNode(true));
                info.appendChild(quick);
            }
        }

        if (!media.children.length) {
            const empty = document.createElement('div');
            empty.className = 'guest-desktop-detail-no-media';
            empty.textContent = (window.getTrackingLanguage?.() === 'zh_cn') ? '此订单没有图片' : 'Este pedido no tiene imágenes';
            media.appendChild(empty);
        }

        if (card && window.OrderGuestDetail) {
            const head = info.querySelector('.guest-order-head');
            const panels = Array.from(info.querySelectorAll('.guest-panel'));
            const root = document.createElement('div');
            root.dataset.orderMedia = '';
            root.dataset.mediaJson = JSON.stringify(Array.from(card.querySelectorAll('.guest-cover img')).map(img => ({
                media_type:'image', url:img.dataset.full || img.currentSrc || img.src,
                name:img.alt, uploaded_at_epoch:Number(img.closest('.guest-cover-slide')?.querySelector('[data-media-uploaded-at]')?.dataset.mediaUploadedAt || 0)
            })));
            root.dataset.documentsJson = '[]';
            const selected = card.querySelectorAll('.guest-cover img')[activeIndex] || card.querySelector('.guest-cover img');
            const seed = selected?.currentSrc || selected?.getAttribute('src') || '';
            media.replaceChildren(root); info.replaceChildren();
            panel.classList.add('has-unified-detail');
            detailViewer = window.OrderGuestDetail.mount(root,{head,panels,close:closeDetail,initialIndex:activeIndex,initialImage:seed});
            root.classList.add('od-pending');
        }

        if (typeof window.applyTrackingLanguage === 'function') window.applyTrackingLanguage(layout);
        guestApplyBilingualText();
        loading.hidden = true;
        layout.hidden = false;
        info.scrollTop = 0;
    }

    function normalizeDetailImages(root) {
        root.querySelectorAll('img').forEach(function (img, index) {
            const raw = img.getAttribute('src') || img.dataset.src || '';
            if (raw && raw.includes('/image/')) {
                img.setAttribute('src', raw.replace('/image/', '/thumb/'));
            } else if (!img.getAttribute('src') && img.dataset.src) {
                img.setAttribute('src', img.dataset.src);
            }
            img.removeAttribute('data-src');
            img.decoding = 'async';
            img.loading = index < 2 ? 'eager' : 'lazy';
        });
    }

    function hydrateDetailHtml(url, html) {
        if (activeUrl !== absoluteUrl(url)) return;
        const doc = new DOMParser().parseFromString(html, 'text/html');
        const orderHead = doc.querySelector('.guest-order-head');
        const galleryShell = doc.querySelector('.guest-gallery-shell');
        const panels = Array.from(doc.querySelectorAll('.guest-panel:not(.pdf-documents)'));
        if (!orderHead && !galleryShell && !panels.length) return;

        const unified = doc.querySelector('[data-order-media]');
        const selectedUrl = detailViewer?.currentURL();
        const seed = media.querySelector('.od-image img.od-ready')?.currentSrc || media.querySelector('[data-od-placeholder]')?.currentSrc || '';
        detailViewer?.destroy(); detailViewer = null;
        media.replaceChildren(); info.replaceChildren();
        if (unified && window.OrderGuestDetail) {
            panel.classList.add('has-unified-detail');
            const root = unified.cloneNode(true); media.append(root);
            detailViewer = window.OrderGuestDetail.mount(root,{
                head:orderHead?.cloneNode(true),panels:panels.map(p => p.cloneNode(true)),
                close:closeDetail,initialIndex:activeIndex,initialUrl:selectedUrl,initialImage:seed
            });
        } else {
            panel.classList.remove('has-unified-detail');
            if (galleryShell) {const gallery=galleryShell.cloneNode(true); normalizeDetailImages(gallery);media.append(gallery);}
            if (orderHead) info.append(orderHead.cloneNode(true));
            panels.forEach(section => info.append(section.cloneNode(true)));
        }
        if (typeof window.applyTrackingLanguage === 'function') window.applyTrackingLanguage(layout);
        guestApplyBilingualText();
        initGallery(media);
        loading.hidden = true;
        layout.hidden = false;
        info.scrollTop = 0;
        detailViewer?.root.querySelector('.od-close')?.focus({preventScroll:true});
    }

    function fetchDetail(url, signal) {
        const key = absoluteUrl(url);
        if (detailCache.has(key) && Date.now() - (detailCacheAt.get(key) || 0) < 30000) return Promise.resolve(detailCache.get(key));
        const pending = detailInflight.get(key);
        if (pending && !pending.signal?.aborted) return pending.promise;

        const promise = fetch(url, {
            credentials:'same-origin',
            cache:'no-store',
            signal:signal,
            headers:{'X-Requested-With':'XMLHttpRequest'}
        }).then(function (response) {
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return response.text();
        }).then(function (html) {
            detailCache.set(key, html); detailCacheAt.set(key, Date.now());
            if(detailCache.size > 40){const oldest=detailCache.keys().next().value;detailCache.delete(oldest);detailCacheAt.delete(oldest);}
            if(detailInflight.get(key)?.promise === promise) detailInflight.delete(key);
            return html;
        }).catch(function (error) {
            if(detailInflight.get(key)?.promise === promise) detailInflight.delete(key);
            throw error;
        });
        detailInflight.set(key, {promise,signal});
        return promise;
    }

    function prefetchDetail(url) {
        if (!isDesktop() || !url) return;
        const key = absoluteUrl(url);
        if ((detailCache.has(key) && Date.now()-(detailCacheAt.get(key)||0)<30000) || detailInflight.has(key)) return;
        fetchDetail(url).catch(function () {});
    }

    async function openDetail(url, initialIndex = 0) {
        if (!isDesktop() || !url) return;
        if (requestController) {
            try { requestController.abort(); } catch (_) {}
        }
        const version = ++requestVersion;
        detailViewer?.destroy(); detailViewer = null;
        activeIndex = Math.max(0,Number(initialIndex)||0);
        requestController = new AbortController();
        const controller = requestController;
        activeUrl = absoluteUrl(url);
        overlay.hidden = false;
        overlay.setAttribute('aria-hidden', 'false');
        document.body.classList.add('guest-desktop-detail-open');

        // Zero-wait first paint: reuse data/image already present on the wall.
        showInstantCardShell(url);

        try {
            const html = await fetchDetail(url, controller.signal);
            if (version === requestVersion) hydrateDetailHtml(url, html);
        } catch (error) {
            if (version !== requestVersion || error?.name === 'AbortError') return;
            // Keep the instant card shell visible; only surface the background failure subtly.
            console.warn('[ORDER] modal detail hydration failed', error);
        } finally {
            if (version === requestVersion) requestController = null;
        }
    }

    window.__guestOpenDesktopDetail = openDetail;
    if (window.__guestPendingDesktopDetailUrl) {
        const pendingUrl = window.__guestPendingDesktopDetailUrl;
        window.__guestPendingDesktopDetailUrl = '';
        document.addEventListener("DOMContentLoaded",()=>openDetail(pendingUrl,window.__guestPendingDetailIndex||0),{once:true});
    }

    document.addEventListener('tracking:guestcardsupdated',()=>{detailCache.clear();detailCacheAt.clear();});

    // Start fetching before a click without competing with the first page paint.
    document.addEventListener('pointerenter', function (event) {
        const card = event.target?.closest?.('[data-guest-card]');
        if (card) prefetchDetail(card.getAttribute('href'));
    }, true);
    document.addEventListener('focusin', function (event) {
        const card = event.target?.closest?.('[data-guest-card]');
        if (card) prefetchDetail(card.getAttribute('href'));
    });

    // Do not automatically prefetch nearby order-detail HTML.
    // The wall already opens an instant thumbnail shell on click; hover/focus prefetch
    // above is enough to make deliberate desktop navigation fast without downloading
    // many unseen 16-23KB detail pages and competing with thumbnail traffic.

    closeButton?.addEventListener('click', closeDetail);
    overlay.addEventListener('click', function (event) {
        if (event.target === overlay) closeDetail();
    });
    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && !overlay.hidden) closeDetail();
    });
    desktopQuery?.addEventListener?.('change', function () {
        if (!isDesktop() && !overlay.hidden) closeDetail();
    });
})();
