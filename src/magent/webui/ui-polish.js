document.querySelectorAll("[data-new]").forEach((button) => {
  button.addEventListener("click", () => document.getElementById("newMenu").classList.add("hidden"));
});
