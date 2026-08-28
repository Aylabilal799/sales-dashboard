function showToast(msg, duration = 2800) {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.classList.remove('hidden');
  setTimeout(() => t.classList.add('hidden'), duration);
}

function formatNum(n) {
  return Math.round(Number(n) || 0).toLocaleString('en-US');
}

function copyToClipboard(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    return navigator.clipboard.writeText(text).then(() => {
      showToast('Message copied to clipboard!');
    }).catch(() => fallbackCopy(text));
  }
  return fallbackCopy(text);
}

function fallbackCopy(text) {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.left = '-9999px';
  document.body.appendChild(ta);
  ta.select();
  try {
    document.execCommand('copy');
    showToast('Message copied to clipboard!');
  } catch (e) {
    showToast('Copy failed – please select and copy manually');
  }
  document.body.removeChild(ta);
}

function initUploadPage(resultData) {
  if (!resultData) return;

  const otherInputs = document.querySelectorAll('.other-city-input');
  const tpInputs = document.querySelectorAll('.tp-input');
  const msgEl = document.getElementById('generated-message');
  const copyBtn = document.getElementById('copy-message-btn');
  const saveBtn = document.getElementById('save-report-btn');

  function collectProducts() {
    const products = JSON.parse(JSON.stringify(resultData.products));
    let totalTodayVal = 0;
    let totalOtherVal = 0;
    let totalCurrentVal = 0;
    let totalTgtValue = 0;

    products.forEach((p, idx) => {
      const otherInp = document.querySelector(`.other-city-input[data-idx="${idx}"]`);
      const tpInp = document.querySelector(`.tp-input[data-idx="${idx}"]`);
      const other = otherInp ? (parseFloat(otherInp.value) || 0) : 0;
      const tp = tpInp ? (parseFloat(tpInp.value) || 0) : (Number(p.tp) || 0);
      const mtd = Number(p.mtd_qty) || 0;
      const todayQty = Number(p.today_qty) || 0;
      const tgt = Number(p.monthly_target) || 0;
      const current = Math.max(0, mtd - other);

      p.other_city_sales = other;
      p.tp = tp;
      p.current_sale = current;
      p.today_value = Math.round(todayQty * tp * 100) / 100;
      p.mtd_value = Math.round(mtd * tp * 100) / 100;
      p.other_city_value = Math.round(other * tp * 100) / 100;
      p.current_sale_value = Math.round(current * tp * 100) / 100;
      p.target_value = Math.round(tgt * tp * 100) / 100;

      totalTodayVal += p.today_value;
      totalOtherVal += p.other_city_value;
      totalCurrentVal += p.current_sale_value;
      totalTgtValue += p.target_value;

      const curCell = document.getElementById('current-sale-' + idx);
      if (curCell) curCell.textContent = current;
      const tgtValCell = document.getElementById('target-value-' + idx);
      if (tgtValCell) tgtValCell.textContent = formatNum(p.target_value);

      if (otherInp) {
        if (other > mtd) otherInp.classList.add('input-error');
        else otherInp.classList.remove('input-error');
      }
    });

    const set = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = formatNum(val);
    };
    set('total-today-value', totalTodayVal);
    set('total-today-value-2', totalTodayVal);
    set('total-other-city-value', totalOtherVal);
    set('total-current-sale-value', totalCurrentVal);
    set('total-mtd-value', totalCurrentVal);
    set('total-target-value', totalTgtValue);
    set('total-target-value-2', totalTgtValue);

    return products;
  }

  async function refreshMessage() {
    const products = collectProducts();
    const payload = {
      report_date: resultData.report_date,
      psp_name: resultData.psp_name,
      town: resultData.town,
      per_day_target: resultData.per_day_target,
      today_sale_value: resultData.today_sale_value,
      today_achievement: resultData.today_achievement,
      mtd_sale_value: resultData.mtd_sale_value,
      mtd_target: resultData.mtd_target,
      mtd_achievement: resultData.mtd_achievement,
      zero_display: resultData.zero_display,
      working_days: resultData.working_days || 26,
      per_day_target_override: resultData.per_day_target_override,
      monthly_target_base: resultData.monthly_target_base,
      products: products,
    };
    try {
      const res = await fetch('/api/regenerate-message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (msgEl) msgEl.textContent = data.message;
      resultData.products = data.products;
      resultData.generated_message = data.message;
      if (data.today_sale_value !== undefined) {
        resultData.today_sale_value = data.today_sale_value;
        resultData.mtd_sale_value = data.mtd_sale_value;
        resultData.today_achievement = data.today_achievement;
        resultData.mtd_achievement = data.mtd_achievement;
        if (data.mtd_target !== undefined) resultData.mtd_target = data.mtd_target;
        if (data.per_day_target !== undefined) resultData.per_day_target = data.per_day_target;
        if (data.monthly_target_base !== undefined) resultData.monthly_target_base = data.monthly_target_base;
        const cToday = document.getElementById('card-today-sale');
        const cMtd = document.getElementById('card-mtd-sale');
        const cTa = document.getElementById('card-today-ach');
        const cMa = document.getElementById('card-mtd-ach');
        const cMt = document.getElementById('card-mtd-target');
        if (cToday) cToday.textContent = formatNum(data.today_sale_value);
        if (cMtd) cMtd.textContent = formatNum(data.mtd_sale_value);
        if (cTa) cTa.textContent = Math.round(data.today_achievement) + '%';
        if (cMa) cMa.textContent = Math.round(data.mtd_achievement) + '%';
        if (cMt && data.mtd_target !== undefined) cMt.textContent = formatNum(data.mtd_target);
      }
    } catch (e) {
      console.error(e);
    }
  }

  function onInputChange(inp) {
    collectProducts();
    clearTimeout(inp._timer);
    inp._timer = setTimeout(refreshMessage, 350);
  }

  otherInputs.forEach(inp => {
    inp.addEventListener('input', () => onInputChange(inp));
  });
  tpInputs.forEach(inp => {
    inp.addEventListener('input', () => onInputChange(inp));
  });

  collectProducts();

  if (copyBtn) {
    copyBtn.addEventListener('click', () => {
      const text = msgEl ? msgEl.textContent : resultData.generated_message;
      copyToClipboard(text);
    });
  }

  if (saveBtn) {
    saveBtn.addEventListener('click', async () => {
      if (resultData.overwrite_warning) {
        if (!confirm('A report for this date already exists. Overwrite it?')) return;
      }
      const products = collectProducts();
      await refreshMessage();
      const payload = {
        ...resultData,
        products: products,
        generated_message: resultData.generated_message,
      };
      saveBtn.disabled = true;
      saveBtn.textContent = 'Saving…';
      try {
        const res = await fetch('/api/save-report', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (data.ok) {
          showToast('Report saved successfully!');
          setTimeout(() => { window.location.href = '/history/' + data.report_id; }, 800);
        } else {
          showToast('Save failed');
          saveBtn.disabled = false;
          saveBtn.textContent = 'Save Report';
        }
      } catch (e) {
        showToast('Save error');
        saveBtn.disabled = false;
        saveBtn.textContent = 'Save Report';
      }
    });
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const zone = document.getElementById('upload-zone');
  const fileInput = document.getElementById('pdf-file');
  if (zone && fileInput) {
    zone.addEventListener('click', () => fileInput.click());
    zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragover'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
    zone.addEventListener('drop', e => {
      e.preventDefault();
      zone.classList.remove('dragover');
      if (e.dataTransfer.files.length) {
        fileInput.files = e.dataTransfer.files;
        document.getElementById('upload-form').submit();
      }
    });
    fileInput.addEventListener('change', () => {
      if (fileInput.files.length) {
        document.getElementById('upload-form').submit();
      }
    });
  }
});
