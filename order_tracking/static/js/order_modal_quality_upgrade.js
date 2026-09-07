// Desktop WEB: keep the instant thumbnail visible at all times, then layer the WEB
// image above it only after the high-quality bitmap has fully loaded and decoded.
// The thumbnail is never removed/replaced, so there is no blank-frame flash.
(function () {
    const root = document.getElementById('guestDesktopDetailMedia');
    if (!root) return;

    const requested = new WeakSet();

    function highQualityUrl(img) {
        const raw = String(img?.getAttribute('src') || '').trim();
        if (!raw || !raw.includes('/thumb/')) return '';
        return raw.replace('/thumb/', '/image/');
    }

    function baseImages(gallery) {
        return Array.from(gallery?.querySelectorAll('.guest-slide img:not([data-modal-hq-overlay])') || []);
    }

    function revealHighQuality(baseImg, high, loader) {
        if (!baseImg?.isConnected || baseImg.dataset.modalHighQualitySrc !== high) return;
        const slide = baseImg.closest('.guest-slide');
        if (!slide || slide.querySelector('img[data-modal-hq-overlay]')) return;

        const overlay = document.createElement('img');
        overlay.dataset.modalHqOverlay = '1';
        overlay.alt = baseImg.alt || '';
        overlay.src = high;
        overlay.decoding = 'async';
        overlay.draggable = false;

        const baseStyle = getComputedStyle(baseImg);
        const slideStyle = getComputedStyle(slide);
        if (slideStyle.position === 'static') slide.style.position = 'relative';

        overlay.style.position = 'absolute';
        overlay.style.inset = '0';
        overlay.style.width = '100%';
        overlay.style.height = '100%';
        overlay.style.objectFit = baseStyle.objectFit || 'contain';
        overlay.style.objectPosition = baseStyle.objectPosition || '50% 50%';
        overlay.style.pointerEvents = 'none';
        overlay.style.opacity = '0';
        overlay.style.transition = 'opacity 120ms ease-out';
        overlay.style.willChange = 'opacity';

        slide.appendChild(overlay);
        baseImg.dataset.modalHighQualityReady = '1';

        // Keep the thumbnail painted underneath until the decoded WEB image is already
        // in the DOM. Only opacity changes, so there is no src swap and no white/black flash.
        requestAnimationFrame(function () {
            requestAnimationFrame(function () {
                if (!overlay.isConnected) return;
                overlay.style.opacity = '1';
                window.setTimeout(function () {
                    if (overlay.isConnected) overlay.style.willChange = 'auto';
                }, 180);
            });
        });
    }

    function upgradeImage(baseImg) {
        if (!baseImg || requested.has(baseImg)) return;
        const high = highQualityUrl(baseImg);
        if (!high) return;
        requested.add(baseImg);
        baseImg.dataset.modalHighQualitySrc = high;

        const loader = new Image();
        loader.decoding = 'async';
        loader.src = high;

        const show = function () {
            // decode() prevents a loaded-but-not-yet-decoded bitmap from causing a repaint hitch.
            const decoded = (typeof loader.decode === 'function') ? loader.decode().catch(function () {}) : Promise.resolve();
            decoded.then(function () { revealHighQuality(baseImg, high, loader); });
        };

        if (loader.complete && loader.naturalWidth > 0) show();
        else loader.onload = show;

        loader.onerror = function () {
            // Thumbnail remains visible. A failed quality upgrade must never hurt the modal.
            baseImg.dataset.modalHighQualityFailed = '1';
        };
    }

    function currentIndex(gallery, images) {
        if (!gallery || !images.length) return 0;
        const width = gallery.clientWidth || 1;
        return Math.max(0, Math.min(images.length - 1, Math.round(gallery.scrollLeft / width)));
    }

    function upgradeCurrent(gallery) {
        const images = baseImages(gallery);
        if (!images.length) return;
        const index = currentIndex(gallery, images);
        upgradeImage(images[index]);

        // Warm only neighbours and only after the current slide has had first priority.
        window.setTimeout(function () {
            if (index + 1 < images.length) upgradeImage(images[index + 1]);
            if (index > 0) upgradeImage(images[index - 1]);
        }, 180);
    }

    function bindGallery(gallery) {
        if (!gallery || gallery.dataset.modalQualityBound === '1') return;
        gallery.dataset.modalQualityBound = '1';
        let timer = 0;
        gallery.addEventListener('scroll', function () {
            window.clearTimeout(timer);
            timer = window.setTimeout(function () { upgradeCurrent(gallery); }, 90);
        }, {passive:true});

        // Two animation frames guarantee the thumbnail gets the first paint.
        requestAnimationFrame(function () {
            requestAnimationFrame(function () { upgradeCurrent(gallery); });
        });
    }

    function scan(node) {
        const scope = node && node.querySelectorAll ? node : root;
        if (scope.matches?.('[data-guest-detail-gallery]')) bindGallery(scope);
        scope.querySelectorAll?.('[data-guest-detail-gallery]').forEach(bindGallery);
    }

    const observer = new MutationObserver(function (records) {
        records.forEach(function (record) {
            record.addedNodes.forEach(function (node) {
                if (node.nodeType === 1) scan(node);
            });
        });
    });
    observer.observe(root, {childList:true, subtree:true});
    scan(root);
})();
