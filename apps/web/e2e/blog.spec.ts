import { test, expect, type APIRequestContext } from "@playwright/test";

const API_BASE = "http://localhost:8000";
const ADMIN_EMAIL = "admin@getbeam.fyi";
const ADMIN_PASSWORD = "password123";

// ─── Helpers ───────────────────────────────────────────────

/** Log in as the seeded admin user and return a bearer token. */
async function getAdminToken(request: APIRequestContext): Promise<string> {
  const res = await request.post(`${API_BASE}/api/v1/auth/login`, {
    data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
  });
  expect(res.ok(), "admin login should succeed (is the admin user seeded?)").toBeTruthy();
  const { access_token } = await res.json();
  expect(access_token).toBeTruthy();
  return access_token;
}

/** Create + publish a post via the admin API. Returns its slug. */
async function createPublishedPost(
  request: APIRequestContext,
  token: string,
  title: string,
  body: string
): Promise<string> {
  const create = await request.post(`${API_BASE}/api/v1/blog/posts`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { title, body_markdown: body },
  });
  expect(create.ok(), "create draft should succeed").toBeTruthy();
  const post = await create.json();
  const pub = await request.post(
    `${API_BASE}/api/v1/blog/posts/${post.id}/publish`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  expect(pub.ok(), "publish should succeed").toBeTruthy();
  return post.slug;
}

// ─── Public blog ───────────────────────────────────────────

test.describe("Blog — public pages", () => {
  let slug: string;
  let title: string;
  const body = "Automated e2e body paragraph for the public blog post.";

  test.beforeAll(async ({ request }) => {
    const token = await getAdminToken(request);
    title = `E2E Public Post ${Date.now()}`;
    slug = await createPublishedPost(request, token, title, body);
  });

  test("index lists published posts", async ({ page }) => {
    await page.goto("/blog");
    await expect(
      page.getByRole("heading", { name: "Blog", level: 1 })
    ).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("link", { name: title })).toBeVisible({
      timeout: 15_000,
    });
  });

  test("post page renders title and body", async ({ page }) => {
    await page.goto(`/blog/${slug}`);
    await expect(
      page.getByRole("heading", { name: title, level: 1 })
    ).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(body)).toBeVisible({ timeout: 15_000 });
  });

  test("unknown slug 404s", async ({ page }) => {
    const res = await page.goto("/blog/this-slug-does-not-exist");
    expect(res?.status()).toBe(404);
  });

  test("tag hub page filters posts by tag", async ({ page, request }) => {
    const token = await getAdminToken(request);
    const ts = Date.now();
    const tag = `e2e-tag-${ts}`;
    const created = await request.post(`${API_BASE}/api/v1/blog/posts`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { title: `Tagged Post ${ts}`, tags: [tag], body_markdown: "Body." },
    });
    const post = await created.json();
    await request.post(`${API_BASE}/api/v1/blog/posts/${post.id}/publish`, {
      headers: { Authorization: `Bearer ${token}` },
    });

    await page.goto(`/blog/tag/${tag}`);
    await expect(page.getByRole("heading", { level: 1 })).toContainText(tag, {
      timeout: 15_000,
    });
    await expect(
      page.getByRole("link", { name: `Tagged Post ${ts}` })
    ).toBeVisible({ timeout: 15_000 });
  });
});

// ─── Admin editor ──────────────────────────────────────────

test.describe("Blog — admin editor", () => {
  // The shared storageState is the non-admin demo user; blog admin routes are
  // require_admin-gated. Start clean and inject an admin token instead.
  test.use({ storageState: { cookies: [], origins: [] } });

  test("create draft, publish, appears on public blog", async ({
    page,
    request,
  }) => {
    test.slow();
    const token = await getAdminToken(request);
    const title = `E2E Admin Post ${Date.now()}`;

    // Seed the admin token into the app's localStorage (legacy JWT auth path —
    // Clerk is disabled in E2E).
    await page.goto("/");
    await page.evaluate((t) => localStorage.setItem("auth_token", t), token);

    // Create a draft through the editor UI.
    await page.goto("/dashboard/blog/new");
    await page.fill("input#title", title);
    await page.fill("textarea#body", `Admin-created body for ${title}.`);
    await page.getByRole("button", { name: "Create draft" }).click();

    // Redirected to the admin list; the new post shows as a draft.
    await expect(page).toHaveURL(/\/dashboard\/blog$/, { timeout: 15_000 });
    const row = page.getByRole("listitem").filter({ hasText: title });
    await expect(row).toBeVisible({ timeout: 15_000 });
    await expect(row.getByText("Draft")).toBeVisible({ timeout: 15_000 });

    // Publish it.
    await row.getByRole("button", { name: "Publish", exact: true }).click();
    await expect(row.getByText("Published")).toBeVisible({ timeout: 15_000 });

    // Now visible on the public blog (dev mode → no ISR cache lag).
    await page.goto("/blog");
    await expect(page.getByRole("link", { name: title })).toBeVisible({
      timeout: 15_000,
    });
  });

  test("SEO assistant scores the post as you write", async ({ page, request }) => {
    const token = await getAdminToken(request);
    await page.goto("/");
    await page.evaluate((t) => localStorage.setItem("auth_token", t), token);
    await page.goto("/dashboard/blog/new");

    // Empty editor → poor score.
    await expect(page.getByText("SEO score")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("Needs work")).toBeVisible({ timeout: 15_000 });

    // Filling title + focus keyword + a solid body lifts the score out of "poor".
    await page.fill("#title", "Website Visitor Identification: A Practical Guide");
    await page.fill("#focus-keyword", "website visitor identification");
    await page.fill(
      "#body",
      "Website visitor identification turns anonymous traffic into named companies.\n\n" +
        "## How website visitor identification works\n\n" +
        "Reverse IP lookup matches a visit to a company and intent signals reveal buyers. ".repeat(40) +
        "\n\n[Read our guide](/blog)."
    );

    await expect(page.getByText("Needs work")).toBeHidden({ timeout: 15_000 });
  });
});
