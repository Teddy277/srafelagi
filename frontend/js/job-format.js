// ============ JOB DESCRIPTION FORMATTER ============
// Shared by the job modal (app.js) and the /job/<id> pages, so a description
// looks the same wherever it's opened.
//
// Descriptions arrive as plain text from Telegram posts and scrapers (plus the
// odd <a> link). They're full of structure the text only implies: "Label: value"
// rows, "Requirements:" headings, "•"/"▪️"/"1." bullets, and run-on walls where
// several "Label: value" pairs share one line. formatJobDescription turns that
// into headings, fact rows, lists and paragraphs, and groups known sections
// (Responsibilities, Requirements, How to apply…) into highlighted blocks.

const JOB_DESC_ALLOWED_TAGS = new Set(['A', 'BR', 'P', 'UL', 'OL', 'LI', 'STRONG', 'B', 'EM', 'I']);
const JOB_DESC_DROPPED_TAGS = new Set(['SCRIPT', 'STYLE', 'IFRAME', 'OBJECT', 'EMBED', 'TEMPLATE', 'NOSCRIPT', 'SVG', 'MATH', 'IMG', 'VIDEO', 'AUDIO', 'FORM', 'INPUT', 'BUTTON']);
const JOB_DESC_BLOCK_TAGS = new Set(['DIV', 'SECTION', 'ARTICLE', 'TABLE', 'TR', 'BLOCKQUOTE', 'PRE', 'HR']);

/**
 * Keep only simple formatting tags. Unknown wrappers (<div>, <span>…) are
 * unwrapped so their text survives; dangerous ones are dropped with their content.
 * Parses inside a <template>, which is inert: nothing loads or runs.
 */
function sanitizeDescriptionHtml(html) {
    if (!html) return '';
    const tpl = document.createElement('template');
    tpl.innerHTML = String(html);

    function clean(parent) {
        for (const n of Array.from(parent.childNodes)) {
            if (n.nodeType === Node.COMMENT_NODE) { n.remove(); continue; }
            if (n.nodeType !== Node.ELEMENT_NODE) continue;
            const tag = n.tagName.toUpperCase();
            if (JOB_DESC_DROPPED_TAGS.has(tag)) { n.remove(); continue; }
            if (/^H[1-6]$/.test(tag)) {
                // Headings become a bold-only paragraph, which the formatter reads as a heading
                const p = document.createElement('p');
                const b = document.createElement('strong');
                b.textContent = n.textContent.trim();
                p.appendChild(b);
                n.replaceWith(p);
                continue;
            }
            if (!JOB_DESC_ALLOWED_TAGS.has(tag)) {
                clean(n);
                const frag = document.createDocumentFragment();
                const isBlock = JOB_DESC_BLOCK_TAGS.has(tag);
                if (isBlock) frag.appendChild(document.createTextNode('\n'));
                while (n.firstChild) frag.appendChild(n.firstChild);
                if (isBlock) frag.appendChild(document.createTextNode('\n'));
                n.replaceWith(frag);
                continue;
            }
            for (const a of Array.from(n.attributes)) n.removeAttribute(a.name);
            clean(n);
        }
    }

    // Read link targets before clean() strips every attribute, then put back
    // only safe schemes (no javascript: or data: URLs).
    const links = new Map();
    tpl.content.querySelectorAll('a').forEach(a => {
        const href = (a.getAttribute('href') || '').trim();
        if (/^(https?:|mailto:|tel:)/i.test(href)) links.set(a, href);
    });
    clean(tpl.content);
    links.forEach((href, a) => {
        if (!tpl.content.contains(a)) return;
        a.setAttribute('href', href);
        a.setAttribute('target', '_blank');
        a.setAttribute('rel', 'noopener nofollow');
    });

    const div = document.createElement('div');
    div.appendChild(tpl.content);
    return div.innerHTML;
}

// Short lines that name a section even without a trailing colon
const JOB_DESC_HEADING_WORDS = /^(job (summary|description|purpose|overview|requirements?|details)|about (us|the (role|job|position|company))|(key |main |major |general )?(responsibilities|duties)( and responsibilities)?|duties (and|&(amp;)?) responsibilities|(minimum |required |basic )?(qualifications?|requirements?)( (and|&(amp;)?) experience)?|(required |preferred )?(skills|competenc(y|ies))|experience|education(al)? (background|qualifications?)|benefits|what we offer|how to apply|application (process|procedure)|performance target|terms of employment|note|remark)$/i;

// Canonical sections that get a highlighted block (label is only used for matching)
const JOB_DESC_SECTIONS = [
    { key: 'about',    icon: 'fa-circle-info',  test: /^(about|overview|job (summary|purpose|overview)|role overview|ስለ ስራው|ስለ ሥራው|የሥራው አጭር መግለጫ|የስራው አጭር መግለጫ)/i },
    { key: 'resp',     icon: 'fa-list-check',   test: /(responsibilit|duties|what you('ll| will) do|ኃላፊነቶች|ሃላፊነቶች|ሀላፊነቶች|ተግባራት)/i },
    { key: 'req',      icon: 'fa-user-check',   test: /(requirement|qualification|skills|competenc|experience|education|who you are|ብቃቶች|መስፈርቶች|ችሎታዎች)/i },
    { key: 'benefits', icon: 'fa-gift',         test: /(benefit|what we offer|perks|compensation|ጥቅማ ?ጥቅሞች)/i },
    { key: 'apply',    icon: 'fa-paper-plane',  test: /(how to apply|application (process|procedure)|to apply|እንዴት ማመልከት|ለማመልከት|የመጠየቂያ ሂደት)/i },
];

// Leading decoration: emoji, arrows, check marks, flags (with variation selectors)
const JOB_DESC_DECOR = /^(?:[\p{Extended_Pictographic}\p{Emoji_Modifier}‍️⃣←-⇿✀-➿■-◿⬀-⯿•·*#]|\p{Regional_Indicator})+\s*/u;
const JOB_DESC_BULLET = /^(?:[-–—*•·▪▫◦‣►▸▹➤➢➣→⇒✓✔☑✅✳◆◇○●■□♦❖⁃❯»]️?\s*|\d{1,2}[.)]\s+|[a-hA-H][.)]\s+|\(\d{1,2}\)\s*)/u;
const JOB_DESC_KV = /^([^:：፦]{2,40}?)\s*[:：፦]\s*(\S.*)$/u;

function jobDescNormalizeKey(s) {
    return String(s || '').replace(/<[^>]+>/g, '').replace(/[^\p{L}\p{N}]+/gu, '').toLowerCase();
}

function jobDescStripDecor(line) {
    return line.replace(JOB_DESC_DECOR, '').trim();
}

function jobDescIsHeading(line) {
    const bare = jobDescStripDecor(line).replace(/<[^>]+>/g, '').trim();
    if (!bare || bare.length > 70) return null;
    // "Requirements:" / "Educational Qualification:" / "ዋና ዋና ሀላፊነቶች፦"
    if (/[:：፦]$/.test(bare) && !/[:：፦]./.test(bare.slice(0, -1).replace(/https?:/g, ''))) {
        return bare.replace(/\s*[:：፦]$/, '');
    }
    if (/^position\s*\d+\s*[:：\-–]/i.test(bare)) return bare;
    if (JOB_DESC_HEADING_WORDS.test(bare)) return bare;
    // ALL-CAPS line such as "MINIMUM QUALIFICATION & EXPERIENCE"
    const letters = bare.replace(/&amp;/g, '').replace(/[^A-Za-z]/g, '');
    if (letters.length >= 4 && letters === letters.toUpperCase() && bare.split(/\s+/).length <= 9 && !/[.!?]$/.test(bare)) {
        return bare;
    }
    return null;
}

/** Break run-on text so each "Label: value" and "Position N:" starts its own line. */
function jobDescSplitRunOns(text) {
    return text
        // "Education:Bachelor's" → "Education: Bachelor's" (not URLs: those have "//" after the colon)
        .replace(/([a-z)])[:：](?=[A-Z])/g, '$1: ')
        // "…related field. Work Experience: 2 years" → new line before the label
        .replace(/([.;!?)])[ \t]+(?=[A-Z][\w’'()\/-]*(?:[ \t](?:&amp;|[\w’'()\/-]+)){0,4}[ \t]*[:：][ \t])/g, '$1\n')
        .replace(/[ \t]+(?=Position[ \t]*\d+[ \t]*[:：])/g, '\n')
        // Amharic fields run together: "የሥራ ቦታ፦ አዲስ አበባ የቅጥር ሁኔታ፦ ሙሉ ጊዜ ደመወዝ፦ …".
        // Word boundaries can't tell label from value here, so split before known labels.
        .replace(new RegExp(`([^\\n])[ \\t]+(?=(?:${JOB_DESC_AMHARIC_LABELS})[ \\t]*[፦:])`, 'gu'), '$1\n');
}

// Common Amharic field labels (see jobDescSplitRunOns)
const JOB_DESC_AMHARIC_LABELS = [
    'የሥራ ቦታ', 'የስራ ቦታ', 'የቅጥር ሁኔታ', 'የቅጥር ዓይነት', 'ደመወዝ', 'ደሞዝ', 'የአፈጻጸም ቦነስ',
    'የትምህርት ደረጃ', 'የትምህርት ዝግጅት', 'የሥራ ልምድ', 'የስራ ልምድ', 'ብዛት', 'የሚፈለገው ብዛት',
    'የመመዝገቢያ ጊዜ', 'የማመልከቻ ጊዜ', 'የመጨረሻ ቀን', 'ስልክ', 'ቴሌግራም', 'ኢሜይል', 'ፆታ', 'ጾታ',
].join('|');

/** Plain text (already HTML-escaped by the sanitizer, may contain <a>) → structured HTML. */
function jobDescTextToHtml(safeHtml, title) {
    // Shield links so no rule splits or re-labels inside their markup
    const links = [];
    let text = safeHtml.replace(/<a\s[^>]*>[\s\S]*?<\/a>/gi, m => `\u0001${links.push(m) - 1}\u0002`);
    text = text.replace(/<br\s*\/?>/gi, '\n').replace(/\r\n?/g, '\n');
    text = jobDescSplitRunOns(text);

    const titleKey = jobDescNormalizeKey(title);
    const rows = [];
    for (const raw of text.split('\n')) {
        const line = raw.replace(/[ \t ]+/g, ' ').trim();
        if (!line) { rows.push({ kind: 'blank' }); continue; }
        // Separators, empty "Job Type: :" fields, and scraper junk
        if (/^[=\-_*~.•·]{4,}$/.test(line)) { rows.push({ kind: 'blank' }); continue; }
        if (/^[^:]{1,40}:\s*:\s*$/.test(line)) continue;
        if (/want to apply easily from your phone/i.test(line)) continue;
        // A line that's just the title again (often first, sometimes after a details block)
        if (titleKey && jobDescNormalizeKey(jobDescStripDecor(line)) === titleKey) continue;

        const bullet = line.match(JOB_DESC_BULLET);
        if (bullet && line.length > bullet[0].length) {
            const rest = line.slice(bullet[0].length).trim();
            const heading = jobDescIsHeading(rest);
            // "✅ POSITION: OFFICE ENGINEER" and "▪️Requirements:" are headings, not list items
            if (heading && /^[✓✔☑✅✳◆◇►▸➤➢▪]/u.test(line)) { rows.push({ kind: 'heading', text: heading }); continue; }
            rows.push({ kind: 'li', text: rest });
            continue;
        }
        const heading = jobDescIsHeading(line);
        if (heading) { rows.push({ kind: 'heading', text: heading }); continue; }

        const kv = jobDescStripDecor(line).match(JOB_DESC_KV);
        if (kv && !/https?$|\u0001/.test(kv[1]) && kv[1].split(/\s+/).length <= 5 && !/[.!?,]/.test(kv[1])) {
            rows.push({ kind: 'kv', label: kv[1].trim(), value: kv[2].trim() });
            continue;
        }
        rows.push({ kind: 'text', text: line });
    }

    // Headings the text only implies by position:
    //  - a short line directly followed by list items ("Key Responsibilities" + bullets)
    //  - a short line standing alone as its own paragraph, followed by more content
    //    ("Job Summary", "የሥራው አጭር መግለጫ"), which is how rich-text sources write headings
    const isShort = t => t.length <= 45 && t.split(/\s+/).length <= 6 && !/[.!,;።፣]$/.test(t);
    for (let i = 0; i + 1 < rows.length; i++) {
        const r = rows[i], next = rows[i + 1];
        if (r.kind !== 'text' || !isShort(r.text)) continue;
        const text = jobDescStripDecor(r.text);
        const standalone = (i === 0 || rows[i - 1].kind === 'blank') && next.kind === 'blank'
            && rows.slice(i + 2).some(x => x.kind === 'text' || x.kind === 'li');
        const questionHeading = /\?$/.test(text) && JOB_DESC_SECTIONS.some(s => s.test.test(text));
        if (next.kind === 'li' || (standalone && (!/\?$/.test(text) || questionHeading))) {
            rows[i] = { kind: 'heading', text };
        }
    }

    const out = [];
    let i = 0;
    while (i < rows.length) {
        const r = rows[i];
        if (r.kind === 'blank') { i++; continue; }
        if (r.kind === 'heading') { out.push(`<h5 class="desc-heading">${r.text}</h5>`); i++; continue; }
        if (r.kind === 'li') {
            const items = [];
            while (i < rows.length && (rows[i].kind === 'li' || (rows[i].kind === 'blank' && rows[i + 1]?.kind === 'li'))) {
                if (rows[i].kind === 'li') items.push(`<li>${rows[i].text}</li>`);
                i++;
            }
            out.push(`<ul>${items.join('')}</ul>`);
            continue;
        }
        if (r.kind === 'kv') {
            const facts = [];
            while (i < rows.length && rows[i].kind === 'kv') {
                facts.push(`<li><span class="desc-fact-label">${rows[i].label}</span><span class="desc-fact-value">${rows[i].value}</span></li>`);
                i++;
            }
            out.push(`<ul class="desc-facts">${facts.join('')}</ul>`);
            continue;
        }
        const para = [];
        while (i < rows.length && rows[i].kind === 'text') { para.push(rows[i].text); i++; }
        out.push(`<p>${para.join('<br>')}</p>`);
    }
    return out.join('').replace(/\u0001(\d+)\u0002/g, (_, n) => links[+n]);
}

/** Group content under recognised section headings into highlighted blocks. */
function decorateSections(html) {
    const container = document.createElement('div');
    container.innerHTML = html;

    const groups = [];
    let current = { section: null, heading: null, nodes: [] };
    for (const node of Array.from(container.childNodes)) {
        let headingText = null;
        if (node.nodeType === 1 && node.tagName === 'H5') headingText = node.textContent.trim();
        // Bold-only paragraph from HTML sources, e.g. <p><strong>Requirements</strong></p>
        else if (node.nodeType === 1 && node.tagName === 'P' && node.children.length === 1
                 && /^(STRONG|B)$/.test(node.firstElementChild.tagName)
                 && node.textContent.trim() === node.firstElementChild.textContent.trim()
                 && node.textContent.trim().length <= 70) headingText = node.textContent.trim().replace(/[:：፦]$/, '');
        const def = headingText ? JOB_DESC_SECTIONS.find(s => s.test.test(headingText)) : null;
        if (def) {
            if (current.nodes.length || current.section) groups.push(current);
            current = { section: def, heading: headingText, nodes: [] };
            continue;
        }
        // "Position 2: …" starts a new job in a multi-position post, so it closes the open section
        if (headingText && current.section && /^position\s*\d+/i.test(headingText)) {
            groups.push(current);
            current = { section: null, heading: null, nodes: [] };
        }
        if (headingText && node.tagName === 'P') {
            const h = document.createElement('h5');
            h.className = 'desc-heading';
            h.textContent = headingText;
            current.nodes.push(h);
            continue;
        }
        current.nodes.push(node);
    }
    if (current.nodes.length || current.section) groups.push(current);
    if (!groups.some(g => g.section)) return container.innerHTML;

    const out = document.createElement('div');
    for (const g of groups) {
        if (!g.section) { g.nodes.forEach(n => out.appendChild(n)); continue; }
        const block = document.createElement('div');
        block.className = `description-block description-block--${g.section.key}`;
        const h = document.createElement('h5');
        h.className = 'description-block-title';
        h.innerHTML = `<i class="fas ${g.section.icon}" aria-hidden="true"></i><span></span>`;
        h.querySelector('span').textContent = g.heading;
        block.appendChild(h);
        const body = document.createElement('div');
        body.className = 'description-block-body';
        g.nodes.forEach(n => body.appendChild(n));
        block.appendChild(body);
        out.appendChild(block);
    }
    return out.innerHTML;
}

/**
 * Description text/HTML → safe, structured HTML.
 * @param {string} description raw description
 * @param {{title?: string}} [opts] title, so a first line repeating it can be dropped
 */
function formatJobDescription(description, opts) {
    const title = (opts && opts.title) || '';
    if (!description || !String(description).trim()) {
        return '<p class="desc-empty">No description available. Use the source link for full details.</p>';
    }
    const safe = sanitizeDescriptionHtml(description);
    const hasBlocks = /<(p|ul|ol|li)[\s>]/i.test(safe);
    const structured = hasBlocks ? safe : jobDescTextToHtml(safe, title);
    return decorateSections(structured);
}

/**
 * A few posts get parsed with a field row as the title ("Employment Type: Full-Time").
 * Recover the real position from the description when that happens.
 */
function displayJobTitle(job) {
    const title = (job && job.title) || '';
    if (!/^\W*(employment type|job type|location|salary|deadline|company|category|experience|education|place of work|work place)\s*[:：]/i.test(title)) {
        return title;
    }
    const m = String(job.description || '').match(/(?:position|vacancy|job title)\s*[:：\-–]\s*([^\n<]{3,80})/i);
    if (!m) return title;
    const found = m[1].replace(/[\p{Extended_Pictographic}️]/gu, '').trim();
    return found === found.toUpperCase()
        ? found.toLowerCase().replace(/\b\p{L}/gu, c => c.toUpperCase())
        : found;
}
