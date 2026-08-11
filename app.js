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
                const contentId = `issue-content-${idx}`;
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
                       `<button class="issue-toggle" type="button" ` +
                               `aria-expanded="false" aria-controls="${contentId}" ` +
                               `aria-label="Expand issue ${idx}">` +
                           `<svg class="icon small" aria-hidden="true"><use href="#px-triangle"/></svg>` +
                           `<span class="issue-label">Issue ${idx}</span>` +
                       `</button>` +
                       `<div class="issue-content" id="${contentId}">${inner}${tagsHTML}</div>` +
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
const expandedTagCategories = new Set();
let routeGeneration = 0;

function isCurrentRoute(generation) {
    return generation === routeGeneration;
}

async function loadManifest(force = false) {
    if (manifest && !force) return manifest;
    try {
        const resp = await fetch('posts/manifest.json', { cache: 'no-store' });
        manifest = await resp.json();
    } catch {
        manifest = manifest || { version: 1, reports: [] };
    }
    return manifest;
}

async function loadMarkdown(date) {
    const resp = await fetch(`posts/${date}.md`, { cache: 'no-store' });
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

function escapeHtml(value) {
    return String(value)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
}

/** Render only $...$ fragments from manifest titles; keep all other text inert. */
function renderInlineMath(value) {
    const source = String(value || '');
    if (typeof katex === 'undefined' || !source.includes('$')) {
        return escapeHtml(source);
    }

    const pattern = /\$([^$\n]+?)\$(?!\d)/g;
    let cursor = 0;
    let html = '';
    for (const match of source.matchAll(pattern)) {
        html += escapeHtml(source.slice(cursor, match.index));
        html += katex.renderToString(match[1], {
            displayMode: false,
            throwOnError: false,
            output: 'html',
        });
        cursor = match.index + match[0].length;
    }
    return html + escapeHtml(source.slice(cursor));
}

function prettyCategoryName(slug) {
    return slug.split('-').map(part => part.charAt(0).toUpperCase() + part.slice(1)).join(' ');
}

function normalizeReportHref(href) {
    if (!href) return href;
    const match = href.match(/^(?:\.\.\/)?posts\/(\d{4}-\d{2}-\d{2})\.md(?:[#?].*)?$/)
        || href.match(/^(\d{4}-\d{2}-\d{2})\.md(?:[#?].*)?$/);
    return match ? `#${match[1]}` : href;
}

function normalizeArticleLinks(container) {
    if (!container) return;
    container.querySelectorAll('a[href]').forEach(link => {
        const href = link.getAttribute('href');
        const normalized = normalizeReportHref(href);
        if (normalized !== href) {
            link.setAttribute('href', normalized);
        }
    });
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
async function showArticle(date, expandIssue, generation) {
    showLoading();

    const md = await loadMarkdown(date);
    if (!isCurrentRoute(generation)) return;
    if (!md) {
        const message = document.createElement('div');
        message.className = 'loading-text';
        message.textContent = `404 — no report for ${date}`;
        document.getElementById('loading').replaceChildren(message);
        return;
    }

    let man = await loadManifest();
    if (!isCurrentRoute(generation)) return;
    let reports = man.reports || [];
    let entry = reports.find(r => r.date === date);
    if (!entry) {
        // A stale manifest can hide newly deployed reports from navigation/index.
        man = await loadManifest(true);
        if (!isCurrentRoute(generation)) return;
        reports = man.reports || [];
        entry = reports.find(r => r.date === date);
    }

    // Expose tag definitions globally for issue-block tag rendering
    window._tagDefs = man.tags || {};

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
    normalizeArticleLinks(document.getElementById('article-body'));

    // Extract sidenotes from <template> data carriers into the external column
    buildSidenoteColumn();
    normalizeArticleLinks(document.getElementById('sidenote-column'));

    // Expand a specific issue if requested (via #date:N), otherwise all start collapsed
    if (expandIssue) {
        const target = document.querySelector(`.issue-block[data-issue-index="${expandIssue}"]`);
        if (target) setIssueExpanded(target, true);
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

function setIssueExpanded(block, expanded) {
    if (!block) return;
    block.classList.toggle('collapsed', !expanded);
    const button = block.querySelector('.issue-toggle');
    if (!button) return;
    const issueIndex = block.dataset.issueIndex || '';
    button.setAttribute('aria-expanded', String(expanded));
    button.setAttribute('aria-label', `${expanded ? 'Collapse' : 'Expand'} issue ${issueIndex}`);
}

function toggleIssue(block) {
    setIssueExpanded(block, block.classList.contains('collapsed'));
    syncSidenoteVisibility();
    requestAnimationFrame(positionSidenotes);
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
async function showIndex(filterTag, generation) {
    showLoading();

    const man = await loadManifest(true);
    if (!isCurrentRoute(generation)) return;
    const reports = man.reports || [];
    const tagDefs = man.tags || {};
    const categoryDefs = man.categories || {};
    const tagUsage = new Map();
    reports.forEach(r => {
        (r.papers || []).forEach(p => {
            [...new Set(p.tags || [])].forEach(t => {
                tagUsage.set(t, (tagUsage.get(t) || 0) + 1);
            });
        });
    });

    const groupedTags = new Map();
    for (const [tag, count] of tagUsage.entries()) {
        const info = tagDefs[tag] || {};
        const category = info.category || 'uncategorized';
        if (!groupedTags.has(category)) groupedTags.set(category, []);
        groupedTags.get(category).push({ tag, count, info });
    }

    if (filterTag) {
        const category = (tagDefs[filterTag] || {}).category || 'uncategorized';
        expandedTagCategories.clear();
        expandedTagCategories.add(category);
    }

    // --- Tag filter bar ---
    const tagsEl = document.getElementById('index-tags');
    const categoryOrder = Object.entries(categoryDefs)
        .sort((a, b) => (a[1].order ?? 999) - (b[1].order ?? 999))
        .map(([key]) => key);
    const orderedCategories = [
        ...categoryOrder.filter(key => groupedTags.has(key)),
        ...[...groupedTags.keys()].filter(key => !categoryOrder.includes(key)).sort(),
    ];
    tagsEl.innerHTML = orderedCategories.map(category => {
            const catInfo = categoryDefs[category] || { name: prettyCategoryName(category) };
            const tags = (groupedTags.get(category) || []).sort((a, b) =>
                b.count - a.count || (a.info.name || a.tag).localeCompare(b.info.name || b.tag)
            );
            const expanded = expandedTagCategories.has(category);
            const preview = tags.slice(0, 2);
            const accent = catInfo.accent || 'var(--accent)';
            const categoryId = `tag-category-${category}`;
            return `<section class="tag-category${expanded ? ' expanded' : ''}"
                             style="--category-accent:${accent}">
                        <button class="tag-category-toggle" type="button" data-tag-category="${category}"
                                aria-expanded="${expanded}" aria-controls="${categoryId}">
                            <span class="tag-category-heading">
                                <span class="tag-category-name">${catInfo.name}</span>
                                <span class="tag-category-meta">${tags.length} tags</span>
                            </span>
                        </button>
                        <div class="tag-category-preview">
                            ${preview.map(({ tag, info }) => {
                                const bg = info.color || 'var(--secondary)';
                                return `<span class="pixel-badge tag-preview-badge"
                                            style="--tag-color:${bg};background:${bg}">${info.name || tag}</span>`;
                            }).join('')}
                        </div>
                        <div class="tag-category-tags" id="${categoryId}">
                            ${tags.map(({ tag, info }) => {
                                const bg = info.color || 'var(--secondary)';
                                const active = filterTag === tag;
                                return `<a class="pixel-badge tag-filter${active ? ' active' : ''}"
                                            href="#tag/${encodeURIComponent(tag)}"
                                            style="--tag-color:${bg};background:${bg}">${info.name || tag}</a>`;
                            }).join('')}
                        </div>
                    </section>`;
        }).join('');

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
                        <span class="paper-row-title">${renderInlineMath(p.title || p.arxiv_id)}</span>
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
    const generation = ++routeGeneration;
    const hash = location.hash.slice(1) || '';

    // Clear sidenote column on every route change
    document.getElementById('sidenote-column').innerHTML = '';

    try {
        // #index
        if (hash === 'index') {
            await showIndex(null, generation);
            return;
        }

        // #tag/xxx
        const tagMatch = hash.match(/^tag\/(.+)$/);
        if (tagMatch) {
            await showIndex(decodeURIComponent(tagMatch[1]), generation);
            return;
        }

        // #YYYY-MM-DD:N — show article with issue N expanded
        const dateIssueMatch = hash.match(/^(\d{4}-\d{2}-\d{2})(?::(\d+))?$/);
        if (dateIssueMatch) {
            await showArticle(
                dateIssueMatch[1],
                dateIssueMatch[2] ? parseInt(dateIssueMatch[2]) : null,
                generation,
            );
            return;
        }

        // Empty hash — show latest issue
        if (hash === '' || hash === '#') {
            const man = await loadManifest(true);
            if (!isCurrentRoute(generation)) return;
            const dates = (man.reports || []).map(r => r.date).sort();
            if (dates.length) {
                await showArticle(dates[dates.length - 1], null, generation);
            } else {
                await showIndex(null, generation);
            }
            return;
        }

        // Fallback: try as date
        await showArticle(hash, null, generation);
    } catch (error) {
        if (!isCurrentRoute(generation)) return;
        console.error('Failed to render route:', error);
        const message = document.createElement('div');
        message.className = 'loading-text';
        message.textContent = 'Unable to load this page. Please try again.';
        document.getElementById('loading').replaceChildren(message);
    }
}

/* ═══════════════════════════════════════════════════════════
   Init
   ═══════════════════════════════════════════════════════════ */

async function init() {
    Theme.init();
    initMarked();

    // Issue-block toggle (event delegation on persistent element)
    document.getElementById('article-body').addEventListener('click', e => {
        const button = e.target.closest('.issue-toggle');
        if (button) toggleIssue(button.closest('.issue-block'));
    });
    document.getElementById('article-body').addEventListener('keydown', e => {
        const button = e.target.closest('.issue-toggle');
        if (!button || (e.key !== 'Enter' && e.key !== ' ')) return;
        e.preventDefault();
        toggleIssue(button.closest('.issue-block'));
    });

    document.getElementById('index-tags').addEventListener('click', e => {
        const tag = e.target.closest('.tag-filter');
        if (tag) {
            const href = tag.getAttribute('href') || '';
            const targetTag = href.startsWith('#tag/') ? decodeURIComponent(href.slice(5)) : '';
            const currentMatch = location.hash.slice(1).match(/^tag\/(.+)$/);
            const currentTag = currentMatch ? decodeURIComponent(currentMatch[1]) : '';
            if (targetTag && targetTag === currentTag) {
                e.preventDefault();
                location.hash = 'index';
            }
            return;
        }

        const button = e.target.closest('.tag-category-toggle');
        if (!button) return;
        const category = button.dataset.tagCategory;
        const section = button.closest('.tag-category');
        if (!category || !section) return;
        if (expandedTagCategories.has(category)) {
            expandedTagCategories.delete(category);
        } else {
            expandedTagCategories.clear();
            expandedTagCategories.add(category);
        }
        document.querySelectorAll('.tag-category.expanded').forEach(node => {
            if (node !== section) {
                node.classList.remove('expanded');
                node.querySelector('.tag-category-toggle')?.setAttribute('aria-expanded', 'false');
            }
        });
        const expanded = section.classList.toggle('expanded');
        button.setAttribute('aria-expanded', String(expanded));
    });

    window.addEventListener('hashchange', () => { void route(); });
    window.addEventListener('resize', positionSidenotes);

    void route();
}

// Wait for KaTeX to load (it's deferred)
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        setTimeout(init, 100);
    });
} else {
    setTimeout(init, 100);
}
