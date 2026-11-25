const form = document.getElementById('import');
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const file = form.querySelector('input').files[0];
  const status = form.querySelector('output');
  if (file.size > 1048576) { status.textContent = 'Report exceeds 1 MiB.'; return; }
  try {
    const response = await fetch(form.action, {method:'POST', headers:{'Content-Type':'application/json'}, body:file});
    const result = await response.json();
    if (response.ok) location.assign(result.location);
    else status.textContent = result.detail;
  } catch { status.textContent = 'Could not import report.'; }
});
