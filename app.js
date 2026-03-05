/**
 * TCS Daily — app.js
 * Minimal SPA: hash router + marked.js renderer with :::aside extension
 */

/* ═══════════════════════════════════════════════════════════
   Theme  (mirrors main site logic — shares localStorage key)
   ═══════════════════════════════════════════════════════════ */

const Theme = {
    current: 'light',

    init() {
        const saved = localStorage.getItem('theme');
        const system = window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
        this.current = saved || system;
        this.apply();

        document.getElementById('theme-btn').addEventListener('click', () => this.toggle());
    },

    apply() {
        const body = document.body;
        const icon = document.querySelector('#theme-btn .theme-icon use');

        if (this.current === 'dark') {
            body.setAttribute('data-theme', 'dark');
            if (icon) icon.setAttribute('href', '#px-moon');
        } else {
            body.removeAttribute('data-theme');
            if (icon) icon.setAttribute('href', '#px-sun');
        }

        const btn = document.getElementById('theme-btn');
        if (btn) btn.title = `Switch to ${this.current === 'light' ? 'Dark' : 'Light'} Mode`;
    },

    toggle() {
        this.current = this.current === 'dark' ? 'light' : 'dark';
        localStorage.setItem('theme', this.current);
        this.apply();
    }
};

/* ═══════════════════════════════════════════════════════════
   Markdown renderer (marked.js + KaTeX + :::aside)
   ═══════════════════════════════════════════════════════════ */

function initMarked() {
    if (typeof marked === 'undefined') return;

    const renderer = new marked.Renderer();

    // Image renderer (same as blog)
    const origImage = renderer.image;
    renderer.image = function(href, title, text) {
        const img = origImage.call(this, href, title, text);
        if (title) {
            return `<figure class="article-image">
                ${img}
                <figcaption>${title}</figcaption>
            </figure>`;
        }
        return `<figure class="article-image">${img}</figure>`;
    };

    // KaTeX extensions
    if (typeof katex !== 'undefined') {
        const mathBlock = {
            name: 'mathBlock',
            level: 'block',
            start(src) { return src.indexOf('$$'); },
            tokenizer(src) {
                const m = /^\$\$([\s\S]+?)\$\$(?:\n+|$)/.exec(src);
                if (m) return { type: 'mathBlock', raw: m[0], text: m[1].trim() };
            },
            renderer(tok) {
                return katex.renderToString(tok.text, {
                    displayMode: true, throwOnError: false, output: 'html'
                });
            }
        };

        const mathInline = {
            name: 'mathInline',
            level: 'inline',
            start(src) { return src.indexOf('$'); },
            tokenizer(src) {
                const m = /^\$([^$\n]+?)\$(?!\d)/.exec(src);
                if (m) return { type: 'mathInline', raw: m[0], text: m[1] };
            },
            renderer(tok) {
                return katex.renderToString(tok.text, {
                    displayMode: false, throwOnError: false, output: 'html'
                });
            }
        };

        // :::aside[label]\ncontent\n::: extension
        const asideBlock = {
            name: 'asideBlock',
            level: 'block',
            start(src) { return src.indexOf(':::aside['); },
            tokenizer(src) {
                const m = /^:::aside\[([^\]]*)\]\n([\s\S]*?)\n:::\s*(?:\n|$)/.exec(src);
                if (m) return { type: 'asideBlock', raw: m[0], label: m[1], text: m[2].trim() };
            },
            renderer(tok) {
                const inner = marked.parse(tok.text);
                const id = 'aside-' + tok.label.toLowerCase().replace(/[^a-z0-9]+/g, '-');
                // Emit: 1) an anchor marker in-flow  2) a hidden data carrier  3) inline <details> for mobile
                return `<span class="sidenote-anchor" data-aside-id="${id}"></span>` +
                       `<template class="sidenote-data" data-aside-id="${id}" data-label="${tok.label}">${inner}</template>` +
                       `<details class="sidenote-inline">` +
                           `<summary>${tok.label}</summary>` +
                           `<div class="sidenote-content">${inner}</div>` +
                       `</details>`;
            }
        };

        // ::::issue or ::::issue[tag1,tag2]\ncontent\n:::: extension
        let issueCounter = 0;
        window._resetIssueCounter = () => { issueCounter = 0; };
        const issueBlock = {
            name: 'issueBlock',
            level: 'block',
            start(src) { return src.indexOf('::::issue'); },
            tokenizer(src) {
                const m = /^::::issue(?:\[([^\]]*)])?\s*\n([\s\S]*?)\n::::\s*(?:\n|$)/.exec(src);
                if (m) return { type: 'issueBlock', raw: m[0], tags: m[1] || '', text: m[2].trim() };
            },
            renderer(tok) {
                issueCounter++;
                const idx = issueCounter;
                const inner = marked.parse(tok.text);
                const tags = tok.tags ? tok.tags.split(',').map(t => t.trim()).filter(Boolean) : [];
                const tagsHTML = tags.length
                    ? `<div class="issue-tags">${tags.map(t => {
                        const info = (window._tagDefs || {})[t] || {};
                        const bg = info.color || 'var(--secondary)';
                        return `<a class="pixel-badge" href="#tag/${encodeURIComponent(t)}" style="background:${bg}">${info.name || t}</a>`;
                      }).join('')}</div>`
                    : '';
                return `<section class="issue-block collapsed" data-issue-index="${idx}">` +
                       `<div class="issue-gutter">` +
                           `<button class="issue-toggle" aria-label="Toggle issue">` +
                               `<svg class="icon small" aria-hidden="true"><use href="#px-triangle"/></svg>` +
                           `</button>` +
                           `<span class="issue-label"></span>` +
                       `</div>` +
                       `<div class="issue-content">${inner}${tagsHTML}</div>` +
                       `</section>`;
            }
        };

        marked.use({ extensions: [mathBlock, mathInline, asideBlock, issueBlock] });
    }

    marked.setOptions({
        renderer,
        breaks: false,
        gfm: true,
        headerIds: true,
        mangle: false,
        tables: true
    });
}

/* ═══════════════════════════════════════════════════════════
   Data layer
   ═══════════════════════════════════════════════════════════ */

let manifest = null;

async function loadManifest() {
    if (manifest) return manifest;
    try {
        const resp = await fetch('posts/manifest.json');
        manifest = await resp.json();
    } catch {
        manifest = { version: 1, reports: [] };
    }
    return manifest;
}

async function loadMarkdown(date) {
    const resp = await fetch(`posts/${date}.md`);
    if (!resp.ok) return null;
    return resp.text();
}

/**
 * Parse YAML frontmatter from markdown string.
 * Returns { meta: {...}, body: "..." }
 */
function parseFrontmatter(md) {
    const m = /^---\n([\s\S]*?)\n---\n?/.exec(md);
    if (!m) return { meta: {}, body: md };
    const meta = {};
    m[1].split('\n').forEach(line => {
        const colon = line.indexOf(':');
        if (colon > 0) {
            const key = line.slice(0, colon).trim();
            let val = line.slice(colon + 1).trim();
            // Simple array parse for tags: [a, b, c]
            if (val.startsWith('[') && val.endsWith(']')) {
                val = val.slice(1, -1).split(',').map(s => s.trim().replace(/^["']|["']$/g, ''));
            }
            meta[key] = val;
        }
    });
    return { meta, body: md.slice(m[0].length) };
}

/**
 * Ensure $$ display-math blocks have blank lines around them.
 * Without this, marked.js treats the $$ as paragraph text, and a lone '='
 * line inside the formula triggers a setext-heading (h1) interpretation.
 */
function ensureMathBlockSpacing(md) {
    const lines = md.split('\n');
    const out = [];
    for (let i = 0; i < lines.length; i++) {
        const trimmed = lines[i].trim();
        if (trimmed === '$$') {
            // blank line before if previous isn't blank
            if (out.length > 0 && out[out.length - 1].trim() !== '') {
                out.push('');
            }
            out.push(lines[i]);
            // blank line after if next isn't blank
            if (i + 1 < lines.length && lines[i + 1].trim() !== '') {
                out.push('');
            }
        } else {
            out.push(lines[i]);
        }
    }
    return out.join('\n');
}

/* ═══════════════════════════════════════════════════════════
   Views
   ═══════════════════════════════════════════════════════════ */

function showLoading() {
    document.getElementById('loading').style.display = '';
    document.getElementById('article-view').style.display = 'none';
    document.getElementById('index-view').style.display = 'none';
    document.getElementById('footer').style.display = 'none';
}

function hideLoading() {
    document.getElementById('loading').style.display = 'none';
    document.getElementById('footer').style.display = '';
}

/**
 * Render a single issue.
 */
async function showArticle(date, expandIssue) {
    showLoading();

    const man = await loadManifest();
    const reports = man.reports || [];
    const entry = reports.find(r => r.date === date);

    // Expose tag definitions globally for issue-block tag rendering
    window._tagDefs = man.tags || {};

    const md = await loadMarkdown(date);
    if (!md) {
        document.getElementById('loading').innerHTML =
            `<div class="loading-text">404 — no report for ${date}</div>`;
        return;
    }

    const { meta, body } = parseFrontmatter(md);
    // Reset issue counter before each render
    if (typeof marked !== 'undefined' && marked._issueCounter !== undefined) {
        marked._issueCounter = 0;
    }
    // Reset the closure counter by re-calling initMarked's counter
    window._resetIssueCounter && window._resetIssueCounter();
    const html = marked.parse(ensureMathBlockSpacing(body));

    // Compute issue number (reports sorted newest first, so #1 = oldest)
    const sortedDates = reports.map(r => r.date).sort();
    const issueNum = sortedDates.indexOf(date) + 1;

    // Collect tags
    const tags = entry?.tags || meta.tags || [];
    const tagDefs = man.tags || {};

    // Header
    const header = document.getElementById('article-header');
    const tagsHTML = Array.isArray(tags) && tags.length
        ? `<div class="article-tags">${tags.map(t => {
            const info = tagDefs[t] || {};
            const bg = info.color || 'var(--secondary)';
            return `<a class="pixel-badge" href="#tag/${encodeURIComponent(t)}" style="background:${bg}">${info.name || t}</a>`;
          }).join('')}</div>`
        : '';

    // Prev/next nav
    const idx = sortedDates.indexOf(date);
    const prevDate = idx > 0 ? sortedDates[idx - 1] : null;
    const nextDate = idx < sortedDates.length - 1 ? sortedDates[idx + 1] : null;

    const prevBtn = prevDate
        ? `<a class="nav-arrow" href="#${prevDate}" title="${prevDate}"><svg class="icon small" aria-hidden="true"><use href="#px-triangle"/></svg></a>`
        : `<span class="nav-arrow disabled"><svg class="icon small" aria-hidden="true"><use href="#px-triangle"/></svg></span>`;
    const nextBtn = nextDate
        ? `<a class="nav-arrow nav-arrow-next" href="#${nextDate}" title="${nextDate}"><svg class="icon small" aria-hidden="true"><use href="#px-triangle"/></svg></a>`
        : `<span class="nav-arrow nav-arrow-next disabled"><svg class="icon small" aria-hidden="true"><use href="#px-triangle"/></svg></span>`;

    header.innerHTML =
        `<h1 class="article-title">TCS Daily</h1>` +
        `<div class="article-meta">` +
            prevBtn +
            `<span class="article-date">${date}</span>` +
            (issueNum > 0 ? `<span class="article-issue">#${String(issueNum).padStart(3, '0')}</span>` : '') +
            nextBtn +
        `</div>` +
        tagsHTML;

    // Body
    document.getElementById('article-body').innerHTML = html;

    // Extract sidenotes from <template> data carriers into the external column
    buildSidenoteColumn();

    // Expand a specific issue if requested (via #date:N), otherwise all start collapsed
    if (expandIssue) {
        const target = document.querySelector(`.issue-block[data-issue-index="${expandIssue}"]`);
        if (target) target.classList.remove('collapsed');
    }

    // Sync sidenote visibility for initial collapsed state
    syncSidenoteVisibility();

    hideLoading();
    document.getElementById('article-view').style.display = '';

    // Update page title
    document.title = `TCS Daily — ${date}`;

    // Scroll to top
    window.scrollTo(0, 0);

    // Position after layout settles
    requestAnimationFrame(() => requestAnimationFrame(positionSidenotes));
}

/**
 * Extract sidenotes from rendered HTML into the external #sidenote-column.
 * Each <template class="sidenote-data"> in article-body becomes an <aside>
 * in the column. The <span class="sidenote-anchor"> stays in-flow as a
 * position reference.
 */
function buildSidenoteColumn() {
    const col = document.getElementById('sidenote-column');
    col.innerHTML = '';

    const templates = document.querySelectorAll('#article-body .sidenote-data');
    templates.forEach(tpl => {
        const id = tpl.dataset.asideId;
        const label = tpl.dataset.label;
        const inner = tpl.innerHTML;

        const aside = document.createElement('aside');
        aside.className = 'sidenote';
        aside.id = id;
        aside.innerHTML =
            `<span class="sidenote-label">${label}</span>` + inner;
        col.appendChild(aside);
    });
}

/**
 * Hide sidenotes whose anchors belong to a collapsed issue-block.
 * Show sidenotes whose anchors belong to expanded issue-blocks.
 */
function syncSidenoteVisibility() {
    const col = document.getElementById('sidenote-column');
    const notes = col.querySelectorAll('.sidenote');
    notes.forEach(note => {
        const anchor = document.querySelector(`.sidenote-anchor[data-aside-id="${note.id}"]`);
        if (!anchor) return;
        const issueBlock = anchor.closest('.issue-block');
        // If anchor is inside a collapsed issue-block, hide the sidenote
        if (issueBlock && issueBlock.classList.contains('collapsed')) {
            note.style.display = 'none';
        } else {
            note.style.display = '';
        }
    });
}

/**
 * On wide screens, position each sidenote in the external column so its top
 * aligns with the corresponding anchor in the article body.
 * Stacks downward if they would overlap.
 */
function positionSidenotes() {
    const col = document.getElementById('sidenote-column');
    const notes = col.querySelectorAll('.sidenote');
    if (!notes.length) return;

    // On narrow screens the column is hidden — skip positioning
    if (window.innerWidth < 1200) return;

    const containerRect = document.getElementById('container').getBoundingClientRect();
    let lastBottom = 0;

    notes.forEach(note => {
        // Skip hidden sidenotes (from collapsed issue-blocks)
        if (note.style.display === 'none') return;

        const anchor = document.querySelector(`.sidenote-anchor[data-aside-id="${note.id}"]`);
        if (!anchor) return;

        const anchorTop = anchor.getBoundingClientRect().top - containerRect.top;
        const top = Math.max(anchorTop, lastBottom + 12);
        note.style.top = top + 'px';

        // measure after positioning
        lastBottom = top + note.getBoundingClientRect().height;
    });
}

/**
 * Render the index page with issue-level granularity.
 * Each date group shows a date row + indented paper rows.
 * Filtering hides individual papers that don't match;
 * if no papers in a date match, the whole date group is hidden.
 */
async function showIndex(filterTag) {
    showLoading();

    const man = await loadManifest();
    const reports = man.reports || [];
    const tagDefs = man.tags || {};

    // Collect all tags across all papers
    const allTags = new Set();
    reports.forEach(r => {
        (r.tags || []).forEach(t => allTags.add(t));
        (r.papers || []).forEach(p => (p.tags || []).forEach(t => allTags.add(t)));
    });

    // --- Tag filter bar ---
    const tagsEl = document.getElementById('index-tags');
    const tagArr = [...allTags].sort();
    tagsEl.innerHTML = tagArr.map(t => {
        const info = tagDefs[t] || {};
        const bg = info.color || 'var(--secondary)';
        const active = filterTag === t;
        return `<a class="pixel-badge tag-filter${active ? ' active' : ''}"
                    href="#tag/${encodeURIComponent(t)}"
                    style="--tag-color:${bg};background:${bg}">${info.name || t}</a>`;
    }).join('') + (filterTag
        ? ` <a class="pixel-badge tag-filter clear-btn" href="#index">✕ clear</a>`
        : '');

    // --- Build date-grouped list ---
    const listEl = document.getElementById('index-list');
    let html = '';
    const sorted = [...reports].sort((a, b) => b.date.localeCompare(a.date));

    sorted.forEach(r => {
        const papers = r.papers || [];
        if (!papers.length) return;

        // Determine which papers match the filter
        const paperMatches = papers.map(p => {
            if (!filterTag) return true;
            return (p.tags || []).includes(filterTag);
        });
        const anyMatch = paperMatches.some(Boolean);

        html += `<div class="date-group${anyMatch ? '' : ' hidden-by-filter'}">`;
        html += `<a class="date-row" href="#${r.date}">
                    <span class="date-row-date">${r.date}</span>
                 </a>`;

        papers.forEach((p, i) => {
            const issueIdx = i + 1;
            const hidden = filterTag && !paperMatches[i];
            const pTags = (p.tags || []).map(t => {
                const info = tagDefs[t] || {};
                const bg = info.color || 'var(--secondary)';
                const match = filterTag && t === filterTag;
                return `<span class="pixel-badge${match ? ' tag-match' : ''}" style="--tag-color:${bg};background:${bg}">${info.name || t}</span>`;
            }).join('');
            html += `<a class="paper-row${hidden ? ' hidden-by-filter' : ''}" href="#${r.date}:${issueIdx}">
                        <span class="paper-row-index">Issue ${issueIdx}</span>
                        <span class="paper-row-title">${p.title || p.arxiv_id}</span>
                        <span class="paper-row-tags">${pTags}</span>
                     </a>`;
        });

        html += `</div>`;
    });

    listEl.innerHTML = html || `<div class="loading-text" style="padding:40px 0;">no reports${filterTag ? ` tagged "${filterTag}"` : ''}</div>`;

    hideLoading();
    document.getElementById('index-view').style.display = '';
    document.title = 'TCS Daily — Index';
    window.scrollTo(0, 0);
}

/* ═══════════════════════════════════════════════════════════
   Router
   ═══════════════════════════════════════════════════════════ */

async function route() {
    const hash = location.hash.slice(1) || '';

    // Clear sidenote column on every route change
    document.getElementById('sidenote-column').innerHTML = '';

    // #index
    if (hash === 'index') {
        showIndex(null);
        return;
    }

    // #tag/xxx
    const tagMatch = hash.match(/^tag\/(.+)$/);
    if (tagMatch) {
        showIndex(decodeURIComponent(tagMatch[1]));
        return;
    }

    // #YYYY-MM-DD:N — show article with issue N expanded
    const dateIssueMatch = hash.match(/^(\d{4}-\d{2}-\d{2})(?::(\d+))?$/);
    if (dateIssueMatch) {
        showArticle(dateIssueMatch[1], dateIssueMatch[2] ? parseInt(dateIssueMatch[2]) : null);
        return;
    }

    // Empty hash or unknown — show latest issue
    if (hash === '' || hash === '#') {
        const man = await loadManifest();
        const dates = (man.reports || []).map(r => r.date).sort();
        if (dates.length) {
            showArticle(dates[dates.length - 1]);
        } else {
            showIndex(null);
        }
        return;
    }

    // Fallback: try as date
    showArticle(hash);
}

/* ═══════════════════════════════════════════════════════════
   Init
   ═══════════════════════════════════════════════════════════ */

async function init() {
    Theme.init();
    initMarked();

    // Issue-block toggle (event delegation on persistent element)
    document.getElementById('article-body').addEventListener('click', e => {
        let toggled = false;
        // Toggle via entire gutter area (triangle + label)
        const gutter = e.target.closest('.issue-gutter');
        if (gutter) {
            gutter.closest('.issue-block').classList.toggle('collapsed');
            toggled = true;
        }
        // Toggle via heading click (on mobile the gutter is hidden,
        // so the h2 is the only toggle — must work in both directions)
        if (!toggled) {
            const heading = e.target.closest('.issue-block .issue-content > h2');
            if (heading) {
                heading.closest('.issue-block').classList.toggle('collapsed');
                toggled = true;
            }
        }
        // After any toggle, sync sidenote visibility and reposition
        if (toggled) {
            syncSidenoteVisibility();
            requestAnimationFrame(positionSidenotes);
        }
    });

    window.addEventListener('hashchange', route);
    window.addEventListener('resize', positionSidenotes);

    route();
}

// Wait for KaTeX to load (it's deferred)
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        setTimeout(init, 100);
    });
} else {
    setTimeout(init, 100);
}
