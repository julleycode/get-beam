import { test, expect, type Page } from "@playwright/test";

// Guided LinkedIn onboarding wizard (dashboard side).
//
// The Beam extension cannot be loaded into this Playwright config (MV3 needs a
// persistent context — that half lives in apps/extension/e2e). So the extension
// side is a SYNTHETIC PROXY here: we stub `window.chrome.runtime.sendMessage`
// and the `data-beam-extension` marker. This proves the wizard's REACTION to the
// signals, not Chrome's delivery of them — the delivery mechanism itself was
// proven empirically by the FEASIBILITY probe (reload-based install detection)
// and by the MV3 harness specs in apps/extension/e2e. Known, accepted boundary.

type StubOptions = { installed?: boolean; signedIn?: boolean };

async function stubExtension(page: Page, opts: StubOptions = {}) {
  await page.addInitScript((o) => {
    const state = { installed: !!o.installed, signedIn: !!o.signedIn };
    (window as unknown as { __beamStub: typeof state }).__beamStub = state;

    (window as unknown as { chrome: unknown }).chrome = {
      runtime: {
        lastError: undefined,
        sendMessage(
          _extId: string,
          message: { type?: string },
          cb?: (r: unknown) => void
        ) {
          if (!cb) return; // register-nonce — no reply expected
          if (message?.type === "beam-session-check") {
            // Status only — mirrors the real extension's shape (no cookie key).
            cb(
              state.signedIn
                ? { signedIn: true }
                : { signedIn: false, reason: "not_signed_in" }
            );
            return;
          }
          if (message?.type === "beam-connect-request") {
            cb(
              state.signedIn
                ? {
                    ok: true,
                    cookie: "AQEDA-fake-li_at",
                    userAgent: navigator.userAgent,
                  }
                : { ok: false, reason: "not_signed_in" }
            );
          }
        },
      },
    };

    if (state.installed) {
      document.documentElement.dataset.beamExtension = "1";
    }
  }, opts);
}

/** Flip the synthetic extension-installed signal at runtime (AC2's proxy). */
async function signalInstalled(page: Page) {
  await page.evaluate(() => {
    (window as unknown as { __beamStub: { installed: boolean } }).__beamStub.installed = true;
    document.documentElement.dataset.beamExtension = "1";
    window.dispatchEvent(new CustomEvent("beam-extension-detected"));
  });
}

/** Flip the synthetic LinkedIn-signed-in signal at runtime. */
async function signalSignedIn(page: Page) {
  await page.evaluate(() => {
    (window as unknown as { __beamStub: { signedIn: boolean } }).__beamStub.signedIn = true;
  });
}

async function mockOutreachApi(page: Page, connected = false) {
  await page.route("**/social/accounts/linkedin/outreach-status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ configured: true, outreach_connected: connected }),
    })
  );
  await page.route("**/social/accounts/linkedin/outreach-connect", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true, name: "Mock LinkedIn User" }),
    })
  );
}

async function openWizard(page: Page) {
  await page.goto("/dashboard/social-accounts");
  const launch = page.getByRole("button", {
    name: /^(Connect|Reconnect) LinkedIn$/,
  });
  await expect(launch.first()).toBeVisible({ timeout: 20_000 });
  await launch.first().click();
  await expect(page.getByTestId("wizard-progress")).toBeVisible();
}

test.describe("LinkedIn connect wizard", () => {
  test("AC1 + AC13: Step 1 auto-passes on Chrome; install step shows permission copy before the CTA", async ({
    page,
  }) => {
    await mockOutreachApi(page);
    await stubExtension(page, { installed: false, signedIn: false });
    await openWizard(page);

    // No click needed to leave the browser-check step.
    await expect(page.getByTestId("wizard-step-install")).toBeVisible();
    await expect(page.getByTestId("wizard-step-browser")).toHaveCount(0);

    // AC13: transparency block appears BEFORE the install CTA in DOM order.
    const step = page.getByTestId("wizard-step-install");
    await expect(page.getByTestId("wizard-permission-transparency")).toBeVisible();
    const order = await step.evaluate((el) => {
      const kids = Array.from(el.querySelectorAll("*"));
      const copy = kids.findIndex(
        (k) => (k as HTMLElement).dataset?.testid === "wizard-permission-transparency"
      );
      const cta = kids.findIndex((k) => k.textContent?.trim() === "Get the add-on");
      return { copy, cta };
    });
    expect(order.copy).toBeGreaterThanOrEqual(0);
    expect(order.cta).toBeGreaterThan(order.copy);

    // Copy must never promise silent install detection (FEASIBILITY NOT-VIABLE).
    await expect(step).not.toContainText(/detect.*automatically/i);
    // Plain-language rule: no cookie/DevTools/session-token wording in the wizard.
    await expect(step).not.toContainText(/cookie|DevTools|session token/i);
  });

  test("AC2: install signal auto-advances to the sign-in step with no click", async ({
    page,
  }) => {
    await mockOutreachApi(page);
    await stubExtension(page, { installed: false, signedIn: false });
    await openWizard(page);
    await expect(page.getByTestId("wizard-step-install")).toBeVisible();

    await signalInstalled(page);

    await expect(page.getByTestId("wizard-step-signin")).toBeVisible();
    await expect(page.getByTestId("wizard-step-install")).toHaveCount(0);
  });

  test("AC3: signed-in probe response auto-advances to the connect step with no click", async ({
    page,
  }) => {
    await mockOutreachApi(page);
    await stubExtension(page, { installed: true, signedIn: false });
    await openWizard(page);
    await expect(page.getByTestId("wizard-step-signin")).toBeVisible();

    // No click, no reload, no synthetic event — the capped backstop poll picks
    // the new probe answer up on its own within 2s.
    await signalSignedIn(page);

    await expect(page.getByTestId("wizard-step-connect")).toBeVisible({
      timeout: 10_000,
    });
  });

  test("AC4: returning to the tab re-triggers detection and advances, no reload", async ({
    page,
    context,
  }) => {
    await mockOutreachApi(page);
    await stubExtension(page, { installed: false, signedIn: false });
    await openWizard(page);
    await expect(page.getByTestId("wizard-step-install")).toBeVisible();

    // Real browser-level tab switch (CDP Page.bringToFront), not a synthetic
    // JS-dispatched visibilitychange.
    const other = await context.newPage();
    await other.goto("about:blank");
    await other.bringToFront();

    await page.evaluate(() => {
      (window as unknown as { __beamStub: { installed: boolean } }).__beamStub.installed =
        true;
      document.documentElement.dataset.beamExtension = "1";
    });

    const navigations: string[] = [];
    page.on("framenavigated", (f) => navigations.push(f.url()));

    await page.bringToFront();

    await expect(page.getByTestId("wizard-step-signin")).toBeVisible({
      timeout: 10_000,
    });
    expect(navigations).toHaveLength(0); // advanced without a page reload
    await other.close();
  });

  test("AC7 + AC8: full guided flow reaches Connected with no manual paste; ToS always shown", async ({
    page,
  }) => {
    await mockOutreachApi(page);
    await stubExtension(page, { installed: false, signedIn: false });
    await openWizard(page);

    await expect(page.getByTestId("wizard-step-install")).toBeVisible();
    await signalInstalled(page);
    await expect(page.getByTestId("wizard-step-signin")).toBeVisible();
    await signalSignedIn(page);
    await expect(page.getByTestId("wizard-step-connect")).toBeVisible({
      timeout: 10_000,
    });

    // AC8: ToS warning is present on the connect step.
    await expect(
      page
        .getByTestId("wizard-step-connect")
        .getByText(/against LinkedIn's Terms of Service/i)
    ).toBeVisible();

    await page.getByRole("button", { name: "Connect LinkedIn" }).click();
    await expect(page.getByTestId("wizard-connected")).toContainText(
      "Connected as Mock LinkedIn User"
    );
  });

  test("AC10 + AC8: already set up short-circuits to the connect step, ToS still shown", async ({
    page,
  }) => {
    await mockOutreachApi(page, true);
    await stubExtension(page, { installed: true, signedIn: true });
    await openWizard(page);

    await expect(page.getByTestId("wizard-step-connect")).toBeVisible();
    await expect(page.getByTestId("wizard-step-install")).toHaveCount(0);
    await expect(page.getByTestId("wizard-step-signin")).toHaveCount(0);
    await expect(
      page
        .getByTestId("wizard-step-connect")
        .getByText(/against LinkedIn's Terms of Service/i)
    ).toBeVisible();
  });

  test("AC11: reconnect uses the identical Step 4 flow as a first connect", async ({
    page,
  }) => {
    await mockOutreachApi(page, true);
    await stubExtension(page, { installed: true, signedIn: true });
    await openWizard(page);

    await expect(page.getByTestId("wizard-step-connect")).toBeVisible();
    await page.getByRole("button", { name: "Refresh connection" }).click();
    await expect(page.getByTestId("wizard-connected")).toContainText(
      "Connected as Mock LinkedIn User"
    );
  });

  test("AC12: manual form stays reachable from inside the wizard", async ({ page }) => {
    await mockOutreachApi(page);
    await stubExtension(page, { installed: true, signedIn: true });
    await openWizard(page);

    await page.getByRole("button", { name: /Use the manual option instead/i }).click();

    // Wizard closes and the advanced manual form is revealed on the page.
    await expect(page.getByTestId("wizard-progress")).toHaveCount(0);
    await expect(page.getByLabel(/LinkedIn login key/i)).toBeVisible();
  });
});

test.describe("LinkedIn connect wizard — unsupported browser", () => {
  test.use({
    userAgent:
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
  });

  test("AC9: Safari dead-ends to the manual form with no install CTA anywhere", async ({
    page,
  }) => {
    await mockOutreachApi(page);
    // No window.chrome stub at all — mirrors a real Firefox/Safari.
    await page.goto("/dashboard/social-accounts");
    await expect(
      page.getByText(/against LinkedIn's Terms of Service/i)
    ).toBeVisible({ timeout: 20_000 });

    // No wizard launcher, no install CTA, and the manual form is the only path.
    await expect(page.getByRole("button", { name: /^Connect LinkedIn$/ })).toHaveCount(0);
    await expect(page.getByText("Get the add-on")).toHaveCount(0);
    await expect(page.getByLabel(/LinkedIn login key/i)).toBeVisible();
  });
});
