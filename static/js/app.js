(() => {
  "use strict";

  // Restore the user's theme choice.
  const savedTheme = localStorage.getItem("taskpilot-theme");
  if (savedTheme === "dark" || savedTheme === "light") {
    document.documentElement.dataset.theme = savedTheme;
  }

  // Add a theme toggle beside the navigation links.
  const nav = document.querySelector(".navbar .d-flex");
  if (nav) {
    const themeButton = document.createElement("button");
    themeButton.type = "button";
    themeButton.className = "btn btn-sm btn-outline-light";
    themeButton.setAttribute("aria-label", "Toggle light and dark theme");
    themeButton.textContent =
      document.documentElement.dataset.theme === "dark" ? "☀️" : "🌙";

    themeButton.addEventListener("click", () => {
      const nextTheme =
        document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = nextTheme;
      localStorage.setItem("taskpilot-theme", nextTheme);
      themeButton.textContent = nextTheme === "dark" ? "☀️" : "🌙";
    });

    nav.prepend(themeButton);
  }

  // Prevent a task from having a start date after its due date.
  document.querySelectorAll('form input[type="date"]').forEach((dateInput) => {
    dateInput.addEventListener("change", () => {
      const form = dateInput.form;
      if (!form) return;

      const start = form.querySelector('[name="start_date"]');
      const due = form.querySelector('[name="due_date"]');

      if (start && due && start.value && due.value) {
        due.setCustomValidity(
          due.value < start.value ? "Due date must be on or after the start date." : ""
        );
      }
    });
  });

  // Confirm before deleting a task or project.
  document.querySelectorAll('form[action$="/delete"]').forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!window.confirm("Delete this item? This action cannot be undone.")) {
        event.preventDefault();
      }
    });
  });

  // Automatically hide status messages after a few seconds.
  document.querySelectorAll(".alert").forEach((alert) => {
    window.setTimeout(() => {
      alert.style.transition = "opacity 250ms ease, transform 250ms ease";
      alert.style.opacity = "0";
      alert.style.transform = "translateY(-6px)";
      window.setTimeout(() => alert.remove(), 280);
    }, 4500);
  });
})();