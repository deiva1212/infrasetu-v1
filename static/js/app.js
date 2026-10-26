/* Infrasetu front-end helpers (no dependencies). */
(function () {
  "use strict";

  const metaCache = {};
  function fetchMeta(catId) {
    if (!catId) return Promise.resolve(null);
    if (!metaCache[catId]) {
      metaCache[catId] = fetch(`/api/categories/${catId}/meta`).then(r => (r.ok ? r.json() : null));
    }
    return metaCache[catId];
  }

  function el(tag, attrs = {}, children = []) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v === false || v === null || v === undefined) continue;
      if (k === "text") n.textContent = v;
      else if (k === "html") n.innerHTML = v;
      else n.setAttribute(k, v === true ? "" : v);
    }
    children.forEach(c => c && n.appendChild(c));
    return n;
  }

  function opt(value, label, selected) {
    const o = el("option", { value, text: label });
    if (selected) o.selected = true;
    return o;
  }

  function radioValue(scope, name) {
    const r = scope.querySelector(`input[name="${name}"]:checked`);
    return r ? r.value : "";
  }

  /* ---------------------------------------------- client-side validation */
  function showFieldError(input, msg) {
    const field = input.closest(".field") || input.parentElement;
    field.classList.add("has-error");
    let e = field.querySelector(".field-error");
    if (!e) { e = el("div", { class: "field-error", role: "alert" }); field.appendChild(e); }
    e.textContent = msg;
  }
  function clearFieldError(input) {
    const field = input.closest(".field");
    if (!field) return;
    field.classList.remove("has-error");
    const e = field.querySelector(".field-error");
    if (e) e.remove();
  }
  function fieldLabel(input) {
    const field = input.closest(".field");
    const l = field && field.querySelector("label");
    return l ? l.textContent.replace("*", "").trim() : "This field";
  }

  // We show our own inline messages instead of the browser bubbles.
  document.querySelectorAll("form[data-validate]").forEach(f => (f.noValidate = true));

  document.addEventListener("submit", ev => {
    const form = ev.target;
    if (!form.hasAttribute("data-validate")) return;
    let first = null;
    const radiosChecked = new Set();
    form.querySelectorAll("input, select, textarea").forEach(input => {
      if (input.closest("[hidden]") || input.type === "hidden" || input.disabled) return;
      if (input.type === "radio") {
        if (radiosChecked.has(input.name)) return;
        radiosChecked.add(input.name);
        const group = form.querySelectorAll(`input[name="${input.name}"]`);
        const req = [...group].some(r => r.required);
        if (req && ![...group].some(r => r.checked)) {
          showFieldError(input, "Please choose an option.");
          first = first || input;
        }
        return;
      }
      clearFieldError(input);
      if (input.type === "file") {
        if (input.required && !input.files.length) { showFieldError(input, "Please upload at least one photo."); first = first || input; }
        return;
      }
      if (!input.checkValidity()) {
        let msg = input.validationMessage;
        if (input.validity.valueMissing) msg = `${fieldLabel(input)} is required.`;
        showFieldError(input, msg);
        first = first || input;
      }
    });
    if (first) {
      ev.preventDefault();
      first.scrollIntoView({ behavior: "smooth", block: "center" });
      setTimeout(() => first.focus({ preventScroll: true }), 300);
    }
  }, true);

  document.addEventListener("input", ev => {
    if (ev.target.closest("form[data-validate]")) clearFieldError(ev.target);
  });

  /* ---------------------------------------------- dynamic attribute field */
  function attributeField(a, value, error, mode) {
    // mode: "form" (listing form) or "filter" (search sidebar)
    const name = `attr_${a.id}`;
    const id = `f-${name}`;
    const label = a.label + (a.unit ? ` (${a.unit})` : "");
    const required = mode === "form" && a.required;
    const field = el("div", { class: "field" + (error ? " has-error" : "") + (a.type === "boolean" && mode === "form" ? " check check-pad" : "") });
    let control;
    if (a.type === "boolean" && mode === "form") {
      control = el("input", { type: "checkbox", name, value: "1", id });
      if (value === "1" || value === "Yes") control.checked = true;
      field.appendChild(el("label", { class: "checkbox" }, [control, document.createTextNode(" " + label)]));
    } else {
      field.appendChild(el("label", { for: id, html: (mode === "filter" && a.type === "number" ? "Min " + label : label) + (required ? ' <span class="req">*</span>' : "") }));
      if (a.type === "select" || a.type === "boolean") {
        control = el("select", { name, id, required });
        control.appendChild(opt("", mode === "filter" ? "Any" : "Select…"));
        const options = a.type === "boolean" ? ["Yes", "No"] : a.options;
        options.forEach(o => control.appendChild(opt(o, o, o === value)));
      } else {
        control = el("input", {
          name, id, required, type: a.type === "number" ? "number" : "text",
          step: a.type === "number" ? "any" : null, min: a.type === "number" ? "0" : null,
        });
        control.value = value || "";
      }
      field.appendChild(control);
    }
    if (error) field.appendChild(el("div", { class: "field-error", text: error }));
    return field;
  }

  /* ---------------------------------------------- search form */
  window.initSearchForm = function (form) {
    if (!form) return;
    const catSel = form.querySelector("[data-meta-target]");
    const mfrSel = form.querySelector("[data-manufacturer]");
    const modelSel = form.querySelector("[data-model]");
    const attrBox = form.querySelector("[data-attr-filters]");
    const values = JSON.parse(form.dataset.attrValues || "{}");
    let meta = null;
    let first = true;

    function fillModels() {
      const mfr = mfrSel.value;
      const keep = first ? form.dataset.selectedModel : modelSel.value;
      modelSel.innerHTML = "";
      modelSel.appendChild(opt("", "Any model"));
      if (!meta) return;
      meta.catalogue.filter(c => !mfr || c.manufacturer === mfr)
        .forEach(c => modelSel.appendChild(opt(c.id, mfr ? c.model : c.name, String(c.id) === keep)));
    }

    function load() {
      fetchMeta(catSel.value).then(m => {
        meta = m;
        const keepMfr = first ? form.dataset.selectedManufacturer : "";
        mfrSel.innerHTML = "";
        mfrSel.appendChild(opt("", "Any make"));
        attrBox.innerHTML = "";
        if (m) {
          [...new Set(m.catalogue.map(c => c.manufacturer))].forEach(x => mfrSel.appendChild(opt(x, x, x === keepMfr)));
          m.attributes.filter(a => a.searchable).forEach(a => {
            attrBox.appendChild(attributeField(a, first ? values[`attr_${a.id}`] : "", null, "filter"));
          });
        }
        fillModels();
        first = false;
      });
    }

    catSel.addEventListener("change", load);
    mfrSel.addEventListener("change", fillModels);
    form.querySelectorAll('input[name="intent"]').forEach(r => r.addEventListener("change", () => {
      form.querySelectorAll("[data-rent-only]").forEach(s => (s.hidden = radioValue(form, "intent") !== "rent"));
    }));
    load();
  };

  /* ---------------------------------------------- listing form */
  window.initProductForm = function (box) {
    if (!box) return;
    const form = box.closest("form");
    const data = JSON.parse(box.dataset.form || "{}");
    const errors = JSON.parse(box.dataset.errors || "{}");
    const catSel = box.querySelector("[data-meta-target]");
    const modelSel = box.querySelector("[data-model]");
    const attrSection = box.querySelector("[data-attr-section]");
    const attrBox = box.querySelector("[data-attr-fields]");
    const usageInput = box.querySelector("[data-usage-input]");
    const regInput = box.querySelector("[data-reg-input]");
    const ownSel = box.querySelector('[name="ownership"]');
    const condSel = box.querySelector('[name="condition"]');
    let meta = null;
    let first = true;

    function setRequired(input, req) {
      if (!input) return;
      input.required = req;
      const label = input.closest(".field")?.querySelector("label");
      if (!label) return;
      let star = label.querySelector(".req");
      if (req && !star) label.insertAdjacentHTML("beforeend", ' <span class="req">*</span>');
      if (!req && star) star.remove();
    }

    function applyType() {
      const t = radioValue(box, "listing_type");
      box.querySelectorAll("[data-sell-only]").forEach(s => (s.hidden = t !== "sell"));
      box.querySelectorAll("[data-rent-only]").forEach(s => (s.hidden = t !== "rent"));
      box.querySelectorAll("[data-req-sell]").forEach(i => setRequired(i, t === "sell"));
      box.querySelectorAll("[data-req-rent]").forEach(i => setRequired(i, t === "rent"));
    }

    function applyConditionRules() {
      const used = condSel.value && condSel.value !== "New";
      setRequired(ownSel, !!used);
      setRequired(regInput, !!(used && meta && meta.group === "Commercial Vehicle"));
    }

    function load() {
      fetchMeta(catSel.value).then(m => {
        meta = m;
        const keep = first ? String(data.catalogue_id || "") : "";
        modelSel.innerHTML = "";
        attrBox.innerHTML = "";
        if (!m) {
          modelSel.appendChild(opt("", "Select category first…"));
          attrSection.hidden = true;
        } else {
          modelSel.appendChild(opt("", m.catalogue.length ? "Select make & model…" : "No models in catalogue yet"));
          const groups = {};
          m.catalogue.forEach(c => (groups[c.manufacturer] = groups[c.manufacturer] || []).push(c));
          Object.entries(groups).forEach(([mfr, items]) => {
            const g = el("optgroup", { label: mfr });
            items.forEach(c => g.appendChild(opt(c.id, c.name, String(c.id) === keep)));
            modelSel.appendChild(g);
          });
          m.attributes.forEach(a => {
            const k = `attr_${a.id}`;
            attrBox.appendChild(attributeField(a, first ? data[k] : "", first ? errors[k] : null, "form"));
          });
          attrSection.hidden = m.attributes.length === 0;
          box.querySelector("[data-cat-name]").textContent = m.name;
          usageInput.closest(".field").querySelector("label").innerHTML =
            (m.usage_unit === "hours" ? "Engine hours" : "Kilometres driven") + ' <span class="req">*</span>';
          box.querySelectorAll('input[name="listing_type"]').forEach(r => {
            const allowed = r.value === "sell" ? m.allow_sell : m.allow_rent;
            r.disabled = !allowed;
            r.closest("label").title = allowed ? "" : "Not available for this category";
            if (!allowed && r.checked) {
              const other = box.querySelector(`input[name="listing_type"][value="${r.value === "sell" ? "rent" : "sell"}"]`);
              other.checked = true;
            }
          });
        }
        applyType();
        applyConditionRules();
        first = false;
      });
    }

    box.querySelectorAll('input[name="listing_type"]').forEach(r => r.addEventListener("change", applyType));
    catSel.addEventListener("change", load);
    condSel.addEventListener("change", applyConditionRules);

    // photo previews
    const imgInput = box.querySelector("[data-image-input]");
    const preview = box.querySelector("[data-image-preview]");
    if (imgInput) {
      if (!box.querySelector(".img-edit")) imgInput.required = !form.hasAttribute("data-admin");
      imgInput.addEventListener("change", () => {
        preview.innerHTML = "";
        [...imgInput.files].slice(0, 8).forEach(f => {
          const img = el("img", { alt: f.name });
          img.src = URL.createObjectURL(f);
          preview.appendChild(img);
        });
      });
    }
    applyType();
    load();
  };

  /* ---------------------------------------------- gallery */
  document.addEventListener("click", ev => {
    const btn = ev.target.closest("[data-gallery] .thumbs button");
    if (!btn) return;
    const g = btn.closest("[data-gallery]");
    g.querySelector("[data-gallery-main]").src = btn.dataset.src;
    g.querySelectorAll(".thumbs button").forEach(b => b.classList.toggle("active", b === btn));
  });

  /* ---------------------------------------------- admin: select all */
  document.addEventListener("change", ev => {
    if (ev.target.matches("[data-check-all]")) {
      document.querySelectorAll('input[name="ids"]').forEach(c => (c.checked = ev.target.checked));
    }
  });
})();
