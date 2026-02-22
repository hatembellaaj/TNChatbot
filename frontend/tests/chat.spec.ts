import { expect, test } from "@playwright/test";

type ChatButton = {
  id: string;
  label: string;
};

type ChatPayload = {
  assistant_message: string;
  buttons: ChatButton[];
  suggested_next_step: string;
  slot_updates: Record<string, string>;
  safety?: {
    rag_selected_chunks?: Array<{ content: string }>;
    rag_context?: string;
  };
};

const buildPayload = (
  assistant_message: string,
  step: string,
  buttons: ChatButton[] = [],
  slot_updates?: Record<string, string>,
  safety?: ChatPayload["safety"],
): ChatPayload => ({
  assistant_message,
  buttons,
  suggested_next_step: step,
  slot_updates: slot_updates ?? {},
  safety,
});

test.beforeEach(async ({ page }) => {
  await page.route("**/api/chat/session", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ session_id: "test-session" }),
    });
  });

  await page.route("**/api/chat/message", async (route) => {
    const body = route.request().postDataJSON() as {
      user_message: string;
    };

    let payload: ChatPayload;

    switch (body.user_message) {
      case "Bonjour":
        payload = buildPayload("Bienvenue ! Choisissez un menu.", "MAIN_MENU", [
          { id: "BUDGET", label: "Budget" },
          { id: "CALL_BACK", label: "Parler à un conseiller" },
        ]);
        break;
      case "Budget":
        payload = buildPayload(
          "Parfait, partagez votre budget et vos coordonnées.",
          "BUDGET",
        );
        break;
      case "Menu principal":
        payload = buildPayload("Retour au menu principal.", "MAIN_MENU", [
          { id: "BUDGET", label: "Budget" },
          { id: "CALL_BACK", label: "Parler à un conseiller" },
        ]);
        break;
      case "Parler à un conseiller":
        payload = buildPayload(
          "Un conseiller va vous rappeler.",
          "CALL_BACK",
          [],
        );
        break;
      case "Streaming test":
        payload = buildPayload(
          "Flux en cours avant final.",
          "STREAMING_TEST",
          [{ id: "CTA", label: "CTA" }],
        );
        break;
      case "Question RAG":
        payload = buildPayload(
          "Réponse basée sur chunks.",
          "RAG",
          [],
          {},
          {
            rag_context: "[1] Chunk A\n\n[2] Chunk B",
            rag_selected_chunks: [{ content: "[1] Chunk A" }, { content: "[2] Chunk B" }],
          },
        );
        break;
      default:
        if (body.user_message.startsWith("Résumé formulaire")) {
          payload = buildPayload(
            "Merci, nous revenons vers vous rapidement.",
            "LEAD_CAPTURED",
            [],
            {
              company: "TN",
              email: "contact@tn.fr",
              phone: "0600000000",
              budget: "10k - 50k €",
            },
          );
        } else {
          payload = buildPayload(
            "Je ne peux pas répondre à cette demande (hors scope lecteur).",
            "OUT_OF_SCOPE",
          );
        }
    }

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(payload),
    });
  });
});

test("accueil/menu", async ({ page }) => {
  await page.goto("/");

  const menuButton = page.getByRole("button", { name: "Budget" });
  await expect(menuButton).toBeVisible();

  const assistantMessage = page.locator('[data-testid="message-assistant"]').last();
  await expect(assistantMessage).toContainText("Bienvenue");
});

test("parcours budget", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Budget" }).click();

  await expect(page.getByTestId("budget-form")).toBeVisible();

  await page.getByLabel("Société").fill("TN");
  await page.getByLabel("Email").fill("contact@tn.fr");
  await page.getByLabel("Téléphone").fill("0600000000");
  await page.getByLabel("Budget média").selectOption("10k - 50k €");
  await page.getByRole("button", { name: "Envoyer le brief" }).click();

  await expect(page.getByTestId("state-step")).toContainText("LEAD_CAPTURED");
  await expect(page.getByText("company : TN")).toBeVisible();
});

test("hors-scope lecteur", async ({ page }) => {
  await page.goto("/");
  await page.getByPlaceholder("Posez votre question ou choisissez un menu...").fill(
    "Montre moi la doc lecteur",
  );
  await page.getByRole("button", { name: "Envoyer" }).click();

  const assistantMessage = page.locator('[data-testid="message-assistant"]').last();
  await expect(assistantMessage).toContainText("hors scope lecteur");
});

test("typing effect after full response", async ({ page }) => {
  await page.goto("/");
  await page
    .getByPlaceholder("Posez votre question ou choisissez un menu...")
    .fill("Streaming test");
  await page.getByRole("button", { name: "Envoyer" }).click();

  const assistantMessage = page.locator('[data-testid="message-assistant"]').last();

  const finalText = "Flux en cours avant final.";

  await expect.poll(async () => {
    const text = (await assistantMessage.textContent()) ?? "";
    return text.length;
  }).toBeGreaterThan(0);

  await expect.poll(async () => {
    const text = (await assistantMessage.textContent()) ?? "";
    return text.length;
  }).toBeLessThan(finalText.length);

  await expect(assistantMessage).toHaveText(finalText);
});


test("inspection des chunks élus", async ({ page }) => {
  await page.goto("/");
  await page
    .getByPlaceholder("Posez votre question ou choisissez un menu...")
    .fill("Question RAG");
  await page.getByRole("button", { name: "Envoyer" }).click();

  await expect(page.getByRole("button", { name: "Voir les chunks élus" }).last()).toBeVisible();
  await page.getByRole("button", { name: "Voir les chunks élus" }).last().click();

  const panel = page.getByTestId("rag-panel").last();
  await expect(panel).toContainText("Contexte envoyé au LLM");
  await expect(panel).toContainText("[1] Chunk A");
  await expect(panel).toContainText("[2] Chunk B");
});
