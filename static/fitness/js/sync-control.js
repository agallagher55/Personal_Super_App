// Shared "Sync now" button + "Last synced" label wiring, used by both the
// dashboard header and every metric detail page header.
import { getHealth, triggerSync } from "./api.js";

function formatRelativeTime(isoTimestamp) {
  if (!isoTimestamp) return "never";

  const diffSeconds = Math.round((Date.now() - new Date(isoTimestamp).getTime()) / 1000);
  if (diffSeconds < 5) return "just now";
  if (diffSeconds < 60) return `${diffSeconds}s ago`;

  const diffMinutes = Math.round(diffSeconds / 60);
  if (diffMinutes < 60) return `${diffMinutes}m ago`;

  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;

  const diffDays = Math.round(diffHours / 24);
  return `${diffDays}d ago`;
}

function setLastSynced(el, isoTimestamp) {
  el.textContent = `Last synced: ${formatRelativeTime(isoTimestamp)}`;
}

export async function loadLastSynced(el) {
  try {
    const health = await getHealth();
    setLastSynced(el, health.data_store_last_modified);
  } catch (err) {
    el.textContent = "";
  }
}

/**
 * Wires a header's sync button. `setStatus(message, isError)` reports
 * progress/results on the page's status line; `onDone()` runs after the
 * sync attempt settles (success or failure) so the caller can reload data.
 */
export function wireSyncButton(button, lastSyncedEl, { setStatus, onDone }) {
  button.addEventListener("click", async () => {
    button.disabled = true;
    setStatus("Syncing…");
    try {
      const result = await triggerSync();
      const counts = Object.entries(result.synced)
        .map(([metric, count]) => `${metric}: ${count}`)
        .join(", ");
      // A partial failure (see docs/api-contract.md's POST /api/sync) still
      // means the other metrics genuinely synced - report both rather than
      // hiding the failure or treating the whole sync as an error.
      if (result.errors && Object.keys(result.errors).length > 0) {
        const failed = Object.keys(result.errors).join(", ");
        setStatus(`Synced (${counts}) — failed: ${failed}`, true);
      } else {
        setStatus(`Synced (${counts})`);
      }
      setLastSynced(lastSyncedEl, result.synced_at);
    } catch (err) {
      setStatus(`Sync failed: ${err.message}`, true);
    } finally {
      button.disabled = false;
      onDone();
    }
  });
}
