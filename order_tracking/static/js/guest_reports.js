(function () {
    'use strict';

    const body = document.body;
    const token = String(body?.dataset?.guestToken || '').trim();
    const base = String(body?.dataset?.guestReportBase || '').replace(/\/$/, '');
    const root = document.getElementById('guestReportQueueRoot');
    const queueButton = document.getElementById('guestReportQueueButton');
    const queueBadge = document.getElementById('guestReportQueueBadge');
    if (!token || !base || !root) return;

    const storageKey = 'trackingGuestReportJobs:' + token;
    const jobs = new Map();
    let pollTimer = null;
    let estimateAbort = null;
    function tr(zh, es) { return (window.getTrackingLanguage && window.getTrackingLanguage() === 'zh_cn') ? zh : es; }

    function bytesText(bytes) {
        const n = Math.max(0, Number(bytes || 0));
        if (!n) return '—';
        if (n < 1024 * 1024) return `≈ ${Math.max(1, Math.round(n / 1024))} KB`;
        return `≈ ${(n / 1024 / 1024).toFixed(n >= 10 * 1024 * 1024 ? 0 : 1)} MB`;
    }

    function secondsText(low, high) {
        low = Math.max(0, Number(low || 0));
        high = Math.max(low, Number(high || 0));
        if (!high) return tr('时间视内容而定', 'tiempo variable');
        if (high < 60) return `≈ ${Math.max(3, Math.round(low))}–${Math.max(5, Math.round(high))} s`;
        const lowMin = Math.max(1, Math.floor(low / 60));
        const highMin = Math.max(lowMin + (high > low ? 1 : 0), Math.ceil(high / 60));
        return `≈ ${lowMin}–${highMin} min`;
    }

    function formatName() {
        return 'PDF';
    }

    function openLabel() {
        return tr('打开 PDF', 'Abrir PDF');
    }

    function generatedText(value) {
        if (!value) return '';
        const d = new Date(String(value).replace(' ', 'T'));
        if (Number.isNaN(d.getTime())) return String(value);
        return d.toLocaleString((window.getTrackingLanguage && window.getTrackingLanguage() === 'zh_cn') ? 'zh-CN' : 'es-CL', {day:'2-digit', month:'2-digit', year:'numeric', hour:'2-digit', minute:'2-digit'});
    }

    function openQueue() {
        root.classList.add('open');
    }

    function closeQueue() {
        root.classList.remove('open');
    }

    function saveIds() {
        try {
            const ids = Array.from(jobs.keys()).slice(-10);
            sessionStorage.setItem(storageKey, JSON.stringify(ids));
        } catch (_) {}
    }

    function loadIds() {
        try {
            const parsed = JSON.parse(sessionStorage.getItem(storageKey) || '[]');
            return Array.isArray(parsed) ? parsed.filter(Boolean).slice(-10) : [];
        } catch (_) {
            return [];
        }
    }

    function removeJob(jobId) {
        jobs.delete(String(jobId));
        saveIds();
        renderQueue();
    }

    function jobFileUrl(jobId, fileIndex, inline) {
        const url = `${base}/report-jobs/${encodeURIComponent(jobId)}/files/${Number(fileIndex)}`;
        return inline ? `${url}?inline=1` : url;
    }

    function esc(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function jobMeta(job) {
        const bits = [];
        if (job.estimated_bytes) bits.push(bytesText(job.estimated_bytes));
        if (job.estimated_seconds_high) bits.push(secondsText(job.estimated_seconds_low, job.estimated_seconds_high));
        if (job.pdf_page_count) bits.push(`${Number(job.pdf_page_count)} ${tr('页 PDF','pág. PDF')}`);
        return bits.join(' · ');
    }

    function renderQueue() {
        const list = Array.from(jobs.values());
        if (!list.length) {
            root.innerHTML = '';
            root.classList.remove('show', 'open');
            if (queueButton) queueButton.hidden = true;
            if (queueBadge) { queueBadge.hidden = true; queueBadge.textContent = '0'; }
            return;
        }

        const readyCount = list.filter(function (job) { return job.status === 'completed' || job.status === 'failed'; }).length;
        root.classList.add('show');
        if (queueButton) {
            queueButton.hidden = false;
            queueButton.classList.toggle('ready', readyCount > 0);
        }
        if (queueBadge) {
            queueBadge.hidden = false;
            queueBadge.textContent = String(readyCount || list.length);
        }
        root.innerHTML = `<section class="guest-report-queue-panel">
            <div class="guest-report-queue-head">
                <div><strong>${tr('报告队列','Informes')}</strong><span>${tr('后台生成中，可以继续查看订单。','Se preparan en segundo plano. Puede seguir revisando pedidos.')}</span></div>
                <span class="guest-report-queue-count">${list.length}</span>
            </div>
            <div class="guest-report-queue-list">
                ${list.map(function (job) {
                    const fmt = formatName(job.format);
                    const status = String(job.status || 'queued');
                    const meta = jobMeta(job);
                    let body = '';
                    if (status === 'completed') {
                        const files = Array.isArray(job.files) ? job.files : [];
                        body = files.map(function (file, idx) {
                            const fileIndex = Number.isFinite(Number(file.file_index)) ? Number(file.file_index) : idx;
                            const generated = generatedText(job.finished_at || job.created_at);
                            return `<div class="guest-report-ready-file">
                                <span>${esc(file.name || fmt)} · ${esc(bytesText(file.size || 0).replace(/^≈\s*/, ''))}${generated ? ` · ${tr('生成：','Generado:')} ${esc(generated)}` : ''}</span>
                                <div>
                                    <a class="guest-report-open" href="${esc(jobFileUrl(job.id, fileIndex, true))}" target="_blank" rel="noopener">${esc(openLabel(job.format))}</a>
                                    <a class="guest-report-save" href="${esc(jobFileUrl(job.id, fileIndex, false))}" download>${tr('下载','Descargar')}</a>
                                </div>
                            </div>`;
                        }).join('');
                        if (!body) body = `<div class="guest-report-error-copy">${tr('报告已完成，但没有可用文件。','El informe terminó, pero no hay archivo disponible.')}</div>`;
                    } else if (status === 'failed') {
                        body = `<div class="guest-report-error-copy">${esc(job.error || tr('报告生成失败。','No se pudo generar el informe.'))}</div>`;
                    } else {
                        const stateText = status === 'processing' ? tr('生成中…','Generando…') : (Number(job.queue_ahead || 0) > 0 ? `${tr('排队中','En cola')} · ${Number(job.queue_ahead)} ${tr('个任务在前','delante')}` : tr('排队中…','En cola…'));
                        body = `<div class="guest-report-progress"><i></i></div><div class="guest-report-progress-copy">${esc(stateText)}</div>`;
                    }
                    return `<article class="guest-report-queue-item ${esc(status)}" data-job-id="${esc(job.id)}">
                        <div class="guest-report-queue-item-top">
                            <div><strong>${esc(fmt)}</strong><small>${esc(meta || tr('准备报告','Preparando informe'))}</small></div>
                            ${(status === 'completed' || status === 'failed') ? `<button type="button" class="guest-report-dismiss" data-dismiss-job="${esc(job.id)}" aria-label="${tr('关闭','Cerrar')}">×</button>` : ''}
                        </div>
                        ${body}
                    </article>`;
                }).join('')}
            </div>
        </section>`;

        root.querySelectorAll('[data-dismiss-job]').forEach(function (btn) {
            btn.addEventListener('click', function () { removeJob(btn.dataset.dismissJob); });
        });
    }

    function announceReady(job) {
        if (job.__announced) return;
        job.__announced = true;
        try { if (navigator.vibrate) navigator.vibrate([70, 45, 70]); } catch (_) {}
        if (queueButton) {
            queueButton.hidden = false;
            queueButton.classList.add('ready');
        }
    }

    async function fetchJob(jobId) {
        try {
            const response = await fetch(`${base}/report-jobs/${encodeURIComponent(jobId)}`, {
                credentials: 'same-origin', cache: 'no-store'
            });
            if (!response.ok) {
                if (response.status === 404 || response.status === 410) removeJob(jobId);
                return;
            }
            const payload = await response.json();
            if (!payload?.success || !payload?.job) return;
            const previous = jobs.get(String(jobId));
            const next = {...previous, ...payload.job};
            jobs.set(String(jobId), next);
            if (next.status === 'completed' && previous?.status !== 'completed') announceReady(next);
            renderQueue();
        } catch (_) {}
    }

    function schedulePoll(delay) {
        if (pollTimer) clearTimeout(pollTimer);
        const active = Array.from(jobs.values()).some(function (job) {
            return job.status === 'queued' || job.status === 'processing' || !job.status;
        });
        if (!active) return;
        pollTimer = setTimeout(async function () {
            const ids = Array.from(jobs.entries())
                .filter(function (pair) { return pair[1].status === 'queued' || pair[1].status === 'processing' || !pair[1].status; })
                .map(function (pair) { return pair[0]; });
            await Promise.all(ids.map(fetchJob));
            schedulePoll(1300);
        }, Math.max(250, Number(delay || 1300)));
    }

    async function createJob(format, button) {
        format = String(format || '').toLowerCase();
        if (format !== 'pdf') return;
        if (button) {
            button.disabled = true;
            button.classList.add('busy');
        }
        try {
            const response = await fetch(`${base}/report-jobs`, {
                method: 'POST',
                credentials: 'same-origin',
                cache: 'no-store',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({format: format})
            });
            const payload = await response.json().catch(function () { return null; });
            if (!response.ok || !payload?.success || !payload?.job) {
                throw new Error(payload?.error || tr('无法加入生成队列。','No se pudo agregar a la cola.'));
            }
            const job = payload.job;
            jobs.set(String(job.id), job);
            saveIds();
            renderQueue();
            openQueue();
            schedulePoll(350);
        } catch (error) {
            const id = 'local-error-' + Date.now();
            jobs.set(id, {id:id, format:format, status:'failed', error:error.message || tr('请稍后重试。','Intente nuevamente.'), created_at:new Date().toISOString()});
            renderQueue();
            openQueue();
        } finally {
            if (button) {
                button.disabled = false;
                button.classList.remove('busy');
            }
        }
    }

    async function loadEstimate(button) {
        const format = String(button.dataset.guestReportCreate || '').toLowerCase();
        const url = String(button.dataset.estimateUrl || '');
        const node = document.querySelector(`[data-guest-report-estimate="${format}"]`);
        if (!url || !node) return;
        try {
            const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store'});
            const data = await response.json();
            if (!response.ok || !data?.success) throw new Error();
            const bits = [bytesText(data.estimated_bytes), secondsText(data.estimated_seconds_low, data.estimated_seconds_high)];
            if (Number(data.pdf_page_count || 0) > 0) bits.push(`${Number(data.pdf_page_count)} ${tr('页 PDF','pág. PDF')}`);
            if (Number(data.queue_ahead || 0) > 0) bits.push(`${tr('排队','cola')}: ${Number(data.queue_ahead)} ${tr('个任务在前','delante')}`);
            node.textContent = bits.join(' · ') + ' · ' + tr('先准备完成，再由客人决定打开或下载','primero se prepara; no descarga automáticamente');
        } catch (_) {
            node.textContent = tr('大小与时间取决于图片和 PDF 页数 · 不会自动下载','El tamaño y el tiempo dependen de las imágenes y páginas PDF · no descarga automáticamente');
        }
    }

    document.querySelectorAll('[data-guest-report-create]').forEach(function (button) {
        button.addEventListener('click', function () { createJob(button.dataset.guestReportCreate, button); });
        loadEstimate(button);
    });

    if (queueButton) {
        queueButton.addEventListener('click', function () {
            root.classList.toggle('open');
            if (root.classList.contains('open')) queueButton.classList.remove('ready');
        });
    }

    loadIds().forEach(function (jobId) {
        jobs.set(String(jobId), {id: String(jobId), status: ''});
    });
    if (jobs.size) {
        renderQueue();
        Promise.all(Array.from(jobs.keys()).map(fetchJob)).finally(function () { schedulePoll(900); });
    }
    document.addEventListener('tracking:languagechange', function () {
        renderQueue();
        document.querySelectorAll('[data-guest-report-create]').forEach(loadEstimate);
    });
})();
