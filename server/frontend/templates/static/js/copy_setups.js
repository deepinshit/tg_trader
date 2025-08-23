document.addEventListener("DOMContentLoaded", () => {
  // === Telegram Chats Multi-Select ===
  const tgChatsSelect = document.getElementById("tg-chats");
  const toggleBtn = document.getElementById("toggle-select-chats");
  const countEl = document.getElementById("tg-count");

  let tgChatsChoices = null;

  if (tgChatsSelect) {
    tgChatsChoices = new Choices(tgChatsSelect, {
      removeItemButton: true,
      searchEnabled: true,
      placeholderValue: "Select Telegram chats",
      searchPlaceholderValue: "Search chats",
      maxItemCount: 0,
      duplicateItemsAllowed: false,
      shouldSort: false,
      allowHTML: false,
      silent: false,
    });

    // Update selected count
    const updateTgCount = () => {
      const selectedCount = tgChatsChoices.getValue(true).length;
      countEl.textContent = `${selectedCount} selected`;
      toggleBtn.textContent = selectedCount ? "Deselect All" : "Select All";
    };

    tgChatsChoices.passedElement.element.addEventListener("addItem", updateTgCount);
    tgChatsChoices.passedElement.element.addEventListener("removeItem", updateTgCount);

    // Toggle All / Deselect All button
    toggleBtn?.addEventListener("click", () => {
      const selectedCount = tgChatsChoices.getValue(true).length;
      const allValues = Array.from(tgChatsSelect.options).map(o => o.value);

      tgChatsChoices.removeActiveItems(); // clear current selection

      if (selectedCount === 0) {
        tgChatsChoices.setChoiceByValue(allValues); // select all
      }

      setTimeout(updateTgCount, 0);
    });

    updateTgCount();
  }

  // === Dynamic Symbol Rows ===
  const addBtn = document.getElementById("add-symbol");
  const container = document.getElementById("symbols-container");

  if (addBtn && container) {
    addBtn.addEventListener("click", () => {
      const row = document.createElement("div");
      row.classList.add("symbol-row");
      row.innerHTML = `
        <input type="text" name="symbols[]" placeholder="Symbol (e.g., GBPUSD)" required>
        <input type="text" name="synonyms[]" placeholder="Synonyms (comma separated)">
        <button type="button" class="btn btn-small remove-symbol">Remove</button>
      `;
      container.appendChild(row);
    });
  }

  // Remove symbol row
  document.addEventListener("click", (e) => {
    if (e.target.classList.contains("remove-symbol")) {
      e.target.closest(".symbol-row")?.remove();
    }
  });
});
