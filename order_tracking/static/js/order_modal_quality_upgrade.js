// Desktop WEB: keep the instant 480px modal paint, then upgrade only the visible
// slide to the WEB image in the background. High-quality loading never blocks open.
(function () {
    const root = document.getElementById('guestDesktopDetailMedia');
    if (!root) return;

    const requested = new WeakSet();

    function highQualityUrl(img) {
        const raw = String(img?.getAttribute('src') || '').trim();
        if (!raw || !raw.includes('/thumb/')) return '';
        return raw.replace('/thumb/', '/image/');
    }

    function upgradeImage(img) {
        if (!img || requested.has(img)) return;
        const high = highQualityUrl(img);
        if (!high) return;
        requested.add(img);
        img.dataset.modalHighQualitySrc = high;

        const loader = new Image();
        loader.decoding = 'async';
        loader.onload = function () {
            if (!img.isConnected || img.dataset.modalHighQualitySrc !== high) return;
            // Keep layout untouched; only replace the bitmap after the WEB image is ready.
            img.src = high;
            img.dataset.modalHighQualityReady = '1';
        };
        loader.onerror = function () {
            // Thumbnail remains visible. A failed quality upgrade must never hurt the modal.
            img.dataset.modalHighQualityFailed = '1';
        };
        loader.src = high;
    }

    function galleryImages(gallery) {
        return Array.from(gallery?.querySelectorAll('.guest-slide img') || []);
    }

    function currentIndex(gallery, images) {
        if (!gallery || !images.length) return 0;
        const width = gallery.clientWidth || 1;
        return Math.max(0, Math.min(images.length - 1, Math.round(gallery.scrollLeft / width)));
    }

    function upgradeCurrent(gallery) {
        const images = galleryImages(gallery);
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

        // Two animation frames guarantee the thumb gets a chance to paint first.
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
