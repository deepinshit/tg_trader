/**
 * Universal form handler for all forms.
 * Submits as FormData (standard form-encoded) to work with FastAPI Form(...) endpoints.

function attachFormHandlers() {
  document.querySelectorAll("form").forEach(form => {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();

      const submitBtn = form.querySelector('[type="submit"]');
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.dataset.originalText = submitBtn.innerText;
        submitBtn.innerText = "Submitting...";
      }

      try {
        const body = new FormData(form); // normal form submission

        const res = await fetch(form.action, {
          method: form.method || "POST",
          body, // form-encoded automatically
        });

        const contentType = res.headers.get("content-type") || "";
        let data;
        if (contentType.includes("application/json")) {
          data = await res.json();
        } else {
          data = await res.text(); // fallback
        }

        if (!res.ok) {
          console.error("❌ Validation or submission error:", data);
          alert("Submission failed. Check console for details.");
          return;
        }

        console.log("✅ Success:", data);

        // For HTML redirects (like login), reload page
        if (typeof data === "string") {
          window.location.href = res.url;
        } else {
          alert("Form submitted successfully!");
        }

      } catch (err) {
        console.error("❌ Error:", err);
        alert("Something went wrong during form submission.");
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.innerText = submitBtn.dataset.originalText;
        }
      }
    });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  attachFormHandlers();
});
*/