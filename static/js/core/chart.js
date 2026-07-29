/**
 * 轻量 Canvas 折线图（零依赖）
 * 支持多序列、渐变填充、悬停提示、DPR 缩放、主题色自适应。
 */

function cssVar(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
}

/**
 * 绘制趋势折线图
 * @param {HTMLCanvasElement} canvas
 * @param {object} data
 * @param {string[]} data.labels - X 轴标签（如日期）
 * @param {{name: string, values: number[], color?: string}[]} data.series
 * @param {object} [opts]
 * @param {number} [opts.height=220]
 * @returns {{redraw: Function, destroy: Function}}
 */
export function drawTrendChart(canvas, data, opts = {}) {
    const height = opts.height || 220;
    let hoverIndex = -1;

    function render() {
        const dpr = window.devicePixelRatio || 1;
        const cssWidth = canvas.parentElement ? canvas.parentElement.clientWidth : 600;
        canvas.width = cssWidth * dpr;
        canvas.height = height * dpr;
        canvas.style.height = height + 'px';
        const ctx = canvas.getContext('2d');
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, cssWidth, height);

        const { labels, series } = data;
        if (!labels || labels.length === 0) return;

        const textDim = cssVar('--text-dim', '#8fa0bf');
        const lineWeak = cssVar('--line-weak', '#162339');
        const accent = cssVar('--accent', '#2aa8ff');
        const palette = [accent, cssVar('--success', '#10b981'), cssVar('--warning', '#f59e0b')];

        const padding = { top: 14, right: 14, bottom: 26, left: 38 };
        const plotW = cssWidth - padding.left - padding.right;
        const plotH = height - padding.top - padding.bottom;

        const maxVal = Math.max(1, ...series.flatMap((s) => s.values));
        const niceMax = niceCeil(maxVal);
        const xStep = labels.length > 1 ? plotW / (labels.length - 1) : 0;
        const xAt = (i) => padding.left + (labels.length > 1 ? i * xStep : plotW / 2);
        const yAt = (v) => padding.top + plotH - (v / niceMax) * plotH;

        // 网格 + Y 轴刻度
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        const gridLines = 4;
        for (let g = 0; g <= gridLines; g++) {
            const val = (niceMax / gridLines) * g;
            const y = yAt(val);
            ctx.strokeStyle = lineWeak;
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(padding.left, y);
            ctx.lineTo(cssWidth - padding.right, y);
            ctx.stroke();
            ctx.fillStyle = textDim;
            ctx.fillText(formatNum(val), padding.left - 6, y);
        }

        // X 轴标签（稀疏显示，避免重叠）
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        const labelEvery = Math.max(1, Math.ceil(labels.length / Math.floor(plotW / 58)));
        labels.forEach((label, i) => {
            if (i % labelEvery !== 0 && i !== labels.length - 1) return;
            ctx.fillStyle = textDim;
            ctx.fillText(shortLabel(label), xAt(i), padding.top + plotH + 8);
        });

        // 序列
        series.forEach((s, si) => {
            const color = s.color || palette[si % palette.length];
            // 填充
            if (labels.length > 1) {
                const grad = ctx.createLinearGradient(0, padding.top, 0, padding.top + plotH);
                grad.addColorStop(0, colorWithAlpha(color, 0.22));
                grad.addColorStop(1, colorWithAlpha(color, 0));
                ctx.beginPath();
                s.values.forEach((v, i) => {
                    const x = xAt(i), y = yAt(v);
                    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
                });
                ctx.lineTo(xAt(labels.length - 1), padding.top + plotH);
                ctx.lineTo(xAt(0), padding.top + plotH);
                ctx.closePath();
                ctx.fillStyle = grad;
                ctx.fill();
            }
            // 折线
            ctx.beginPath();
            s.values.forEach((v, i) => {
                const x = xAt(i), y = yAt(v);
                i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
            });
            ctx.strokeStyle = color;
            ctx.lineWidth = 2;
            ctx.lineJoin = 'round';
            ctx.stroke();
            // 数据点
            s.values.forEach((v, i) => {
                ctx.beginPath();
                ctx.arc(xAt(i), yAt(v), i === hoverIndex ? 4 : 2.5, 0, Math.PI * 2);
                ctx.fillStyle = color;
                ctx.fill();
            });
        });

        // 悬停提示
        if (hoverIndex >= 0 && hoverIndex < labels.length) {
            const x = xAt(hoverIndex);
            ctx.strokeStyle = colorWithAlpha(accent, 0.4);
            ctx.setLineDash([4, 4]);
            ctx.beginPath();
            ctx.moveTo(x, padding.top);
            ctx.lineTo(x, padding.top + plotH);
            ctx.stroke();
            ctx.setLineDash([]);

            const lines = [labels[hoverIndex], ...series.map((s) => `${s.name}: ${s.values[hoverIndex]}`)];
            ctx.font = '11px sans-serif';
            const boxW = Math.max(...lines.map((l) => ctx.measureText(l).width)) + 16;
            const boxH = lines.length * 16 + 10;
            let bx = x + 10;
            if (bx + boxW > cssWidth - 4) bx = x - boxW - 10;
            const by = padding.top + 4;
            ctx.fillStyle = cssVar('--surface', '#0e1a2d');
            ctx.strokeStyle = cssVar('--line-strong', '#223650');
            roundRect(ctx, bx, by, boxW, boxH, 6);
            ctx.fill();
            ctx.stroke();
            ctx.textAlign = 'left';
            ctx.textBaseline = 'top';
            lines.forEach((line, li) => {
                ctx.fillStyle = li === 0 ? cssVar('--text-main', '#d9e5ff') : textDim;
                ctx.fillText(line, bx + 8, by + 6 + li * 16);
            });
        }

        canvas._xAt = xAt;
        canvas._plotLeft = padding.left;
        canvas._plotRight = cssWidth - padding.right;
    }

    function onMouseMove(e) {
        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const { labels } = data;
        if (!labels || labels.length === 0) return;
        const plotW = canvas._plotRight - canvas._plotLeft;
        const step = labels.length > 1 ? plotW / (labels.length - 1) : plotW;
        const idx = Math.round((x - canvas._plotLeft) / step);
        const next = (idx >= 0 && idx < labels.length) ? idx : -1;
        if (next !== hoverIndex) {
            hoverIndex = next;
            render();
        }
    }

    function onMouseLeave() {
        if (hoverIndex !== -1) {
            hoverIndex = -1;
            render();
        }
    }

    canvas.addEventListener('mousemove', onMouseMove);
    canvas.addEventListener('mouseleave', onMouseLeave);
    window.addEventListener('resize', render);
    document.addEventListener('themechange', render);

    render();

    return {
        redraw(newData) {
            if (newData) data = newData;
            hoverIndex = -1;
            render();
        },
        destroy() {
            canvas.removeEventListener('mousemove', onMouseMove);
            canvas.removeEventListener('mouseleave', onMouseLeave);
            window.removeEventListener('resize', render);
            document.removeEventListener('themechange', render);
        },
    };
}

function niceCeil(v) {
    const mag = Math.pow(10, Math.floor(Math.log10(v)));
    const norm = v / mag;
    let nice;
    if (norm <= 1) nice = 1;
    else if (norm <= 2) nice = 2;
    else if (norm <= 5) nice = 5;
    else nice = 10;
    return nice * mag;
}

function formatNum(v) {
    if (v >= 1000) return (v / 1000).toFixed(v % 1000 === 0 ? 0 : 1) + 'k';
    return String(Math.round(v));
}

function shortLabel(label) {
    // 日期缩短为 MM-DD
    const m = String(label).match(/^\d{4}-(\d{2}-\d{2})$/);
    return m ? m[1] : String(label);
}

function colorWithAlpha(hex, alpha) {
    const m = hex.match(/^#([0-9a-f]{6})$/i);
    if (!m) return hex;
    const n = parseInt(m[1], 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
}
