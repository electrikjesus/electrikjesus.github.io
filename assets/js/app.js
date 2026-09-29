const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/* ---------- Theme: auto → light → dark ---------- */
const THEMES = ["auto", "light", "dark"];
$$("[data-theme-toggle]").forEach((btn) =>
  btn.addEventListener("click", () => {
    const root = document.documentElement;
    const next = THEMES[(THEMES.indexOf(root.dataset.theme) + 1) % THEMES.length];
    root.dataset.theme = next;
    localStorage.setItem("theme", next);
    toast(`Theme: ${next === "auto" ? "match system" : next}`);
  })
);

/* ---------- App bar: hairline + collapsing large title ---------- */
const appbar = $("[data-appbar]");
const largeTitle = $("[data-large-title]");
if (appbar) {
  const onScroll = () => appbar.classList.toggle("scrolled", window.scrollY > 4);
  onScroll();
  addEventListener("scroll", onScroll, { passive: true });
  if (largeTitle && "IntersectionObserver" in window) {
    new IntersectionObserver(([e]) => appbar.classList.toggle("show-title", !e.isIntersecting), {
      rootMargin: `-${appbar.offsetHeight}px 0px 0px 0px`,
    }).observe(largeTitle);
  } else {
    document.body.classList.add("no-large-title");
  }
}

/* Back button returns to the previous page when it was on this site. */
$$("[data-back]").forEach((a) =>
  a.addEventListener("click", (e) => {
    if (document.referrer && new URL(document.referrer).origin === location.origin && history.length > 1) {
      e.preventDefault();
      history.back();
    }
  })
);

/* ---------- Relative dates ---------- */
const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
const dtf = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });
const dtfFull = new Intl.DateTimeFormat(undefined, { dateStyle: "long", timeStyle: "short" });
function relTime(date) {
  const diff = (date - Date.now()) / 1000;
  const abs = Math.abs(diff);
  if (abs < 60) return rtf.format(Math.round(diff), "second");
  if (abs < 3600) return rtf.format(Math.round(diff / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), "hour");
  if (abs < 86400 * 7) return rtf.format(Math.round(diff / 86400), "day");
  return null;
}
$$("time[data-rel]").forEach((t) => {
  const d = new Date(t.getAttribute("datetime"));
  if (isNaN(d)) return;
  t.title = dtfFull.format(d);
  t.textContent = relTime(d) || (t.hasAttribute("data-full") ? dtfFull.format(d) : dtf.format(d));
});

/* ---------- Spoilers ---------- */
document.addEventListener("click", (e) => {
  const s = e.target.closest(".spoiler");
  if (s) s.classList.add("revealed");
});

/* ---------- Snackbar ---------- */
let toastTimer;
function toast(msg) {
  const bar = $("[data-snackbar]");
  if (!bar) return;
  bar.textContent = msg;
  bar.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => bar.classList.remove("show"), 2200);
}

/* ---------- Filter chips ---------- */
$$("[data-chip-bar]").forEach((bar) => {
  const row = $(".chip-row", bar);
  const [prev, next] = $$(".chip-scroll", bar);
  const maxScroll = () => row.scrollWidth - row.clientWidth;
  const update = () => {
    const left = row.scrollLeft > 1;
    const right = row.scrollLeft < maxScroll() - 1;
    bar.classList.toggle("more-left", left);
    bar.classList.toggle("more-right", right);
    prev.hidden = !left;
    next.hidden = !right;
  };
  const page = (dir) => row.scrollBy({ left: dir * row.clientWidth * 0.75, behavior: "smooth" });
  prev.addEventListener("click", () => page(-1));
  next.addEventListener("click", () => page(1));
  row.addEventListener("scroll", update, { passive: true });
  new ResizeObserver(update).observe(row);

  /* A vertical wheel scrolls the chips sideways until they reach an end, then the page scrolls again. */
  row.addEventListener("wheel", (e) => {
    if (e.ctrlKey || Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return;
    const atStart = row.scrollLeft <= 0;
    const atEnd = row.scrollLeft >= maxScroll() - 1;
    if ((e.deltaY < 0 && atStart) || (e.deltaY > 0 && atEnd)) return;
    e.preventDefault();
    row.scrollLeft += e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY;
  }, { passive: false });

  const selected = $(".chip.selected", row);
  if (selected) {
    const offset = selected.getBoundingClientRect().left - row.getBoundingClientRect().left;
    if (offset + selected.offsetWidth > row.clientWidth) {
      row.scrollLeft += offset - (row.clientWidth - selected.offsetWidth) / 2;
    }
  }
  update();
});

/* ---------- Native share sheet ---------- */
$$("[data-share]").forEach((btn) =>
  btn.addEventListener("click", async () => {
    const data = { title: btn.dataset.title, url: btn.dataset.url };
    try {
      if (navigator.share) return await navigator.share(data);
      await navigator.clipboard.writeText(data.url);
      toast("Link copied");
    } catch (err) {
      if (err.name !== "AbortError") toast("Couldn't share this link");
    }
  })
);

/* ---------- Telegram videos ---------- */
/* Video links carry tokens that expire; when one no longer loads, show Telegram's own player for that post. */
const isDark = () => {
  const t = document.documentElement.dataset.theme;
  return t === "dark" || (t !== "light" && matchMedia("(prefers-color-scheme: dark)").matches);
};
$$("video[data-tg-post]").forEach((video) =>
  video.addEventListener("error", () => {
    const cell = video.closest(".tg-video");
    if (!cell || cell.classList.contains("tg-embed")) return;
    const frame = document.createElement("iframe");
    frame.src = `https://t.me/${video.dataset.tgPost}?embed=1&userpic=false${isDark() ? "&dark=1" : ""}`;
    frame.title = "Video on Telegram";
    frame.loading = "lazy";
    frame.allow = "autoplay; fullscreen";
    cell.classList.add("tg-embed");
    cell.replaceChildren(frame);
  })
);
addEventListener("message", (e) => {
  if (e.origin !== "https://t.me") return;
  let data;
  try { data = typeof e.data === "string" ? JSON.parse(e.data) : e.data; } catch { return; }
  if (data?.event !== "resize" || !data.height) return;
  const frame = $$(".tg-embed iframe").find((f) => f.contentWindow === e.source);
  if (frame) frame.style.height = `${data.height}px`;
});

/* ---------- Lightbox with swipe ---------- */
const lb = $("[data-lightbox-root]");
if (lb) {
  const stage = $("[data-lb-stage]", lb);
  const count = $("[data-lb-count]", lb);
  let items = [];
  let index = 0;

  const show = (i) => {
    index = (i + items.length) % items.length;
    stage.innerHTML = "";
    const img = new Image();
    img.src = items[index];
    img.alt = "";
    stage.append(img);
    count.textContent = `${index + 1} / ${items.length}`;
  };
  const open = (group, start) => {
    items = group;
    lb.classList.toggle("single", items.length < 2);
    lb.hidden = false;
    document.body.style.overflow = "hidden";
    show(start);
  };
  const close = () => {
    lb.hidden = true;
    document.body.style.overflow = "";
  };

  document.addEventListener("click", (e) => {
    const a = e.target.closest("a[data-lightbox]");
    if (!a || e.metaKey || e.ctrlKey) return;
    e.preventDefault();
    const group = $$(`a[data-lightbox="${a.dataset.lightbox}"]`);
    open(group.map((g) => g.href), group.indexOf(a));
  });
  $("[data-lb-close]", lb).addEventListener("click", close);
  $("[data-lb-prev]", lb).addEventListener("click", () => show(index - 1));
  $("[data-lb-next]", lb).addEventListener("click", () => show(index + 1));
  stage.addEventListener("click", (e) => e.target === stage && close());
  addEventListener("keydown", (e) => {
    if (lb.hidden) return;
    if (e.key === "Escape") close();
    if (e.key === "ArrowLeft") show(index - 1);
    if (e.key === "ArrowRight") show(index + 1);
  });

  let sx = 0, sy = 0, dx = 0, dy = 0, tracking = false;
  lb.addEventListener("pointerdown", (e) => {
    if (e.target.closest(".lb-btn")) return;
    tracking = true;
    sx = e.clientX; sy = e.clientY; dx = dy = 0;
  });
  lb.addEventListener("pointermove", (e) => {
    if (!tracking) return;
    dx = e.clientX - sx; dy = e.clientY - sy;
    const img = $("img", stage);
    if (!img) return;
    img.style.transition = "none";
    if (Math.abs(dy) > Math.abs(dx)) {
      img.style.transform = `translateY(${dy}px) scale(${1 - Math.min(Math.abs(dy) / 1200, 0.2)})`;
      lb.style.background = `rgb(0 0 0 / ${0.94 - Math.min(Math.abs(dy) / 600, 0.6)})`;
    } else {
      img.style.transform = `translateX(${dx}px)`;
    }
  });
  const end = () => {
    if (!tracking) return;
    tracking = false;
    const img = $("img", stage);
    lb.style.background = "";
    if (img) { img.style.transition = ""; img.style.transform = ""; }
    if (Math.abs(dy) > 120 && Math.abs(dy) > Math.abs(dx)) close();
    else if (dx < -60 && items.length > 1) show(index + 1);
    else if (dx > 60 && items.length > 1) show(index - 1);
  };
  lb.addEventListener("pointerup", end);
  lb.addEventListener("pointercancel", end);
}

/* ---------- Search ---------- */
let indexPromise;
const loadIndex = (url) => (indexPromise ||= fetch(url).then((r) => r.json()).catch(() => []));
const escapeHtml = (s) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const norm = (s) => (s || "").toLowerCase().normalize("NFKD").replace(/[\u0300-\u036f]/g, "");

function highlight(text, terms) {
  let out = escapeHtml(text);
  for (const t of terms) {
    if (t.length < 2) continue;
    out = out.replace(new RegExp(`(${t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi"), "<mark>$1</mark>");
  }
  return out;
}

function snippet(text, terms) {
  const lower = norm(text);
  const pos = Math.max(0, ...terms.map((t) => lower.indexOf(t)).filter((p) => p >= 0).concat(0));
  const start = Math.max(0, pos - 60);
  return (start ? "…" : "") + text.slice(start, start + 180) + (text.length > start + 180 ? "…" : "");
}

function search(index, query) {
  const terms = norm(query).split(/\s+/).filter(Boolean);
  if (!terms.length) return [];
  const scored = [];
  for (const doc of index) {
    const title = norm(doc.t), tags = norm((doc.g || []).join(" ")), body = norm(doc.s + " " + doc.x);
    let score = 0;
    for (const t of terms) {
      const s = (title.includes(t) ? 10 : 0) + (tags.includes(t) ? 6 : 0) + (body.includes(t) ? 2 : 0);
      if (!s) { score = 0; break; }
      score += s;
    }
    if (score) scored.push([score, doc]);
  }
  return scored.sort((a, b) => b[0] - a[0]).slice(0, 30).map(([, d]) => ({ doc: d, terms }));
}

function bindSearch(input, results) {
  let active = -1;
  const render = async () => {
    const q = input.value.trim();
    const index = await loadIndex(input.dataset.index);
    if (!q) { results.innerHTML = ""; return; }
    const hits = search(index, q);
    active = -1;
    results.innerHTML = hits.length
      ? hits.map(({ doc, terms }) => `
        <a class="sr-item" role="option" href="${doc.u}">
          ${doc.i ? `<img class="sr-thumb" src="${doc.i}" alt="" loading="lazy">` : `<span class="sr-thumb">#</span>`}
          <span class="sr-body">
            <span class="sr-title">${highlight(doc.t, terms)}</span>
            <span class="sr-meta">${escapeHtml(doc.d)}${doc.g?.length ? " · " + escapeHtml(doc.g.slice(0, 3).join(", ")) : ""}</span>
            <span class="sr-snippet">${highlight(snippet(doc.s || doc.x, terms), terms)}</span>
          </span>
        </a>`).join("")
      : `<p class="sr-empty">No posts match “${escapeHtml(q)}”.</p>`;
  };
  let timer;
  input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(render, 90); });
  input.addEventListener("keydown", (e) => {
    const items = $$(".sr-item", results);
    if (!items.length) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      active = (active + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      items.forEach((el, i) => el.setAttribute("aria-selected", i === active));
      items[active].scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter") {
      (items[active] || items[0]).click();
    }
  });
  const q = new URLSearchParams(location.search).get("q");
  if (q && !input.closest("dialog")) { input.value = q; render(); }
}

$$(".search-page [data-search-input]").forEach((input) => bindSearch(input, $("[data-search-results]", input.closest(".search-page"))));

const sheet = $("[data-search-sheet]");
if (sheet && typeof sheet.showModal === "function") {
  const input = $("[data-search-input]", sheet);
  bindSearch(input, $("[data-search-results]", sheet));
  const openSheet = () => {
    if (sheet.open) return;
    sheet.showModal();
    loadIndex(input.dataset.index);
    requestAnimationFrame(() => input.focus());
  };
  if (!$(".search-page")) {
    $$("[data-search-open]").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); openSheet(); }));
  }
  $("[data-search-close]", sheet).addEventListener("click", () => sheet.close());
  sheet.addEventListener("click", (e) => e.target === sheet && sheet.close());
  addEventListener("keydown", (e) => {
    const typing = /INPUT|TEXTAREA/.test(document.activeElement?.tagName);
    if ((e.key === "/" && !typing) || (e.key === "k" && (e.metaKey || e.ctrlKey))) {
      if ($(".search-page")) return;
      e.preventDefault();
      openSheet();
    }
  });
}
