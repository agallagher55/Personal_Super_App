// Upload form for the CSV-import approach (finance/ARCHITECTURE.md Part A).
// Sends the selected file's raw bytes as the fetch() body (no multipart
// encoding) to POST /finance/import?filename=<name>, so
// backend/server.py can read it with a plain Content-Length +
// rfile.read() the same way its other POST handlers do, no multipart
// parser needed on either side.

const IMPORT_URL = "/finance/import";

function formatDate(iso) {
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function initFinanceImport() {
  const input = document.getElementById("fin-import-input");
  const button = document.getElementById("fin-import-button");
  const status = document.getElementById("fin-import-status");
  if (!input || !button || !status) return;

  button.addEventListener("click", () => input.click());

  input.addEventListener("change", async () => {
    const file = input.files[0];
    if (!file) return;

    button.disabled = true;
    status.classList.remove("fin-import-status-error");
    status.textContent = `Importing ${file.name}...`;

    try {
      const res = await fetch(`${IMPORT_URL}?filename=${encodeURIComponent(file.name)}`, {
        method: "POST",
        body: file,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.message || `HTTP ${res.status}`);

      status.textContent =
        `Imported ${data.rows_imported} row${data.rows_imported === 1 ? "" : "s"} into "${data.account_id}" ` +
        `(${formatDate(data.date_start)} – ${formatDate(data.date_end)}).`;
    } catch (err) {
      status.classList.add("fin-import-status-error");
      status.textContent = `Import failed: ${err.message}`;
    } finally {
      button.disabled = false;
      input.value = "";
    }
  });
}
