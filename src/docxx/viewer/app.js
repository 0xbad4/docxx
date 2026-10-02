const $ = s => document.querySelector(s);

// ====================== DOM helpers ======================
// Tiny wrapper around createElement so the rest of the file reads as
// "build an <tag class=cls>text</tag>" instead of 4 lines each time.
function celement(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
}

// Same as celement, but sets innerHTML instead of textContent - used only
// for output that already went through Documentation.highlight_cpp(),
// which HTML-escapes everything itself. Never pass raw user text here.
function celement_html(tag, cls, html) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
}

// FontAwesome icon factory. "fa-fw" fixes the width so labels line up
// regardless of which glyph is used.
function icon(name, extra) {
    return celement("i", "fa-solid fa-fw fa-" + name + (extra ? " " + extra : ""));
}

class Documentation {
    // Types allowed to appear in the LEFT tree (namespaces/classes only).
    static NAV_TYPES = ["namespace", "class"];
    static ICONS = { namespace: "cubes", class: "cube" };
    static SUB_ICONS = {
        enum: "list-ol", struct: "cubes", alias: "link", macro: "hashtag",
        function: "code", method: "code", constructor: "wand-magic-sparkles",
        destructor: "trash", field: "grip-lines", variable: "grip-lines",
    };
    // Title-case section label per type. No folding: constructor and
    // destructor are separate groups, function and method are separate,
    // field and variable are separate - this drives BOTH the sub nav and
    // the body groups, so the two always agree on what a "section" is.
    static SUB_GROUPS = {
        enum: "Enums", struct: "Structs", alias: "Aliases", macro: "Macros",
        function: "Functions", method: "Methods", constructor: "Constructors",
        destructor: "Destructors", field: "Fields", variable: "Variables",
    };
    static NOTE_ICONS = { warn: "triangle-exclamation", info: "circle-info", danger: "skull" };

    // Minimal C++ token set - keyword / string / number / preprocessor,
    // matching the .kw/.st/.nm/.pp classes in main.css. Identifiers and
    // type names are intentionally left uncolored so the highlight stays
    // readable instead of turning into noise.
    static CPP_KEYWORDS = new Set([
        "const", "static", "virtual", "override", "final", "constexpr", "explicit", "noexcept",
        "class", "struct", "enum", "using", "typename", "template", "public", "private", "protected",
        "return", "void", "bool", "true", "false", "nullptr", "auto", "namespace", "inline", "mutable",
        "volatile", "operator", "sizeof", "decltype", "default", "delete", "friend", "extern",
        "unsigned", "signed", "long", "short", "int", "char", "float", "double",
    ]);

    #current_item = undefined;
    #current_sub_item = undefined;

    constructor(url) {
        this.url = url;
        this.data = null;
        this.path = "/";
    }

    // ---------- safe string coercion ----------
    // JSON fields the schema treats as optional (a struct field with no
    // field_type, an enum value with no value, an alias with no target...)
    // come through as `undefined`. Template literals and string
    // concatenation stringify `undefined` into the literal text
    // "undefined" - this is the one place that's allowed to touch such a
    // field before it goes into a string, so every call site stays safe.
    static s(v) {
        return v == null ? "" : String(v);
    }

    // HTML escaping for safe text rendering
    static escape_html(text) {
        const t = Documentation.s(text);
        const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;" };
        return t.replace(/[&<>]/g, c => map[c]);
    }

    // Plain text with newlines converted to <br>
    static text_html(text) {
        return Documentation.escape_html(Documentation.s(text)).replace(/\n/g, "<br>");
    }

    // Markdown rendering — delegates to marked.js when available and falls
    // back to plain escaped text so the viewer degrades gracefully without CDN.
    static render_markdown(content) {
        if (typeof window !== "undefined" && window.marked) {
            let html = window.marked.parse(Documentation.s(content));
            if (window.hljs) {
                const temp = document.createElement("div");
                temp.innerHTML = html;
                temp.querySelectorAll("pre code").forEach(block =>
                    window.hljs.highlightElement(block)
                );
                html = temp.innerHTML;
            }
            return html;
        }
        return Documentation.text_html(content);
    }

    // ---------- metadata ----------
    render_metadata() {
        const meta = this.data.metadata || {};
        $("#project-name").textContent = meta.name || "";
        $("#project-version").textContent = meta.version || "";
        $("#project-desc").textContent = meta.brief || meta.description || "";
        $("#author").textContent = meta.author || "";
        $("#repo").href = meta.repo || "#";

        // Browser tab title: prefer metadata.title, fall back to metadata.name.
        if (meta.title || meta.name) {
            document.title = meta.title || meta.name;
        }

        // Favicon: inject or replace a <link rel="icon"> from metadata.favicon.
        if (meta.favicon) {
            let link = document.querySelector("link[rel~='icon']");
            if (!link) {
                link = document.createElement("link");
                link.rel = "icon";
                document.head.appendChild(link);
            }
            link.href = meta.favicon;
        }

        // Project icon: render an image above the title if provided.
        const header = document.querySelector(".sb-head");
        if (header) {
            let existing = header.querySelector('.sb-icon');
            if (meta.icon) {
                if (!existing) {
                    existing = document.createElement('div');
                    existing.className = 'sb-icon';
                    header.insertBefore(existing, header.firstChild);
                }
                existing.innerHTML = '';
                const img = document.createElement('img');
                img.src = meta.icon;
                img.alt = meta.name || 'icon';
                existing.appendChild(img);
            } else if (existing) {
                existing.remove();
            }
        }

        // Highlight.js theme: inject a stylesheet link based on metadata.hjs_code_theme.
        const theme = (meta.hjs_code_theme || 'atom-one-dark').replace(/[^A-Za-z0-9\-_.]/g, '');
        const existingTheme = document.getElementById('hjs-theme');
        const href = `https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/${theme}.min.css`;
        if (existingTheme) {
            existingTheme.href = href;
        } else {
            const l = document.createElement('link');
            l.rel = 'stylesheet';
            l.id = 'hjs-theme';
            l.href = href;
            document.head.appendChild(l);
        }

        // std/license aren't in index.html yet - wired defensively so
        // adding <span id="project-std">/<span id="project-license">
        // later "just works" without touching this file again.
        const stdEl = $("#project-std");
        if (stdEl) stdEl.textContent = meta.std || "";
        const licEl = $("#project-license");
        if (licEl) licEl.textContent = meta.license || "";
    }

    // ---------- sorting / grouping ----------
    static nav_sort(a, b) {
        const rank = n => Documentation.NAV_TYPES.indexOf(n.type);
        return rank(a) - rank(b) || a.name.localeCompare(b.name);
    }

    static by_name(a, b) {
        return a.name.localeCompare(b.name);
    }

    // Everything in a node that is NOT a namespace/class, grouped by type
    // (no folding), label-sorted. Used by BOTH the sub nav and the body,
    // so a click on either always finds a matching #id in the other.
    static group_members(node) {
        const members = (node.content || []).filter(m => !Documentation.NAV_TYPES.includes(m.type));
        const groups = new Map();
        members.forEach(m => {
            const label = Documentation.SUB_GROUPS[m.type] || m.type;
            if (!groups.has(label)) groups.set(label, []);
            groups.get(label).push(m);
        });
        return new Map(
            [...groups.entries()]
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([label, items]) => [label, items.sort(Documentation.by_name)])
        );
    }

    // ---------- left tree ----------
    nav_item(label, icon_name, path, kids, type, description) {
        const has_kids = kids && kids.length;
        const li = celement("li", "nav-item");
        const row = celement(path ? "a" : "div", "nav-row");
        if (path) li.dataset.path = path;

        const chevron = icon("chevron-right", "nav-chevron" + (has_kids ? "" : " spacer"));
        chevron.addEventListener("click", (e) => {
            e.preventDefault();
            e.stopPropagation();
            if (!has_kids) return;
            li.classList.toggle("open");
        });

        const labelWrap = celement("span", "nav-label-group");
        labelWrap.append(celement("span", "nav-label", label));
        if (description) labelWrap.append(celement("span", "nav-brief", description));

        row.append(
            chevron,
            icon(icon_name, "nav-icon" + (type ? " icon-" + type : "")),
            labelWrap
        );
        li.append(row);

        if (has_kids) {
            const ul = celement("ul", "nav-children");
            kids.forEach(k => ul.append(k));
            li.append(ul);
        }

        row.addEventListener("click", (e) => {
            if (e.target === chevron || chevron.contains(e.target)) return;
            this.nav_item_clicked(li);
        });
        return li;
    }

    render_markdown_nav(entry) {
        const body = $("#content");
        body.replaceChildren();
        $("#sub-list").replaceChildren();

        const head = celement("div", "page-head");
        const iconName = entry.icon || "file-lines";
        head.append(icon(iconName, "page-icon icon-root"));
        head.append(celement("h1", "page-title", entry.label || "Documentation"));
        body.append(head);

        const text = entry.content || entry.url || "";
        const wrap = celement("div", "markdown-block");
        const mdBody = celement("div", "markdown-body");
        mdBody.innerHTML = Documentation.render_markdown(text);
        wrap.append(mdBody);
        body.append(wrap);
    }

    tree_item(ns, parent_path) {
        const path = parent_path + "/" + ns.name;
        const kids = (ns.content || [])
            .filter(n => Documentation.NAV_TYPES.includes(n.type))
            .sort(Documentation.nav_sort)
            .map(n => this.tree_item(n, path));
        return this.nav_item(
            ns.name,
            ns.icon || Documentation.ICONS[ns.type] || "circle",
            path,
            kids,
            ns.type,
            ""
        );
    }

    render_nav() {
        const list = $("#nav-list");
        list.replaceChildren();
        list.append(this.nav_item("Overview", "house", "/", null, "root"));

        const mods = (this.data.modules || [])
            .filter(n => Documentation.NAV_TYPES.includes(n.type))
            .sort(Documentation.nav_sort);
        if (mods.length) {
            const item = this.nav_item("Modules", "diagram-project", null, mods.map(n => this.tree_item(n, "")), "root");
            item.classList.add("open");
            list.append(item);
        }

        const navExtra = (this.data.metadata && this.data.metadata.nav) || [];
        navExtra.forEach(entry => {
            if (!entry.label || !entry.url) return;
            const li = celement("li", "nav-item nav-item-external");
            const kind = (entry.type || "external").toLowerCase();

            if (kind === "markdown") {
                const row = celement("button", "nav-row");
                row.type = "button";
                row.dataset.navType = "markdown";
                row.addEventListener("click", (e) => {
                    e.preventDefault();
                    this.render_markdown_nav(entry);
                });
                row.append(
                    icon("chevron-right", "nav-chevron spacer"),
                    icon(entry.icon || "file-lines", "nav-icon"),
                    celement("span", "nav-label", entry.label)
                );
                li.append(row);
            } else {
                const a = celement("a", "nav-row");
                a.href = entry.url;
                a.target = "_blank";
                a.rel = "noopener";
                const iconName = entry.icon || "arrow-up-right-from-square";
                a.append(
                    icon("chevron-right", "nav-chevron spacer"),
                    icon(iconName, "nav-icon"),
                    celement("span", "nav-label", entry.label)
                );
                li.append(a);
            }
            list.append(li);
        });
    }

    // ---------- right sub nav ----------
    sub_nav_item(member) {
        const li = celement("li", "sub-item");
        const row = celement("div", "sub-row");
        row.dataset.target = member.name;
        row.append(
            icon(Documentation.SUB_ICONS[member.type] || "circle", "sub-icon icon-" + member.type),
            celement("span", "sub-label", member.name)
        );
        li.append(row);
        row.addEventListener("click", () => this.sub_nav_item_clicked(li));
        return li;
    }

    render_sub_nav(node) {
        const list = $("#sub-list");
        list.replaceChildren();
        const groups = Documentation.group_members(node);
        for (const [label, items] of groups) {
            list.append(celement("li", "sub-group-label", label));
            items.forEach(m => list.append(this.sub_nav_item(m)));
        }
    }

    // ====================== BODY ======================

    // note.type is one of warn | info | danger.
    static notes_block(notes) {
        if (!notes || !notes.length) return null;
        const wrap = celement("div", "body-notes");
        notes.forEach(n => {
            const box = celement("div", "callout callout-" + n.type);
            box.append(icon(Documentation.NOTE_ICONS[n.type] || "circle-info", "callout-icon"));
            box.append(celement("p", "callout-text", n.content));
            wrap.append(box);
        });
        return wrap;
    }

    // file:line -> a link.
    // Priority: 1) per-item source.url (computed by the generator from source_url template),
    //           2) source_base prefix + file + line anchor (from metadata.source_base),
    //           3) plain <span> when no URL is available.
    static source_link(source, source_base) {
        if (!source || !source.file) return null;
        const label = source.file + (source.line ? ":" + source.line : "");
        const href = source.url
            || (source_base ? source_base + source.file + (source.line ? "#L" + source.line : "") : null);
        if (href) {
            const a = celement("a", "body-source", label);
            a.href = href;
            a.target = "_blank";
            a.rel = "noopener";
            return a;
        }
        return celement("span", "body-source", label);
    }

    // "type text" signature for anything callable (function/method/
    // constructor/destructor). Not a real parser - just enough to read
    // like a declaration. The return type lives HERE, in the signature
    // itself - there's no separate "returns" column anymore, since
    // showing it twice in the same row was redundant.
    static build_signature(m) {
        const flags = m.flags || [];
        const is_ctor_dtor = m.type === "constructor" || m.type === "destructor";

        const prefix = ["static", "virtual", "constexpr"].filter(f => flags.includes(f));
        const ret = !is_ctor_dtor && m.return && m.return.type ? m.return.type + " " : "";
        const params = (m.params || []).map(p => Documentation.s(p.type) + (p.name ? " " + p.name : "")).join(", ");

        const suffix = ["const", "override"].filter(f => flags.includes(f));
        let tail = "";
        if (flags.includes("pure")) tail = " = 0";
        else if (flags.includes("default")) tail = " = default";
        else if (flags.includes("delete")) tail = " = delete";

        return `${prefix.length ? prefix.join(" ") + " " : ""}${ret}${m.name}(${params})${suffix.length ? " " + suffix.join(" ") : ""}${tail};`;
    }

    // "signature" column text, per type.
    static signature_text(m) {
        switch (m.type) {
            case "function": case "method": case "constructor": case "destructor":
                return Documentation.build_signature(m).replace(/;$/, "");
            case "field": case "variable":
                return `${Documentation.s(m.field_type)} ${Documentation.s(m.name)}`.trim();
            default:
                return m.name;
        }
    }

    // Plain "name / type / description" table with a header row. Used for
    // enum values and struct fields (same shape, different source data).
    static rows_table(rows, head) {
        const table = celement("table", "body-table");
        const theadRow = celement("tr");
        head.forEach(h => theadRow.append(celement("th", null, h)));
        const theadWrap = celement("thead");
        theadWrap.append(theadRow);
        table.append(theadWrap);

        const tbody = celement("tbody");
        rows.forEach(r => {
            const tr = celement("tr");
            tr.append(celement("td", "body-table-name", r.name));
            tr.append(celement_html("td", "body-table-type", Documentation.highlight_cpp(Documentation.s(r.type))));
            tr.append(celement("td", "body-table-desc", r.desc || ""));
            tbody.append(tr);
        });
        table.append(tbody);
        return table;
    }

    // Plain "name / type / description" table with NO header row, used
    // inside an expanded row for a function/method's parameters.
    static param_table(params) {
        const table = celement("table", "param-table");
        params.forEach(p => {
            const tr = celement("tr");
            tr.append(celement("td", "param-name", p.name));
            tr.append(celement_html("td", "param-type", Documentation.highlight_cpp(Documentation.s(p.type))));
            tr.append(celement("td", "param-desc", p.description || ""));
            table.append(tr);
        });
        return table;
    }

    // Tokenizes a snippet of C++-ish text and returns an HTML string with
    // <span class="kw|st|nm|pp"> around keywords, string literals, numeric
    // literals and preprocessor directives. Escapes everything itself -
    // the result is safe to assign to innerHTML.
    static highlight_cpp(text) {
        if (!text) return "";
        const re = /(#\w+)|("(?:[^"\\]|\\.)*")|(\b0[xX][0-9a-fA-F]+\b|\b\d+\.?\d*\b)|(\b[A-Za-z_]\w*\b)/g;
        const esc = s => s.replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

        let out = "", last = 0, m;
        while ((m = re.exec(text))) {
            if (m.index > last) out += esc(text.slice(last, m.index));
            if (m[1]) out += `<span class="pp">${esc(m[1])}</span>`;
            else if (m[2]) out += `<span class="st">${esc(m[2])}</span>`;
            else if (m[3]) out += `<span class="nm">${esc(m[3])}</span>`;
            else if (m[4]) out += Documentation.CPP_KEYWORDS.has(m[4]) ? `<span class="kw">${esc(m[4])}</span>` : esc(m[4]);
            last = re.lastIndex;
        }
        out += esc(text.slice(last));
        return out;
    }

    // Signature / description table, one row per member, with an
    // expandable detail row underneath for the return type, parameters,
    // full description, notes and source location - only when there IS
    // something to show there.
    signature_table(items) {
        const table = celement("table", "sig-table");
        const theadRow = celement("tr");
        ["signature", "description"].forEach(h => theadRow.append(celement("th", null, h)));
        const theadWrap = celement("thead");
        theadWrap.append(theadRow);
        table.append(theadWrap);

        const source_base = this.data.metadata && this.data.metadata.source_base;
        const tbody = celement("tbody");

        items.forEach(m => {
            const is_callable = ["function", "method", "constructor", "destructor"].includes(m.type);
            const has_return = is_callable && m.return && m.return.type;
            const has_detail = !!((m.params && m.params.length) || m.description
                || (m.notes && m.notes.length) || m.source || has_return);

            const tr = celement("tr", "sig-row icon-" + m.type + (has_detail ? "" : " no-detail"));
            tr.id = m.name; // scroll target for the sub nav - must match sub_nav_item's data-target
            tr.append(celement_html("td", "sig-cell", Documentation.highlight_cpp(Documentation.signature_text(m))));
            const desc = celement("td", "desc-cell", m.brief || m.description || "");
            desc.append(icon("chevron-right", "row-chevron" + (has_detail ? "" : " spacer")));
            tr.append(desc);
            tbody.append(tr);

            if (has_detail) {
                const detailTr = celement("tr", "sig-detail");
                const detailTd = celement("td");
                detailTd.colSpan = 2;

                if (m.params && m.params.length) {
                    detailTd.append(celement("h4", "detail-heading", "parameters"));
                    detailTd.append(Documentation.param_table(m.params));
                }
                if (has_return) {
                    detailTd.append(celement("h4", "detail-heading", "returns"));
                    const retBlock = celement("div", "detail-return");
                    retBlock.append(celement_html("code", "detail-return-type", Documentation.highlight_cpp(Documentation.s(m.return.type))));
                    if (m.return.description) retBlock.append(celement("span", "detail-return-desc", m.return.description));
                    detailTd.append(retBlock);
                }
                // Render description through Markdown so @code fences and
                // inline markup authored in doc-comments display correctly.
                if (m.description) {
                    const descEl = celement("div", "detail-desc");
                    descEl.innerHTML = Documentation.render_markdown(m.description);
                    detailTd.append(descEl);
                }
                // @markdown blocks embedded in the item's doc-comment.
                if (m.markdown && Array.isArray(m.markdown)) {
                    m.markdown.forEach(md => {
                        const wrap = celement("div", "markdown-block");
                        if (md.description) wrap.append(celement("div", "markdown-title", md.description));
                        const body = celement("div", "markdown-body");
                        body.innerHTML = Documentation.render_markdown(md.content);
                        wrap.append(body);
                        detailTd.append(wrap);
                    });
                }
                const notes = Documentation.notes_block(m.notes);
                if (notes) detailTd.append(notes);
                const src = Documentation.source_link(m.source, source_base);
                if (src) detailTd.append(src);

                detailTr.append(detailTd);
                tbody.append(detailTr);

                tr.addEventListener("click", () => tr.classList.toggle("open"));
            }
        });
        table.append(tbody);
        return table;
    }

    // ---- enum / struct / alias / macro: not table rows, standalone
    // blocks with a small heading (name + kind badge) followed by the
    // plain C++ declaration, then whatever else that type shows. ----
    member_block_head(name, kind) {
        const head = celement("div", "member-head");
        head.append(celement("span", "member-name", name));
        head.append(celement("span", "kind-badge icon-" + kind, kind));
        return head;
    }

    render_enum_block(e) {
        const wrap = celement("div", "member-block icon-enum");
        wrap.id = e.name;
        wrap.append(this.member_block_head(e.name, "enum"));
        wrap.append(celement_html("code", "member-block-sig",
            Documentation.highlight_cpp((e.scoped ? "enum class " : "enum ") + Documentation.s(e.name) + (e.underlying ? " : " + e.underlying : ""))));
        if (e.brief) wrap.append(celement("p", "body-item-brief", e.brief));
        if (e.description) {
            const descEl = celement("div", "body-item-desc");
            descEl.innerHTML = Documentation.render_markdown(e.description);
            wrap.append(descEl);
        }
        if (e.values && e.values.length) {
            wrap.append(Documentation.rows_table(
                e.values.map(v => ({ name: v.name, type: v.value, desc: v.description })),
                ["name", "value", "description"]
            ));
        }
        if (e.markdown && Array.isArray(e.markdown)) {
            e.markdown.forEach(md => {
                const mdWrap = celement("div", "markdown-block");
                if (md.description) mdWrap.append(celement("div", "markdown-title", md.description));
                const body = celement("div", "markdown-body");
                body.innerHTML = Documentation.render_markdown(md.content);
                mdWrap.append(body);
                wrap.append(mdWrap);
            });
        }
        const notes = Documentation.notes_block(e.notes);
        if (notes) wrap.append(notes);
        const src = Documentation.source_link(e.source, this.data.metadata && this.data.metadata.source_base);
        if (src) wrap.append(src);
        return wrap;
    }

    render_struct_block(s) {
        const wrap = celement("div", "member-block icon-struct");
        wrap.id = s.name;
        wrap.append(this.member_block_head(s.name, "struct"));
        wrap.append(celement_html("code", "member-block-sig", Documentation.highlight_cpp("struct " + Documentation.s(s.name))));
        if (s.brief) wrap.append(celement("p", "body-item-brief", s.brief));
        if (s.description) {
            const descEl = celement("div", "body-item-desc");
            descEl.innerHTML = Documentation.render_markdown(s.description);
            wrap.append(descEl);
        }
        const fields = (s.content || []).filter(f => f.type === "field");
        if (fields.length) {
            wrap.append(Documentation.rows_table(
                fields.map(f => ({ name: f.name, type: f.field_type, desc: f.description })),
                ["field", "type", "description"]
            ));
        }
        if (s.markdown && Array.isArray(s.markdown)) {
            s.markdown.forEach(md => {
                const mdWrap = celement("div", "markdown-block");
                if (md.description) mdWrap.append(celement("div", "markdown-title", md.description));
                const body = celement("div", "markdown-body");
                body.innerHTML = Documentation.render_markdown(md.content);
                mdWrap.append(body);
                wrap.append(mdWrap);
            });
        }
        const notes = Documentation.notes_block(s.notes);
        if (notes) wrap.append(notes);
        const src = Documentation.source_link(s.source, this.data.metadata && this.data.metadata.source_base);
        if (src) wrap.append(src);
        return wrap;
    }

    render_alias_block(a) {
        const wrap = celement("div", "member-block icon-alias");
        wrap.id = a.name;
        wrap.append(this.member_block_head(a.name, "alias"));
        // Use underlying (output field name) with fallback to target for older JSON.
        const target = Documentation.s(a.underlying || a.target);
        wrap.append(celement_html("code", "member-block-sig",
            Documentation.highlight_cpp(`using ${Documentation.s(a.name)} = ${target};`)));
        if (a.brief) wrap.append(celement("p", "body-item-brief", a.brief));
        if (a.description) {
            const descEl = celement("div", "body-item-desc");
            descEl.innerHTML = Documentation.render_markdown(a.description);
            wrap.append(descEl);
        }
        if (a.markdown && Array.isArray(a.markdown)) {
            a.markdown.forEach(md => {
                const mdWrap = celement("div", "markdown-block");
                if (md.description) mdWrap.append(celement("div", "markdown-title", md.description));
                const body = celement("div", "markdown-body");
                body.innerHTML = Documentation.render_markdown(md.content);
                mdWrap.append(body);
                wrap.append(mdWrap);
            });
        }
        return wrap;
    }

    render_macro_block(mc) {
        const wrap = celement("div", "member-block icon-macro");
        wrap.id = mc.name;
        wrap.append(this.member_block_head(mc.name, "macro"));
        wrap.append(celement_html("code", "member-block-sig", Documentation.highlight_cpp("#define " + Documentation.s(mc.name))));
        if (mc.brief) wrap.append(celement("p", "body-item-brief", mc.brief));
        if (mc.description) {
            const descEl = celement("div", "body-item-desc");
            descEl.innerHTML = Documentation.render_markdown(mc.description);
            wrap.append(descEl);
        }
        if (mc.markdown && Array.isArray(mc.markdown)) {
            mc.markdown.forEach(md => {
                const mdWrap = celement("div", "markdown-block");
                if (md.description) mdWrap.append(celement("div", "markdown-title", md.description));
                const body = celement("div", "markdown-body");
                body.innerHTML = Documentation.render_markdown(md.content);
                mdWrap.append(body);
                wrap.append(mdWrap);
            });
        }
        return wrap;
    }

    // One group (e.g. "Methods", "Enums") -> [heading, ...content].
    // Dispatches by the group's member type. Shared by the class page and
    // the namespace page, so both render every type the same way.
    render_group(label, items) {
        const type = items[0].type;
        const out = [celement("h3", "body-group-heading", label.toLowerCase())];

        if (["constructor", "destructor", "method", "function", "field", "variable"].includes(type)) {
            out.push(this.signature_table(items));
        } else if (type === "enum") {
            items.forEach(e => out.push(this.render_enum_block(e)));
        } else if (type === "struct") {
            items.forEach(s => out.push(this.render_struct_block(s)));
        } else if (type === "alias") {
            items.forEach(a => out.push(this.render_alias_block(a)));
        } else if (type === "macro") {
            items.forEach(mc => out.push(this.render_macro_block(mc)));
        }
        return out;
    }

    // ---------- class page ----------
    get_render_class(node) {
        const section = celement("section", "class-page");

        const head = celement("div", "page-head");
        head.append(icon(Documentation.ICONS.class, "page-icon icon-class"));
        head.append(celement("h1", "page-title icon-class", node.name));
        head.append(celement("span", "kind-badge icon-class", "class"));
        const src = Documentation.source_link(node.source, this.data.metadata && this.data.metadata.source_base);
        if (src) head.append(src);
        section.append(head);

        const parents = node.parent || [];
        const decl = "class " + Documentation.s(node.name) + (
            parents.length ? " : " + parents.map(p => `${p.access || "public"} ${Documentation.s(p.name)}`).join(", ") : ""
        );
        const sigBox = celement("div", "page-sig");
        sigBox.append(celement_html("code", null, Documentation.highlight_cpp(decl)));
        section.append(sigBox);

        if (parents.length) {
            const row = celement("div", "inherits-row");
            row.append(celement("span", "inherits-label", "inherits"));
            parents.forEach(p => {
                row.append(celement("span", "inherits-access", p.access || "public"));
                row.append(celement("span", "inherits-name", p.name));
            });
            section.append(row);
        }

        if (node.brief) section.append(celement("p", "body-item-brief", node.brief));
        if (node.description) section.append(celement("p", "body-item-desc", node.description));

        const notes = Documentation.notes_block(node.notes);
        if (notes) section.append(notes);

        const groups = Documentation.group_members(node);
        for (const [label, items] of groups) {
            this.render_group(label, items).forEach(el => section.append(el));
        }

        return section;
    }

    // ---------- namespace page ----------
    // Same shape as get_render_class: icon + heading, own brief/
    // description, notes, then every child group rendered with
    // render_group - just without the "inherits" row.
    // NEW: Shows child namespaces/classes and markdown blocks
    get_render_namespace(node) {
        const out = [];

        const head = celement("div", "page-head");
        head.append(icon(Documentation.ICONS.namespace, "page-icon icon-namespace"));
        head.append(celement("h1", "page-title icon-namespace", node.name));
        head.append(celement("span", "kind-badge icon-namespace", "namespace"));
        const src = Documentation.source_link(node.source, this.data.metadata && this.data.metadata.source_base);
        if (src) head.append(src);
        out.push(head);

        if (node.brief) out.push(celement("p", "body-item-brief", node.brief));
        if (node.description) {
            const desc = celement("p", "body-item-desc");
            desc.innerHTML = Documentation.text_html(node.description);
            out.push(desc);
        }

        const notes = Documentation.notes_block(node.notes);
        if (notes) out.push(notes);

        // Render markdown blocks if present
        if (node.markdown && Array.isArray(node.markdown)) {
            node.markdown.forEach(md => {
                const wrap = celement("div", "markdown-block");
                if (md.description) {
                    wrap.append(celement("div", "markdown-title", md.description));
                }
                const body = celement("div", "markdown-body");
                body.innerHTML = Documentation.render_markdown(md.content);
                wrap.append(body);
                out.push(wrap);
            });
        }

        const groups = Documentation.group_members(node);
        for (const [label, items] of groups) {
            out.push(...this.render_group(label, items));
        }

        // Add child namespaces and classes at the end
        const children = (node.content || []).filter(n => Documentation.NAV_TYPES.includes(n.type));
        if (children.length) {
            out.push(celement("h3", "body-group-heading", "related items"));
            const childList = celement("div", "nested-children");
            children.forEach(child => {
                const row = celement("div", "nested-child-row");
                row.append(icon(Documentation.ICONS[child.type] || "circle", "nested-icon icon-" + child.type));
                const link = celement("a", "nested-name", child.name);
                link.href = "#";
                link.addEventListener("click", (e) => {
                    e.preventDefault();
                    const fullPath = this.find_node_path(child.name, child.type);
                    const li = document.querySelector(`.nav-item[data-path="${CSS.escape(fullPath)}"]`);
                    if (li) this.nav_item_clicked(li);
                });
                row.append(link);

                if (child.brief) row.append(celement("span", "nested-brief", child.brief));
                childList.append(row);
            });
            out.push(childList);
        }

        return out;
    }

    find_node_path(name, type) {
        const walk = (items, prefix = "") => {
            for (const item of items || []) {
                const p = prefix ? prefix + "/" + item.name : "/" + item.name;
                if (item.name === name && item.type === type) return p;
                if (item.content) {
                    const found = walk(item.content, p);
                    if (found) return found;
                }
            }
            return null;
        };
        return walk(this.data.modules || []) || "/";
    }

    // ---------- overview page ----------
    // metadata (name/description/std/license/repo) plus a flat, clickable
    // list of every top-level namespace/class - a table of contents, not
    // prose. This is what "Overview" in the left tree resolves to.
    overview_row(n) {
        const path = "/" + n.name;
        const row = celement("div", "overview-row");
        row.dataset.path = path;
        row.append(icon(Documentation.ICONS[n.type] || "circle", "overview-icon icon-" + n.type));
        row.append(celement("span", "overview-name", n.name));
        row.append(celement("span", "kind-badge icon-" + n.type, n.type));
        if (n.brief) row.append(celement("span", "overview-brief", n.brief));

        row.addEventListener("click", () => {
            // Reuse the tree's own click handling so selecting from the
            // overview list stays highlighted/expanded in sync with the
            // left nav - no separate navigation logic to keep correct.
            const li = document.querySelector(`.nav-item[data-path="${CSS.escape(path)}"]`);
            if (li) this.nav_item_clicked(li);
        });
        return row;
    }

    get_render_overview() {
        const out = [];
        const meta = this.data.metadata || {};

        const head = celement("div", "page-head");
        head.append(icon("house", "page-icon icon-root"));
        head.append(celement("h1", "page-title", meta.name || "Overview"));
        out.push(head);

        if (meta.description) {
            const desc = celement("p", "body-item-brief");
            desc.innerHTML = Documentation.text_html(meta.description);
            out.push(desc);
        }

        // Render overview blocks. Both "text" and "markdown" block types are
        // pushed through render_markdown so @mainpage/@brief/@details content
        // authored in Doxygen Markdown reaches the viewer fully rendered.
        const overview = this.data.overview || [];
        for (const block of overview) {
            if (block.type === "text" || block.type === "markdown") {
                const wrap = celement("div", "markdown-block");
                const body = celement("div", "markdown-body");
                body.innerHTML = Documentation.render_markdown(block.text || block.content || "");
                wrap.append(body);
                out.push(wrap);
            } else if (block.type === "note") {
                const box = celement("div", "callout callout-" + (block.kind || "info"));
                box.append(icon(Documentation.NOTE_ICONS[block.kind] || "circle-info", "callout-icon"));
                const text = celement("p", "callout-text");
                text.innerHTML = Documentation.render_markdown(block.text);
                box.append(text);
                out.push(box);
            }
        }

        const metaRow = celement("div", "overview-meta");
        if (meta.std) metaRow.append(celement("span", "meta-pill", meta.std));
        if (meta.license) metaRow.append(celement("span", "meta-pill", meta.license));
        if (meta.repo) {
            const a = celement("a", "meta-pill", meta.repo.replace(/^https?:\/\//, ""));
            a.href = meta.repo; a.target = "_blank"; a.rel = "noopener";
            metaRow.append(a);
        }
        if (metaRow.children.length) out.push(metaRow);

        const mods = (this.data.modules || []).filter(n => Documentation.NAV_TYPES.includes(n.type)).sort(Documentation.nav_sort);
        if (mods.length) {
            out.push(celement("h3", "body-group-heading", "contents"));
            const list = celement("div", "overview-list");
            mods.forEach(n => list.append(this.overview_row(n)));
            out.push(list);
        }

        return out;
    }

    render_overview() {
        $("#sub-list").replaceChildren();
        const body = $("#content");
        body.replaceChildren();
        this.get_render_overview().forEach(el => body.append(el));
    }

    // ---------- dispatch ----------
    render_body(node) {
        const body = $("#content");
        body.replaceChildren();

        if (node.type === "class") {
            body.append(this.get_render_class(node));
        } else if (node.type === "namespace") {
            this.get_render_namespace(node).forEach(el => body.append(el));
        }
    }

    render() {
        this.render_metadata();
        this.render_nav();
        // Land on Overview by default instead of leaving the body empty.
        const overview_li = $("#nav-list .nav-item");
        if (overview_li) this.nav_item_clicked(overview_li);
    }

    // ---------- events: left tree ----------
    nav_item_clicked(item) {
        const path = item.dataset.path;
        if (!path) return;

        const parts = path.split("/").filter(Boolean);
        let items = this.data.modules;
        let result;
        for (const part of parts) {
            result = items?.find(entry => entry.name === part);
            if (!result) break; // path segment not found in the JSON
            items = result.content;
        }

        // Selection highlight moves regardless of what was found - even
        // "Overview" (path "/", no matching JSON node) is a real selection.
        if (this.#current_item) {
            this.#current_item.querySelector(".nav-row")?.classList.remove("item-selected");
        }
        item.querySelector(".nav-row")?.classList.add("item-selected");
        this.#current_item = item;
        this.#current_sub_item = undefined;

        if (!result) {
            if (path === "/") {
                this.render_overview();
            } else {
                $("#sub-list").replaceChildren();
                $("#content").replaceChildren();
            }
            return;
        }

        this.render_sub_nav(result);
        this.render_body(result);
    }

    // ---------- events: right sub nav ----------
    sub_nav_item_clicked(item) {
        const target = item.querySelector(".sub-row")?.dataset.target;
        if (!target) return;

        if (this.#current_sub_item) {
            this.#current_sub_item.querySelector(".sub-row")?.classList.remove("item-selected");
        }
        item.querySelector(".sub-row")?.classList.add("item-selected");
        this.#current_sub_item = item;

        const target_el = document.getElementById(target);
        if (!target_el) {
            console.warn("sub nav: no element with id", target);
            return;
        }
        target_el.scrollIntoView({ behavior: "smooth", block: "start" });
        target_el.classList.add("open"); // auto-expand if it's a collapsible sig-row
    }

    // ---------- search ----------
    // Recursively collect every named item from a content tree, recording
    // the nav path needed to navigate to the item's parent node.
    #collect_search_index(items, nav_path) {
        const results = [];
        for (const item of items || []) {
            const is_nav = Documentation.NAV_TYPES.includes(item.type);
            const item_path = is_nav
                ? (nav_path ? nav_path + "/" + item.name : "/" + item.name)
                : nav_path;

            results.push({
                name: item.name,
                type: item.type,
                brief: item.brief || "",
                nav_path: item_path,
                anchor: is_nav ? null : item.name,
            });

            if (item.content) {
                results.push(...this.#collect_search_index(item.content, item_path));
            }
        }
        return results;
    }

    #build_search_index() {
        if (this._search_index) return this._search_index;
        this._search_index = this.#collect_search_index(this.data.modules || [], "");
        return this._search_index;
    }

    // Wire the search input. Called from init() after data is loaded.
    bind_search() {
        const input = $("#search-input");
        if (!input) return;
        input.addEventListener("input", () => {
            const q = input.value.trim().toLowerCase();
            if (!q) {
                if (this.#current_item) {
                    this.nav_item_clicked(this.#current_item);
                } else {
                    this.render_overview();
                }
                return;
            }
            this.#render_search_results(q);
        });
    }

    #render_search_results(query) {
        const index = this.#build_search_index();
        const hits = index.filter(e =>
            e.name.toLowerCase().includes(query) ||
            e.brief.toLowerCase().includes(query)
        );

        $("#sub-list").replaceChildren();
        const body = $("#content");
        body.replaceChildren();

        const head = celement("div", "page-head");
        head.append(icon("magnifying-glass", "page-icon icon-root"));
        head.append(celement("h1", "page-title", `Search — "${query}"`));
        body.append(head);

        if (!hits.length) {
            body.append(celement("p", "body-item-brief", "No results found."));
            return;
        }

        const list = celement("div", "overview-list");
        hits.forEach(hit => {
            const row = celement("div", "overview-row");
            row.append(icon(
                Documentation.SUB_ICONS[hit.type] || Documentation.ICONS[hit.type] || "circle",
                "overview-icon icon-" + hit.type
            ));
            row.append(celement("span", "overview-name", hit.name));
            row.append(celement("span", "kind-badge icon-" + hit.type, hit.type));
            if (hit.brief) row.append(celement("span", "overview-brief", hit.brief));

            row.addEventListener("click", () => {
                $("#search-input").value = "";
                if (!hit.nav_path) return;
                const li = document.querySelector(
                    `.nav-item[data-path="${CSS.escape(hit.nav_path)}"]`
                );
                if (!li) return;
                this.nav_item_clicked(li);
                if (hit.anchor) {
                    setTimeout(() => {
                        const el = document.getElementById(hit.anchor);
                        if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
                    }, 80);
                }
            });
            list.append(row);
        });
        body.append(list);
    }

    // ---------- events: expand/collapse ----------
    bind_events() {
        $("#nav-list").addEventListener("click", e => {
            const row = e.target.closest(".nav-row");
            if (!row) return;
            const li = row.parentElement;
            if (!li.querySelector(":scope > .nav-children")) return;
            if (e.target.closest(".nav-chevron") || !row.dataset.path) {
                e.preventDefault();
                li.classList.toggle("open");
            } else {
                li.classList.add("open");
            }
        });
    }

    // ---------- loading ----------
    tryLoad(text) {
        try {
            this.data = JSON.parse(text);
            if (!this.data) return false;
            this.render();
            return true;
        } catch (err) {
            console.log(err);
        }
    }

    init() {
        this.bind_events();
        fetch(this.url)
            .then(r => {
                if (!r.ok) throw new Error("HTTP " + r.status);
                return r.text();
            })
            .then(text => {
                this.tryLoad(text);
                this.bind_search();
            });
    }
}

new Documentation("./docs.json").init();
