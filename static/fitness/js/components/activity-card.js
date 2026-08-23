import { buildActivityIcon } from "./activity-icons.js";
import { openActivityDetail } from "./activity-detail.js";

function formatType(type) {
  if (!type) return "Activity";
  return type
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

// `records` is docs/api-contract.md's activity shape:
// [{ date, exercises: [{ type, duration_minutes, calories }] }].
export function renderActivity(container, records) {
  container.innerHTML = "";

  const flattened = [];
  for (const day of records) {
    for (const ex of day.exercises) {
      flattened.push({ date: day.date, ...ex });
    }
  }

  if (flattened.length === 0) {
    const empty = document.createElement("div");
    empty.className = "card-sublabel";
    empty.textContent = "no activity in range";
    container.appendChild(empty);
    return;
  }

  flattened.sort((a, b) => (a.date < b.date ? 1 : -1));

  const list = document.createElement("ul");
  list.className = "activity-list";
  for (const ex of flattened) {
    const item = document.createElement("li");
    item.classList.add("activity-list-item-clickable");
    item.tabIndex = 0;
    item.setAttribute("role", "button");
    item.addEventListener("click", () => openActivityDetail(ex));
    item.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openActivityDetail(ex);
      }
    });

    const info = document.createElement("div");
    info.className = "activity-info";

    const type = document.createElement("span");
    type.className = "activity-type";
    type.appendChild(buildActivityIcon(ex.type));
    type.appendChild(document.createTextNode(formatType(ex.type)));
    info.appendChild(type);

    if (typeof ex.duration_minutes === "number") {
      const duration = document.createElement("span");
      duration.className = "activity-meta";
      duration.textContent = `${ex.duration_minutes} min`;
      info.appendChild(duration);
    }

    if (typeof ex.calories === "number") {
      const calories = document.createElement("span");
      calories.className = "activity-meta";
      calories.textContent = `${ex.calories} cal`;
      info.appendChild(calories);
    }

    item.appendChild(info);

    const date = document.createElement("span");
    date.className = "activity-date";
    date.textContent = ex.date;
    item.appendChild(date);

    list.appendChild(item);
  }
  container.appendChild(list);
}
