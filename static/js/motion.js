// Motion helpers: staggered reveal, count-up stats, button ripples, bars, flash fade, confetti.
(function () {
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Staggered reveal of cards, tiles and table rows as they scroll into view.
  const groups = [
    ...document.querySelectorAll(".grid, .tiles, .kiosk, .stack"),
    ...document.querySelectorAll("tbody"),
  ];
  const singles = document.querySelectorAll(".container > .card, .container > section.card, .container > form.card");
  const targets = [];
  groups.forEach(g => {
    [...g.children].slice(0, 40).forEach((el, i) => { el.style.setProperty("--i", i); targets.push(el); });
  });
  singles.forEach(el => { if (!targets.includes(el)) targets.push(el); });
  targets.forEach(el => el.classList.add("reveal"));

  const show = el => {
    el.classList.add("in");
    el.querySelectorAll(".bar").forEach(b => b.classList.add("go"));
    el.querySelectorAll(".stat .num").forEach(countUp);
  };
  if (reduce || !("IntersectionObserver" in window)) {
    targets.forEach(show);
  } else {
    const io = new IntersectionObserver(entries => {
      entries.forEach(e => { if (e.isIntersecting) { show(e.target); io.unobserve(e.target); } });
    }, { threshold: 0.08 });
    targets.forEach(el => io.observe(el));
  }
  // Bars/stats that are not inside a revealed element.
  setTimeout(() => {
    document.querySelectorAll(".bar:not(.go)").forEach(b => b.classList.add("go"));
    document.querySelectorAll(".stat .num:not([data-counted])").forEach(countUp);
  }, 400);

  // Count numbers up from 0 (keeps any suffix such as "%").
  function countUp(el) {
    if (el.dataset.counted) return;
    el.dataset.counted = "1";
    const m = el.textContent.trim().match(/^(-?\d+(?:\.\d+)?)(.*)$/);
    if (!m || reduce) return;
    const end = parseFloat(m[1]), suffix = m[2], dec = (m[1].split(".")[1] || "").length;
    if (end === 0) return;
    const dur = 900, t0 = performance.now();
    const step = now => {
      const p = Math.min(1, (now - t0) / dur), eased = 1 - Math.pow(1 - p, 3);
      el.textContent = (end * eased).toFixed(dec) + suffix;
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  // Ripple on every button click.
  document.addEventListener("pointerdown", e => {
    const btn = e.target.closest(".btn");
    if (!btn || reduce) return;
    const r = btn.getBoundingClientRect(), size = Math.max(r.width, r.height);
    const s = document.createElement("span");
    s.className = "ripple";
    s.style.cssText = `width:${size}px;height:${size}px;left:${e.clientX - r.left - size / 2}px;top:${e.clientY - r.top - size / 2}px`;
    btn.appendChild(s);
    setTimeout(() => s.remove(), 650);
  });

  // Flash messages fade out after a few seconds.
  document.querySelectorAll(".messages li").forEach((li, i) => {
    setTimeout(() => { li.classList.add("out"); setTimeout(() => li.remove(), 520); }, 5000 + i * 400);
  });

  // Confetti burst from an element (used when attendance is marked).
  window.celebrate = function (fromEl) {
    if (reduce) return;
    const r = fromEl.getBoundingClientRect();
    const colors = ["#3b5bdb", "#7048e8", "#51cf66", "#fcc419", "#ff8787", "#22b8cf"];
    for (let i = 0; i < 46; i++) {
      const c = document.createElement("span");
      c.className = "confetti";
      const angle = Math.random() * Math.PI * 2, dist = 120 + Math.random() * 220;
      c.style.cssText = `left:${r.left + r.width / 2}px;top:${r.top + 40}px;background:${colors[i % colors.length]};` +
        `--dx:${Math.cos(angle) * dist}px;--dy:${Math.sin(angle) * dist + 160}px;--r:${Math.random() * 720 - 360}deg;` +
        `animation-delay:${Math.random() * 120}ms`;
      document.body.appendChild(c);
      setTimeout(() => c.remove(), 1700);
    }
  };
})();
